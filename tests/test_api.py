import pytest
import respx
from tests.test_scraper import SAMPLE_HOMEPAGE, SAMPLE_PRICING, SAMPLE_RSS


@pytest.mark.asyncio
async def test_api_status(client):
    resp = await client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app_name"] == "MarketLens"
    assert "groq_ai" in data
    assert "notifications" in data


@pytest.mark.asyncio
@respx.mock
async def test_api_competitors_lifecycle(client):
    # Setup scraper mocks for initial auto-scan: specific routes first
    respx.get("https://example.com/blog/feed").respond(200, text=SAMPLE_RSS, headers={"content-type": "application/xml"})
    respx.get("https://example.com/pricing").respond(200, text=SAMPLE_PRICING, headers={"content-type": "text/html"})
    respx.get("https://example.com/").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})
    respx.get("https://example.com").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})

    # 1. Add Competitor
    create_resp = await client.post(
        "/api/competitors",
        json={"domain": "example.com", "auto_scan": True},
    )
    assert create_resp.status_code == 201
    comp_data = create_resp.json()["competitor"]
    comp_id = comp_data["id"]
    assert comp_data["normalized_domain"] == "example.com"

    # 2. List Competitors
    list_resp = await client.get("/api/competitors")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 3. Get Competitor Details
    detail_resp = await client.get(f"/api/competitors/{comp_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert len(detail["articles"]) == 2
    assert len(detail["scans"]) == 1

    # 4. Trigger Scan
    scan_resp = await client.post(f"/api/competitors/{comp_id}/scan")
    assert scan_resp.status_code == 200
    scan_res = scan_resp.json()
    assert scan_res["new_articles_count"] == 0  # No duplicate alert on second scan

    # 5. Simulate New Post for Demo
    sim_resp = await client.post(f"/api/competitors/{comp_id}/demo/simulate-new-post")
    assert sim_resp.status_code == 200

    # 6. Delete Competitor
    del_resp = await client.delete(f"/api/competitors/{comp_id}")
    assert del_resp.status_code == 200

    # Verify deleted
    empty_list = await client.get("/api/competitors")
    assert len(empty_list.json()) == 0
