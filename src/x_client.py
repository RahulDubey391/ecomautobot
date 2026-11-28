import base64
import hashlib
import hmac
import time
import uuid
from typing import Any, Dict, Optional
from urllib.parse import quote
import requests
from .config import get_x_credentials


class XAPIError(Exception):
    """Raised when X (Twitter) API v2 returns an error or credentials are missing."""


def _pct(value: str) -> str:
    return quote(str(value), safe="~")


class XClient:
    """Minimal OAuth 1.0a User-Context client for X API v2 (zero external OAuth dependencies)."""

    TWEETS_URL = "https://api.x.com/2/tweets"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
    ):
        creds = get_x_credentials()
        self.api_key = api_key or creds["api_key"]
        self.api_key_secret = api_key_secret or creds["api_key_secret"]
        self.access_token = access_token or creds["access_token"]
        self.access_token_secret = access_token_secret or creds["access_token_secret"]

        if not all([self.api_key, self.api_key_secret, self.access_token, self.access_token_secret]):
            raise XAPIError(
                "Missing X OAuth 1.0a credentials. Set X_API_KEY, X_API_KEY_SECRET, "
                "X_ACCESS_TOKEN, and X_ACCESS_TOKEN_SECRET in CREDS.txt, .env, or GitHub Secrets."
            )

    def _oauth1_header(self, method: str, url: str) -> str:
        oauth_params = {
            "oauth_consumer_key": self.api_key,
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.access_token,
            "oauth_version": "1.0",
        }
        sorted_items = sorted((_pct(k), _pct(v)) for k, v in oauth_params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
        base_str = f"{method.upper()}&{_pct(url)}&{_pct(param_str)}"
        signing_key = f"{_pct(self.api_key_secret)}&{_pct(self.access_token_secret)}"
        digest = hmac.new(signing_key.encode("utf-8"), base_str.encode("utf-8"), hashlib.sha1).digest()
        oauth_params["oauth_signature"] = base64.b64encode(digest).decode("utf-8")

        header_parts = ", ".join(
            f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth_params.items())
        )
        return f"OAuth {header_parts}"

    def post_tweet(self, text: str, reply_to_id: Optional[str] = None) -> Dict[str, Any]:
        """Publish a post on X via POST /2/tweets."""
        payload: Dict[str, Any] = {"text": text}
        if reply_to_id:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}

        resp = requests.post(
            self.TWEETS_URL,
            headers={
                "Authorization": self._oauth1_header("POST", self.TWEETS_URL),
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise XAPIError(f"Non-JSON X response ({resp.status_code}): {resp.text[:300]}") from exc

        if not resp.ok:
            raise XAPIError(f"X API error ({resp.status_code}): {data}")

        tweet_data = data.get("data", {})
        tweet_id = tweet_data.get("id")
        return {
            "id": tweet_id,
            "text": tweet_data.get("text", text),
            "url": f"https://x.com/i/web/status/{tweet_id}" if tweet_id else None,
        }
