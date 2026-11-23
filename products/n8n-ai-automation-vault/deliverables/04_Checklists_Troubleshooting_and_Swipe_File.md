# Module 4: Production Audit Rubric, Performance Tuning & Node Swipe File

This module serves as your production operational manual. When running high-throughput agentic workflows, autonomous scraping pipelines, and customer-facing API webhooks, standard out-of-the-box n8n configurations will degrade, leak memory, and crash under burst loads. 

Use this guide to audit your instance against enterprise reliability standards, tune Node.js runtime parameters, implement resilient backoff patterns, and copy-paste production-tested JavaScript transformations directly into your workflows.

---

## 1. Production Readiness & Architectural Audit Rubric

Run through this 25-point audit rubric before deploying any mission-critical n8n workflow to production. Every item must achieve a **PASS** status.

| Category | Check ID | Audit Item | Verification Command / Target Standard | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Execution Architecture** | ARC-01 | Queue Mode Activated | `EXECUTIONS_MODE=queue` configured with Redis broker. Main process does not execute workflow jobs. | [ ] |
| | ARC-02 | Multi-Worker Scaling | Minimum 2 worker instances deployed across distinct vCPUs/hosts to prevent single-point-of-failure. | [ ] |
| | ARC-03 | Webhook Isolation | Dedicated webhook processor configured via `n8n webhook` command to isolate ingest traffic from execution jobs. | [ ] |
| | ARC-04 | Process Supervisor | Container orchestrated via Docker Swarm, Kubernetes, or Docker Compose with `restart: always` or `restart: unless-stopped`. | [ ] |
| | ARC-05 | Binary Storage Offload | `N8N_DEFAULT_BINARY_DATA_MODE=filesystem` or `s3` set. In-memory binary storage is disabled. | [ ] |
| **Database & Pruning** | DAT-01 | External PostgreSQL Engine | SQLite is strictly eliminated. PostgreSQL 14+ used with a minimum pool size of 20 (`DB_POSTGRESDB_POOL_SIZE=20`). | [ ] |
| | DAT-02 | Execution Pruning Enabled | `EXECUTIONS_DATA_PRUNE=true` active in environment variables. | [ ] |
| | DAT-03 | Max Execution Age Cap | `EXECUTIONS_DATA_MAX_AGE=168` (7 days max) or lower depending on regulatory/volume profiles. | [ ] |
| | DAT-04 | Prune Execution Batching | `EXECUTIONS_DATA_PRUNE_MAX_COUNT=50000` set to prevent Postgres locks during prune jobs. | [ ] |
| | DAT-05 | Hard-Failure-Only Logging | `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` active on high-concurrency workflows; only error context is persisted. | [ ] |
| **Memory & Runtime** | MEM-01 | V8 Heap Allocation | `NODE_OPTIONS="--max-old-space-size=4096"` (or 8192) explicitly declared matching container cgroup allocations. | [ ] |
| | MEM-02 | Container Memory Headroom | Container limit set to at least 1.25x the V8 max old space size (e.g., 5GB container limit for 4GB V8 heap). | [ ] |
| | MEM-03 | Concurrency Throttle | `N8N_CONCURRENCY_PRODUCTION_LIMIT` configured per worker to avoid saturating Node event loop thread pool. | [ ] |
| | MEM-04 | Payload Size Ceiling | `N8N_PAYLOAD_SIZE_MAX=64` (in MB) set to drop memory-bomb payloads at ingress. | [ ] |
| | MEM-05 | Event Loop Delay Alerting | Prometheus metrics monitored; 99th percentile event loop lag does not exceed 100ms during peak load. | [ ] |
| **Security & Auth** | SEC-01 | Basic Auth / SAML Hardening | Basic Auth disabled in favor of SSO/OIDC or protected behind reverse-proxy Cloudflare Access/Tailscale. | [ ] |
| | SEC-02 | Webhook HMAC Validation | All public-facing webhooks enforce cryptographic signature verification (HMAC-SHA256). | [ ] |
| | SEC-03 | Credential Encryption | `N8N_ENCRYPTION_KEY` backed up securely in an external secret manager (AWS Secrets Manager, HashiCorp Vault). | [ ] |
| | SEC-04 | Environment Variable Masking | Sensitive tokens, internal API keys, and database passwords isolated from workflow JSON export definitions. | [ ] |
| | SEC-05 | Network Isolation | n8n internal network prevents workers from hitting internal metadata endpoints (e.g., `169.254.169.254`). | [ ] |
| **Reliability & LLMs** | REL-01 | LLM Circuit Breakers | Every external AI model call implemented with a 30-to-60-second timeout and structured fallback branch. | [ ] |
| | REL-02 | Rate Limit Backoff Logic | All API nodes integrate explicit exponential backoff with random jitter on HTTP 429/503 responses. | [ ] |
| | REL-03 | JSON Schema Defensive Parsing | All structured LLM completions passed through a resilient sanitizer node handling incomplete JSON and code fences. | [ ] |
| | REL-04 | Token Budget Thresholds | Inputs trimmed dynamically with token estimators prior to context window injection to prevent silent context drops. | [ ] |
| | REL-05 | Global Error Workflow | `Error Trigger` workflow configured globally at instance level, pinging an on-call PagerDuty/Slack routing channel. | [ ] |

