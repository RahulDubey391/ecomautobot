# Module 4: Deployment Playbooks, Anti-Bot Checklists & CLI Cheat Sheet

## 1. Production Deployment Blueprint: systemd Services & Timers

Using traditional `cron` for long-running or mission-critical Python scrapers exposes pipelines to silent failures: processes overlap, crashed tasks don't restart, log files saturate disks, and memory leaks freeze nodes. The standard Linux enterprise approach uses `systemd` services coupled with `systemd` timers. This guarantees sandboxed permissions, automatic restart logic, process isolation, and centralized structured logging via `journald`.

### 1.1 Hardened systemd Service Template

Save the service definition at `/etc/systemd/system/scraper-worker.service`. This configuration runs non-root, binds memory limits to prevent runaway Chrome processes from causing an Out-Of-Memory (OOM) kernel panic, and enforces a strict read-only filesystem policy.

```ini
[Unit]
Description=Python Vault Production Scraper Worker
After=network.target network-online.target
Wants=network-online.target
Documentation=https://github.com/your-org/scraper-vault

[Service]
Type=simple
User=scraperdaemon
Group=scraperdaemon
WorkingDirectory=/opt/scraper-vault
EnvironmentFile=/etc/scraper-vault/production.env
ExecStart=/opt/scraper-vault/venv/bin/python -u -m src.runners.cli_worker --pipeline market_data --concurrency 8
ExecStop=/bin/kill -s SIGTERM $MAINPID

# Process Lifecycle & Recovery
Restart=on-failure
RestartSec=15s
TimeoutStopSec=45s
KillMode=mixed

# Resource Sandboxing & Constraints (cgroups v2)
MemoryMax=4G
MemoryHigh=3.5G
CPUQuota=200%
TasksMax=250

# Security Hardening
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
ReadWritePaths=/var/log/scraper-vault /opt/scraper-vault/runtime_data

# Standard I/O to systemd-journald
StandardOutput=journal
StandardError=journal
SyslogIdentifier=scraper-worker

[Install]
WantedBy=multi-user.target
```

### 1.2 systemd Timer Template (Deterministic & Jittered Scheduling)

Save the companion timer definition at `/etc/systemd/system/scraper-worker.timer`. Timers supersede crontabs by supporting built-in randomized jitter (`RandomizedDelaySec`). This prevents downstream anti-bot triggers caused by firing scraping jobs at the exact microsecond of an hour.

```ini
[Unit]
Description=Trigger Python Vault Scraper Pipeline on Randomized Jitter Schedule
Requires=scraper-worker.service

[Timer]
# Trigger daily at 02:30:00 UTC
OnCalendar=*-*-* 02:30:00
# Add uniform random delay between 0 and 900 seconds (15 minutes) to avoid detection
RandomizedDelaySec=900s
# Catch up immediately if the server was offline during the scheduled interval
Persistent=true
Unit=scraper-worker.service

[Install]
WantedBy=timers.target
```

### 1.3 Production Deployment & Maintenance Workflow

Execute these commands sequentially on Debian/Ubuntu systems to install users, secure permissions, and manage unit states:

```bash
# 1. Provision dedicated system user with restricted home directory
sudo useradd -r -s /usr/sbin/nologin -d /opt/scraper-vault scraperdaemon

# 2. Establish deployment directories and permissions
sudo mkdir -p /opt/scraper-vault /var/log/scraper-vault /etc/scraper-vault
sudo chown -R scraperdaemon:scraperdaemon /opt/scraper-vault /var/log/scraper-vault
sudo chmod 750 /opt/scraper-vault /var/log/scraper-vault
sudo chmod 700 /etc/scraper-vault

# 3. Create hardened environment file
sudo touch /etc/scraper-vault/production.env
sudo chown root:scraperdaemon /etc/scraper-vault/production.env
sudo chmod 640 /etc/scraper-vault/production.env

# Inject secrets securely
cat << 'EOF' | sudo tee /etc/scraper-vault/production.env > /dev/null
PYTHONPATH=/opt/scraper-vault
ENVIRONMENT=production
PROXIES_ROTATION_URL=http://usr_enterprise_tier:Pass_8819@gate.smartproxy.io:7000
DATABASE_URL=postgresql://scraper_admin:Secured_P4ssW0rd!@10.0.4.12:5432/scraping_warehouse
SENTRY_DSN=https://abc123token@o0.ingest.sentry.io/456789
LOG_LEVEL=INFO
EOF

# 4. Copy unit definitions into systemd registry
sudo cp scraper-worker.service /etc/systemd/system/scraper-worker.service
sudo cp scraper-worker.timer /etc/systemd/system/scraper-worker.timer

# 5. Reload daemon and start the pipeline
sudo systemctl daemon-reload
sudo systemctl enable --now scraper-worker.timer

# 6. Verify scheduled execution windows and logs
systemctl list-timers --all | grep scraper-worker
sudo journalctl -u scraper-worker.service -f --output=cat
```

