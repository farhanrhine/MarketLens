import pytest
import respx
import httpx
from app.services.scraper import (
    CompetitorScraper,
    normalize_domain,
    clean_url,
    is_likely_article_url,
)

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Blog</title>
    <link>https://example.com/blog</link>
    <item>
      <title>10 Proven Ways to Automate Competitor Tracking</title>
      <link>https://example.com/blog/automate-competitor-tracking</link>
      <description>Learn how to monitor competitors automatically.</description>
      <pubDate>Mon, 15 Jan 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>SaaS Pricing Strategy Guide for Growth Teams</title>
      <link>https://example.com/blog/pricing-strategy-guide</link>
      <description>Everything about SaaS pricing tiers.</description>
      <pubDate>Wed, 17 Jan 2026 14:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_HOMEPAGE = """<!doctype html>
<html>
<head>
  <title>Acme Software</title>
  <link rel="alternate" type="application/rss+xml" title="Blog RSS" href="/blog/feed" />
</head>
<body>
  <nav>
    <a href="/pricing">Pricing Plans</a>
    <a href="/blog">Our Blog</a>
  </nav>
  <h1>Welcome to Acme</h1>
</body>
</html>
"""

SAMPLE_PRICING = """<!doctype html>
<html>
<body>
  <h1>Pricing Plans</h1>
  <div class="pricing-card"><h3>Starter</h3><p>$19/mo</p></div>
  <div class="pricing-card"><h3>Pro</h3><p>$49/mo</p></div>
</body>
</html>
"""


def test_normalize_domain():
    base, norm = normalize_domain("https://www.clickup.com/blog")
    assert base == "https://www.clickup.com"
    assert norm == "clickup.com"

    base2, norm2 = normalize_domain("buffer.com/")
    assert base2 == "https://buffer.com"
    assert norm2 == "buffer.com"


def test_is_likely_article_url():
    assert is_likely_article_url("https://example.com/blog/automated-testing-guide", "example.com") is True
    assert is_likely_article_url("https://example.com/2026/01/how-to-grow", "example.com") is True
    assert is_likely_article_url("https://example.com/pricing", "example.com") is False
    assert is_likely_article_url("https://example.com/blog", "example.com") is False
    assert is_likely_article_url("https://otherdomain.com/blog/post", "example.com") is False


@pytest.mark.asyncio
@respx.mock
async def test_scraper_rss_tier1():
    scraper = CompetitorScraper()

    # Mock specific subpaths first
    respx.get("https://example.com/blog/feed").respond(200, text=SAMPLE_RSS, headers={"content-type": "application/xml"})
    respx.get("https://example.com/pricing").respond(200, text=SAMPLE_PRICING, headers={"content-type": "text/html"})
    # Mock homepage
    respx.get("https://example.com/").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})
    respx.get("https://example.com").respond(200, text=SAMPLE_HOMEPAGE, headers={"content-type": "text/html"})

    result = await scraper.scrape("example.com")
    assert result.status == "COMPLETED"
    assert len(result.articles) == 2
    assert result.articles[0].title == "10 Proven Ways to Automate Competitor Tracking"
    assert result.pricing_url == "https://example.com/pricing"
    assert result.pricing_content_hash is not None


@pytest.mark.asyncio
@respx.mock
async def test_scraper_no_blog_detected():
    scraper = CompetitorScraper()
    # Homepage with no blog links or feeds
    static_html = "<html><body><h1>Static Landing Page</h1><p>Contact us at info@example.com</p></body></html>"
    respx.get("https://noblog.com").respond(200, text=static_html)
    # 404 on common feeds
    respx.get(respx.patterns.M("https://noblog.com/.*")).respond(404)

    result = await scraper.scrape("noblog.com")
    assert result.status == "NO_BLOG"
    assert len(result.articles) == 0


@pytest.mark.asyncio
@respx.mock
async def test_scraper_cloudflare_blocked():
    scraper = CompetitorScraper()
    # 403 response simulating bot block
    respx.get("https://protected.com").respond(
        403,
        text="<html><body>Attention Required! Cloudflare Turnstile Challenge</body></html>",
        headers={"cf-ray": "8439023480"}
    )

    result = await scraper.scrape("protected.com")
    assert result.status == "BLOCKED"
    assert "Anti-Bot" in result.error_message
