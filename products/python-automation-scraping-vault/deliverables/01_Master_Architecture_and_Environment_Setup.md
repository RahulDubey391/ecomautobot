# Module 1: Automation Architecture & Resilient Environment Setup

Building production-grade web scrapers and browser automation agents requires shifting away from brittle, local-machine scripts toward hardened, resilient infrastructure. This module establishes the master architectural blueprint for running high-throughput, undetectable automation pipelines capable of bypassing modern anti-bot perimeter defenses (Cloudflare Turnstile, DataDome, Akamai, and Kasada) while preserving compute resources and proxy budgets.

---

## 1. Enterprise Directory Blueprint & Isolation

To support dozens of concurrent scrapers without dependency collisions or state contamination, use an isolated workspace layout. This structure enforces a separation of concerns between scraper logic, browser runtime configurations, persistent state profiles, proxy managers, and pipeline orchestrators.

### Standardized Automation Repository Layout

```text
scraping_vault/
├── .env.example
├── pyproject.toml
├── requirements.txt
├── config/
│   ├── __init__.py
│   ├── browser_profiles.json
│   ├── headers_pool.json
│   └── settings.py
├── core/
│   ├── __init__.py
│   ├── circuit_breaker.py
│   ├── exceptions.py
│   ├── fingerprints.py
│   ├── proxy_manager.py
│   └── retry_engine.py
├── drivers/
│   ├── __init__.py
│   ├── playwright_factory.py
│   └── uc_factory.py
├── pipelines/
│   ├── __init__.py
│   └── base_pipeline.py
├── storage/
│   ├── sessions/
│   ├── logs/
│   └── raw_artifacts/
├── tests/
│   ├── test_fingerprints.py
│   └── test_proxies.py
└── scripts/
    └── bootstrap_env.sh
```

### Production Dependency Specification: `requirements.txt`

The dependencies below are pinned to versions that prevent ABI breaks across browser automation libraries, C extensions, and asynchronous networking engines.

```text
# --- Networking, TLS & HTTP Clients ---
curl_cffi==0.7.4
httpx[http2]==0.27.2
aiohttp==3.10.10
requests==2.32.3
urllib3==2.2.3

# --- Browser Automation Runtimes ---
playwright==1.48.0
playwright-stealth==1.0.6
undetected-chromedriver==3.5.5
selenium==4.25.0

# --- Parsing & DOM Extraction ---
beautifulsoup4==4.12.3
lxml==5.3.0
parsel==1.9.1
selectolax==0.3.21

# --- Resiliency, Scheduling & Concurrency ---
tenacity==9.0.0
pydantic==2.9.2
pydantic-settings==2.5.2
celery==5.4.0
redis==5.1.1
loguru==0.7.2
pyyaml==6.0.2

# --- Systems, Signals & Emulation ---
fake-useragent==1.5.1
python-dotenv==1.0.1
xvfbwrapper==0.2.9
psutil==6.0.0
```

### Automated Infrastructure Provisioning: `scripts/bootstrap_env.sh`

This script handles Linux/macOS environment preparation, installs underlying OS dependencies for headless Chromium, configures the virtual environment, and installs Playwright binaries.