---

## 2. Serverless Scheduling: GitHub Actions Production Cron Runners

GitHub Actions allows you to run distributed scraping workflows without provisioning persistent cloud servers. This setup handles persistent browser dependencies, implements headless displays (Xvfb), manages artifacts on failures, and posts alerts to Discord or Slack.

Save this workflow to `.github/workflows/scraper-cron.yml`:

```yaml
name: Production Scraping Pipeline

on:
  schedule:
    # Runs at minute 15 past every 4th hour: 00:15, 04:15, 08:15, 12:15, 16:15, 20:15 UTC
    - cron: '15 */4 * * *'
  workflow_dispatch:
    inputs:
      target_env:
        description: 'Target Target Environment'
        required: true
        default: 'production'
        type: choice
        options:
          - production
          - staging
      max_pages:
        description: 'Override Maximum Scraping Page Depth'
        required: false
        default: '50'

concurrency:
  group: scraping-pipeline-${{ github.ref }}
  cancel-in-progress: false

jobs:
  run-pipeline:
    name: Scrape Engine Execution
    runs-on: ubuntu-22.04
    timeout-minutes: 45

    steps:
      - name: Checkout Source Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Set Up Python 3.11 Runtime
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: '**/requirements.txt'

      - name: Install System Dependencies for Headless Browsers
        run: |
          sudo apt-get update
          sudo apt-get install -y --no-install-recommends \
            libnss3 \
            libatk1.0-0 \
            libatk-bridge2.0-0 \
            libcups2 \
            libxkbcommon0 \
            libxcomposite1 \
            libxdamage1 \
            libxfixes3 \
            libxrandr2 \
            libgbm1 \
            libpango-1.0-0 \
            libcairo2 \
            libasound2 \
            xvfb \
            tesseract-ocr

      - name: Install Python Package Dependencies
        run: |
          python -m pip install --upgrade pip setuptools wheel
          pip install -r requirements.txt
          # Explicitly install modern browser binaries with system-level wrappers
          playwright install --with-deps chromium

      - name: Execute Scraping Pipeline Engine
        id: scrape
        env:
          TARGET_ENV: ${{ inputs.target_env || 'production' }}
          MAX_PAGES: ${{ inputs.max_pages || '100' }}
          PROXY_POOL_CREDENTIALS: ${{ secrets.PROXY_POOL_CREDENTIALS }}
          STORAGE_S3_KEY_ID: ${{ secrets.STORAGE_S3_KEY_ID }}
          STORAGE_S3_SECRET_KEY: ${{ secrets.STORAGE_S3_SECRET_KEY }}
          WAREHOUSE_POSTGRES_DSN: ${{ secrets.WAREHOUSE_POSTGRES_DSN }}
          HEADLESS: "true"
        run: |
          # Use Xvfb to supply a simulated virtual display, bypassing headless checks
          xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24 -ac" \
            python -m src.pipelines.runner \
            --env "$TARGET_ENV" \
            --pages "$MAX_PAGES" \
            --export-format parquet

      - name: Capture Failure State & Telemetry Artifacts
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: runtime-crash-dumps-${{ github.run_id }}
          path: |
            runtime_data/screenshots/*.png
            runtime_data/dom_dumps/*.html
            runtime_data/har_network/*.har
            logs/*.log
          retention-days: 7

      - name: Send Slack Webhook on Pipeline Failure
        if: failure()
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: |
          curl -s -X POST -H 'Content-type: application/json' \
            --data "{
              \"text\": \":rotating_light: *SCRAPER RUNTIME FAILURE* :rotating_light:\n*Workflow:* ${GITHUB_WORKFLOW}\n*Run ID:* ${GITHUB_RUN_ID}\n*Triggered By:* ${GITHUB_EVENT_NAME}\n*Logs:* https://github.com/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}\"
            }" "$SLACK_WEBHOOK_URL"
```

