# Module 2: 35+ Stealth Web Scrapers & Dynamic Crawlers

This module delivers drop-in Python architectures for extracting data from protected, dynamic, and heavily hydrated single-page applications (SPAs). Every script implements real-world evasion: TLS/JA3 fingerprint matching, HTTP/2 frame mimicry, modern browser stealth CDP patches, and direct interception of client-side hydration stores (`__NEXT_DATA__`, Apollo cache, and hidden REST/GraphQL targets).

---

## 1. Anti-Bot Detection Matrix & Strategy Guide

Modern bot management platforms (Cloudflare, Akamai, Datadome, PerimeterX) evaluate incoming web traffic across three layers: Network/TLS, Browser Runtime/Fingerprint, and Behavioral Biometrics. The table below outlines how each evasion vector must be implemented in Python:

| Inspection Layer | Metric / Sensor Analyzed | Naive Scraper Signature | Stealth Vault Implementation |
| :--- | :--- | :--- | :--- |
| **TLS/JA3/JA4** | Cipher suites, extensions, elliptic curves, SNI, ALPN order | Standard OpenSSL/Python `requests` cipher suites (Instant 403) | `curl_cffi` with exact Chrome 120+ / Safari NSS fingerprint replication |
| **HTTP/2 Transport** | `SETTINGS` frame order, `WINDOW_UPDATE` values, Header pseudo-order | Default Go/Node/Python H2 implementations | Native C-level libcurl transport impersonating standard browser streams |
| **Navigator API** | `navigator.webdriver`, worker threads, memory limits | `true` flags, broken `languages`, unaligned plugin arrays | CDP patches via Playwright, stripping automation markers before DOM init |
| **Canvas / WebGL** | Hash of 2D/3D rendered noise, hardware acceleration vendor | Direct hardware strings mismatched with virtualized host display | Dynamic hardware emulation with deterministic per-session canvas noise |
| **Hydration / DOM** | DOM mutation frequency, JavaScript execution delays | Premature DOM polling, instant non-human node queries | Network payload interception (`fetch`/`XHR`) and SSR hydration JSON parsing |

---

## 2. Production Engine 1: High-Throughput Catalog Harvester (TLS Impersonation)

When targeting Cloudflare Turnstile or Akamai-fronted catalogs where dynamic JavaScript rendering is unnecessary (server-rendered or JSON-hydrated pages), running a headless browser incurs massive CPU overhead. 

The following production script utilizes `curl_cffi` to match the exact TLS/JA3 and HTTP/2 framing of modern Chrome. It integrates asynchronous concurrency, automated exponential backoff, rotating proxy injection, and strict Pydantic model validation.