```bash
#!/usr/bin/env bash
set -eo pipefail

echo "===> [1/5] Initializing Python Virtual Environment..."
PYTHON_BIN=$(command -v python3.11 || command -v python3)
$PYTHON_BIN -m venv .venv
source .venv/bin/activate

echo "===> [2/5] Upgrading Core Packaging Utilities..."
pip install --upgrade pip setuptools wheel

echo "===> [3/5] Installing Pinned Dependencies..."
pip install -r requirements.txt

echo "===> [4/5] Installing Playwright Operating System Dependencies & Browsers..."
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux host requirements (Ubuntu/Debian-based)
    if command -v apt-get &> /dev/null; then
        echo "Detected Debian/Ubuntu. Installing Xvfb and shared libraries..."
        sudo apt-get update && sudo apt-get install -y \
            xvfb \
            libxi6 \
            libgconf-2-4 \
            libnss3 \
            libasound2 \
            libatk1.0-0 \
            libatk-bridge2.0-0 \
            libcups2 \
            libdrm2 \
            libxkbcommon0 \
            libxcomposite1 \
            libxdamage1 \
            libxfixes3 \
            libxrandr2 \
            libgbm1 \
            libpango-1.0-0 \
            libcairo2
    fi
fi

# Fetch Chromium, Firefox, WebKit headless runtimes
playwright install chromium
playwright install-deps chromium

echo "===> [5/5] Creating Storage Runtime Directories..."
mkdir -p storage/sessions storage/logs storage/raw_artifacts

echo "===> Environment Setup Complete. Activate via: source .venv/bin/activate"
```

---

## 2. Stealth Browser Infrastructure

Standard headless browser sessions emit distinct runtime artifacts. Automation engines modify `window.navigator`, emit execution anomalies via the Chrome DevTools Protocol (CDP), and produce inconsistent WebGL/Canvas hashes. 

Below are the two core production factories: Playwright with targeted CDP patches and `undetected-chromedriver` running atop a virtual frame buffer.

### Playwright Stealth Engine: `drivers/playwright_factory.py`

This implementation removes the `navigator.webdriver` flag, standardizes WebGL renderer signatures, bypasses runtime permission prompts, and aligns modern user-agent client hints (`sec-ch-ua`).

```python
"""
Core Playwright driver initialization module.
Configures evasion flags, Context parameters, and dynamic route blocking.
"""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

class PlaywrightStealthFactory:
    def __init__(self, headless: bool = True, proxy_url: Optional[str] = None):
        self.headless = headless
        self.proxy_url = proxy_url
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None

    async def initialize(self) -> None:
        """Starts Playwright and boots Chromium with hardened launch arguments."""
        self.playwright = await async_playwright().start()
        
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-client-side-phishing-detection",
            "--disable-default-apps",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-features=Translate,BackForwardCache,AcceptCHFrame,MediaRouter,OptimizationHints",
            "--disable-ipc-flooding-protection",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-renderer-backgrounding",
            "--force-color-profile=srgb",
            "--metrics-recording-only",
            "--no-first-run",
            "--password-store=basic",
            "--use-mock-keychain",
            "--no-sandbox"
        ]

        proxy_config = {"server": self.proxy_url} if self.proxy_url else None

        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
            proxy=proxy_config,
            chromium_sandbox=False
        )
        logger.info(f"Chromium instance booted. Headless: {self.headless} | Proxy: {bool(self.proxy_url)}")

    async def create_stealth_context(
        self,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        user_agent: Optional[str] = None,
        locale: str = "en-US",
        timezone_id: str = "America/New_York"
    ) -> BrowserContext:
        """Creates an isolated, patched context that neutralizes common bot-detection hooks."""
        if not self.browser:
            raise RuntimeError("Browser not initialized. Call initialize() first.")

        ua = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )

        context = await self.browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            user_agent=ua,
            locale=locale,
            timezone_id=timezone_id,
            color_scheme="dark",
            device_scale_factor=1,
            has_touch=False,
            is_mobile=False,
            java_script_enabled=True,
            ignore_https_errors=True
        )

        # Inject stealth runtime scripts before any page scripts evaluate
        await context.add_init_script("""
            // Patch navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Patch Chrome runtime object
            window.chrome = {
                app: { isInstalled: false, InstallState: { DISABLED: 'DISABLED' }, RunningState: { CANNOT_RUN: 'CANNOT_RUN' } },
                runtime: { OnInstalledReason: { INSTALL: 'install' }, PlatformOs: { MAC: 'mac', WIN: 'win' } },
                loadTimes: function() {},
                csi: function() {}
            };

            // Patch Notification permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // Prevent PluginArray inspection fingerprinting
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Patch WebGL Vendor and Renderer
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) {
                    return 'Google Inc. (NVIDIA)';
                }
                if (parameter === 37446) {
                    return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                }
                return getParameter.apply(this, [parameter]);
            };
        """)

        return context

    async def close(self) -> None:
        """Gracefully terminates browser and driver threads."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Playwright driver teardown complete.")
```