---

## 3. Containerized Micro-Runners: Docker & Docker Compose

Running browser scrapers inside containers often causes resource issues—like Chromium memory crashes via depleted shared memory (`/dev/shm`), zombie PID accumulation, or deadlocks. The following production Dockerfile uses a multi-stage approach, a non-root security context, and `dumb-init` to handle child browser processes cleanly.

### 3.1 Production Hardened `Dockerfile`

Save as `Dockerfile`:

```dockerfile
# ==========================================
# Stage 1: Build virtualenv & wheels
# ==========================================
FROM python:3.11-slim-bullseye AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ==========================================
# Stage 2: Minimalist Production Runner
# ==========================================
FROM python:3.11-slim-bullseye AS runner

# Stop Python from generating .pyc files and enable unbuffered stdout/stderr streaming
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install native dependencies required by Chromium & dumb-init
RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    ca-certificates \
    curl \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Pull prepared virtual environment from Stage 1
COPY --from=builder /opt/venv /opt/venv

# Install Playwright browser engines explicitly into centralized system path
RUN /opt/venv/bin/playwright install chromium

# Create unprivileged application user
RUN groupadd -g 10001 scraper && \
    useradd -u 10001 -g scraper -s /bin/bash -m scraper && \
    mkdir -p /app/data /app/logs /ms-playwright && \
    chown -R scraper:scraper /app /ms-playwright

# Copy project source tree with secured ownership
COPY --chown=scraper:scraper . .

USER scraper:scraper

# Forward signal processing to dumb-init to avoid Chrome zombie process accumulation
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

CMD ["python", "-m", "src.main", "--mode=cluster"]
```

### 3.2 Production `docker-compose.yml`

This deployment profile configures resource limits, mounts `/dev/shm` to prevent browser crashes, and adds automated health checking:

```yaml
version: '3.8'

services:
  scraper-runner:
    build:
      context: .
      dockerfile: Dockerfile
    image: scraper-vault:micro-runner-latest
    restart: unless-stopped
    ipc: host # Grants access to the host's shared memory, preventing Chromium bus crashes
    shm_size: '2gb' # Explicit fallback if host IPC is disabled
    user: "10001:10001"
    
    deploy:
      resources:
        limits:
          cpus: '3.00'
          memory: 4096M
        reservations:
          cpus: '0.50'
          memory: 512M

    environment:
      - RUNTIME_ENV=production
      - CONCURRENCY=6
      - DATABASE_URL=postgresql://svc_app:Pr0d_Vault_98!@warehouse-db:5432/scraping_db
      - REDIS_METRICS_URL=redis://redis-state:6379/0
      - PROXY_ENDPOINT=http://p.webshare.io:80
      - PROXY_USERNAME=scraper_subuser
      - PROXY_PASSWORD=Secret_Token_098

    volumes:
      - scraper_data:/app/data
      - scraper_logs:/app/logs

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

  warehouse-db:
    image: postgres:15-alpine
    restart: always
    environment:
      POSTGRES_DB: scraping_db
      POSTGRES_USER: svc_app
      POSTGRES_PASSWORD: Pr0d_Vault_98!
    volumes:
      - pgdata:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          memory: 2048M

  redis-state:
    image: redis:7-alpine
    restart: always
    deploy:
      resources:
        limits:
          memory: 512M

volumes:
  scraper_data:
  scraper_logs:
  pgdata:
```