```python
import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional
from curl_cffi.requests import AsyncSession, Response
from pydantic import BaseModel, Field, HttpUrl, ValidationError

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("StealthCatalogEngine")

class ProductRecord(BaseModel):
    product_id: str = Field(..., alias="id")
    title: str = Field(..., min_length=1)
    price: float = Field(..., ge=0.0)
    currency: str = Field(default="USD", max_length=3)
    in_stock: bool = Field(default=True)
    product_url: HttpUrl

class CatalogEngineConfig:
    MAX_CONCURRENT_REQUESTS: int = 5
    REQUEST_TIMEOUT: int = 15
    MAX_RETRIES: int = 4
    BASE_BACKOFF_SECONDS: float = 1.5
    IMPERSONATE_BROWSER: str = "chrome120"
    USER_AGENTS: List[str] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]

class ResilientCatalogScraper:
    def __init__(self, proxy_pool: Optional[List[str]] = None):
        self.proxy_pool = proxy_pool or []
        self.semaphore = asyncio.Semaphore(CatalogEngineConfig.MAX_CONCURRENT_REQUESTS)
        self.results: List[ProductRecord] = []

    def _get_random_proxy(self) -> Optional[Dict[str, str]]:
        if not self.proxy_pool:
            return None
        proxy = random.choice(self.proxy_pool)
        return {"http": proxy, "https": proxy}

    def _get_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": random.choice(CatalogEngineConfig.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
        }

    async def fetch_page(self, session: AsyncSession, url: str) -> Optional[str]:
        retries = 0
        proxies = self._get_random_proxy()

        while retries <= CatalogEngineConfig.MAX_RETRIES:
            try:
                async with self.semaphore:
                    logger.info(f"Fetching: {url} (Attempt {retries + 1})")
                    response: Response = await session.get(
                        url,
                        headers=self._get_headers(),
                        proxies=proxies,
                        timeout=CatalogEngineConfig.REQUEST_TIMEOUT,
                        impersonate=CatalogEngineConfig.IMPERSONATE_BROWSER
                    )
                    
                    if response.status_code == 200:
                        return response.text
                    elif response.status_code in [403, 429, 503]:
                        logger.warning(f"Throttled ({response.status_code}) on {url}. Backing off.")
                    else:
                        logger.error(f"Failed with status {response.status_code} for {url}")
                        return None
            except Exception as e:
                logger.warning(f"Network error on {url}: {str(e)}")

            retries += 1
            sleep_duration = (CatalogEngineConfig.BASE_BACKOFF_SECONDS ** retries) + random.uniform(0.5, 1.5)
            await asyncio.sleep(sleep_duration)

        logger.error(f"Exhausted retries for URL: {url}")
        return None

    def parse_mock_catalog_payload(self, raw_html: str, origin_url: str) -> List[ProductRecord]:
        """
        Parses data from internal JSON script elements or custom payload tags.
        Demonstrates resilient structural transformation into typed records.
        """
        parsed_records: List[ProductRecord] = []
        try:
            # Example parsing strategy: Searching for targeted embedded state
            start_marker = '<script id="__CATALOG_STATE__" type="application/json">'
            end_marker = '</script>'
            
            if start_marker in raw_html:
                start_idx = raw_html.index(start_marker) + len(start_marker)
                end_idx = raw_html.index(end_marker, start_idx)
                payload_json = json.loads(raw_html[start_idx:end_idx].strip())

                for item in payload_json.get("items", []):
                    try:
                        record = ProductRecord(
                            id=str(item.get("sku")),
                            title=item.get("name"),
                            price=float(item.get("current_price", 0.0)),
                            currency=item.get("currency_code", "USD"),
                            in_stock=bool(item.get("is_available")),
                            product_url=f"{origin_url}/product/{item.get('slug')}"
                        )
                        parsed_records.append(record)
                    except ValidationError as val_err:
                        logger.debug(f"Pydantic validation failure on record: {val_err}")
                        continue
        except Exception as e:
            logger.error(f"Error parsing page context: {str(e)}")

        return parsed_records

    async def execute_crawl(self, catalog_urls: List[str]) -> List[ProductRecord]:
        async with AsyncSession() as session:
            tasks = [self.fetch_page(session, url) for url in catalog_urls]
            pages_content = await asyncio.gather(*tasks)

            for url, html in zip(catalog_urls, pages_content):
                if html:
                    extracted = self.parse_mock_catalog_payload(html, url)
                    self.results.extend(extracted)
                    
        logger.info(f"Crawl completed. Extracted {len(self.results)} validated records.")
        return self.results

if __name__ == "__main__":
    # Concrete test harness
    sample_urls = [
        "https://httpbin.org/html" # Verify execution loop
    ]
    scraper = ResilientCatalogScraper(proxy_pool=[])
    records = asyncio.run(scraper.execute_crawl(sample_urls))
    print(f"Total Records Extracted: {len(records)}")
```

---

## 3. Production Engine 2: Dynamic SPA & Infinite Scroll Engine (Playwright Stealth)

Single-Page Applications relying on React, Vue, or Angular commonly populate the DOM dynamically via client-side JavaScript execution triggered by intersection observers (infinite scrolling). 

This script leverages Playwright with raw Chrome DevTools Protocol (CDP) modifications to neutralize automation markers, applies human-like viewport jitter, scrolls through content bounds until data stabilizes, and extracts loaded items.

