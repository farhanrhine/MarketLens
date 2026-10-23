import hashlib
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import defusedxml.ElementTree as ET
import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Browser Fingerprint Headers (Preventing 403 / Cloudflare blocks as in spec.md)
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

COMMON_FEED_PATHS = [
    "/blog/feed",
    "/feed",
    "/rss",
    "/rss.xml",
    "/blog/rss.xml",
    "/atom.xml",
    "/blog/atom.xml",
    "/feed/rss",
    "/feed/atom",
]

COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/blog-sitemap.xml",
    "/post-sitemap.xml",
    "/posts-sitemap.xml",
    "/sitemap-posts.xml",
]

COMMON_BLOG_PATHS = [
    "/blog",
    "/resources",
    "/articles",
    "/insights",
    "/news",
    "/learn",
]

COMMON_PRICING_PATHS = [
    "/pricing",
    "/pricing-plans",
    "/plans",
    "/product/pricing",
    "/subscription",
]


def normalize_domain(domain_input: str) -> Tuple[str, str]:
    """
    Normalizes user domain input (e.g. 'clickup.com', 'https://buffer.com/blog')
    Returns (base_url, normalized_domain).
    """
    raw = domain_input.strip()
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "https://" + raw

    parsed = urlparse(raw)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return base_url, netloc