---

## 4. The 25-Point Production Anti-Bot & Fingerprint Checklist

Before running any scraper at scale, audit the target against this 25-point checklist. Modern anti-bot platforms (Cloudflare Turnstile/Under Attack Mode, Datadome, Akamai BMP, PerimeterX/HUMAN) evaluate traffic across multiple network and runtime layers.

```
+-------------------------------------------------------------------------------+
|             ANTI-BOT & BROWSER FINGERPRINT TRIAGE ARCHITECTURE                |
+-------------------------------------------------------------------------------+
|  LAYER 1: NETWORK & TRANSPORT                                                 |
|    [X] Dedicated IPv4/IPv6 Residential Subnets (No ASN Leaks)                 |
|    [X] Validated TLS Fingerprint via Cipher Ordering (JA3/JA4 Parity)         |
|    [X] HTTP/2 Framing, Stream Multiplexing & SETTINGS Alignment               |
|    [X] Consistent Host/Proxy Latency (<120ms Jitter Dispersion)               |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|  LAYER 2: RUNTIME ENGINE & CDP SHIELDING                                      |
|    [X] Nullified navigator.webdriver Object Properties                        |
|    [X] Evaded CDP (Runtime.enable & Console Debugging Traces)                 |
|    [X] Re-bound Function.prototype.toString to Native Built-in Signatures     |
|    [X] Synchronized Canvas/WebGL/WebAudio Noise Injection                     |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|  LAYER 3: BEHAVIORAL DISPERSION & EXECUTION HYGIENE                           |
|    [X] Non-Linear Bezier Cursor Trajectories via Algorithmic Mouse Models     |
|    [X] Realistic Per-Keystroke Latencies (Normal Distribution Curves)         |
|    [X] Human Session Traversal with Organic Mouse Enter/Leave Triggering     |
+-------------------------------------------------------------------------------+
```

### Layer 1: Network & TLS Fingerprinting
- [ ] **1. Clean ASN Reputation:** Run target IP tests via `ipinfo.io`. Ensure your proxy IPs resolve to residential or commercial ISPs (Comcast, AT&T, Verizon), never hosting ASNs (OVH, AWS, DigitalOcean, Hetzner).
- [ ] **2. JA3/JA4 Fingerprint Parity:** Ensure your client TLS fingerprint matches modern browsers. Python's default `requests` library leaks OpenSSL signature orders; use `curl_cffi` or `tls-client` targeting Chrome 120+.
- [ ] **3. HTTP/2 SETTINGS Frame Verification:** Check that the initialization frame sends standard browser parameters (`HEADER_TABLE_SIZE: 65536`, `MAX_CONCURRENT_STREAMS: 1000`, `INITIAL_WINDOW_SIZE: 6291456`).
- [ ] **4. HTTP/2 Header Casing & Order:** Verify that pseudo-headers appear in the required order (`:method`, `:authority`, `:scheme`, `:path`) with lowercase keys.
- [ ] **5. TLS ALPN Negotiation:** Verify the TLS Application-Layer Protocol Negotiation explicitly offers `h2` and `http/1.1`, avoiding raw TCP pipelines that fail to advertise ALPN.
- [ ] **6. Proxy DNS Leak Prevention:** Check that DNS resolution resolves on the remote proxy gateway, not the scraper's host machine (e.g., using `--proxy-type socks5h` instead of `socks5`).

### Layer 2: JavaScript Runtime & CDP Signatures
- [ ] **7. `navigator.webdriver` Nullification:** Verify `navigator.webdriver` is explicitly `false` or `undefined`.
  ```javascript
  // Pass test in DevTools Console:
  Object.getOwnPropertyDescriptor(navigator, 'webdriver'); // Must be undefined
  ```
- [ ] **8. Elimination of Chrome DevTools Protocol (CDP) Leaks:** Anti-bot scripts detect CDP bindings via `window.cdc_adoQpoasnfa76pfcZLmcfl_Array`. Ensure binary patching or use undetected drivers (`undetected-chromedriver` or `playwright-stealth`).
- [ ] **9. Runtime `Function.prototype.toString` Integrity:** Verify patched native functions cannot be detected via inspection:
  ```javascript
  // Must print native code signature:
  WebGLRenderingContext.prototype.getParameter.toString(); 
  // "function getParameter() { [native code] }"
  ```
