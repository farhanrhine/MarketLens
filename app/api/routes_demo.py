from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Article, Competitor, Scan
from app.services.detector import detector

router = APIRouter(prefix="/api/competitors", tags=["Loom Demo Controls"])


@router.post("/{competitor_id}/demo/simulate-new-post")
async def demo_simulate_new_post(competitor_id: int, db: AsyncSession = Depends(get_db)):
    """
    Drops the newest article from the database index.
    Allows user to click 'Scan Now' on camera and immediately demonstrate
    delta detection, AI keyword extraction, and live Slack/Email alerting!
    """
    comp = await db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    res = await detector.simulate_new_post(db, competitor_id)
    return res


@router.post("/{competitor_id}/demo/simulate-pricing")
async def demo_simulate_pricing(competitor_id: int, db: AsyncSession = Depends(get_db)):
    """Injects a simulated pricing plan change and triggers notification."""
    comp = await db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    res = await detector.simulate_pricing_change(db, competitor_id)
    return res


@router.post("/{competitor_id}/demo/reset-baseline")
async def demo_reset_baseline(competitor_id: int, db: AsyncSession = Depends(get_db)):
    """
    Deletes all indexed articles and scans for this competitor,
    resetting it to baseline state.
    """
    comp = await db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    await db.execute(delete(Article).where(Article.competitor_id == competitor_id))
    await db.execute(delete(Scan).where(Scan.competitor_id == competitor_id))
    comp.status = "ACTIVE"
    await db.commit()

    return {
        "message": f"Successfully reset baseline for {comp.normalized_domain}. All historical index data cleared."
    }