### Undetected-ChromeDriver Factory: `drivers/uc_factory.py`

When targets use deep browser instrumentation, `undetected-chromedriver` bypasses checks by patching binary offsets in the `chromedriver` executable at runtime (specifically renaming `$cdc_` and `$wdc_` strings).

```python
"""
Undetected ChromeDriver factory with native Xvfb virtualization for Linux servers.
"""

from __future__ import annotations
import sys
import os
from typing import Optional
from loguru import logger
import undetected_chromedriver as uc

class UCStealthDriver:
    def __init__(
        self,
        headless: bool = True,
        proxy_url: Optional[str] = None,
        user_data_dir: Optional[str] = None
    ):
        self.headless = headless
        self.proxy_url = proxy_url
        self.user_data_dir = user_data_dir
        self.driver: Optional[uc.Chrome] = None
        self._xvfb = None

    def start(self) -> uc.Chrome:
        """Initializes undetected-chromedriver under an Xvfb display if running headless on Linux."""
        options = uc.ChromeOptions()
        
        # Core flags for running inside containers or CI/CD VPS
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=en-US")

        if self.proxy_url:
            options.add_argument(f"--proxy-server={self.proxy_url}")

        if self.user_data_dir:
            options.add_argument(f"--user-data-dir={self.user_data_dir}")

        # Undetected-chromedriver headless detection workaround on Linux
        if self.headless:
            if sys.platform.startswith("linux"):
                logger.info("Initializing virtual frame buffer (Xvfb) for undetected-chromedriver...")
                from xvfbwrapper import Xvfb
                self._xvfb = Xvfb(width=1920, height=1080, colordepth=24)
                self._xvfb.start()
                # Run as normal headful instance inside the virtual display
                self.driver = uc.Chrome(options=options, headless=False)
            else:
                # Use the new headless mode on Windows/macOS
                options.add_argument("--headless=new")
                self.driver = uc.Chrome(options=options, headless=True)
        else:
            self.driver = uc.Chrome(options=options, headless=False)

        # Enforce page load timeout constraints
        self.driver.set_page_load_timeout(35)
        logger.info("Undetected-Chromedriver process initialized successfully.")
        return self.driver

    def quit(self) -> None:
        """Ensures both the driver process and virtual displays terminate cleanly."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Error during UC driver quit: {e}")
        if self._xvfb:
            self._xvfb.stop()
            logger.info("Virtual frame buffer (Xvfb) stopped.")
```

---

## 3. Dynamic Header Synthesis & Fingerprint Management

Anti-bot systems match HTTP headers against the underlying TCP/IP, TLS (JA3/JA4), and HTTP/2 settings. For example, sending a Chrome 128 User-Agent with HTTP/1.1 or out-of-order headers triggers an immediate block.

### Modern Anti-Bot Evaluation Matrix

| Detection Layer | Vector Evaluated | Detection Trigger | Production Countermeasure |
| :--- | :--- | :--- | :--- |
| **L4 / Transport** | TCP SYN Packet (Window Size, TTL, Options) | Linux TCP stack signature mismatching Windows User-Agent | Host-level OS alignment or MTU/TCP scrubbing via gateway proxy |
| **L7 / TLS** | JA3/JA4 Fingerprint, Cipher Suite Suites, Extensions | Python `requests` or `urllib3` default OpenSSL cipher order | Impersonate browser TLS engine using `curl_cffi` |
| **L7 / HTTP/2** | SETTINGS frames, WINDOW_UPDATE parameters, pseudo-header order | Non-browser frame order (`:method` after `:path`) | Native HTTP/2 framing enforcement (`curl_cffi` or Playwright) |
| **L7 / Semantic** | Client Hints (`Sec-Ch-Ua`), Accept-Language, Ordering | Header keys sent in alphabetical order (standard Python library defaults) | Ordered casing maps matching target browser brand |
| **Client Runtime** | `navigator.webdriver`, Canvas hashes, AudioContext latency | Missing native prototypes, zero-latency rendering | JavaScript dynamic prototype manipulation & driver binary patching |