- [ ] **10. WebGL Vendor & Renderer Masquerading:** Confirm your headless browser presents legitimate GPU strings rather than SwiftShader:
  *   *Renderer:* `ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)`
  *   *Vendor:* `Google Inc. (NVIDIA)`
- [ ] **11. Canvas Hash Noise/Consistency:** Ensure Canvas operations generate consistent hashes across the session without matching a known headless default.
- [ ] **12. AudioContext Fingerprint Generation:** Verify that `AudioContext` and `OfflineAudioContext` return valid frequency vectors and dynamic audio buffer decays.
- [ ] **13. Navigator Screen/Window Parity:** Check that window metric checks resolve correctly:
  ```javascript
  window.outerWidth - window.innerWidth >= 0; // True
  window.screen.availHeight <= window.screen.height; // True
  window.devicePixelRatio >= 1; // Must never be 0
  ```
- [ ] **14. Hardware Concurrency & Memory Profiles:** Verify realistic values:
  *   `navigator.hardwareConcurrency` must be an even integer (`4`, `8`, `16`).
  *   `navigator.deviceMemory` must be a valid memory boundary (`4`, `8`), never `undefined`.
- [ ] **15. Peripheral Detection:** Confirm `navigator.plugins.length > 0` and `navigator.mimeTypes` contain expected PDF and browser extensions.

### Layer 3: Protocol, Headers & Context Tracking
- [ ] **16. Complete User-Agent / Sec-CH-UA Consistency:** Verify Client Hint headers match the User-Agent:
  ```http
  User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36
  sec-ch-ua: "Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"
  sec-ch-ua-mobile: ?0
  sec-ch-ua-platform: "Windows"
  ```
- [ ] **17. Accept-Language & Timezone Consistency:** Match system headers to your proxy's geolocation:
  *   *Proxy Region:* Frankfurt, Germany.
  *   *Header:* `Accept-Language: de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7`
  *   *Emulated Timezone:* `Europe/Berlin` (via `Intl.DateTimeFormat().resolvedOptions().timeZone`).
- [ ] **18. Referer Header Lifecycle Management:** Do not send naked, non-referral GET requests directly to internal product sub-routes. Seed history from search landing pages or search engines first.
- [ ] **19. Cache Headers & Static Resource Flow:** Request linked `.css`, `.js`, font, and image files naturally instead of stripping asset calls entirely, which triggers basic bot detection.

### Layer 4: Behavioral Profiling & Traversal Mechanics
- [ ] **20. Curved Human-Like Mouse Trajectories:** Use cubic Bezier curves with varying velocity models. Avoid straight-line cursor jumps (`moveTo(x, y)`).
- [ ] **21. Realistic Keyboard Dynamics:** Inject typing cadence with human-like variance (70ms–240ms delays per keystroke, with occasional backspaces).
- [ ] **22. Natural Scrolling Dynamics:** Scroll using incremental steps, dynamic deceleration, and brief pauses to mimic real content consumption:
  ```python
  # Example step:
  await page.mouse.wheel(delta_x=0, delta_y=random.randint(180, 420))
  ```
- [ ] **23. DOM Focus & FocusOut States:** Trigger standard document focus events (`window.onfocus`, `element.focus()`) before typing input fields.
- [ ] **24. Session Pacing:** Enforce Poisson-distributed delays between target actions. Avoid static sleeping patterns (`time.sleep(5)`).
- [ ] **25. Automated CAPTCHA Fallback:** If a CAPTCHA appears, verify your system isolates cookies, extracts the site key, calls an external solver (such as 2Captcha, CapSolver, or Anti-Captcha), and injects the response token cleanly without reloading the base page context.

---

## 5. Zero-Downtime Triage & Live Debugging CLI Cheatsheet

This cheatsheet provides production Linux, Docker, and network diagnostics for real-time scraper troubleshooting.