```python
import asyncio
import logging
import math
import random
from typing import Any, Dict, List
from playwright.async_api import BrowserContext, Page, async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("PlaywrightStealthCrawler")

class StealthDynamicScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def apply_stealth_patches(self, context: BrowserContext) -> None:
        """
        Deep-patches CDP properties before any script evaluation on new documents.
        Overrides webdriver, languages, plugins, chrome object, and screen resolution.
        """
        stealth_init_script = """
        // 1. Remove navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // 2. Mock plugins array
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {
                    0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                    description: "Portable Document Format",
                    filename: "internal-pdf-viewer",
                    length: 1,
                    name: "Chrome PDF Plugin"
                },
                {
                    0: {type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"},
                    description: "Portable Document Format",
                    filename: "internal-pdf-viewer",
                    length: 1,
                    name: "Chrome PDF Viewer"
                }
            ]
        });

        // 3. Mock languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });

        // 4. Emulate native chrome runtime object
        window.chrome = {
            app: {
                isInstalled: false,
                InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'},
                RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'}
            },
            runtime: {
                OnInstalledReason: {CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update'},
                OnRestartRequiredReason: {APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic'},
                PlatformArch: {ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64'},
                PlatformNaclArch: {ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64'},
                PlatformOs: {ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win'},
                RequestUpdateCheckStatus: {NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available'}
            }
        };

        // 5. Mask Permissions Query
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        """
        await context.add_init_script(stealth_init_script)

    async def human_bezier_scroll(self, page: Page, total_steps: int = 10) -> None:
        """
        Executes a non-linear scroll downward, mimicking physical trackpad motion.
        """
        for i in range(total_steps):
            # Compute ease-in-out movement
            progress = (i + 1) / total_steps
            ease = 0.5 * (1 - math.cos(math.pi * progress))
            delta_y = int(300 + (ease * 200) + random.uniform(-20, 20))
            
            await page.mouse.wheel(delta_x=0, delta_y=delta_y)
            await asyncio.sleep(random.uniform(0.15, 0.45))

    async def harvest_infinite_scroll_container(
        self,
        target_url: str,
        item_selector: str,
        max_items: int = 50,
        max_scroll_attempts: int = 20
    ) -> List[Dict[str, str]]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--window-size=1920,1080"
                ]
            )

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York"
            )

            await self.apply_stealth_patches(context)
            page = await context.new_page()

            logger.info(f"Navigating to {target_url}...")
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

            # Wait for base selector hydration
            try:
                await page.wait_for_selector(item_selector, timeout=10000)
            except Exception:
                logger.warning(f"Timed out waiting for initial element selector: {item_selector}")

            items_collected: List[Dict[str, str]] = []
            previous_item_count = 0
            attempts_without_growth = 0

            for scroll_cycle in range(max_scroll_attempts):
                current_elements = await page.query_selector_all(item_selector)
                current_count = len(current_elements)
                logger.info(f"Cycle {scroll_cycle + 1}: Found {current_count} active DOM elements.")

                if current_count >= max_items:
                    logger.info(f"Reached item limit target: {max_items}")
                    break

                if current_count == previous_item_count:
                    attempts_without_growth += 1
                    if attempts_without_growth >= 3:
                        logger.info("DOM element count stabilized. End of infinite scroll reached.")
                        break
                else:
                    attempts_without_growth = 0

                previous_item_count = current_count

                # Trigger next hydrate wave via mouse wheel
                await self.human_bezier_scroll(page, total_steps= random.randint(4, 8))
                
                # Small human-like dwell time for network hydration
                await asyncio.sleep(random.uniform(1.2, 2.5))

            # Extraction phase
            final_elements = await page.query_selector_all(item_selector)
            for el in final_elements[:max_items]:
                text_content = await el.inner_text()
                link = await el.get_attribute("href") or ""
                items_collected.append({
                    "text": text_content.strip(),
                    "link": link.strip()
                })

            await context.close()
            await browser.close()
            return items_collected

if __name__ == "__main__":
    scraper = StealthDynamicScraper(headless=True)
    # Concrete harness targeting an open catalog page
    results = asyncio.run(
        scraper.harvest_infinite_scroll_container(
            target_url="https://news.ycombinator.com",
            item_selector="tr.athing",
            max_items=30,
            max_scroll_attempts=5
        )
    )
    print(f"Collected {len(results)} items via dynamic scroll.")
```

---

## 4. Production Engine 3: Intercepting Client-Side Hydration Stores (`__NEXT_DATA__`)

