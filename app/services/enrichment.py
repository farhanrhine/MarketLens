import hashlib
import logging
import re
from typing import Dict, List, Optional, Tuple

import httpx

from app.config import settings
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "ways", "top", "best", "guide", "ultimate", "simple",
    "proven", "new", "complete", "step", "steps",
}


def extract_rule_based_keyword(title: str, url: str) -> Tuple[str, str]:
    """
    Deterministic 100% offline keyword & intent extraction from Title + URL Slug.
    Works with zero APIs or external network calls.
    """
    # 1. Clean slug tokens
    path = url.split("?")[0].rstrip("/")
    slug = path.split("/")[-1] if "/" in path else ""
    slug_words = [w.lower() for w in re.split(r"[-_]", slug) if w.isalnum()]

    # 2. Clean title tokens
    clean_title = re.sub(r"[^\w\s]", " ", title)
    title_words = [w.lower() for w in clean_title.split() if w.isalnum()]

    # Filter stopwords
    slug_filtered = [w for w in slug_words if w not in STOPWORDS and len(w) > 2]
    title_filtered = [w for w in title_words if w not in STOPWORDS and len(w) > 2]

    # Combine candidates prioritizing words present in both slug and title
    intersection = [w for w in slug_filtered if w in title_filtered]
    
    if len(intersection) >= 2:
        candidate_words = intersection[:4]
    elif len(slug_filtered) >= 2:
        candidate_words = slug_filtered[:3]
    elif len(title_filtered) >= 2:
        candidate_words = title_filtered[:3]
    elif slug_filtered:
        candidate_words = slug_filtered
    elif title_filtered:
        candidate_words = title_filtered
    else:
        candidate_words = ["competitor", "strategy"]

    target_keyword = " ".join(candidate_words)

    # Detect search intent
    lower_title = title.lower()
    if any(p in lower_title for p in ["vs", "versus", "comparison", "review", "pricing", "alternative", "best"]):
        intent = "Commercial"
    elif any(p in lower_title for p in ["buy", "discount", "download", "demo", "free trial", "pricing plans"]):
        intent = "Transactional"
    else:
        intent = "Informational"

    return target_keyword, intent


def estimate_sandbox_volume(keyword: str) -> int:
    """
    Generates deterministic, realistic search volume numbers for sandbox / offline mode.
    Consistent for the same keyword.
    """
    cleaned = keyword.lower().strip()
    h = int(hashlib.md5(cleaned.encode("utf-8")).hexdigest()[:6], 16)
    
    # Bucket into realistic monthly search volumes (400 to 24,000/mo)
    word_count = len(cleaned.split())
    if word_count <= 2:
        base = 5000 + (h % 15000)
    elif word_count == 3:
        base = 1500 + (h % 6500)
    else:
        base = 400 + (h % 2200)

    # Round to clean tens/hundreds
    return int(round(base, -2))


async def fetch_search_volume(keyword: str) -> Tuple[int, str]:
    """
    Fetches search volume from configured SEO provider with resilient fallback.
    Returns (volume, status).
    """
    provider = settings.seo_provider.lower()

    if provider == "dataforseo_sandbox" and settings.seo_api_key and settings.seo_api_login:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                auth = (settings.seo_api_login, settings.seo_api_key)
                payload = [{"keywords": [keyword], "location_code": 2840, "language_code": "en"}]
                resp = await client.post(
                    "https://sandbox.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
                    json=payload,
                    auth=auth,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tasks = data.get("tasks", [])
                    if tasks and tasks[0].get("result"):
                        res = tasks[0]["result"][0]
                        vol = res.get("search_volume")
                        if vol is not None:
                            return int(vol), "SUCCESS"
        except Exception as e:
            logger.warning(f"DataForSEO Sandbox request failed for '{keyword}': {e}")

    elif provider == "rapidapi" and settings.seo_api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://keyword-research-for-seo.p.rapidapi.com/search",
                    params={"keyword": keyword},
                    headers={
                        "X-RapidAPI-Key": settings.seo_api_key,
                        "X-RapidAPI-Host": "keyword-research-for-seo.p.rapidapi.com",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    vol = data.get("search_volume") or data.get("volume")
                    if vol is not None:
                        return int(vol), "SUCCESS"
        except Exception as e:
            logger.warning(f"RapidAPI request failed for '{keyword}': {e}")

    # Fallback to realistic sandbox volume estimation
    volume = estimate_sandbox_volume(keyword)
    return volume, "FALLBACK_RULE"


async def enrich_article_data(
    title: str, url: str, meta_description: Optional[str] = None
) -> Dict[str, any]:
    """
    Enriches an article with target keyword, search intent, and estimated search volume.
    1. Tries Groq AI (if available).
    2. Falls back seamlessly to rule-based keyword extraction.
    3. Fetches / estimates search volume without ever crashing.
    """
    target_keyword = None
    search_intent = "Informational"
    enrichment_status = "PENDING"

    # 1. Attempt Groq AI Enhancement
    if ai_service.is_available:
        ai_data = await ai_service.extract_seo_keyword(title=title, url=url, meta_description=meta_description)
        if ai_data and ai_data.get("target_keyword"):
            target_keyword = ai_data["target_keyword"]
            search_intent = ai_data.get("search_intent", "Informational")
            enrichment_status = "SUCCESS"

    # 2. Rule-based Fallback if Groq unavailable or returned None
    if not target_keyword:
        target_keyword, search_intent = extract_rule_based_keyword(title=title, url=url)
        enrichment_status = "FALLBACK_RULE"

    # 3. Pull Search Volume
    volume, vol_status = await fetch_search_volume(target_keyword)
    if vol_status == "FALLBACK_RULE" and enrichment_status == "SUCCESS":
        enrichment_status = "SUCCESS_ESTIMATED_VOLUME"

    return {
        "target_keyword": target_keyword,
        "search_intent": search_intent,
        "search_volume": volume,
        "enrichment_status": enrichment_status,
    }
