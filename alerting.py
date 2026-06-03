import logging
import os

import requests as _requests

logger = logging.getLogger(__name__)


def send_alert(title: str, message: str, level: str = "error") -> None:
    """
    POST a Slack/Discord-compatible alert to ALERT_WEBHOOK_URL.
    Silently skips when the env var is not set.
    """
    webhook_url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return

    scraper_name = os.getenv("SCRAPER_NAME", "charging-scraper")
    text = f"*[{level.upper()}] {scraper_name}: {title}*\n{message}"

    try:
        resp = _requests.post(webhook_url, json={"text": text}, timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"Failed to send alert: {exc}")
