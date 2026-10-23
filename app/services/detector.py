import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Article, Competitor, PricingChange, PricingSnapshot, Scan
from app.services.ai_service import ai_service
from app.services.alerting import alert_service
from app.services.enrichment import enrich_article_data
from app.services.scraper import CompetitorScraper, ScrapeResult

logger = logging.getLogger(__name__)


class ContentDetector:
    """
    Orchestrates crawler execution, baseline vs delta detection,
    pricing diffing, AI enrichment, and alerting dispatch.
    """

    def __init__(self):
        self.scraper = CompetitorScraper()

    async def execute_scan(
        self, session: AsyncSession, competitor_id: int
    ) -> Dict[str, Any]:
        """
        Executes a scan for a given competitor:
        - Detects if first scan (baseline) or delta scan.
        - Scrapes feeds, sitemaps, HTML.
        - Computes newly discovered articles.
        - Enriches new articles.
        - Checks pricing page changes.
        - Dispatches alerts if new articles or pricing changes found.
        """
        competitor = await session.get(Competitor, competitor_id)
        if not competitor:
            raise ValueError(f"Competitor {competitor_id} not found")

        # Create scan record
        scan = Scan(
            competitor_id=competitor.id,
            started_at=datetime.now(timezone.utc),
            status="RUNNING",
            is_baseline=False,
        )
        session.add(scan)
        await session.commit()
        await session.refresh(scan)

        # Check if competitor has any existing completed scans
        stmt_prev = select(Scan).where(
            Scan.competitor_id == competitor.id,
            Scan.status == "COMPLETED",
        )
        prev_scans = (await session.execute(stmt_prev)).scalars().all()
        is_baseline = len(prev_scans) == 0
        scan.is_baseline = is_baseline

        # Scrape competitor
        scrape_result: ScrapeResult = await self.scraper.scrape(competitor.domain)

        # Handle non-200 / blocked / no blog status
        if scrape_result.status in ("FAILED", "BLOCKED", "NO_BLOG"):
            scan.status = scrape_result.status
            scan.completed_at = datetime.now(timezone.utc)
            scan.error_message = scrape_result.error_message

            # Generate AI explanation if Groq is available
            if ai_service.is_available:
                ai_exp = await ai_service.explain_scan_failure(
                    status=scrape_result.status,
                    domain=competitor.domain,
                    error_details=scrape_result.error_message,
                )
                if ai_exp:
                    scan.ai_summary = ai_exp

            competitor.status = scrape_result.status
            competitor.last_scan_at = datetime.now(timezone.utc)
            await session.commit()

            return {
                "scan_id": scan.id,
                "status": scan.status,
                "is_baseline": is_baseline,
                "error_message": scan.error_message,
                "ai_summary": scan.ai_summary,
                "articles_found": 0,
                "new_articles_count": 0,
            }

        # Update competitor metadata
        competitor.status = "ACTIVE"
        if scrape_result.blog_url:
            competitor.blog_url = scrape_result.blog_url
        if scrape_result.pricing_url:
            competitor.pricing_url = scrape_result.pricing_url
        competitor.last_scan_at = datetime.now(timezone.utc)

        # Query existing articles for this competitor to determine deltas
        stmt_existing = select(Article.normalized_url).where(
            Article.competitor_id == competitor.id
        )
        existing_urls: set[str] = set((await session.execute(stmt_existing)).scalars().all())

        new_articles_data = []
        all_articles_count = len(scrape_result.articles)

        # Baseline Scan: index all current articles without firing spam alerts
        if is_baseline:
            scan.status = "COMPLETED"
            scan.total_articles_found = all_articles_count
            scan.new_articles_found = 0
            scan.ai_summary = f"Baseline scan complete: {all_articles_count} existing articles indexed. Monitoring active."

            for scraped_art in scrape_result.articles:
                enrichment = await enrich_article_data(
                    title=scraped_art.title,
                    url=scraped_art.url,
                    meta_description=scraped_art.meta_description,
                )
                article_record = Article(
                    competitor_id=competitor.id,
                    normalized_url=scraped_art.url,
                    title=scraped_art.title,
                    published_at=scraped_art.published_at,
                    meta_description=scraped_art.meta_description,
                    target_keyword=enrichment["target_keyword"],
                    search_intent=enrichment["search_intent"],
                    search_volume=enrichment["search_volume"],
                    enrichment_status=enrichment["enrichment_status"],
                    last_scan_id=scan.id,
                )
                session.add(article_record)

            # Record initial pricing snapshot
            if scrape_result.pricing_url and scrape_result.pricing_content_hash:
                snapshot = PricingSnapshot(
                    competitor_id=competitor.id,
                    pricing_url=scrape_result.pricing_url,
                    content_hash=scrape_result.pricing_content_hash,
                    plans_json=None,
                )
                session.add(snapshot)

            scan.completed_at = datetime.now(timezone.utc)
            await session.commit()

            return {
                "scan_id": scan.id,
                "status": "COMPLETED",
                "is_baseline": True,
                "articles_found": all_articles_count,
                "new_articles_count": 0,
                "pricing_changes": [],
                "ai_summary": scan.ai_summary,
            }

        # Delta Scan: Identify newly discovered articles
        for scraped_art in scrape_result.articles:
            if scraped_art.url not in existing_urls:
                new_articles_data.append(scraped_art)

        new_article_records: List[Article] = []
        for scraped_art in new_articles_data:
            enrichment = await enrich_article_data(
                title=scraped_art.title,
                url=scraped_art.url,
                meta_description=scraped_art.meta_description,
            )
            art_obj = Article(
                competitor_id=competitor.id,
                normalized_url=scraped_art.url,
                title=scraped_art.title,
                published_at=scraped_art.published_at,
                meta_description=scraped_art.meta_description,
                target_keyword=enrichment["target_keyword"],
                search_intent=enrichment["search_intent"],
                search_volume=enrichment["search_volume"],
                enrichment_status=enrichment["enrichment_status"],
                last_scan_id=scan.id,
            )
            session.add(art_obj)
            new_article_records.append(art_obj)

        # Check for Pricing Changes
        pricing_changes_found: List[str] = []
        if scrape_result.pricing_url and scrape_result.pricing_content_hash:
            stmt_latest_snap = (
                select(PricingSnapshot)
                .where(PricingSnapshot.competitor_id == competitor.id)
                .order_by(desc(PricingSnapshot.observed_at))
                .limit(1)
            )
            latest_snap = (await session.execute(stmt_latest_snap)).scalar_one_or_none()

            if latest_snap is None:
                # First snapshot
                snapshot = PricingSnapshot(
                    competitor_id=competitor.id,
                    pricing_url=scrape_result.pricing_url,
                    content_hash=scrape_result.pricing_content_hash,
                )
                session.add(snapshot)
            elif latest_snap.content_hash != scrape_result.pricing_content_hash:
                # Content changed! Generate diff summary
                change_summary = f"Pricing content update detected on {scrape_result.pricing_url}."
                if ai_service.is_available and scrape_result.pricing_text:
                    diff_res = await ai_service.summarize_pricing_diff(
                        old_text=None, new_text=scrape_result.pricing_text
                    )
                    if diff_res and diff_res.get("summary"):
                        change_summary = diff_res["summary"]

                # Record pricing change and new snapshot
                pc = PricingChange(
                    competitor_id=competitor.id,
                    summary=change_summary,
                )
                session.add(pc)
                pricing_changes_found.append(change_summary)

                new_snap = PricingSnapshot(
                    competitor_id=competitor.id,
                    pricing_url=scrape_result.pricing_url,
                    content_hash=scrape_result.pricing_content_hash,
                )
                session.add(new_snap)

        # Determine Scan Summary & AI Strategic Insight
        scan.total_articles_found = all_articles_count
        scan.new_articles_found = len(new_article_records)
        scan.status = "COMPLETED"
        scan.completed_at = datetime.now(timezone.utc)

        if new_article_records:
            articles_dict_list = [a.to_dict() for a in new_article_records]
            # Try AI strategic insight
            if ai_service.is_available:
                ai_strat = await ai_service.generate_alert_strategy_summary(
                    competitor_name=competitor.normalized_domain,
                    articles=articles_dict_list,
                    pricing_changes=pricing_changes_found,
                )
                scan.ai_summary = ai_strat
            else:
                scan.ai_summary = f"{competitor.normalized_domain} published {len(new_article_records)} new articles."

            # Trigger Notifications (Slack & Email)
            await alert_service.send_slack_alert(
                competitor_domain=competitor.normalized_domain,
                articles=articles_dict_list,
                ai_summary=scan.ai_summary,
                pricing_changes=pricing_changes_found,
            )
            await alert_service.send_email_alert(
                competitor_domain=competitor.normalized_domain,
                articles=articles_dict_list,
                ai_summary=scan.ai_summary,
                pricing_changes=pricing_changes_found,
            )
        elif pricing_changes_found:
            scan.ai_summary = f"Pricing plan changes detected: {'; '.join(pricing_changes_found)}"
            await alert_service.send_slack_alert(
                competitor_domain=competitor.normalized_domain,
                articles=[],
                ai_summary=scan.ai_summary,
                pricing_changes=pricing_changes_found,
            )
            await alert_service.send_email_alert(
                competitor_domain=competitor.normalized_domain,
                articles=[],
                ai_summary=scan.ai_summary,
                pricing_changes=pricing_changes_found,
            )
        else:
            scan.ai_summary = "Scan complete: 0 new posts found. No duplicate alerts sent."

        await session.commit()

        return {
            "scan_id": scan.id,
            "status": "COMPLETED",
            "is_baseline": False,
            "articles_found": all_articles_count,
            "new_articles_count": len(new_article_records),
            "pricing_changes": pricing_changes_found,
            "ai_summary": scan.ai_summary,
        }

    async def simulate_new_post(
        self, session: AsyncSession, competitor_id: int
    ) -> Dict[str, Any]:
        """
        Loom Demo Helper:
        Drops the most recently added article from SQLite.
        When the user clicks 'Scan Now' on camera, that post will be immediately detected
        as NEW, triggering Groq AI enrichment, search volume, and live Slack/Email alerts!
        If no existing article exists, injects a simulated test article.
        """
        stmt = (
            select(Article)
            .where(Article.competitor_id == competitor_id)
            .order_by(desc(Article.first_seen_at))
            .limit(1)
        )
        latest_art = (await session.execute(stmt)).scalar_one_or_none()

        if latest_art:
            url_dropped = latest_art.normalized_url
            title_dropped = latest_art.title
            await session.delete(latest_art)
            await session.commit()
            return {
                "action": "unindexed_existing",
                "message": f"Successfully dropped post '{title_dropped}' from index. Click 'Scan Now' to watch MarketLens detect it as a fresh new post!",
                "dropped_url": url_dropped,
            }
        else:
            # Inject a demo post to showcase delta detection
            demo_url = f"https://demo.com/blog/ai-growth-trends-{int(datetime.now(timezone.utc).timestamp())}"
            enrichment = await enrich_article_data(
                title="AI Growth Trends & Automated Competitive Intelligence 2026",
                url=demo_url,
                meta_description="How modern teams monitor competitor product updates and content in real-time.",
            )
            new_art = Article(
                competitor_id=competitor_id,
                normalized_url=demo_url,
                title="AI Growth Trends & Automated Competitive Intelligence 2026",
                published_at=datetime.now(timezone.utc),
                meta_description="How modern teams monitor competitor product updates and content in real-time.",
                target_keyword=enrichment["target_keyword"],
                search_intent=enrichment["search_intent"],
                search_volume=enrichment["search_volume"],
                enrichment_status=enrichment["enrichment_status"],
            )
            session.add(new_art)
            await session.commit()
            return {
                "action": "injected_demo",
                "message": "Demo article added to competitor.",
                "article": new_art.to_dict(),
            }

    async def simulate_pricing_change(
        self, session: AsyncSession, competitor_id: int
    ) -> Dict[str, Any]:
        """
        Loom Demo Helper:
        Injects a simulated pricing change to showcase pricing change detection.
        """
        competitor = await session.get(Competitor, competitor_id)
        if not competitor:
            raise ValueError("Competitor not found")

        summary = "Pro Plan updated from $29/mo to $35/mo with added AI Intelligence features."
        pc = PricingChange(
            competitor_id=competitor.id,
            summary=summary,
        )
        session.add(pc)
        await session.commit()

        # Trigger notification across both Slack and Email
        await alert_service.send_slack_alert(
            competitor_domain=competitor.normalized_domain,
            articles=[],
            ai_summary="Simulated pricing change for demonstration.",
            pricing_changes=[summary],
        )
        await alert_service.send_email_alert(
            competitor_domain=competitor.normalized_domain,
            articles=[],
            ai_summary="Simulated pricing change for demonstration.",
            pricing_changes=[summary],
        )

        return {
            "message": "Simulated pricing update recorded and dispatched to alert channels.",
            "summary": summary,
        }


detector = ContentDetector()
