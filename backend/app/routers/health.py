"""
health.py - "Is the app alive and able to reach its database?"

Load balancers call this every few seconds. If it stops answering "ok", the
load balancer stops sending users to this copy of the app and replaces it
(remember the "10 copies" discussion). Handy for you too: open
http://localhost:8000/health to check the backend is running.
"""

from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings, get_settings
from app.db import get_db
from app.models import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus)
async def health(
    db: AsyncDatabase = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        await db.command("ping")
    except Exception:
        # 503 = "service unavailable": tells the load balancer we're unhealthy.
        raise HTTPException(status_code=503, detail="Database unreachable")
    return {"status": "ok", "environment": settings.environment}