---

## 2. High-Concurrency Performance Tuning & Memory Optimization

Running production-grade agentic workflows with dozens of LLM tool interactions requires separating processes, shifting binary streams to disk, and tuning the Node.js V8 garbage collector.

### Production `docker-compose.yml` Architecture

The architecture below isolates the **Editor/Main UI**, the **Webhook Receiver**, and auto-scalable **Workers** connected via a high-throughput Redis instance and an optimized PostgreSQL engine.

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    container_name: n8n_postgres
    restart: always
    environment:
      POSTGRES_USER: n8n_db_user
      POSTGRES_PASSWORD: ReplaceWithProductionSuperPassword123!
      POSTGRES_DB: n8n_production
    volumes:
      - postgres_storage:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U n8n_db_user -d n8n_production"]
      interval: 5s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: "4.0"
          memory: 4096M
        reservations:
          cpus: "1.0"
          memory: 1024M

  redis:
    image: redis:7-alpine
    container_name: n8n_redis
    restart: always
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "2gb", "--maxmemory-policy", "noeviction"]
    volumes:
      - redis_storage:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  # Webhook Ingestion Service (Stateless scale-out)
  n8n-webhook:
    image: docker.n8n.io/n8nio/n8n:latest
    command: webhook
    restart: always
    environment:
      - DB_TYPE=postgresdb
      - DB_POSTGRESDB_HOST=postgres
      - DB_POSTGRESDB_PORT=5432
      - DB_POSTGRESDB_DATABASE=n8n_production
      - DB_POSTGRESDB_USER=n8n_db_user
      - DB_POSTGRESDB_PASSWORD=ReplaceWithProductionSuperPassword123!
      - DB_POSTGRESDB_POOL_SIZE=20
      - EXECUTIONS_MODE=queue
      - QUEUE_BULL_REDIS_HOST=redis
      - QUEUE_BULL_REDIS_PORT=6379
      - N8N_PAYLOAD_SIZE_MAX=64
      - NODE_OPTIONS=--max-old-space-size=2048
      - N8N_DEFAULT_BINARY_DATA_MODE=filesystem
      - N8N_BINARY_DATA_STORAGE_PATH=/data/binary
    volumes:
      - shared_binary_storage:/data/binary
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2560M

  # Main Web Service (Editor and Task Orchestration)
  n8n-main:
    image: docker.n8n.io/n8nio/n8n:latest
    container_name: n8n_main
    restart: always
    ports:
      - "5678:5678"
    environment:
      - N8N_ENCRYPTION_KEY=GenerateAndInsertA64CharacterHexSecretEncryptionKeyHere
      - DB_TYPE=postgresdb
      - DB_POSTGRESDB_HOST=postgres
      - DB_POSTGRESDB_PORT=5432
      - DB_POSTGRESDB_DATABASE=n8n_production
      - DB_POSTGRESDB_USER=n8n_db_user
      - DB_POSTGRESDB_PASSWORD=ReplaceWithProductionSuperPassword123!
      - DB_POSTGRESDB_POOL_SIZE=30
      - EXECUTIONS_MODE=queue
      - QUEUE_BULL_REDIS_HOST=redis
      - QUEUE_BULL_REDIS_PORT=6379
      - EXECUTIONS_DATA_PRUNE=true
      - EXECUTIONS_DATA_MAX_AGE=72
      - EXECUTIONS_DATA_PRUNE_MAX_COUNT=25000
      - EXECUTIONS_DATA_SAVE_ON_SUCCESS=none
      - EXECUTIONS_DATA_SAVE_ON_ERROR=all
      - EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=true
      - N8N_DEFAULT_BINARY_DATA_MODE=filesystem
      - N8N_BINARY_DATA_STORAGE_PATH=/data/binary
      - NODE_OPTIONS=--max-old-space-size=4096
      - N8N_PAYLOAD_SIZE_MAX=64
      - N8N_METRICS=true
      - N8N_METRICS_PREFIX=n8n_
    volumes:
      - n8n_storage:/home/node/.n8n
      - shared_binary_storage:/data/binary
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "4.0"
          memory: 5120M

  # Concurrency Worker Nodes
  n8n-worker:
    image: docker.n8n.io/n8nio/n8n:latest
    command: worker --concurrency=10
    restart: always
    environment:
      - DB_TYPE=postgresdb
      - DB_POSTGRESDB_HOST=postgres
      - DB_POSTGRESDB_PORT=5432
      - DB_POSTGRESDB_DATABASE=n8n_production
      - DB_POSTGRESDB_USER=n8n_db_user
      - DB_POSTGRESDB_PASSWORD=ReplaceWithProductionSuperPassword123!
      - DB_POSTGRESDB_POOL_SIZE=20
      - EXECUTIONS_MODE=queue
      - QUEUE_BULL_REDIS_HOST=redis
      - QUEUE_BULL_REDIS_PORT=6379
      - N8N_ENCRYPTION_KEY=GenerateAndInsertA64CharacterHexSecretEncryptionKeyHere
      - N8N_DEFAULT_BINARY_DATA_MODE=filesystem
      - N8N_BINARY_DATA_STORAGE_PATH=/data/binary
      - NODE_OPTIONS=--max-old-space-size=4096
    volumes:
      - shared_binary_storage:/data/binary
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: "4.0"
          memory: 5120M

