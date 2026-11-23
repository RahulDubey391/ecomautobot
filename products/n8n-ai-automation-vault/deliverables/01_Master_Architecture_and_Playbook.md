# Module 1: Complete n8n Architecture, Queue Scaling & Production Hardening

This guide covers the deployment, scaling, and operational hardening of self-hosted n8n in high-throughput environments. It is designed for engineers running multi-step AI agent pipelines, long-running LLM completions, and high-frequency webhook ingestions.

---

## 1. Production Architecture Overview & Topology

Default single-container n8n instances collapse under heavy AI workloads. Running embeddings, agentic step loops, and raw payload parsing within a single Node.js event loop creates CPU starvation, drops incoming webhooks, and exhausts database connection pools.

To support production workloads, n8n must run in **Queue Mode** using Redis as a shared state/message broker, PostgreSQL 16 as the persistent transactional store, and dedicated, decoupled process types:

```
                                  [ Internet / Ingress Traffic ]
                                                 │
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │    Reverse Proxy / Edge (Nginx/TLS)   │
                             └───────┬───────────────────────┬───────┘
                                     │                       │
           Path: /webhook/*, /webhook-test/*                 │ Path: /, /rest/*, /api/*
                                     ▼                       ▼
                        ┌────────────────────────┐  ┌────────────────────────┐
                        │   n8n-webhook (1..N)   │  │    n8n-main (Leader)   │
                        │   Fast HTTP Ingestion  │  │   UI, Editor, Cron     │
                        └────────────┬───────────┘  └────────────┬───────────┘
                                     │                           │
                                     │  BullMQ Task Delegation   │
                                     ▼                           ▼
                        ┌────────────────────────────────────────────────────┐
                        │                 Redis 7 (In-Memory)                │
                        │            Queue Broker & Pub/Sub Layer            │
                        └────────────────────────────┬───────────────────────┘
                                                     │
                                                     ▼
                                     ┌───────────────────────────────┐
                                     │       n8n-worker (1..M)       │
                                     │    Heavy Execution Engine     │
                                     │  (AI, Agents, Data Transform) │
                                     └───────────────┬───────────────┘
                                                     │
                                                     ▼
                        ┌────────────────────────────────────────────────────┐
                        │              PostgreSQL 16 (Storage)               │
                        │        Workflows, Executions, Credentials          │
                        └────────────────────────────────────────────────────┘
```

### Component Roles and Failure Boundaries

1. **n8n-main (Orchestrator & Webhook Scheduler):**
   * Hosts the UI editor, REST APIs, and the workflow activation engine.
   * Runs the scheduler (`CRON`) and triggers poll-based nodes (e.g., IMAP, polling APIs).
   * **Failure Boundary:** If this node crashes, running executions continue via workers, and webhook ingestion remains functional. Only UI access, cron triggers, and manual testing are interrupted.

2. **n8n-webhook (Dedicated Ingest Node):**
   * Operates with `EXECUTIONS_MODE=queue` using the command `n8n webhook`.
   * Stripped of UI and cron responsibilities; its sole job is to receive HTTP requests, push the job to Redis BullMQ, and immediately return `200 OK` or `202 Accepted`.
   * **Failure Boundary:** Scale horizontally behind your load balancer. Even if workers are saturated, webhooks are captured without dropping requests.

3. **n8n-worker (Compute Execution Engine):**
   * Operates with `EXECUTIONS_MODE=queue` using the command `n8n worker --concurrency=10`.
   * Pulls serialized jobs from Redis, executes nodes (including Python/JS transforms and LangChain/AI nodes), streams execution states to PostgreSQL, and pushes execution updates back over Redis Pub/Sub.
   * **Scaling Policy:** Scale based on Redis queue depth (`bull:jobs:waiting`) and CPU utilization.

4. **Redis 7 (BullMQ Broker):**
   * Retains the short-term state of all running, waiting, and failed executions.
   * Runs with `appendonly yes` and strict eviction policies (`noeviction`) to prevent job loss.

5. **PostgreSQL 16 (Relational Source of Truth):**
   * Stores JSON workflow structures, workflow execution metadata, user credentials, and encrypted variables.
   * Requires proactive pruning configurations to prevent table bloat from high-volume JSON logs.

---

## 2. Production Docker Compose Stack

This multi-container Docker Compose file includes resource boundaries, health checks, network segregation, and optimized container configurations.

