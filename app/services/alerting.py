import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AlertService:
    """
    Manages notifications across Slack Webhook and Email (Resend / SMTP).
    Follows verbatim notification format from assignment specification.
    """

    async def send_slack_alert(
        self,
        competitor_domain: str,
        articles: List[Dict[str, Any]],
        ai_summary: Optional[str] = None,
        pricing_changes: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
    ) -> bool:
        target_webhook = webhook_url or settings.slack_webhook_url
        if not target_webhook or not target_webhook.strip():
            logger.info("No Slack webhook URL configured; skipping Slack alert.")
            return False

        count = len(articles)
        header_text = f"Competitor {competitor_domain} published {count} new posts this week"
        if count == 0 and pricing_changes:
            header_text = f"Competitor {competitor_domain} updated pricing plans"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": header_text,
                    "emoji": False,
                },
            }
        ]

        section_lines = []
        if ai_summary:
            section_lines.append(f"*AI Strategy Insight:* _{ai_summary}_\n")

        for art in articles[:10]:
            title = art.get("title", "Untitled Article")
            url = art.get("url") or art.get("normalized_url", "#")
            kw = art.get("target_keyword", "N/A")
            vol = art.get("search_volume")
            vol_str = f"{vol:,}/mo" if vol else "N/A"
            intent = art.get("search_intent", "Informational")

            line = f"- *<{url}|{title}>*\n  *Target Keyword:* `{kw}` | *Est. Volume:* `{vol_str}` | *Intent:* {intent}"
            section_lines.append(line)

        if pricing_changes:
            section_lines.append("\n*Pricing Changes Detected:*")
            for pc in pricing_changes:
                section_lines.append(f"• {pc}")

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n\n".join(section_lines) if section_lines else "No details available.",
                },
            }
        )

        payload = {
            "text": header_text,
            "blocks": blocks,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(target_webhook, json=payload)
                if resp.status_code in (200, 204):
                    logger.info(f"Slack alert successfully dispatched for {competitor_domain}")
                    return True
                else:
                    logger.warning(f"Slack webhook returned HTTP {resp.status_code}: {resp.text}")
                    return False
        except Exception as e:
            logger.warning(f"Failed to post Slack alert: {e}")
            return False

    async def send_email_alert(
        self,
        competitor_domain: str,
        articles: List[Dict[str, Any]],
        ai_summary: Optional[str] = None,
        pricing_changes: Optional[List[str]] = None,
        recipient_override: Optional[str] = None,
    ) -> bool:
        recipient = recipient_override or settings.notification_email_to
        if not recipient:
            logger.info("No recipient email configured; skipping email alert.")
            return False

        count = len(articles)
        time_tag = datetime.now(timezone.utc).strftime("%b %d, %H:%M:%S UTC")
        subject = f"Competitor {competitor_domain} published {count} new posts this week • {time_tag}"
        if count == 0 and pricing_changes:
            subject = f"Competitor {competitor_domain} updated pricing plans • {time_tag}"

        # Generate HTML Body (Birchline warm styling)
        articles_html = ""
        for art in articles:
            vol = art.get("search_volume")
            vol_str = f"{vol:,}/mo" if vol else "N/A"
            articles_html += f"""
            <div style="border-bottom: 1px solid #F0EEE6; padding: 12px 0;">
                <div style="font-weight: 500; font-size: 15px; margin-bottom: 4px;">
                    <a href="{art.get('url') or art.get('normalized_url')}" style="color: #141413; text-decoration: none;">{art.get('title')}</a>
                </div>
                <div style="font-family: monospace; font-size: 12px; color: #87867F;">
                    <span style="color: #D97757;">Keyword:</span> {art.get('target_keyword', 'N/A')} &nbsp;|&nbsp;
                    <span style="color: #D97757;">Volume:</span> {vol_str} &nbsp;|&nbsp;
                    <span style="color: #D97757;">Intent:</span> {art.get('search_intent', 'Informational')}
                </div>
            </div>
            """

        pricing_html = ""
        if pricing_changes:
            pricing_html = "<div style='margin-top: 20px;'><h3 style='font-size: 14px; text-transform: uppercase;'>Pricing Changes:</h3><ul>"
            for pc in pricing_changes:
                pricing_html += f"<li>{pc}</li>"
            pricing_html += "</ul></div>"

        html_body = f"""
        <html>
        <body style="font-family: system-ui, -apple-system, sans-serif; background-color: #FAF9F5; padding: 32px 16px; color: #141413;">
            <div style="max-width: 640px; margin: 0 auto; background: #FFFFFF; border: 1.5px solid #D1CFC5; border-radius: 12px; padding: 24px;">
                <div style="font-family: monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #87867F;">MarketLens Competitor Alert</div>
                <h1 style="font-family: Georgia, serif; font-size: 24px; font-weight: 500; margin: 8px 0 16px;">{subject}</h1>
                
                {f'<div style="background: #F0EEE6; border-radius: 6px; padding: 12px 16px; margin-bottom: 20px; font-style: italic; color: #3D3D3A;"><strong>AI Strategic Insight:</strong> {ai_summary}</div>' if ai_summary else ''}
                
                <div style="margin-top: 16px;">
                    {articles_html}
                </div>
                
                {pricing_html}
                
                <div style="margin-top: 28px; padding-top: 16px; border-top: 1px solid #D1CFC5; font-size: 12px; color: #87867F; text-align: center;">
                    Generated by MarketLens Competitor Monitoring Tool
                </div>
            </div>
        </body>
        </html>
        """

        # Resend API Provider
        if settings.email_provider.lower() == "resend" and settings.resend_api_key:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                        json={
                            "from": "MarketLens <onboarding@resend.dev>",
                            "to": [recipient],
                            "subject": subject,
                            "html": html_body,
                        },
                    )
                    if resp.status_code in (200, 201):
                        logger.info(f"Email sent via Resend to {recipient}")
                        return True
                    else:
                        logger.warning(f"Resend API returned {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.warning(f"Resend email dispatch error: {e}")

        # Standard SMTP Provider
        elif settings.email_provider.lower() == "smtp" and settings.smtp_host:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = settings.smtp_from
                msg["To"] = recipient
                msg.attach(MIMEText(html_body, "html"))

                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=8.0) as server:
                    server.starttls()
                    if settings.smtp_user and settings.smtp_password:
                        server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(settings.smtp_from, [recipient], msg.as_string())
                    logger.info(f"Email sent via SMTP to {recipient}")
                    return True
            except Exception as e:
                logger.warning(f"SMTP email dispatch error: {e}")

        return False

    async def send_test_alert(
        self,
        channel: str = "slack",
        competitor_domain: Optional[str] = None,
        articles: Optional[List[Dict[str, Any]]] = None,
        ai_summary: Optional[str] = None,
        pricing_changes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Sends an alert (either for a real competitor or fallback sample)."""
        target_domain = competitor_domain or "acme.com"
        target_articles = articles if articles is not None else [
            {
                "title": "10 Proven Ways to Automate Competitor Tracking in 2026",
                "url": "https://example.com/blog/automate-competitor-tracking",
                "target_keyword": "automate competitor tracking",
                "search_volume": 12100,
                "search_intent": "Informational",
            },
            {
                "title": "SaaS Pricing Strategy Guide for Growth Teams",
                "url": "https://example.com/blog/pricing-tips",
                "target_keyword": "saas pricing strategy",
                "search_volume": 8400,
                "search_intent": "Commercial",
            },
        ]
        target_summary = ai_summary or f"Competitor {target_domain} is heavily targeting automated intelligence workflows this week."
        target_pricing = pricing_changes if pricing_changes is not None else ["Pro plan updated to $35/mo with annual billing option"]

        if channel == "slack":
            success = await self.send_slack_alert(
                competitor_domain=target_domain,
                articles=target_articles,
                ai_summary=target_summary,
                pricing_changes=target_pricing,
            )
            return {"channel": "slack", "success": success, "message": f"Test alert for {target_domain} sent to Slack!" if success else "Failed to send Slack alert. Check SLACK_WEBHOOK_URL."}
        else:
            success = await self.send_email_alert(
                competitor_domain=target_domain,
                articles=target_articles,
                ai_summary=target_summary,
                pricing_changes=target_pricing,
            )
            return {"channel": "email", "success": success, "message": f"Real alert for {target_domain} sent to your Email!" if success else "Failed to send Email alert. Check RESEND_API_KEY in .env."}


alert_service = AlertService()

