import math
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
import requests
from .config import get_gumroad_token, get_gumroad_oauth_credentials, get_default_currency


class GumroadAPIError(Exception):
    """Raised when Gumroad API v2 returns an error or non-success payload."""


class GumroadClient:
    """Wrapper for Gumroad REST API v2."""

    BASE_URL = "https://api.gumroad.com/v2"
    OAUTH_AUTHORIZE_URL = "https://gumroad.com/oauth/authorize"
    OAUTH_TOKEN_URL = "https://api.gumroad.com/oauth/token"

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token or get_gumroad_token()
        if not self.access_token:
            oauth = get_gumroad_oauth_credentials()
            if oauth.get("client_id") and oauth.get("client_secret"):
                raise GumroadAPIError(
                    "Found APPLICATION ID & APPLICATION SECRET in CREDS.txt, but GUMROAD_ACCESS_TOKEN is not set yet. "
                    "Either click 'Generate access token' under your Gumroad Application settings and add "
                    "'ACCESS TOKEN=...' to CREDS.txt, or run `python -m src.cli oauth-url` to authorize via OAuth."
                )
            raise GumroadAPIError(
                "Missing GUMROAD_ACCESS_TOKEN. Add it to CREDS.txt or .env (Settings -> Advanced -> Applications on Gumroad)."
            )

    @staticmethod
    def stage_local_file_for_ingestion(file_path: str | Path) -> str:
        """Stage a local cover or thumbnail image to a public HTTPS URL so Gumroad's media endpoints can ingest it."""
        path = Path(file_path)
        if not path.exists():
            raise GumroadAPIError(f"Local file not found: {path}")
        with open(path, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (path.name, f)},
                timeout=60,
            )
        resp.raise_for_status()
        staged_url = resp.text.strip()
        if not staged_url.startswith("https://"):
            raise GumroadAPIError(f"Unexpected staging response: {staged_url[:200]}")
        return staged_url

    def upload_product_file(self, file_path: str | Path) -> str:
        """Upload a local deliverable file using Gumroad's native /v2/files/presign -> S3 PUT -> /v2/files/complete flow."""
        path = Path(file_path)
        if not path.exists():
            raise GumroadAPIError(f"Deliverable file not found: {path}")

        file_bytes = path.read_bytes()
        file_size = len(file_bytes)

        presign_resp = self._request(
            "POST",
            "/files/presign",
            data={"filename": path.name, "file_size": str(file_size)},
        )
        upload_id = presign_resp["upload_id"]
        s3_key = presign_resp["key"]
        parts = presign_resp.get("parts", [])
        if not parts:
            raise GumroadAPIError(f"No upload parts returned from /v2/files/presign: {presign_resp}")

        chunk_size = math.ceil(file_size / len(parts)) if len(parts) > 1 else file_size
        complete_data: List[tuple] = [
            ("upload_id", upload_id),
            ("key", s3_key),
        ]

        for idx, part in enumerate(parts):
            part_num = part["part_number"]
            presigned_url = part["presigned_url"]
            start = idx * chunk_size
            end = min(start + chunk_size, file_size)
            chunk = file_bytes[start:end]

            s3_put = requests.put(presigned_url, data=chunk, timeout=120)
            s3_put.raise_for_status()
            etag = s3_put.headers.get("ETag") or s3_put.headers.get("etag")
            if not etag:
                raise GumroadAPIError(f"Missing ETag header from S3 part upload (part {part_num})")

            complete_data.append(("parts[][part_number]", str(part_num)))
            complete_data.append(("parts[][etag]", etag))

        complete_resp = self._request("POST", "/files/complete", data=complete_data)
        return complete_resp.get("file_url") or presign_resp.get("file_url")

    def sync_rich_content_files(
        self,
        product_id: str,
        gumroad_file_url: str,
        display_name: str,
        welcome_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ensure attached files are embedded directly onto the Product Content page (`rich_content` fileEmbed nodes)."""
        product = self.get_product(product_id)
        files = product.get("files", [])
        if not files:
            product = self.update_product(product_id, file_urls=[gumroad_file_url])
            files = product.get("files", [])

        if not files:
            raise GumroadAPIError(f"No attached files found on product {product_id} to embed in rich_content.")

        content_nodes: List[Dict[str, Any]] = []
        if welcome_text:
            content_nodes.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": welcome_text}],
                }
            )

        files_payload: List[Dict[str, Any]] = []
        for idx, f_obj in enumerate(files):
            file_id = f_obj.get("id")
            if not file_id:
                continue
            files_payload.append(
                {
                    "id": file_id,
                    "url": gumroad_file_url if idx == 0 and gumroad_file_url else f_obj.get("url"),
                    "display_name": display_name if idx == 0 else (f_obj.get("name") or display_name),
                }
            )
            content_nodes.append(
                {
                    "type": "fileEmbed",
                    "attrs": {
                        "id": file_id,
                        "uid": str(uuid.uuid4()),
                        "collapsed": False,
                    },
                }
            )

        content_nodes.append({"type": "paragraph"})

        existing_rc = product.get("rich_content") or []
        page_entry: Dict[str, Any] = {
            "title": None,
            "description": {
                "type": "doc",
                "content": content_nodes,
            },
        }
        if existing_rc and existing_rc[0].get("id"):
            page_entry["id"] = existing_rc[0]["id"]
            page_entry["page_id"] = existing_rc[0].get("page_id") or existing_rc[0]["id"]

        payload = {
            "has_same_rich_content_for_all_variants": True,
            "files": files_payload,
            "rich_content": [page_entry],
        }
        return self._request("PUT", f"/products/{product_id}", json=payload).get("product", {})

    @classmethod
    def build_oauth_authorize_url(cls, scope: str = "edit_products view_sales") -> str:
        oauth = get_gumroad_oauth_credentials()
        if not oauth.get("client_id") or not oauth.get("redirect_uri"):
            raise GumroadAPIError("APPLICATION ID and REDIRECT URL are required in CREDS.txt to build OAuth URL.")
        params = {
            "client_id": oauth["client_id"],
            "redirect_uri": oauth["redirect_uri"],
            "scope": scope,
            "response_type": "code",
        }
        return f"{cls.OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    @classmethod
    def exchange_oauth_code(cls, code: str) -> Dict[str, Any]:
        oauth = get_gumroad_oauth_credentials()
        if not oauth.get("client_id") or not oauth.get("client_secret") or not oauth.get("redirect_uri"):
            raise GumroadAPIError("APPLICATION ID, APPLICATION SECRET, and REDIRECT URL must be set in CREDS.txt.")
        resp = requests.post(
            cls.OAUTH_TOKEN_URL,
            data={
                "client_id": oauth["client_id"],
                "client_secret": oauth["client_secret"],
                "redirect_uri": oauth["redirect_uri"],
                "code": code,
            },
            timeout=30,
        )
        payload = resp.json()
        if not resp.ok or "access_token" not in payload:
            raise GumroadAPIError(f"OAuth token exchange failed: {payload}")
        return payload

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        headers = self._headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GumroadAPIError(f"Non-JSON response ({response.status_code}): {response.text[:300]}") from exc

        if not response.ok or not payload.get("success", False):
            msg = payload.get("message") or response.text
            raise GumroadAPIError(f"Gumroad API error ({response.status_code}): {msg}")
        return payload

    def verify_user(self) -> Dict[str, Any]:
        """Verify credentials and return the authenticated Gumroad user object."""
        return self._request("GET", "/user").get("user", {})

    def list_products(self) -> List[Dict[str, Any]]:
        """Return all products on the authenticated user's Gumroad store."""
        return self._request("GET", "/products").get("products", [])

    def get_product(self, product_id: str) -> Dict[str, Any]:
        """Retrieve details for a specific product ID."""
        return self._request("GET", f"/products/{product_id}").get("product", {})

    def create_product(
        self,
        name: str,
        price_cents: int,
        description_html: str = "",
        custom_summary: str = "",
        custom_permalink: Optional[str] = None,
        native_type: str = "digital",
        currency: Optional[str] = None,
        customizable_price: bool = False,
        suggested_price_cents: Optional[int] = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        file_urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new product on Gumroad (created as an unpublished draft by default)."""
        data: List[tuple] = [
            ("name", name),
            ("price", str(price_cents)),
            ("price_currency_type", currency or get_default_currency()),
            ("native_type", native_type),
            ("description", description_html),
            ("customizable_price", "true" if customizable_price else "false"),
        ]
        if custom_summary:
            data.append(("custom_summary", custom_summary))
        if custom_permalink:
            data.append(("custom_permalink", custom_permalink))
        if suggested_price_cents is not None:
            data.append(("suggested_price_cents", str(suggested_price_cents)))
        if category:
            data.append(("category", category))
        for tag in tags or []:
            clean_tag = str(tag).strip()[:19].strip()
            if clean_tag:
                data.append(("tags[]", clean_tag))
        for url in file_urls or []:
            data.append(("files[][url]", url))

        return self._request("POST", "/products", data=data).get("product", {})

    def update_product(self, product_id: str, file_urls: Optional[List[str]] = None, **fields) -> Dict[str, Any]:
        """Update an existing Gumroad product."""
        data: List[tuple] = []
        for key, value in fields.items():
            if value is None:
                continue
            if key == "tags" and isinstance(value, list):
                for tag in value:
                    clean_tag = str(tag).strip()[:19].strip()
                    if clean_tag:
                        data.append(("tags[]", clean_tag))
            elif isinstance(value, bool):
                data.append((key, "true" if value else "false"))
            else:
                data.append((key, str(value)))
        for url in file_urls or []:
            data.append(("files[][url]", url))
        return self._request("PUT", f"/products/{product_id}", data=data).get("product", {})

    def upload_cover(self, product_id: str, image_url_or_path: str) -> Dict[str, Any]:
        """Attach a 16:9 cover image/preview to a product via URL or automatic staging of a local file."""
        if image_url_or_path.startswith(("http://", "https://")):
            url = image_url_or_path
        else:
            url = self.stage_local_file_for_ingestion(image_url_or_path)
        return self._request("POST", f"/products/{product_id}/covers", data={"url": url})

    def upload_thumbnail(self, product_id: str, image_url_or_path: str) -> Dict[str, Any]:
        """Attach a 1:1 square thumbnail image to a product via POST /v2/products/{id}/thumbnail."""
        if image_url_or_path.startswith(("http://", "https://")):
            url = image_url_or_path
        else:
            url = self.stage_local_file_for_ingestion(image_url_or_path)
        return self._request("POST", f"/products/{product_id}/thumbnail", data={"url": url})

    def set_published(self, product_id: str, publish: bool = True) -> Dict[str, Any]:
        """Publish (`enable`) or unpublish (`disable`) a product on Gumroad."""
        action = "enable" if publish else "disable"
        return self._request("PUT", f"/products/{product_id}/{action}").get("product", {})