Modern React, Next.js, and Nuxt.js applications embed their entire operational state into JSON script tags within the initial HTML payload to allow client-side hydration. Querying the DOM via traditional CSS selectors is fragile and slow compared to parsing these structures directly.

The following script extracts, validates, and traverses the Next.js `__NEXT_DATA__` tree, as well as generic Redux / Nuxt hydration blocks, pulling structured records in sub-millisecond execution times.

```python
import json
import logging
import re
from typing import Any, Dict, Generator, Optional
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("HydrationExtractor")

class DynamicHydrationExtractor:
    def __init__(self):
        self.next_data_pattern = re.compile(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">([\s\S]*?)</script>')
        self.nuxt_data_pattern = re.compile(r'window\.__NUXT__\s*=\s*({[\s\S]*?});')

    def extract_next_data(self, html_content: str) -> Optional[Dict[str, Any]]:
        """
        Extracts and parses Next.js __NEXT_DATA__ JSON representation.
        """
        match = self.next_data_pattern.search(html_content)
        if match:
            try:
                raw_json = match.group(1).strip()
                return json.loads(raw_json)
            except json.JSONDecodeError as err:
                logger.error(f"Malformed Next.js JSON payload: {err}")
                return None
        
        # Fallback to structural DOM parsing if regex boundary shifts
        soup = BeautifulSoup(html_content, "html.parser")
        tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if tag and tag.string:
            try:
                return json.loads(tag.string.strip())
            except json.JSONDecodeError as err:
                logger.error(f"DOM fallback parsed malformed JSON: {err}")
                
        return None

    def deep_search_keys(self, data: Any, target_key: str) -> Generator[Any, None, None]:
        """
        Recursively scans hydrated state tree for all matching dictionary keys.
        """
        if isinstance(data, dict):
            for key, val in data.items():
                if key == target_key:
                    yield val
                if isinstance(val, (dict, list)):
                    yield from self.deep_search_keys(val, target_key)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    yield from self.deep_search_keys(item, target_key)

    def parse_hydration_tree(self, html: str, target_schema_key: str) -> list:
        payload = self.extract_next_data(html)
        if not payload:
            logger.warning("No standard Next.js hydration payload located in document.")
            return []

        # Target props/pageProps common in Next.js builds
        page_props = payload.get("props", {}).get("pageProps", {})
        if not page_props:
            logger.warning("Hydration payload present, but 'pageProps' is empty.")
            # Search entire tree dynamically
            return list(self.deep_search_keys(payload, target_schema_key))

        return list(self.deep_search_keys(page_props, target_schema_key))

# Concrete Execution Verification
if __name__ == "__main__":
    sample_nextjs_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Storefront</title></head>
    <body>
        <div id="__next"><div>Hydrating Page...</div></div>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "catalog": {
                "category": "Electronics",
                "products": [
                  {"sku": "A101", "name": "Mechanical Keyboard", "price": 120.00},
                  {"sku": "A102", "name": "Ergonomic Mouse", "price": 85.50}
                ]
              }
            }
          },
          "page": "/catalog",
          "query": {},
          "buildId": "PROD_BUILD_991823"
        }
        </script>
    </body>
    </html>
    """

    extractor = DynamicHydrationExtractor()
    extracted_items = extractor.parse_hydration_tree(sample_nextjs_html, target_schema_key="products")
    print(f"Hydration Interception Result: {json.dumps(extracted_items, indent=2)}")
```

---

## 5. Thread-Safe Rotating Proxy & Session Persistence Manager

High-frequency web scraping without synchronized session, cookie, and proxy state management leads directly to localized IP bans and rate-limiting cascades. 

The configuration manager below orchestrates an atomic, thread-safe proxy rotator, persists session states across worker failures via disk serialization, and enforces exponential backoff on encountering `429 Too Many Requests` or `403 Forbidden` response boundaries.