### 5.1 Host & systemd Inspection

```bash
# Display full systemd status, including real-time cgroup memory consumption
sudo systemctl status scraper-worker.service

# Stream unit logs with microsecond precision timestamps, reverse chronological order
sudo journalctl -u scraper-worker.service -f -o short-precise

# Query journal errors strictly matching exit code failures from previous 6 hours
sudo journalctl -u scraper-worker.service --since "6 hours ago" -p err..emerg

# Trace CPU, Memory, and Disk IO load per systemd unit continuously
systemd-cgtop

# Gracefully signal scraper daemon to finish processing current loop
sudo kill -SIGTERM $(systemctl show --property MainPID --value scraper-worker.service)

# Force-kill a runaway scraper daemon instance
sudo systemctl kill -s SIGKILL scraper-worker.service
```

### 5.2 Process Analysis & Zombie Chrome Cleanup

```bash
# Locate all headless Chrome and Playwright instances along with parent process IDs
ps aux | grep -E '(chrome|chromium|playwright)' | awk '{print $2, $3, $4, $11}'

# Check process trees to find orphaned child browsers whose parent runners crashed
pstree -p -s $(pgrep -f "python.*src.main")

# Terminate all orphaned/zombie Chrome browser processes instantly
sudo kill -9 $(pgrep -f "(chrome|chromium).*headless")

# Count the number of active open file descriptors for the running scraper process
ls -1 /proc/$(pgrep -f "python -m src")/fd | wc -l

# Identify open network sockets tied to a running python scraper process
lsof -Pan -p $(pgrep -f "python -m src") -i
```

### 5.3 Docker Micro-Runner Triage

```bash
# View real-time resource utilization across all scraping containers
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}"

# Follow container logs, displaying only the last 200 lines and appending timestamps
docker compose logs --tail=200 -t -f scraper-runner

# Execute an interactive shell within a running container without stopping it
docker compose exec -it scraper-runner /bin/bash

# Inspect container exits caused by OOM (Out-of-Memory) killer
docker inspect scraper-runner --format='{{range .State}}{{println .ExitCode .OOMKilled}}{{end}}'

# Check available shared memory inside the container (must match host capabilities)
docker compose exec scraper-runner df -h /dev/shm
```

### 5.4 Network, Proxy & TLS Triage

```bash
# Test residential proxy connectivity, latency, and returned public IP address
curl -I -sS -k --proxy "http://user:password@proxy.example.com:8000" "https://httpbin.org/ip"

# Run an in-depth TLS handshake inspection to view negotiated ciphers and protocol versions
openssl s_client -connect target-site.com:443 -servername target-site.com -tls1_3 -brief

# Validate HTTP/2 ALPN availability and display detailed protocol frame negotiations
curl -I --http2 -v -s -o /dev/null https://target-site.com/robots.txt

# Measure round-trip time across different stages of a proxy request (DNS, TLS, Connect)
curl -w "\nLookup: %{time_namelookup}s\nConnect: %{time_connect}s\nAppConnect: %{time_appconnect}s\nStartTransfer: %{time_starttransfer}s\nTotal: %{time_total}s\n" \
     -o /dev/null -s -x "http://user:password@proxy.example.com:8000" "https://target-site.com/api/test"

# Inspect local network interface drops or saturation points
netstat -s | grep -E '(overflows|dropped)'
```

### 5.5 Diagnostics Quick-Reference

| Problem / Symptom | Root Cause | Diagnosis Command | Primary Remediation Action |
| :--- | :--- | :--- | :--- |
| **`TargetClosedError`** | Chromium ran out of memory in `/dev/shm`. | `df -h /dev/shm` | Set `ipc: host` or `shm_size: 2gb` in `docker-compose.yml`. |
| **Cloudflare Error 1020** | Broken TLS fingerprint (JA3/JA4) or datacenter ASN. | `curl_cffi` debug test with proxy. | Switch to residential proxy pool; use TLS impersonation (`impersonate="chrome120"`). |
| **Rapid Process Exit (Code 13
