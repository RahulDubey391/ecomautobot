import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR.parent
ENV_PATH = BASE_DIR / ".env"
CREDS_TXT_PATH = WORKSPACE_DIR / "CREDS.txt"
CONFIG_PATH = BASE_DIR / "config" / "settings.json"
PRODUCTS_DIR = BASE_DIR / "products"
TRENDS_DIR = BASE_DIR / "data" / "trends"

KEY_ALIASES = {
    "ACCESS TOKEN": "GUMROAD_ACCESS_TOKEN",
    "ACCESS_TOKEN": "GUMROAD_ACCESS_TOKEN",
    "GUMROAD_TOKEN": "GUMROAD_ACCESS_TOKEN",
    "APPLICATION ID": "GUMROAD_APPLICATION_ID",
    "APPLICATION SECRET": "GUMROAD_APPLICATION_SECRET",
    "APPLICATION NAME": "GUMROAD_APPLICATION_NAME",
    "REDIRECT URL": "GUMROAD_REDIRECT_URL",
    "USERNAME": "GUMROAD_USERNAME",
    "USEREMAIL": "GUMROAD_USER_EMAIL",
    "GEMINI API KEY": "GEMINI_API_KEY",
    "GOOGLE_API_KEY": "GEMINI_API_KEY",
}


def _load_kv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        clean_key = key.strip()
        clean_val = val.strip().strip('"').strip("'")
        if not clean_val:
            continue
        os.environ[clean_key] = clean_val
        mapped_key = KEY_ALIASES.get(clean_key.upper())
        if mapped_key:
            os.environ[mapped_key] = clean_val


_load_kv_file(ENV_PATH)
_load_kv_file(CREDS_TXT_PATH)


def get_settings() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_gumroad_token() -> str:
    return os.getenv("GUMROAD_ACCESS_TOKEN", "").strip()


def get_gumroad_oauth_credentials() -> dict:
    return {
        "client_id": os.getenv("GUMROAD_APPLICATION_ID", "").strip(),
        "client_secret": os.getenv("GUMROAD_APPLICATION_SECRET", "").strip(),
        "redirect_uri": os.getenv("GUMROAD_REDIRECT_URL", "").strip(),
        "username": os.getenv("GUMROAD_USERNAME", "").strip(),
        "email": os.getenv("GUMROAD_USER_EMAIL", "").strip(),
    }


def get_default_currency() -> str:
    return os.getenv("DEFAULT_CURRENCY", "usd").strip().lower()


def is_auto_publish_enabled() -> bool:
    return os.getenv("GUMROAD_AUTO_PUBLISH", "false").strip().lower() in ("true", "1", "yes")


def get_gemini_api_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

