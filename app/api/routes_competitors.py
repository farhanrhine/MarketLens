from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import Article, Competitor, PricingChange, PricingSnapshot, Scan
from app.services.detector import detector
from app.services.scraper import normalize_domain

router = APIRouter(prefix="/api/competitors", tags=["Competitors"])


class CreateCompetitorRequest(BaseModel):
    domain: str = Field(..., description="Domain or URL of the competitor, e.g. clickup.com or https://buffer.com")
    auto_scan: bool = Field(default=True, description="Whether to trigger initial baseline scan immediately")


@router.get("", response_model=List[Dict[str, Any]])
async def list_competitors(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Competitor)
        .options(selectinload(Competitor.articles))
        .order_by(desc(Competitor.created_at))
    )
    result = await db.execute(stmt)
    competitors = result.scalars().all()
    return [c.to_dict() for c in competitors]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_competitor(payload: CreateCompetitorRequest, db: AsyncSession = Depends(get_db)):
    base_url, norm_domain = normalize_domain(payload.domain)
    if not norm_domain:
        raise HTTPException(status_code=400, detail="Invalid domain provided")

    # Check if competitor domain already exists
    stmt = select(Competitor).where(Competitor.normalized_domain == norm_domain)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return {
            "message": f"Competitor {norm_domain} already registered",
            "competitor": existing.to_dict(),
        }

    competitor = Competitor(
        domain=payload.domain.strip(),
        normalized_domain=norm_domain,
        status="ACTIVE",
    )
    db.add(competitor)
    await db.commit()
    await db.refresh(competitor)

    scan_result = None
    if payload.auto_scan:
        try:
            scan_result = await detector.execute_scan(db, competitor.id)
            await db.refresh(competitor)
        except Exception as e:
            scan_result = {"status": "FAILED", "error": str(e)}

    return {
        "message": f"Competitor {norm_domain} added successfully",
        "competitor": competitor.to_dict(),
        "initial_scan": scan_result,
    }


@router.get("/{competitor_id}")
async def get_competitor_details(competitor_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Competitor)
        .options(
            selectinload(Competitor.articles),
            selectinload(Competitor.scans),
            selectinload(Competitor.pricing_snapshots),
            selectinload(Competitor.pricing_changes),
        )
        .where(Competitor.id == competitor_id)
    )
    comp = (await db.execute(stmt)).scalar_one_or_none()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    # Sort articles by publish date or first_seen_at
    sorted_articles = sorted(
        comp.articles,
        key=lambda a: a.published_at or a.first_seen_at,
        reverse=True,
    )

    return {
        "competitor": comp.to_dict(),
        "articles": [a.to_dict() for a in sorted_articles],
        "scans": [s.to_dict() for s in comp.scans],
        "pricing_changes": [pc.to_dict() for pc in comp.pricing_changes],
    }


@router.delete("/{competitor_id}")
async def delete_competitor(competitor_id: int, db: AsyncSession = Depends(get_db)):
    comp = await db.get(Competitor, competitor_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    domain = comp.normalized_domain
    await db.delete(comp)
    await db.commit()
    return {"message": f"Competitor {domain} deleted successfully"}
