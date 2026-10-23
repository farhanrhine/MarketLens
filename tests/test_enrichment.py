import pytest
from app.services.enrichment import (
    extract_rule_based_keyword,
    estimate_sandbox_volume,
    enrich_article_data,
)


def test_rule_based_keyword_extraction():
    title = "10 Proven Ways to Automate Competitor Tracking in 2026"
    url = "https://competitor.com/blog/automate-competitor-tracking"

    keyword, intent = extract_rule_based_keyword(title, url)
    assert "competitor" in keyword.lower() or "tracking" in keyword.lower() or "automate" in keyword.lower()
    assert intent == "Informational"


def test_commercial_intent_detection():
    title = "Top 5 Competitor Monitoring Tools vs Manual Spreadsheets"
    url = "https://competitor.com/blog/best-competitor-monitoring-tools-vs-manual"

    keyword, intent = extract_rule_based_keyword(title, url)
    assert intent == "Commercial"


def test_estimate_sandbox_volume():
    vol1 = estimate_sandbox_volume("automate competitor tracking")
    vol2 = estimate_sandbox_volume("automate competitor tracking")
    assert vol1 == vol2  # Deterministic
    assert vol1 > 0


@pytest.mark.asyncio
async def test_enrich_article_data_offline_fallback():
    # Runs with Groq offline (GROQ_API_KEY=None)
    data = await enrich_article_data(
        title="Comprehensive SaaS Churn Reduction Playbook",
        url="https://saas.io/blog/saas-churn-reduction-playbook",
        meta_description="Learn proven strategies to reduce SaaS customer churn.",
    )
    assert "target_keyword" in data
    assert data["target_keyword"] is not None
    assert data["search_volume"] > 0
    assert data["enrichment_status"] == "FALLBACK_RULE"
