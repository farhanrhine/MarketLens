import json
import logging
from typing import Any, Dict, List, Optional

from groq import AsyncGroq

from app.config import settings

logger = logging.getLogger(__name__)


class AIService:
    """
    Groq AI Enhancement Layer.
    Gracefully degrades if GROQ_API_KEY is not configured or if any API call fails.
    Model is dynamically read from settings.groq_model, never hardcoded.
    """

    def __init__(self):
        self.api_key = settings.groq_api_key
        self.model = settings.groq_model
        self.temperature = settings.groq_temperature
        self._client: Optional[AsyncGroq] = None

        if self.api_key and self.api_key.strip():
            try:
                self._client = AsyncGroq(api_key=self.api_key.strip())
            except Exception as e:
                logger.warning(f"Could not initialize Groq client: {e}")
                self._client = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    async def extract_seo_keyword(
        self, title: str, url: str, meta_description: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Extracts the primary target keyword (2-4 words) and search intent using Groq.
        Returns None on any error to trigger deterministic fallback.
        """
        if not self.is_available:
            return None

        prompt = f"""You are an expert SEO strategist. Given an article title, URL slug, and meta description, extract the exact primary target keyword (2-4 words) that this article is optimized to rank for on Google, along with search intent.
Respond ONLY with valid JSON in this schema:
{{
  "target_keyword": "string (2-4 words)",
  "search_intent": "Informational | Commercial | Transactional",
  "secondary_keywords": ["keyword 1", "keyword 2"]
}}

Article Title: {title}
Article URL: {url}
Meta Description: {meta_description or 'N/A'}
"""

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a specialized SEO keyword extraction engine. Always output valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=self.temperature,
                max_tokens=1024,
            )
            raw_content = response.choices[0].message.content
            data = json.loads(raw_content)
            if "target_keyword" in data:
                return data
            return None
        except Exception as e:
            logger.warning(f"Groq SEO keyword extraction failed ({self.model}): {e}. Falling back to rule-based.")
            return None

    async def summarize_pricing_diff(
        self, old_text: Optional[str], new_text: str
    ) -> Optional[Dict[str, Any]]:
        """
        Extracts structured plans & prices and writes a 1-sentence summary of any changes.
        """
        if not self.is_available:
            return None

        prompt = f"""Given the raw text of this competitor's pricing page:
1. Extract plan names and prices into JSON: [{{"plan": "Starter", "price": "$19/mo"}}]
2. If previous pricing text is provided, compare them and output a 1-sentence summary of changes.
Respond ONLY with valid JSON in this schema:
{{
  "plans": [{{"plan": "string", "price": "string"}}],
  "summary": "1-sentence summary of pricing changes or current tiers"
}}

Previous Pricing Text:
{old_text[:1500] if old_text else 'None (Initial snapshot)'}

Current Pricing Text:
{new_text[:2000]}
"""

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a SaaS pricing analyst. Always output valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=self.temperature,
                max_tokens=1024,
            )
            raw_content = response.choices[0].message.content
            return json.loads(raw_content)
        except Exception as e:
            logger.warning(f"Groq pricing diff failed: {e}")
            return None

    async def generate_alert_strategy_summary(
        self, competitor_name: str, articles: List[Dict[str, Any]], pricing_changes: List[str]
    ) -> Optional[str]:
        """
        Generates a concise 1-sentence strategic insight for alerts.
        """
        if not self.is_available or not articles:
            return None

        titles = [a.get("title", "") for a in articles[:5]]
        keywords = [a.get("target_keyword", "") for a in articles[:5] if a.get("target_keyword")]

        prompt = f"""Competitor '{competitor_name}' just published {len(articles)} new articles:
Titles: {titles}
Keywords: {keywords}
Pricing updates: {pricing_changes}

In exactly 1 concise, high-impact sentence, describe the competitor's apparent strategy or topical focus (e.g. "Competitor X is targeting automated AI workflows and doubling down on enterprise integrations this week.").
Return ONLY the single sentence, with no quotes or preamble.
"""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a competitive intelligence strategist."},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=1024,
            )
            return response.choices[0].message.content.strip().strip('"')
        except Exception as e:
            logger.warning(f"Groq alert strategy summary failed: {e}")
            return None

    async def explain_scan_failure(
        self, status: str, domain: str, error_details: Optional[str]
    ) -> Optional[str]:
        """
        Provides plain English explanation why a scan found nothing or was blocked.
        """
        if not self.is_available:
            return None

        prompt = f"""Explain in 1 simple, user-friendly sentence why MarketLens could not index articles for domain '{domain}'.
Status: {status}
Error detail: {error_details or 'None'}
Return ONLY the single sentence.
"""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful software diagnostics assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            return response.choices[0].message.content.strip().strip('"')
        except Exception:
            return None


ai_service = AIService()