volumes:
  postgres_storage:
  redis_storage:
  n8n_storage:
  shared_binary_storage:
```

### Critical Environment Parameter Matrix

To permanently prevent degraded execution loops, calibrate these system values:

| Parameter | Recommended Setting | Failure Mechanism if Misconfigured |
| :--- | :--- | :--- |
| `NODE_OPTIONS` | `--max-old-space-size=4096` | Defaults to 1.4GB. Large JSON arrays from Vector Stores or document loaders will trigger out-of-memory container crashes. |
| `EXECUTIONS_DATA_SAVE_ON_SUCCESS` | `none` | Setting to `all` under 50+ concurrent requests per minute locks the Postgres execution table with write operations, cascading into timeouts across all jobs. |
| `N8N_DEFAULT_BINARY_DATA_MODE` | `filesystem` | Default is `default` (in-memory). Processing three concurrent 25MB PDF/Audio uploads will exhaust the Node heap space immediately. |
| `DB_POSTGRESDB_POOL_SIZE` | `20` to `50` | Default connection pool (10) exhausts instantly when multi-worker setups execute multi-branch sub-workflows, throwing connection timeout errors. |
| `N8N_CONCURRENCY_PRODUCTION_LIMIT` | `5` - `20` (per worker) | If set to 0 (unlimited), workers accept all queued tasks immediately, locking the single-threaded Node event loop while parsing payloads. |

---

## 3. Execution Engine Troubleshooting & Crash Playbook

When an n8n production node crashes or behaves unexpectedly, use this step-by-step diagnostic matrix to remediate the underlying issue.

```
                  [ Workflow Crash / Alert Detected ]
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         ▼                                                   ▼
 [Container Exited?]                                [Execution Stalled / Timeout]
         │                                                   │
 ┌───────┴───────┐                                   ┌───────┴───────┐
 ▼               ▼                                   ▼               ▼
(Code 137: OOM)  (Crash on Boot)            (Postgres Pool Wait)   (Downstream 429)
 │               │                                   │               │
 V8 Heap Check   Enforce Permissions                 Increase Pool   Implement Jitter
 Max-Old-Space   DB Migrations Lock                  Or Max Age      Backoff Loop
