import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List
import requests
from .config import TRENDS_DIR, get_settings


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current_href = None
        self.current_text: List[str] = []
        self.links: List[Dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attr_dict = dict(attrs)
            href = attr_dict.get("href", "")
            if "/l/" in href or ".gumroad.com/l/" in href:
                self.current_href = href
                self.current_text = []

    def handle_data(self, data):
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current_href is not None:
            title = " ".join("".join(self.current_text).split())
            if title and len(title) > 3:
                self.links.append({"title": title[:140], "url": self.current_href})
            self.current_href = None
            self.current_text = []


class TrendScanner:
    """Fetches and structures digital product market signals from Gumroad Discover and category pages."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.settings = get_settings()
        TRENDS_DIR.mkdir(parents=True, exist_ok=True)

    def scan_category(self, category_key: str = "software") -> Dict[str, Any]:
        categories = self.settings.get("discover_categories", {})
        cat_info = categories.get(category_key) or {
            "label": category_key.title(),
            "url": f"https://gumroad.com/{category_key}",
            "keywords": [],
        }

        url = cat_info["url"]
        items: List[Dict[str, Any]] = []
        status = "ok"
        error_msg = None

        try:
            resp = requests.get(url, headers={"User-Agent": self.USER_AGENT}, timeout=20)
            resp.raise_for_status()
            html_text = resp.text

            parser = _LinkExtractor()
            parser.feed(html_text)
            items.extend(parser.links)

            matches = re.findall(r'"name"\s*:\s*"([^"]{4,100})"', html_text)
            for m in matches[:25]:
                if not any(i["title"] == m for i in items):
                    items.append({"title": m, "url": url})
        except Exception as exc:
            status = "partial"
            error_msg = str(exc)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report = {
            "category_key": category_key,
            "category_label": cat_info.get("label", category_key),
            "source_url": url,
            "scanned_at": timestamp,
            "status": status,
            "error": error_msg,
            "seed_keywords": cat_info.get("keywords", []),
            "discovered_products": items[:30],
        }

        out_file: Path = TRENDS_DIR / f"trend_{category_key}_{timestamp}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        report["saved_to"] = str(out_file)
        return report