Save this file as `/opt/n8n/docker-compose.yml`:

```yaml
version: '3.8'

x-n8n-common: &n8n-common
  image: docker.n8n.io/n8nio/n8n:1.45.1
  restart: always
  networks:
    - n8n_backend
  env_file:
    - .env.production
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy

services:
  postgres:
    image: postgres:16-alpine
    container_name: n8n_postgres
    restart: always
    networks:
      - n8n_backend
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4096M
        reservations:
          cpus: '0.5'
          memory: 1024M
    command: >
      postgres 
      -c max_connections=200
      -c shared_buffers=1024MB
      -c effective_cache_size=3072MB
      -c maintenance_work_mem=256MB
      -c checkpoint_completion_target=0.9
      -c wal_buffers=16MB
      -c default_statistics_target=100
      -c random_page_cost=1.1
      -c effective_io_concurrency=200
      -c work_mem=10485kB
      -c min_wal_size=1GB
      -c max_wal_size=4GB

  redis:
    image: redis:7.2-alpine
    container_name: n8n_redis
    restart: always
    networks:
      - n8n_backend
    command: >
      redis-server 
      --requirepass ${REDIS_PASSWORD}
      --appendonly yes 
      --appendfsync everysec
      --maxmemory 2048mb 
      --maxmemory-policy noeviction
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 2048M
        reservations:
          cpus: '0.25'
          memory: 512M

  n8n-main:
    <<: *n8n-common
    container_name: n8n_main
    ports:
      - "127.0.0.1:5678:5678"
    volumes:
      - n8n_shared_data:/data
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4096M
        reservations:
          cpus: '0.5'
          memory: 1024M

  n8n-webhook:
    <<: *n8n-common
    container_name: n8n_webhook
    command: webhook
    ports:
      - "127.0.0.1:5679:5678"
    volumes:
      - n8n_shared_data:/data
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '2.0'
          memory: 2048M
        reservations:
          cpus: '0.5'
          memory: 512M

  n8n-worker:
    <<: *n8n-common
    command: worker --concurrency=10
    volumes:
      - n8n_shared_data:/data
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '4.0'
          memory: 8192M
        reservations:
          cpus: '1.0'
          memory: 2048M

networks:
  n8n_backend:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  n8n_shared_data:
    driver: local
```

---

## 3. Production Environment Configuration (`.env.production`)

Store this file at `/opt/n8n/.env.production` with permissions set to `0600` (`chmod 600 .env.production`). Do not omit values or use default dev passwords.

```ini
# ==============================================================================
# BASE SYSTEM CONFIGURATION
# ==============================================================================
NODE_ENV=production
N8N_PORT=5678
N8N_PROTOCOL=https
N8N_HOST=n8n.yourdomain.com
WEBHOOK_URL=https://n8n.yourdomain.com/
GENERIC_TIMEZONE=UTC
TZ=UTC

# ==============================================================================
# CRYPTOGRAPHY & SECURITY SECRETS (Generate with: openssl rand -hex 32)
# ==============================================================================
N8N_ENCRYPTION_KEY=d7a31b2685749f7e8a3c54129e7b26c04f98125a6e87d413b52e098a12c45f3e
N8N_USER_MANAGEMENT_JWT_SECRET=f98125a6e87d413b52e098a12c45f3ed7a31b2685749f7e8a3c54129e7b26c0

# ==============================================================================
# RUNTIME SCALING & QUEUE ARCHITECTURE
# ==============================================================================
EXECUTIONS_MODE=queue
QUEUE_BULL_PREFIX=n8n_prod_queue
QUEUE_HEALTH_CHECK_ACTIVE=true

# ==============================================================================
# DATABASE LAYER: POSTGRESQL 16
# ==============================================================================
DB_TYPE=postgresdb
DB_POSTGRESDB_HOST=postgres
DB_POSTGRESDB_PORT=5432
DB_POSTGRESDB_DATABASE=n8n_production
DB_POSTGRESDB_USER=n8n_app_user
DB_POSTGRESDB_PASSWORD=9a8d7e6f5c4b3a21e0d9c8b7a6543210f9e8d7c6b5a43210e9d8c7b6a543210f
DB_POSTGRESDB_SCHEMA=public
DB_POSTGRESDB_SSL_REJECT_UNAUTHORIZED=true
DB_POSTGRESDB_POOL_SIZE=50

# ==============================================================================
# BROKER LAYER: REDIS 7
# ==============================================================================
QUEUE_BULL_REDIS_HOST=redis
QUEUE_BULL_REDIS_PORT=6379
QUEUE_BULL_REDIS_PASSWORD=a1b2c3d4e5f60718293a4b5c6d7e8f901a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d
QUEUE_BULL_REDIS_DB=0
QUEUE_BULL_REDIS_TIMEOUT_THRESHOLD=10000

# ==============================================================================
# PRUNING & RETENTION (Prevents Disks and Databases from Crashing)
# ==============================================================================
EXECUTIONS_DATA_PRUNE=true
EXECUTIONS_DATA_MAX_AGE=168
EXECUTIONS_DATA_PRUNE_MAX_COUNT=50000
EXECUTIONS_DATA_SAVE_ON_ERROR=all
EXECUTIONS_DATA_SAVE_ON_SUCCESS=none
EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=false

# ==============================================================================
# ENGINE, LOGGING, & TIMEOUTS
# ==============================================================================
N8N_DEFAULT_BINARY_DATA_MODE=filesystem
N8N_BINARY_DATA_STORAGE_PATH=/data/binary
EXECUTIONS_TIMEOUT=1800
EXECUTIONS_TIMEOUT_MAX=3600
N8N_LOG_LEVEL=info
N8N_LOG_OUTPUT=console
N8N_METRICS=true
N8N_METRICS_PREFIX=n8n_

# ==============================================================================
# EXTERNAL CODE EXECUTION / AGENT ISOLATION
# ==============================================================================
NODE_FUNCTION_ALLOW_BUILTIN=*
NODE_FUNCTION_ALLOW_EXTERNAL=crypto,lodash,moment,axios
```

