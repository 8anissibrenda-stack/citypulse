"""Signal API routes (alias for core signals — kept for router separation)."""

from __future__ import annotations

from fastapi import APIRouter

from app import db

router = APIRouter(prefix="/api", tags=["signals"])


@router.get("/junctions")
async def get_junctions() -> list[dict]:
    """Return all junctions with their details."""
    return db.query_all("SELECT * FROM junctions")