### TLS Fingerprint Matching: `core/fingerprints.py`

This script uses `curl_cffi` to mimic Chrome's exact TLS and HTTP/2 fingerprints, and contains a header synthesis engine that matches User-Agent strings with appropriate client hints.

```python
"""
Header and Browser Fingerprint Synchronization Module.
Provides valid Client Hints, HTTP/2 pseudo-header order, and TLS profile impersonation.
"""

from __future__ import annotations
import random
from typing import Dict, Any
from curl_cffi.requests import AsyncSession

class StealthHeaderEngine:
    CHROME_VERSIONS = ["126", "127", "128"]
    
    @classmethod
    def get_headers(cls, platform: str = "windows") -> Dict[str, str]:
        """Generates synchronized HTTP headers matching exact client architecture hints."""
        version = random.choice(cls.CHROME_VERSIONS)
        
        if platform == "windows":
            platform_str = '"Windows"'
            ua_platform = "Windows NT 10.0; Win64; x64"
            platform_version = '"15.0.0"'
        elif platform == "macos":
            platform_str = '"macOS"'
            ua_platform = "Macintosh; Intel Mac OS X 10_15_7"
            platform_version = '"14.5.0"'
        else:
            raise ValueError(f"Unsupported platform: {platform}")

        user_agent = f"Mozilla/5.0 ({ua_platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"

        return {
            "Host": "", # Managed by client runtime
            "Connection": "keep-alive",
            "sec-ch-ua": f'"Not/A)Brand";v="8", "Chromium";v="{version}", "Google Chrome";v="{version}"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": platform_str,
            "sec-ch-ua-platform-version": platform_version,
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Priority": "u=0, i"
        }

async def make_stealth_request(url: str, proxy: str | None = None) -> str:
    """Executes an HTTP request impersonating Chrome's TLS layer and HTTP/2 framing."""
    headers = StealthHeaderEngine.get_headers(platform="windows")
    # Host header is derived automatically; drop empty string
    del headers["Host"]

    async with AsyncSession(impersonate="chrome124") as session:
        response = await session.get(
            url,
            headers=headers,
            proxy=proxy,
            timeout=15.0
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Request failed: HTTP {response.status_code}")
        return response.text
```

---

## 4. Enterprise Proxy Orchestration & Pool Rotation

Production scrapers process hundreds of thousands of pages. Routing them through a single IP triggers ratelimits and perimeter bans. Production workflows require a dynamic proxy pool to distribute load across datacenter, residential, and mobile proxies.

```text
               ┌────────────────────────────────────────────────────────┐
               │                  Scraper Architecture                  │
               └──────────────────────────┬─────────────────────────────┘
                                          │
                            Proxy Checkout & Lease Request
                                          │
                                          ▼
                      ┌───────────────────────────────────────┐
                      │          ProxyPoolManager             │
                      │  - Validates Health / Latency         │
                      │  - Selects Tier (DC / Resi / Mobile)  │
                      │  - Tracks Leases & Cooldowns          │
                      └───────┬───────────────────────┬───────┘
                              │                       │
      Static Datacenter Route │                       │ Rotating Residential Route
      (Low cost, high speed)  │                       │ (High trust, challenge bypass)
                              ▼                       ▼
                     ┌────────────────┐      ┌─────────────────┐
                     │ Datacenter Pool│      │Residential Pool │
                     │   (50-100 IPs) │      │ (10,000+ Nodes) │
                     └───────┬────────┘      └────────┬────────┘
                             │                        │
                             └───────────┬────────────┘
                                         ▼
                            ┌────────────────────────┐
                            │ Target Edge/Protection │
                            │ (Cloudflare/DataDome)  │
                            └────────────────────────┘
```