---

## 4. High-Performance Reverse Proxy (Nginx Configuration)

The reverse proxy must separate standard UI/API sessions from webhook ingestion traffic. In this configuration, all `/webhook/` traffic routes directly to the load-balanced `n8n-webhook` containers, bypassing the `n8n-main` instance.

Save this file as `/etc/nginx/sites-available/n8n.conf`:

```nginx
# Rate Limiting Zones: 100 requests/sec for webhooks, 20 req/sec for UI
limit_req_zone $binary_remote_addr zone=n8n_webhooks:10m rate=100r/s;
limit_req_zone $binary_remote_addr zone=n8n_ui:10m rate=20r/s;

upstream n8n_main_backend {
    server 127.0.0.1:5678 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

upstream n8n_webhook_backend {
    server 127.0.0.1:5679 max_fails=3 fail_timeout=5s;
    keepalive 64;
}

server {
    listen 80;
    listen [::]:80;
    server_name n8n.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name n8n.yourdomain.com;

    # TLS Hardening
    ssl_certificate /etc/letsencrypt/live/n8n.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/n8n.yourdomain.com/privkey.pem;
    ssl_session_timeout 1d;
    ssl_session_cache shared:MozSSL:10m;
    ssl_session_tickets off;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Performance Settings
    client_max_body_size 64M;
    client_body_buffer_size 1M;
    proxy_buffering off;
    proxy_request_buffering off;

    # Routing 1: Dedicated Webhook Path (High Concurrency)
    location ~ ^/(webhook|webhook-test)/ {
        limit_req zone=n8n_webhooks burst=200 nodelay;

        proxy_pass http://n8n_webhook_backend;
        proxy_http_version 1.1;

        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;

        proxy_connect_timeout 5s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Routing 2: Server-Sent Events (SSE) Push Stream
    location /rest/push {
        proxy_pass http://n8n_main_backend;
        proxy_http_version 1.1;

        proxy_set_header Connection '';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 24h;
    }

    # Routing 3: General Dashboard, API, and Static Files
    location / {
        limit_req zone=n8n_ui burst=40 nodelay;

        proxy_pass http://n8n_main_backend;
        proxy_http_version 1.1;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 15s;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

---

## 5. Enterprise Webhook Security: HMAC Signature Verification

Never process an unverified public webhook payload. Attackers can forge inputs, run malicious prompts against downstream AI agent nodes, or trigger costly LLM loops.

### Cryptographic Validation in the n8n Code Node

Configure your Webhook Trigger to capture raw request parameters:
* **HTTP Method:** `POST`
* **Path:** `secure-ingest`
* **Response Mode:** `When Last Node Finishes` (or `On Received` for async worker jobs)
* **Raw Body:** `Enabled` (Crucial: Parsing JSON prior to verification modifies whitespace and breaks the digest calculation)

```
[ Webhook Node ] 
   └─ Raw Body: ON
   └─ Mode: POST
           │
           ▼
