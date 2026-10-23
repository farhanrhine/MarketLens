import pytest
import respx
from app.services.alerting import alert_service


@pytest.mark.asyncio
@respx.mock
async def test_slack_block_kit_payload():
    mock_webhook = "https://hooks.slack.com/services/TEST/TOKEN/123"
    slack_route = respx.post(mock_webhook).respond(200, text="ok")

    articles = [
        {
            "title": "How to Automate Competitor Tracking",
            "url": "https://acme.com/blog/seo-2026",
            "target_keyword": "automate competitor tracking",
            "search_volume": 12100,
            "search_intent": "Informational",
        },
        {
            "title": "SaaS Pricing Strategy Guide",
            "url": "https://acme.com/blog/pricing-tips",
            "target_keyword": "saas pricing strategy",
            "search_volume": 8400,
            "search_intent": "Commercial",
        },
    ]

    success = await alert_service.send_slack_alert(
        competitor_domain="acme.com",
        articles=articles,
        ai_summary="Competitor acme.com is heavily targeting automated intelligence workflows this week.",
        pricing_changes=["Pro plan updated to $35/mo"],
        webhook_url=mock_webhook,
    )

    assert success is True
    assert slack_route.called
    sent_request = slack_route.calls.last.request
    import json
    payload = json.loads(sent_request.content)

    assert "Competitor acme.com published 2 new posts this week" in payload["text"]
    assert len(payload["blocks"]) >= 2
    # Check header
    assert payload["blocks"][0]["text"]["text"] == "Competitor acme.com published 2 new posts this week"
    # Check markdown body
    body_text = payload["blocks"][1]["text"]["text"]
    assert "automate competitor tracking" in body_text
    assert "12,100/mo" in body_text
    assert "https://acme.com/blog/seo-2026" in body_text