def clean_url(url: str) -> str:
    """Strips query parameters and fragments for canonical matching."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def is_likely_article_url(url: str, domain: str) -> bool:
    """Heuristic check to determine if a URL is likely an article/blog post."""
    parsed = urlparse(url)
    if parsed.netloc and domain not in parsed.netloc:
        return False

    path = parsed.path.lower().rstrip("/")
    if not path or path in ["", "/blog", "/resources", "/articles", "/insights", "/news", "/pricing", "/about", "/contact"]:
        return False

    # Skip common non-article extensions
    if any(path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".css", ".js", ".xml"]):
        return False

    # Check for blog path components or slug patterns
    indicators = ["/blog/", "/resources/", "/articles/", "/insights/", "/post/", "/posts/", "/news/"]
    has_indicator = any(ind in path for ind in indicators)

    # Date pattern in path like /2024/03/post-name or /2023/
    has_date = bool(re.search(r"/\d{4}/\d{2}/", path) or re.search(r"/\d{4}/", path))

    # Slug has hyphens and reasonable length
    slug = path.split("/")[-1]
    has_slug = "-" in slug and len(slug) > 8

    # Skip pagination, tag, author, category index pages
    skip_patterns = ["/page/", "/category/", "/tag/", "/author/", "/archive/", "/feed", "/wp-content/", "/wp-json/"]
    if any(pat in path for pat in skip_patterns):
        return False

    return has_indicator or has_date or has_slug


class ScrapedArticleData:
    def __init__(
        self,
        url: str,
        title: str,
        published_at: Optional[datetime] = None,
        meta_description: Optional[str] = None,
    ):
        self.url = clean_url(url)
        self.title = title.strip() if title else ""
        self.published_at = published_at
        self.meta_description = meta_description.strip() if meta_description else None

    def to_dict(self):
        return {
            "url": self.url,
            "title": self.title,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "meta_description": self.meta_description,
        }


class ScrapeResult:
    def __init__(self):
        self.status: str = "COMPLETED"  # COMPLETED, NO_BLOG, BLOCKED, FAILED
        self.blog_url: Optional[str] = None
        self.pricing_url: Optional[str] = None
        self.pricing_content_hash: Optional[str] = None
        self.pricing_text: Optional[str] = None
        self.articles: List[ScrapedArticleData] = []
        self.error_message: Optional[str] = None
        self.tier_found: Optional[str] = None  # RSS, SITEMAP, HTML


class CompetitorScraper:
    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    async def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=self.timeout,
            verify=False,  # Avoid SSL failure on self-signed / misconfigured certs
        )

    async def fetch_page(self, client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
        try:
            resp = await client.get(url)
            return resp
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return None

    def check_for_anti_bot(self, response: httpx.Response) -> bool:
        """Detect Cloudflare, Incapsula, or 403 anti-bot challenges."""
        if response.status_code in (403, 429, 503):
            return True
        text = response.text.lower()
        if "cf-ray" in response.headers or "cloudflare" in text:
            if "just a moment..." in text or "attention required" in text or "turnstile" in text:
                return True
        return False

    async def scrape(self, domain_input: str) -> ScrapeResult:
        result = ScrapeResult()
        base_url, domain = normalize_domain(domain_input)

        async with await self._create_client() as client:
            # 1. Preflight check to domain root
            homepage_resp = await self.fetch_page(client, base_url)
            if homepage_resp is None:
                # Try with www if bare domain failed
                alt_base = base_url.replace("https://", "https://www.") if "www." not in base_url else base_url.replace("www.", "")
                homepage_resp = await self.fetch_page(client, alt_base)
                if homepage_resp is not None:
                    base_url = alt_base

            if homepage_resp is None:
                result.status = "FAILED"
                result.error_message = f"Could not establish connection to {domain_input}"
                return result

            if self.check_for_anti_bot(homepage_resp):
                result.status = "BLOCKED"
                result.error_message = "Site Protected by Anti-Bot Shield (403/Cloudflare)"
                return result

            homepage_html = homepage_resp.text
            homepage_soup = BeautifulSoup(homepage_html, "lxml")

            # Discover Pricing Page
            await self._discover_pricing(client, base_url, homepage_soup, result)

            # Discover Blog Page URL
            blog_url = self._discover_blog_url(base_url, homepage_soup)
            result.blog_url = blog_url

            discovered_articles: Dict[str, ScrapedArticleData] = {}

            # Tier 1: RSS / Atom Feeds
            articles_tier1 = await self._tier1_rss(client, base_url, blog_url, homepage_soup, domain)
            for art in articles_tier1:
                discovered_articles[art.url] = art

            if discovered_articles:
                result.tier_found = "RSS"

            # Tier 2: Sitemaps (if Tier 1 yielded < 5 articles or none)
            if len(discovered_articles) < 5:
                articles_tier2 = await self._tier2_sitemaps(client, base_url, domain)
                for art in articles_tier2:
                    if art.url not in discovered_articles:
                        discovered_articles[art.url] = art
                if articles_tier2 and not result.tier_found:
                    result.tier_found = "SITEMAP"

            # Tier 3: HTML Crawler (if still < 5 articles or none)
            if len(discovered_articles) < 5:
                articles_tier3 = await self._tier3_html(client, base_url, blog_url, domain, homepage_soup)
                for art in articles_tier3:
                    if art.url not in discovered_articles:
                        discovered_articles[art.url] = art
                if articles_tier3 and not result.tier_found:
                    result.tier_found = "HTML"

            # Convert to list and sort
            result.articles = list(discovered_articles.values())

            # Check if site has no blog
            if not result.articles and not blog_url:
                result.status = "NO_BLOG"
                result.error_message = "No blog or editorial section detected on this domain"
            elif not result.articles and blog_url:
                # Blog page exists but no posts could be extracted
                result.status = "NO_BLOG"
                result.error_message = f"Found section {blog_url} but no article posts detected"

            return result

    def _discover_blog_url(self, base_url: str, soup: BeautifulSoup) -> Optional[str]:
        # Check nav / header / footer links for blog
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True).lower()
            if text in ["blog", "our blog", "articles", "resources", "insights", "news"]:
                full_url = urljoin(base_url, href)
                return clean_url(full_url)
            for path in COMMON_BLOG_PATHS:
                if href.rstrip("/") == path or href.rstrip("/") == f"{base_url}{path}":
                    return clean_url(urljoin(base_url, href))

        # Default fallback candidate
        return urljoin(base_url, "/blog")

    async def _discover_pricing(
        self, client: httpx.AsyncClient, base_url: str, soup: BeautifulSoup, result: ScrapeResult
    ):
        pricing_url = None
        # Look for explicit link with 'pricing' in href or text
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True).lower()
            if "pricing" in href.lower() or "pricing" in text or "plans" in text:
                pricing_url = urljoin(base_url, href)
                break

        if not pricing_url:
            for p in COMMON_PRICING_PATHS:
                test_url = urljoin(base_url, p)
                resp = await self.fetch_page(client, test_url)
                if resp and resp.status_code == 200:
                    pricing_url = test_url
                    break

        if pricing_url:
            result.pricing_url = pricing_url
            resp = await self.fetch_page(client, pricing_url)
            if resp and resp.status_code == 200:
                p_soup = BeautifulSoup(resp.text, "lxml")
                # Remove scripts, styles, navigations to focus on content
                for elem in p_soup(["script", "style", "nav", "footer", "header", "noscript"]):
                    elem.decompose()
                clean_text = " ".join(p_soup.get_text(separator=" ").split())
                # Keep first 3000 chars for comparison and hashing
                sample_text = clean_text[:3000]
                result.pricing_text = sample_text
                result.pricing_content_hash = hashlib.sha256(sample_text.encode("utf-8")).hexdigest()

    async def _tier1_rss(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        blog_url: Optional[str],
        homepage_soup: BeautifulSoup,
        domain: str,
    ) -> List[ScrapedArticleData]:
        candidates: Set[str] = set()

        # Check <link rel="alternate" type="application/rss+xml">
        for link in homepage_soup.find_all("link", rel=lambda r: r and "alternate" in r):
            t = link.get("type", "")
            if "rss" in t or "atom" in t or "xml" in t:
                href = link.get("href")
                if href:
                    candidates.add(urljoin(base_url, href))

        # Check common paths
        for path in COMMON_FEED_PATHS:
            candidates.add(urljoin(base_url, path))
            if blog_url:
                candidates.add(urljoin(blog_url + "/", path.lstrip("/")))

        articles: List[ScrapedArticleData] = []
        for feed_url in candidates:
            try:
                resp = await self.fetch_page(client, feed_url)
                if resp and resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "").lower()
                    if "xml" in content_type or "<rss" in resp.text[:200] or "<feed" in resp.text[:200]:
                        feed = feedparser.parse(resp.text)
                        if feed.entries:
                            for entry in feed.entries[:30]:
                                link = getattr(entry, "link", None)
                                title = getattr(entry, "title", None)
                                if link and title and is_likely_article_url(link, domain):
                                    published = None
                                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                                        try:
                                            published = datetime(*entry.published_parsed[:6])
                                        except Exception:
                                            pass
                                    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
                                    clean_summary = BeautifulSoup(summary, "html.parser").get_text()[:250] if summary else None
                                    articles.append(
                                        ScrapedArticleData(
                                            url=link,
                                            title=title,
                                            published_at=published,
                                            meta_description=clean_summary,
                                        )
                                    )
                            if articles:
                                return articles
            except Exception as e:
                logger.debug(f"Feed parse error for {feed_url}: {e}")

        return articles

    async def _tier2_sitemaps(
        self, client: httpx.AsyncClient, base_url: str, domain: str
    ) -> List[ScrapedArticleData]:
        candidates = [urljoin(base_url, p) for p in COMMON_SITEMAP_PATHS]

        # Check robots.txt for Sitemap:
        robots_resp = await self.fetch_page(client, urljoin(base_url, "/robots.txt"))
        if robots_resp and robots_resp.status_code == 200:
            for line in robots_resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    s_url = line.split(":", 1)[1].strip()
                    if s_url not in candidates:
                        candidates.insert(0, s_url)

        articles: List[ScrapedArticleData] = []
        for sitemap_url in candidates:
            try:
                resp = await self.fetch_page(client, sitemap_url)
                if resp and resp.status_code == 200:
                    try:
                        root = ET.fromstring(resp.content)
                    except Exception:
                        continue

                    # Namespace handling: remove namespaces for easy xpath
                    urls_found = []
                    for elem in root.iter():
                        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                        if tag == "loc" and elem.text:
                            loc_url = elem.text.strip()
                            urls_found.append(loc_url)

                    # If it's a sitemap index with nested sitemaps
                    nested_sitemaps = [u for u in urls_found if "post" in u or "blog" in u or "article" in u]
                    if nested_sitemaps:
                        for n_sitemap in nested_sitemaps[:3]:
                            sub_resp = await self.fetch_page(client, n_sitemap)
                            if sub_resp and sub_resp.status_code == 200:
                                try:
                                    sub_root = ET.fromstring(sub_resp.content)
                                    for sub_elem in sub_root.iter():
                                        sub_tag = sub_elem.tag.split("}")[-1] if "}" in sub_elem.tag else sub_elem.tag
                                        if sub_tag == "loc" and sub_elem.text:
                                            urls_found.append(sub_elem.text.strip())
                                except Exception:
                                    pass

                    # Filter for likely article URLs
                    article_urls = [u for u in urls_found if is_likely_article_url(u, domain)]
                    # Sort or limit to recent 15
                    for u in article_urls[-25:]:
                        title = self._url_to_candidate_title(u)
                        articles.append(ScrapedArticleData(url=u, title=title))

                    if articles:
                        return articles
            except Exception as e:
                logger.debug(f"Sitemap error {sitemap_url}: {e}")

        return articles

    async def _tier3_html(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        blog_url: Optional[str],
        domain: str,
        homepage_soup: BeautifulSoup,
    ) -> List[ScrapedArticleData]:
        pages_to_check = [base_url]
        if blog_url and blog_url != base_url:
            pages_to_check.insert(0, blog_url)

        discovered_urls: Set[str] = set()

        for page_url in pages_to_check:
            soup = homepage_soup if page_url == base_url else None
            if not soup:
                resp = await self.fetch_page(client, page_url)
                if resp and resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")

            if not soup:
                continue

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                full_url = clean_url(urljoin(page_url, href))
                if is_likely_article_url(full_url, domain):
                    discovered_urls.add(full_url)

        articles: List[ScrapedArticleData] = []
        # For the discovered URLs (up to 12), enrich title and meta by inspecting or fallback
        for u in list(discovered_urls)[:15]:
            title = self._url_to_candidate_title(u)
            meta_desc = None
            pub_date = None

            # Quick fetch metadata for the top articles
            try:
                art_resp = await self.fetch_page(client, u)
                if art_resp and art_resp.status_code == 200:
                    art_soup = BeautifulSoup(art_resp.text, "lxml")
                    og_title = art_soup.find("meta", property="og:title")
                    if og_title and og_title.get("content"):
                        title = og_title["content"].strip()
                    elif art_soup.title and art_soup.title.string:
                        title = art_soup.title.string.strip()

                    og_desc = art_soup.find("meta", property="og:description") or art_soup.find("meta", attrs={"name": "description"})
                    if og_desc and og_desc.get("content"):
                        meta_desc = og_desc["content"].strip()

                    # Published date
                    pub_meta = art_soup.find("meta", property="article:published_time")
                    if pub_meta and pub_meta.get("content"):
                        try:
                            pub_date = datetime.fromisoformat(pub_meta["content"].replace("Z", "+00:00"))
                        except Exception:
                            pass
            except Exception:
                pass

            articles.append(ScrapedArticleData(url=u, title=title, published_at=pub_date, meta_description=meta_desc))

        return articles

    def _url_to_candidate_title(self, url: str) -> str:
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        words = slug.replace("-", " ").replace("_", " ").split()
        return " ".join(words).title() if words else "Article"