### High-Throughput Proxy Manager: `core/proxy_manager.py`

This thread-safe proxy manager handles health-tracking, latency scoring, protocol conversion, and automatic quarantine with backoff penalties.

```python
"""
Resilient Proxy Pool Management with Health Tracking and Dynamic Quarantine.
"""

from __future__ import annotations
import asyncio
import time
from typing import Dict, List, Optional
from pydantic import BaseModel, HttpUrl
from loguru import logger

class ProxyNode(BaseModel):
    url: str
    protocol: str = "http"
    failure_count: int = 0
    success_count: int = 0
    avg_latency_ms: float = 0.0
    quarantined_until: float = 0.0

    @property
    def is_available(self) -> bool:
        return time.time() > self.quarantined_until

class ProxyPoolManager:
    def __init__(self, proxy_list: List[str], quarantine_duration_secs: int = 300):
        self.quarantine_duration = quarantine_duration_secs
        self._lock = asyncio.Lock()
        self._pool: List[ProxyNode] = []
        
        for p in proxy_list:
            self._pool.append(ProxyNode(url=p))
            
        logger.info(f"Initialized ProxyPoolManager with {len(self._pool)} nodes.")

    async def get_next_proxy(self) -> ProxyNode:
        """Retrieves the healthiest available proxy using a latency-weighted policy."""
        async with self._lock:
            available = [p for p in self._pool if p.is_available]
            if not available:
                # Emergency: Clear expired quarantines or pick lowest penalty
                logger.warning("All proxies quarantined. Overriding node with earliest release.")
                available = sorted(self._pool, key=lambda x: x.quarantined_until)
                return available[0]

            # Sort primarily by lowest failure count, secondarily by latency
            available.sort(key=lambda x: (x.failure_count, x.avg_latency_ms))
            selected = available[0]
            return selected

    async def report_success(self, proxy: ProxyNode, latency_ms: float) -> None:
        """Updates health metrics on successful execution."""
        async with self._lock:
            proxy.success_count += 1
            proxy.failure_count = max(0, proxy.failure_count - 1)
            # Update moving average latency
            if proxy.avg_latency_ms == 0.0:
                proxy.avg_latency_ms = latency_ms
            else:
                proxy.avg_latency_ms = (proxy.avg_latency_ms * 0.8) + (latency_ms * 0.2)

    async def report_failure(self, proxy: ProxyNode, status_code: Optional[int] = None) -> None:
        """Applies penalties and quarantines nodes after threshold limits."""
        async with self._lock:
            proxy.failure_count += 1
            logger.warning(
                f"Proxy {proxy.url} failed. Code: {status_code} | "
                f"Total Failures: {proxy.failure_count}"
            )
            
            # Fast quarantine on definitive access blocks
            if status_code in [403, 429] or proxy.failure_count >= 3:
                penalty_time = self.quarantine_duration * proxy.failure_count
                proxy.quarantined_until = time.time() + penalty_time
                logger.error(f"Quarantining {proxy.url} for {penalty_time}s.")
```

---

## 5. Fault Tolerance, Circuit Breakers & Backoff Strategies

Unchecked exceptions in long-running scrapes can exhaust memory, trigger target-wide bans, or corrupt session state. Production pipelines require structured retries with exponential jitter and circuit-breaker patterns to stop traffic during active defenses.