[ Code Node (Verify HMAC) ] ── (Valid) ───► [ Downstream Processing ]
           │
        (Invalid)
           ▼
[ Stop and Error Node ] (Returns 401 Unauthorized)
```

Place this complete, battle-tested JavaScript code directly inside an n8n **Code Node** positioned immediately after the Webhook Node:

```javascript
const crypto = require('crypto');

// 1. Retrieve Raw Payload and Cryptographic Signature Headers
const headers = $input.first().json.headers;
const rawBody = $input.first().json.body;

// Pull signature matching your gateway (Stripe, GitHub, Shopify, or Custom HMAC)
const receivedSignature = headers['x-hub-signature-256'] 
                       || headers['x-signature-sha256'] 
                       || headers['x-webhook-signature'];

if (!receivedSignature) {
  throw new Error('AUTH_FAILED: Missing cryptographic signature header.');
}

// 2. Load Shared Secret Securely
// Define WEBHOOK_SIGNING_SECRET in the environment variables of your worker containers
const sharedSecret = $env.WEBHOOK_SIGNING_SECRET;
if (!sharedSecret) {
  throw new Error('CONFIG_ERROR: WEBHOOK_SIGNING_SECRET is not configured on this worker.');
}

// 3. Normalize Input: Raw Buffer or UTF-8 String Representation
let payloadData;
if (typeof rawBody === 'object') {
  // If the engine parsed to JSON, stringify without spaces (fallback, not ideal)
  payloadData = JSON.stringify(rawBody);
} else {
  payloadData = rawBody;
}

// 4. Compute Expected HMAC-SHA256
const computedHmac = crypto
  .createHmac('sha256', sharedSecret)
  .update(payloadData, 'utf8')
  .digest('hex');

// Normalize signatures for comparison (handle potential 'sha256=' prefixes)
const cleanReceived = receivedSignature.startsWith('sha256=') 
  ? receivedSignature.slice(7) 
  : receivedSignature;

// 5. Constant-Time Comparison to Thwart Timing Attacks
const receivedBuffer = Buffer.from(cleanReceived, 'hex');
const computedBuffer = Buffer.from(computedHmac, 'hex');

if (receivedBuffer.length !== computedBuffer.length) {
  throw new Error('AUTH_FAILED: Signature length mismatch.');
}

const isSignatureValid = crypto.timingSafeEqual(receivedBuffer, computedBuffer);

if (!isSignatureValid) {
  throw new Error('AUTH_FAILED: Cryptographic signature mismatch. Unauthorized payload discarded.');
}

// 6. Return Clean Parsed Payload to Processing Stream
let parsedPayload;
try {
  parsedPayload = typeof rawBody === 'string' ? JSON.parse(rawBody) : rawBody;
} catch (e) {
  throw new Error('MALFORMED_DATA: Verified payload is not valid JSON.');
}

return [{
  json: {
    authenticated: true,
    verifiedAt: new Date().toISOString(),
    payload: parsedPayload
  }
}];
```

---

## 6. Secret Management & Key Rotation Playbook

n8n uses an encryption key (`N8N_ENCRYPTION_KEY`) to encrypt all saved credentials (API keys, OAuth refresh tokens, SSH keys) in PostgreSQL using `aes-256-gcm`. Losing this key permanently renders your credential store unrecoverable.

### Key Management Rules
* Never commit `.env.production` to source control.
* Treat `N8N_ENCRYPTION_KEY` with the same access controls as production database root credentials.
* Back up the key to a dedicated vault (e.g., AWS Secrets Manager, 1Password Teams, or HashiCorp Vault).

### Key Rotation Procedure

To safely rotate your `N8N_ENCRYPTION_KEY` without corrupting production workflows:

1. **Dump the Current PostgreSQL Store:**
```bash
docker exec -t n8n_postgres pg_dump -U n8n_app_user -d n8n_production | gzip > /opt/backups/n8n_pre_key_rotation_$(date +%F_%T).sql.gz
```

2. **Execute the Migration via n8n CLI:**
Scale all workers and webhook instances to zero to prevent concurrent writes:
```bash
docker compose stop n8n-webhook n8n-worker
```

3. **Generate a New Key:**
```bash
OLD_KEY=$(grep N8N_ENCRYPTION_KEY /opt/n8n/.env.production | cut -d '=' -f2)
NEW_KEY=$(openssl rand -hex 32)
```

4. **Run the Built-In Re-encryption Command:**
```bash
docker compose run --rm \
  -e N8N_ENCRYPTION_KEY=$OLD_KEY \
  n8n-main \
  n8n credentials:re-encrypt --clean --to-key=$NEW_KEY