```

### 1. `FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory`
* **Log Signature:** Process terminates with exit code `137`. Docker displays `OOMKilled: true`.
* **Root Cause:** Node runtime attempted to store dynamic data structures larger than V8's configured boundary. Frequently caused by loading 1,000+ full-text articles or high-dimensional embeddings directly into workflow memory.
* **Remediation Steps:**
  1. Increase the container memory ceiling in your Docker/K8s orchestrator.
  2. Set `NODE_OPTIONS=--max-old-space-size=8192` (matching container memory).
  3. Refactor workflow: Use an iterative batching architecture. Split arrays into chunks of 100 with the `Split In Batches` node or an n8n custom code loop, clearing upstream references.
  4. Ensure `N8N_DEFAULT_BINARY_DATA_MODE=filesystem` is applied so binary buffers are streamed to disk rather than allocated on the heap.

### 2. `QueryFailedError: deadlock detected / connection pool exhausted`
* **Log Signature:** `Connection terminated unexpectedly` or `timeout exceeded when trying to connect to the database`.
* **Root Cause:** Multiple workers and high workflow concurrency are competing for PostgreSQL connection slots, compounded by executions writing every node state to the database.
* **Remediation Steps:**
  1. Set `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`.
  2. Update PostgreSQL's server-level configuration: `max_connections = 200`.
  3. Increase n8n environment pool capacity: `DB_POSTGRESDB_POOL_SIZE=30` on every worker and main service.
  4. Configure PgBouncer in front of PostgreSQL using `transaction` pooling mode if scaling past 5 worker nodes.

### 3. `Workflow execution timed out` / Node Event Loop Freezing
* **Log Signature:** Executions remain in `running` status indefinitely until hitting execution timeout thresholds; UI feels unresponsive.
* **Root Cause:** A Code node is executing CPU-intensive synchronous operations (e.g., synchronous regex on huge text corpora, non-async loops, massive JSON stringify operations), starving the Node.js event loop.
* **Remediation Steps:**
  1. Convert all custom JavaScript string processing to stream-friendly or asynchronously chunked operations.
  2. Check for infinite loops in `while` or `for` loops within custom JavaScript nodes.
  3. Implement strict execution timeouts on every workflow under **Workflow Settings** -> **Timeout Workflow** -> Set to `300` seconds.

### 4. `413 Payload Too Large` / Webhook Rejection
* **Log Signature:** HTTP 413 returned to webhook caller; executions do not trigger.
* **Root Cause:** Payloads exceed the default 16MB Express/body-parser boundary in n8n.
* **Remediation Steps:**
  1. Add `N8N_PAYLOAD_SIZE_MAX=128` (sets maximum payload threshold to 128MB).
  2. If using an Nginx/Cloudflare reverse proxy, configure corresponding limits:
     * Nginx: `client_max_body_size 128M;`
     * Cloudflare: Webhooks exceeding 100MB must be split or transferred using pre-signed S3 links directly to cloud storage, triggering n8n with an S3 object key instead.

### 5. `Error: listen EADDRINUSE: address already in use :::5678`
* **Log Signature:** Container loops on restart, exiting immediately after initialization logs.
* **Root Cause:** Two instances attempting to bind to the same network interface, or orphaned zombie processes holding ports inside a persistent volume environment.
* **Remediation Steps:**
  1. Check process tree: `lsof -i :5678` or `netstat -nlp | grep 5678`.
  2. Kill lingering n8n processes: `kill -9 <PID>`.
  3. If operating on Docker Compose, ensure `n8n-worker` and `n8n-webhook` containers do **not** expose or publish `5678:5678` in their host port mappings. Only the `n8n-main` service should bind to port 5678.

### 6. `Database Migrations Locked / Cannot Acquire Lock`
* **Log Signature:** `MigrationLockedError: Migrations are currently locked!`
* **Root Cause:** An unexpected shutdown occurred while a previous version upgrade or dynamic schema migration was mid-transaction.
* **Remediation Steps:**
  1. Stop all containers accessing the database: `docker compose down`.
  2. Connect directly to the PostgreSQL database via your database client or CLI:
     ```sql
     SELECT * FROM migrations;
     -- Clear the persistent migration lock safely:
     DELETE FROM migrations WHERE locked = true;
     -- Alternatively, for modern TypeORM structures used by n8n:
     UPDATE migrations SET is_locked = 0;
     ```
  3. Restart only the `n8n-main` container to complete schema migrations before starting workers.

---

## 4. Resilient Rate-Limit Backoff & Retry Architecture

High-volume calls to LLM providers (Anthropic, OpenAI) and enterprise APIs will inevitably trigger `HTTP 429 Too Many Requests`. Using fixed delays or basic retry counts often leads to "thundering herd" problems that permanently throttle your infrastructure.

### The Algorithm: Truncated Exponential Backoff with Full Jitter

The formula for resilient backoff calculation is:

$$T_{\text{sleep}} = \text{random}(0, \, \min(M, \, B \times 2^{\text{attempt}}))$$

Where:
* $B$ = Base interval (e.g., 1.5 seconds)
* $\text{attempt}$ = Current zero-indexed retry count
* $M$ = Maximum backoff cap (e.g., 60 seconds)
* $\text{random}(0, x)$ = Uniform distribution providing jitter to de-synchronize concurrent workers

```
[ HTTP Request Node ] ──► [ Result HTTP 429? ]
                               │
                ┌──────────────┴──────────────┐
               YES                            NO
                │                             │
    [ Backoff Evaluator Node ]          [ Continue ]
                │
    Wait (Calculated Jitter MS)
                │
       [ Route to Retry ]
