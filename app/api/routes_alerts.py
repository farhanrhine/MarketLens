import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.database import get_db
from app.db.models import Competitor
from app.services.ai_service import ai_service
from app.services.alerting import alert_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Alerts & System Status"])


class TestAlertRequest(BaseModel):
    channel: str = "slack"  # "slack" or "email"
    competitor_id: Optional[int] = None


@router.post("/api/alerts/test")
async def trigger_test_alert(payload: TestAlertRequest, db: AsyncSession = Depends(get_db)):
    # Check if a specific competitor was requested, or pick the active competitor
    competitor = None
    if payload.competitor_id:
        stmt = (
            select(Competitor)
            .options(
                selectinload(Competitor.articles),
                selectinload(Competitor.pricing_changes),
            )
            .where(Competitor.id == payload.competitor_id)
        )
        competitor = (await db.execute(stmt)).scalar_one_or_none()

    if not competitor:
        stmt = (
            select(Competitor)
            .options(
                selectinload(Competitor.articles),
                selectinload(Competitor.pricing_changes),
            )
            .order_by(desc(Competitor.last_scan_at), desc(Competitor.created_at))
            .limit(1)
        )
        competitor = (await db.execute(stmt)).scalar_one_or_none()

    if competitor and competitor.articles:
        # Send full real data for the competitor with Groq LLM strategy insight
        all_articles = [a.to_dict() for a in competitor.articles]
        sample_pricing = [pc.summary for pc in competitor.pricing_changes]

        # Generate live AI Strategic Summary using Groq LLM
        real_ai_summary = None
        if ai_service.is_available:
            try:
                real_ai_summary = await ai_service.generate_alert_strategy_summary(
                    competitor_name=competitor.normalized_domain,
                    articles=all_articles,
                    pricing_changes=sample_pricing,
                )
            except Exception as e:
                logger.warning(f"Failed to generate AI strategy summary for alert test: {e}")

        if not real_ai_summary:
            real_ai_summary = f"{competitor.normalized_domain} published {len(all_articles)} articles targeting strategic SEO keyword expansion."

        res = await alert_service.send_test_alert(
            channel=payload.channel,
            competitor_domain=competitor.normalized_domain,
            articles=all_articles,
            ai_summary=real_ai_summary,
            pricing_changes=sample_pricing if sample_pricing else ["Current pricing plans actively monitored"],
        )
        return res

    # Fallback if no competitor exists yet in DB
    res = await alert_service.send_test_alert(channel=payload.channel)
    return res


@router.get("/api/status")
async def get_system_status() -> Dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "groq_ai": {
            "configured": bool(settings.groq_api_key and settings.groq_api_key.strip()),
            "model": settings.groq_model,
            "status": "ONLINE" if ai_service.is_available else "OFFLINE (Deterministic Fallbacks Active)",
        },
        "seo_volume": {
            "provider": settings.seo_provider,
            "configured": bool(settings.seo_api_key and settings.seo_api_key.strip()),
        },
        "notifications": {
            "slack": {
                "configured": bool(settings.slack_webhook_url and settings.slack_webhook_url.strip()),
            },
            "email": {
                "provider": settings.email_provider,
                "configured": bool(
                    (settings.email_provider == "resend" and settings.resend_api_key)
                    or (settings.email_provider == "smtp" and settings.smtp_host)
                ),
                "recipient": settings.notification_email_to,
            },
        },
    }
