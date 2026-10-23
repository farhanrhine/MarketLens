import pytest
import respx
from app.db.models import Competitor
from app.services.detector import detector
from tests.test_scraper import SAMPLE_HOMEPAGE, SAMPLE_PRICING, SAMPLE_RSS

SAMPLE_RSS_WITH_NEW_POST = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Blog</title>
    <link>https://example.com/blog</link>
    <item>
      <title>10 Proven Ways to Automate Competitor Tracking</title>
      <link>https://example.com/blog/automate-competitor-tracking</link>
      <pubDate>Mon, 15 Jan 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>SaaS Pricing Strategy Guide for Growth Teams</title>
      <link>https://example.com/blog/pricing-strategy-guide</link>
      <pubDate>Wed, 17 Jan 2026 14:00:00 GMT</pubDate>
    </item>
    <item>
      <title>BRAND NEW: The Future of AI Search Optimization</title>
      <link>https://example.com/blog/future-ai-search-optimization</link>
      <pubDate>Fri, 19 Jan 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
@respx.mock
async def test_baseline_and_delta_scans(db_session):
    # Setup mocks: specific subpaths first
    feed_route = respx.get("https://example.com/blog/feed").respond(200, text=SAMPLE_RSS, headers={"content-type": "application/xml"})
    respx.get("https://example.com/pricing").respond(200, text=SAMPLE_PRICING, headers={"content-type": "text/html"})
    respx.get("https://example.com/").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})
    respx.get("https://example.com").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})

    # 1. Register Competitor
    comp = Competitor(domain="example.com", normalized_domain="example.com", status="ACTIVE")
    db_session.add(comp)
    await db_session.commit()
    await db_session.refresh(comp)

    # 2. First Scan (Baseline)
    res1 = await detector.execute_scan(db_session, comp.id)
    assert res1["status"] == "COMPLETED"
    assert res1["is_baseline"] is True
    assert res1["articles_found"] == 2
    assert res1["new_articles_count"] == 0  # Baseline indexes without false "new" alert

    # 3. Second Scan (Delta Scan with same data)
    res2 = await detector.execute_scan(db_session, comp.id)
    assert res2["status"] == "COMPLETED"
    assert res2["is_baseline"] is False
    assert res2["new_articles_count"] == 0
    assert "0 new posts found. No duplicate alerts sent." in res2["ai_summary"]

    # 4. Third Scan: Competitor publishes a new post
    feed_route.respond(200, text=SAMPLE_RSS_WITH_NEW_POST, headers={"content-type": "application/xml"})
    res3 = await detector.execute_scan(db_session, comp.id)
    assert res3["status"] == "COMPLETED"
    assert res3["is_baseline"] is False
    assert res3["new_articles_count"] == 1
    assert res3["articles_found"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_pricing_change_detection(db_session):
    respx.get("https://example.com/blog/feed").respond(200, text=SAMPLE_RSS, headers={"content-type": "application/xml"})
    pricing_route = respx.get("https://example.com/pricing").respond(200, text=SAMPLE_PRICING, headers={"content-type": "text/html"})
    respx.get("https://example.com/").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})
    respx.get("https://example.com").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})

    comp = Competitor(domain="example.com", normalized_domain="example.com", status="ACTIVE")
    db_session.add(comp)
    await db_session.commit()

    # Initial baseline scan
    await detector.execute_scan(db_session, comp.id)

    # Competitor updates pricing page
    UPDATED_PRICING = """<!doctype html>
    <html><body><h1>Pricing Plans</h1><div class="pricing-card"><h3>Pro Plan</h3><p>$59/mo (was $49)</p></div></body></html>
    """
    pricing_route.respond(200, text=UPDATED_PRICING, headers={"content-type": "text/html"})

    res_delta = await detector.execute_scan(db_session, comp.id)
    assert len(res_delta["pricing_changes"]) > 0
    assert "Pricing content update detected" in res_delta["pricing_changes"][0]


@pytest.mark.asyncio
@respx.mock
async def test_simulate_new_post_demo(db_session):
    respx.get("https://example.com/blog/feed").respond(200, text=SAMPLE_RSS, headers={"content-type": "application/xml"})
    respx.get("https://example.com/pricing").respond(200, text=SAMPLE_PRICING, headers={"content-type": "text/html"})
    respx.get("https://example.com/").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})
    respx.get("https://example.com").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})

    comp = Competitor(domain="example.com", normalized_domain="example.com", status="ACTIVE")
    db_session.add(comp)
    await db_session.commit()

    # Baseline scan
    await detector.execute_scan(db_session, comp.id)

    # Click "Simulate New Post (Demo)"
    sim_res = await detector.simulate_new_post(db_session, comp.id)
    assert sim_res["action"] == "unindexed_existing"

    # Now click "Scan Now" - it should immediately flag the unindexed post as brand new!
    scan_after = await detector.execute_scan(db_session, comp.id)
    assert scan_after["new_articles_count"] == 1
