from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import yue2_specs
from ..orchestrator.manager import manager
from ..orchestrator.process import StartCancelled

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


class SwitchRequest(BaseModel):
    model: str


@router.get("/config")
async def get_config():
    return {
        "yue2_specs": yue2_specs(),
    }


@router.get("/status")
async def get_status():
    return manager.status_snapshot()


@router.post("/switch")
async def switch(req: SwitchRequest):
    try:
        await manager.switch_to(req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StartCancelled as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError) as exc:
        # Startup failed; manager.status_snapshot() already reflects the
        # per-model error state/message for the UI to display.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return manager.status_snapshot()


@router.post("/stop")
async def stop():
    await manager.stop_active()
    return manager.status_snapshot()


@router.post("/yue2/reset")
async def reset_yue2():
    # YuE2's native task API has no cooperative cancel endpoint. Restarting
    # its process releases the cancelled inference and its GPU allocations.
    try:
        await manager.restart_model("yue2")
    except (ValueError, StartCancelled) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return manager.status_snapshot()
