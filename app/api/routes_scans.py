from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Competitor, Scan
from app.services.detector import detector

router = APIRouter(prefix="/api/competitors", tags=["Scans"])


@router.post("/{competitor_id}/scan")
async def trigger_scan(competitor_id: int, db: AsyncSession = Depends(get_db)):
    comp = await db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    try:
        scan_result = await detector.execute_scan(db, competitor_id)
        return scan_result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan execution failed: {str(e)}")


@router.get("/{competitor_id}/scans")
async def list_competitor_scans(competitor_id: int, db: AsyncSession = Depends(get_db)):
    comp = await db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    stmt = select(Scan).where(Scan.competitor_id == competitor_id).order_by(desc(Scan.started_at))
    scans = (await db.execute(stmt)).scalars().all()
    return [s.to_dict() for s in scans]