```text
Request Cycle ──► [Try HTTP Fetch]
                         │
        ┌────────────────┴────────────────┐
     Success                           Failure
        │                                 │
 [Return Data]              [Circuit Breaker Trips?]
                             ├── YES ──► Raise SystemHalt & Abort Scrape
                             └── NO  ──► Check Retry Engine
                                           │
                             [Exponential Backoff + Jitter]
                                           │
                                  [Next Attempt / Proxy]
```

### Custom Exception Hierarchy: `core/exceptions.py`

```python
"""Domain-specific exceptions for automation pipelines."""

class AutomationVaultException(Exception):
    """Base exception for all vault workflows."""

class RateLimitException(AutomationVaultException):
    """Target returned HTTP 429 or dynamic rate limiting response."""

class BotChallengeException(AutomationVaultException):
    """Target triggered Turnstile, Cloudflare IUAM, or DataDome challenge."""

class ProxyConnectionException(AutomationVaultException):
    """Upstream proxy server dropped connection or timed out."""

class TargetSchemaChangedException(AutomationVaultException):
    """DOM structure changed, missing expected selectors."""
```

### Circuit Breaker & Retry Engine: `core/retry_engine.py`

This module uses `tenacity` along with a sliding-window circuit breaker to catch edge failures and stop execution when an IP block or structural change occurs.

```python
"""
Fault-tolerance engine combining exponential jittered retry loops
with a stateful circuit breaker.
"""

from __future__ import annotations
import random
import time
from typing import Callable, Any
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
from core.exceptions import (
    RateLimitException,
    BotChallengeException,
    ProxyConnectionException
)

class ScrapingCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 600):
        self.threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= self.threshold:
            self.state = "OPEN"
            logger.critical(
                f"CIRCUIT BREAKER OPENED: {self.consecutive_failures} sequential failures. "
                f"System paused for {self.recovery_timeout} seconds."
            )

    def can_proceed(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
                logger.info("Circuit breaker shifted to HALF-OPEN. Executing test canary request.")
                return True
            return False
        return True  # HALF-OPEN allows single speculative execution

def custom_retry_policy():
    """Returns a Tenacity retry orchestrator tuned for scraping operations."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=3, max=45),
        retry=retry_if_exception_type(
            (RateLimitException, ProxyConnectionException, TimeoutError)
        ),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry attempt {retry_state.attempt_number} due to: {retry_state.outcome.exception()}"
        )
    )
```

---

## 6. Production Health Checklist & Verification Suite

Before deploying automated pipelines into production, run this end-to-end verification script. It boots the browser and networking engines, executes tests against real-world fingerprint leak listeners, and confirms environment readiness.

### Automated Smoke Verification Script: `tests/test_fingerprints.py`

Run this script inside the newly built `.venv` environment to verify your setup before starting production runs:

```python
"""
End-to-End Validation Engine. Run this to verify local environments against
perimeter detection benchmarks.
"""

from __future__ import annotations
import asyncio
import json
import sys
from loguru import logger
from drivers.playwright_factory import PlaywrightStealthFactory
from core.fingerprints import make_stealth_request

async def test_tls_layer() -> bool:
    logger.info("Executing TLS & HTTP/2 Validation Test...")
    url = "https://tls.peet.ws/api/all"
    try:
        raw_response = await make_stealth_request(url)
        data = json.loads(raw_response)
        http_version = data.get("http_version", "")
        ja3 = data.get("tls", {}).get("ja3_hash", "NONE")
        logger.info(f"Connected using HTTP Version: {http_version} | JA3 Hash: {ja3}")
        if "h2" not in http_version.lower() and "http/2" not in http_version.lower():
            logger.error("TLS engine failed to negotiate HTTP/2 framing.")
            return False
        return True
    except Exception as e:
        logger.error(f"TLS test crashed: {e}")
        return False

async def test_playwright_leaks() -> bool:
    logger.info("Executing Playwright Runtime Leak Test...")
    factory = PlaywrightStealthFactory(headless=True)
    await factory.initialize()
    try:
        context = await factory.create