```

### Concrete Implementation: JavaScript Backoff Engine Node

Configure your HTTP Request Node with **Continue On Fail: True**. Route its output into this custom JavaScript Code Node to calculate precise retry metrics:

```javascript
/**
 * Production Algorithmic Backoff & Jitter Evaluator
 * Evaluates execution responses and computes dynamic delays.
 */

const baseDelaySeconds = 2.0;
const maxDelaySeconds = 60.0;
const maxAllowedRetries = 5;

// Read execution context or initialize tracking
const currentInput = $input.item(0).json;
const errorResponse = currentInput.error || currentInput;
const statusCode = Number(errorResponse.status || errorResponse.statusCode || (currentInput.headers && currentInput.headers.status) || 200);

// Detect rate limiting or transient upstream failures
const isRateLimited = statusCode === 429;
const isTransientServerError = statusCode >= 500 && statusCode <= 504;
const requiresRetry = isRateLimited || isTransientServerError;

let retryCount = Number(currentInput._retryCount || 0);

if (requiresRetry) {
  if (retryCount >= maxAllowedRetries) {
    throw new Error(`CRITICAL: Max retries (${maxAllowedRetries}) reached. API failed with status ${statusCode}. Payload: ${JSON.stringify(errorResponse)}`);
  }

  retryCount += 1;

  // Check if provider sent an explicit Retry-After header (in seconds or HTTP-Date)
  let retryAfterSeconds = null;
  const headers = currentInput.headers || (errorResponse.response && errorResponse.response.headers);
  
  if (headers) {
    const rawHeader = headers['retry-after'] || headers['Retry-After'];
    if (rawHeader) {
      const parsedValue = Number(rawHeader);
      if (!isNaN(parsedValue)) {
        retryAfterSeconds = parsedValue;
      } else {
        // Parse HTTP Date string if applicable
        const dateMs = Date.parse(rawHeader);
        if (!isNaN(dateMs)) {
          retryAfterSeconds = Math.max(0, Math.ceil((dateMs - Date.now()) / 1000));
        }
      }
    }
  }

  let delayMilliseconds = 0;

  if (retryAfterSeconds !== null) {
    // Add jitter to downstream explicit Retry-After header
    const jitter = Math.random() * 1.5;
    delayMilliseconds = Math.round((retryAfterSeconds + jitter) * 1000);
  } else {
    // Exponential Backoff with Full Jitter Calculation
    const calculatedBackoff = Math.min(maxDelaySeconds, baseDelaySeconds * Math.pow(2, retryCount - 1));
    // Full jitter selects randomly between 0 and calculatedBackoff
    const sleepDurationSeconds = Math.random() * calculatedBackoff;
    delayMilliseconds = Math.round(sleepDurationSeconds * 1000);
  }

  return [{
    json: {
      shouldRetry: true,
      statusCode: statusCode,
      _retryCount: retryCount,
      delayMilliseconds: delayMilliseconds,
      retryMessage: `Throttled (Status ${statusCode}). Retrying attempt ${retryCount}/${maxAllowedRetries} after ${delayMilliseconds}ms.`
    }
  }];
}

// Successful response path
return [{
  json: {
    shouldRetry: false,
    statusCode: statusCode,
    _retryCount: retryCount,
    data: currentInput
  }
}];
```

Route the `shouldRetry === true` output directly into an n8n **Wait Node**, mapping its interval property using the expression `{{ $json.delayMilliseconds }}ms`, then connect it back to the original HTTP Request Node.

---

## 5. The Production JavaScript Code Node Swipe File

These drop-in JavaScript code snippets resolve complex transformations, token safety checks, and payload validations without external library dependencies.

### 1. Token Counter & Context Window Truncator
* **Use Case:** Accurately estimate BPE tokens for strings before injecting them into Claude/OpenAI context windows to prevent unexpected API parameter errors.

```javascript
/**
 * Token Counter & Context Window Safety Truncator
 * Strips or truncates inputs that breach specified token allocations.
 * Approximation: 1 token ~= 4 chars of standard English; accounts for token variance.
 */

