"""Read the native YuE2 engine's small, optional progress snapshot."""
from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..config import YUE2_PROGRESS_PATH

router = APIRouter(prefix="/api/yue2")


@router.get("/progress")
def progress():
    try:
        snapshot = json.loads(YUE2_PROGRESS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = None
    return JSONResponse(snapshot, headers={"Cache-Control": "no-store"})
