import re
from typing import Any, Dict, List, Optional
import requests
from .config import get_devto_api_key


class DevToAPIError(Exception):
    """Raised when Dev.to API returns an error or credentials are missing."""


def sanitize_devto_tags(tags: List[str]) -> List[str]:
    """Dev.to allows at most 4 lowercase alphanumeric tags (no spaces/hyphens)."""
    cleaned: List[str] = []
    for raw in tags:
        norm = re.sub(r"[^a-z0-9]", "", str(raw).lower())[:30]
        if norm and norm not in cleaned:
            cleaned.append(norm)
        if len(cleaned) == 4:
            break
    return cleaned or ["ai", "programming", "productivity", "webdev"]


class DevToClient:
    """Wrapper for the Forem / Dev.to REST API v1."""

    BASE_URL = "https://dev.to/api"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_devto_api_key()
        if not self.api_key:
            raise DevToAPIError(
                "Missing DEVTO_API_KEY. Generate one at https://dev.to/settings/extensions "
                "and add DEVTO_API_KEY=... to CREDS.txt, .env, or GitHub Secrets."
            )

    def publish_article(
        self,
        title: str,
        body_markdown: str,
        tags: Optional[List[str]] = None,
        published: bool = True,
        main_image: Optional[str] = None,
        canonical_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and optionally publish an article on Dev.to."""
        article: Dict[str, Any] = {
            "title": title[:128],
            "body_markdown": body_markdown,
            "published": published,
            "tags": sanitize_devto_tags(tags or []),
        }
        if main_image:
            article["main_image"] = main_image
        if canonical_url:
            article["canonical_url"] = canonical_url

        resp = requests.post(
            f"{self.BASE_URL}/articles",
            headers={
                "api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/vnd.forem.api-v1+json",
            },
            json={"article": article},
            timeout=30,
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise DevToAPIError(f"Non-JSON Dev.to response ({resp.status_code}): {resp.text[:300]}") from exc

        if not resp.ok:
            raise DevToAPIError(f"Dev.to API error ({resp.status_code}): {payload.get('error') or payload}")

        return payload