const maxTokenLimit = 8000; // Define maximum budget allowed
const charsPerTokenRatio = 3.6; // Conservative ratio for code, special chars, and prose

for (const item of $input.all()) {
  const content = item.json.content || item.json.prompt || item.json.body || "";
  
  if (typeof content !== 'string') {
    item.json.sanitizedContent = content;
    item.json.tokenStats = { estimatedTokens: 0, truncated: false };
    continue;
  }

  const rawLength = content.length;
  const estimatedTokens = Math.ceil(rawLength / charsPerTokenRatio);

  if (estimatedTokens > maxTokenLimit) {
    const maxCharacterBoundary = Math.floor(maxTokenLimit * charsPerTokenRatio);
    // Truncate cleanly at nearest line break or sentence terminus
    let truncated = content.substring(0, maxCharacterBoundary);
    const lastSafeBreak = Math.max(truncated.lastIndexOf('\n'), truncated.lastIndexOf('. '));
    
    if (lastSafeBreak > maxCharacterBoundary * 0.8) {
      truncated = truncated.substring(0, lastSafeBreak);
    }

    item.json.sanitizedContent = truncated + "\n...[CONTENT TRUNCATED FOR PROMPT SAFETY]...";
    item.json.tokenStats = {
      originalTokens: estimatedTokens,
      estimatedTokens: maxTokenLimit,
      truncated: true,
      charactersRemoved: rawLength - truncated.length
    };
  } else {
    item.json.sanitizedContent = content;
    item.json.tokenStats = {
      originalTokens: estimatedTokens,
      estimatedTokens: estimatedTokens,
      truncated: false,
      charactersRemoved: 0
    };
  }
}

return $input.all();
```

---

### 2. Structured JSON Schema Sanitizer & Fallback Parser
* **Use Case:** Parse unstructured or dirty LLM outputs containing markdown code blocks, conversational prefixes, and trailing commas into valid JSON objects.

```javascript
/**
 * Resilient LLM Output JSON Extractor & Sanitizer
 * Recovers malformed JSON, strips outer Markdown formatting, and parses dirty outputs.
 */

function sanitizeAndParseJSON(rawString) {
  if (typeof rawString !== 'string') return rawString;

  let cleaned = rawString.trim();

  // Strip Markdown JSON code fences (```json ... ``` or ``` ...)
  cleaned = cleaned.replace(/^```(?:json)?\s*/i, '');
  cleaned = cleaned.replace(/\s*```$/, '');
  cleaned = cleaned.trim();

  // Isolate substring bounded by outer braces or brackets if extraneous text exists
  const firstBrace = cleaned.indexOf('{');
  const firstBracket = cleaned.indexOf('[');
  let startIdx = -1;

  if (firstBrace !== -1 && firstBracket !== -1) {
    startIdx = Math.min(firstBrace, firstBracket);
  } else {
    startIdx = Math.max(firstBrace, firstBracket);
  }

  if (startIdx !== -1) {
    const isObject = cleaned[startIdx] === '{';
    const endChar = isObject ? '}' : ']';
    const lastIdx = cleaned.lastIndexOf(endChar);

    if (lastIdx > startIdx) {
      cleaned = cleaned.substring(startIdx, lastIdx + 1);
    }
  }

  // Common LLM error: Remove invalid trailing commas before closing braces/brackets
  cleaned = cleaned.replace(/,\s*([\]}])/g, '$1');

  try {
    return JSON.parse(cleaned);
  } catch (primaryErr) {
    // Secondary cleanup: Escape internal unescaped control tabs/newlines
    try {
      const secondaryClean = cleaned
        .replace(/[\n\r]/g, "\\n")
        .replace(/\t/g, "\\t");
      return JSON.parse(secondaryClean);
    } catch (secondaryErr) {
      return {
        parseError: true,
        errorMessage: primaryErr.message,
        rawContent: rawString
      };
    }
  }
}

for (const item of $input.all()) {
  // Check common LLM fields: text, content, response, message
  const rawOutput = item.json.text || 
                    (item.json.message && item.json.message.content) || 
                    item.json.response || 
                    item.json.output;

  if (raw