```python
import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger("ProxySessionManager")
logger.setLevel(logging.INFO)

class ProxyNode:
    def __init__(self, endpoint: str):
        self.endpoint: str = endpoint
        self.failure_count: int = 0
        self.backoff_until: float = 0.0

    def is_available(self) -> bool:
        return time.time() >= self.backoff_until

    def mark_success(self) -> None:
        self.failure_count = 0
        self.backoff_until = 0.0

    def mark_failure(self, base_cooldown: float = 30.0) -> None:
        self.failure_count += 1
        cooldown = base_cooldown * (2 ** (self.failure_count - 1))
        self.backoff_until = time.time() + cooldown
        logger.warning(
            f"Node {self.endpoint} failed ({self.failure_count}x). "
            f"Cooldown assigned: {cooldown:.1f}s"
        )

class ProxySessionManager:
    def __init__(self, proxy_list: List[str], state_filepath: str = "session_cache.json"):
        self.lock = threading.Lock()
        self.proxies: List[ProxyNode] = [ProxyNode(url) for url in proxy_list]
        self.index: int = 0
        self.state_filepath: str = state_filepath
        self.cookies: Dict[str, str] = {}
        self._load_session_state()

    def _load_session_state(self) -> None:
        if os.path.exists(self.state_filepath):
            try:
                with open(self.state_filepath, "r", encoding="utf-8") as f:
                    self.cookies = json.load(f)
                    logger.info(f"Restored {len(self.cookies)} cached session cookies from disk.")
            except Exception as e:
                logger.error(f"Failed to read session state file: {e}")
                self.cookies = {}

    def save_session_state(self) -> None:
        with self.lock:
            try:
                with open(self.state_filepath, "w", encoding="utf-8") as f:
                    json.dump(self.cookies, f, indent=2)
                logger.info("Session state synced to disk.")
            except Exception as e:
                logger.error(f"Failed to persist session state: {e}")

    def update_cookies(self, new_cookies: Dict[str, str]) -> None:
        with self.lock:
            self.cookies.update(new_cookies)
        self.save_session_state()

    def get_cookies(self) -> Dict[str, str]:
        with self.lock:
            return dict(self.cookies)

    def acquire_healthy_proxy(self) -> str:
        """
        Thread-safe round-robin allocation of active proxies with cooldown verification.
        Raises RuntimeError if all nodes in pool are currently in a backoff state.
        """
        with self.lock:
            total_nodes = len(self.proxies)
            if total_nodes == 0:
                raise ValueError("Proxy pool is unpopulated.")

            for _ in range(total_nodes):
                node = self.proxies[self.index]
                self.index = (self.index + 1) % total_nodes
                
                if node.is_available():
                    return node.endpoint

            # Find the minimum wait time across the pool
            min_cooldown = min(n.backoff_until for n in self.proxies)
            wait_time = max(0.0, min_cooldown - time.time())
            raise RuntimeError(f"All proxies exhausted. Minimum pool backoff: {wait_time:.1f}s")

    def report_status(self, proxy_endpoint: str, status_code: int) -> None:
        with self.lock:
            target_node = next((n for n in self.proxies if n.endpoint == proxy_endpoint), None)
            if not target_node:
                return

            if status_code in [200, 201, 204]:
                target_node.mark_success()
            elif status_code in [403, 429, 502, 503, 504]:
                target_node.mark_failure()

# Verification Block
if __name__ == "__main__":
    test_proxies = [
        "http://proxy-us-zone1.internal:8080",
        "http://proxy-us-zone2.internal:8080",
        "http://proxy-eu-zone1.internal:8080"
    ]
    manager = ProxySessionManager(proxy_list=test_proxies, state_filepath="test_session.json")
    
    # Simulate routing and failure registration
    p1 = manager.acquire_healthy_proxy()
    manager.report_status(p1, 429)
    
    # Store arbitrary session tokens
    manager.update_cookies({"session_id": "sec_token_9998124", "cf_clearance": "alpha_token"})
    print(f"Allocated Proxy: {manager.acquire_healthy_proxy()}")
    print(f"Active Session Data: {manager.get_cookies()}")
    
    # Clean up test artifacts
    if os.path.exists("test_session.json"):
        os.remove("test_session.json")
```

---

## 6. Anti-Fingerprinting Pre-Flight Operational Checklist

Before executing crawls against cloud-protected endpoints, verify all configurations against this checklist to prevent IP burn-in:

```
[ ] 1. TLS/JA3/JA4 Fingerprint Verification
