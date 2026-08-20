"""Liveness and readiness.

``/healthz`` answers "is this process alive" and touches nothing, so a database
blip cannot make the orchestrator kill a healthy API. ``/readyz`` answers "can
this process actually serve traffic" and checks each dependency separately, so the
answer says *which* one is down.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app import SERVICE_NAME, __version__

router = APIRouter(tags=["operations"])


@router.get("/healthz", summary="Liveness — no dependencies")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME, "version": __version__}


@router.get("/readyz", summary="Readiness — one entry per dependency")
async def readyz(request: Request, response: Response) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {
        "database": await _check_database(request),
        "storage": await _check_storage(request),
    }
    healthy = all(check["ok"] for check in checks.values())
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", "checks": checks}


async def _check_database(request: Request) -> dict[str, Any]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return {"ok": False, "detail": "database not configured"}
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__}
    return {"ok": True}


async def _check_storage(request: Request) -> dict[str, Any]:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        return {"ok": False, "detail": "storage not configured"}
    try:
        await storage.exists("catalog/.readyz-probe")
    except Exception as exc:
        return {"ok": False, "detail": type(exc).__name__}
    return {"ok": True}