```

5. **Update `.env.production` and Restart Services:**
```bash
sed -i "s/$OLD_KEY/$NEW_KEY/g" /opt/n8n/.env.production
docker compose up -d
```

---

## 7. Execution Pruning & Database Tuning

Running unpruned execution tables in high-volume environments causes table bloat that degrades workflow lookup times and increases query latency across your workers.

### Production Pruning Rules
* **Never store successful executions** in the database unless required by strict audit regulations (`EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`).
* **Route failure payload logging:** Store error instances for developer remediation (`EXECUTIONS_DATA_SAVE_ON_ERROR=all`), with automated row deletion after 7 days (`EXECUTIONS_DATA_MAX_AGE=168`).

### Manual Emergency Prune Script
If the n8n database disk space exceeds 85%, use this emergency purge script to free storage:

```bash
#!/usr/bin/env bash
set -eo pipefail

echo "===> Checking Current Storage Footprint..."
docker exec -t n8n_postgres psql -U n8n_app_user -d n8n_production -c "
SELECT pg_size_pretty(pg_total_relation_size('execution_entity')) AS execution_table_size;
"

echo "===> Purging Execution Records Older Than 7 Days..."
docker exec -t n8n_postgres psql -U n8n_app_user -d n8n_production -c "
DELETE FROM execution_entity WHERE \"stoppedAt\" < NOW() - INTERVAL '7 days';
"

echo "===> Reclaiming Dead Space (VACUUM FULL)..."
# Warning: VACUUM FULL locks the table. Webhook ingestion will continue queuing in Redis,
# but main editor interactions will briefly wait.
docker exec -t n8n_postgres psql -U n8n_app_user -d n8n_production -c "
VACUUM FULL ANALYZE execution_entity;
"

echo "===> Post-Clean Table Size:"
docker exec -t n8n_postgres psql -U n8n_app_user -d n8n_production -c "
SELECT pg_size_pretty(pg_total_relation_size('execution_entity')) AS execution_table_size;
"
```

---

## 8. Zero-Downtime Deployment & Upgrade Runbook

Deploy code and database schema migrations safely using this step-by-step rollout protocol.

### Production Rolling Upgrade Script (`deploy.sh`)

Save this file as `/opt/n8n/deploy.sh` and make it executable (`chmod +x /opt/n8n/deploy.sh`):

```bash
#!/usr/bin/env bash
set -e

COMPOSE_FILE="/opt/n8n/docker-compose.yml"
ENV_FILE="/opt/n8n/.env.production"
BACKUP_DIR="/opt/n8n_backups"

mkdir -p "$BACKUP_DIR"

echo "===> [Step 1/6] Running Snapshot Backup of Database..."
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
docker exec -t n8n_postgres pg_dump -U n8n_app_user -d n8n_production | gzip > "${BACKUP_DIR}/n8n_backup_${TIMESTAMP}.sql.gz"
echo "Backup preserved: ${BACKUP_DIR}/n8n_backup_${TIMESTAMP}.sql.gz"

echo "===> [Step 2/6] Pulling Updated Container Images..."
docker compose --file "$COMPOSE_FILE" --env-file "$ENV_FILE" pull

echo "===> [Step 3/6] Running Database Migrations via Main Instance..."
# Spin up a temporary main container to execute any database schema changes
docker compose --file "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d postgres redis
docker compose --file "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm n8n-main n8n db:migrate

echo "===> [Step 4/6] Upgrading Orchestrator (Main)..."
docker compose --file "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --no-deps n8n-main

echo "===> [Step 5/6] Rolling Restart: Webhook Tier..."
# Rolling restarts guarantee zero dropped external requests
docker compose --file "$COMPOSE_FILE" --env-
