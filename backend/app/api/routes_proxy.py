"""Generic reverse proxy: /api/{ace,yue2}/* -> the active model's own REST API.

Mirrors the proxy pattern YuE2's own web-ui/server.py already uses for its
/v1/* passthrough (strip hop-by-hop headers, forward method/body/query as-is)
so both frontends can be written against a single same-origin API surface.
"""
from __future__ import annotations

import json
import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import MODELS
from ..orchestrator.manager import manager
from ..orchestrator.state import ModelStatus

router = APIRouter(prefix="/api")

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-encoding", "content-length", "host",
}

_client = httpx.AsyncClient(timeout=None)

_YUE2_COMPACT_ARENAS = {
    "yue2.model_weight_context_mb": "64",
    "yue2.vae_weight_context_mb": "64",
    "yue2.ar_prefill_graph_arena_mb": "256",
    "yue2.ar_decode_graph_arena_mb": "128",
    "yue2.nar_graph_arena_mb": "256",
    "yue2.vae_graph_arena_mb": "128",
}


def _compact_yue2_load(body: bytes) -> bytes:
    """Apply safe metadata arena limits even when a cached UI sends old options."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(payload, dict) or payload.get("id") != "yue2":
        return body
    options = payload.get("session_options")
    if options is None:
        options = {}
    if not isinstance(options, dict):
        return body
    payload["session_options"] = {**_YUE2_COMPACT_ARENAS, **options}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def _proxy_to(base_url: str, request: Request, path: str, model_id: str | None = None) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = await request.body()
    if model_id == "yue2" and request.method == "POST" and path == "v1/models/load":
        body = _compact_yue2_load(body)
    url = httpx.URL(f"{base_url}/{path}", params=list(request.query_params.multi_items()))

    req = _client.build_request(
        request.method,
        url,
        headers=headers,
        content=body,
    )
    upstream = await _client.send(req, stream=True)
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}

    async def body_stream():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        body_stream(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


def _make_proxy_route(model_id: str):
    async def _route(request: Request, path: str = ""):
        rs = manager.state.models[model_id]
        if rs.status != ModelStatus.RUNNING:
            return JSONResponse({"error": f"model '{model_id}' is not active"}, status_code=503)
        try:
            return await _proxy_to(MODELS[model_id].proxy_target, request, path, model_id)
        except httpx.HTTPError as exc:
            return JSONResponse({"error": f"upstream request failed: {exc}"}, status_code=502)

    return _route


for _model_id, _definition in MODELS.items():
    router.add_api_route(
        f"/{_definition.proxy_prefix}/{{path:path}}",
        _make_proxy_route(_model_id),
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
