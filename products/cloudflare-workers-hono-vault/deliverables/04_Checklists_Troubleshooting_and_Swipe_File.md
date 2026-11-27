# Module 4: Edge Production Checklist, Benchmarks & Debugging Swipe File

---

## 1. Pre-Flight Edge Production Readiness Checklist

Every Worker, D1 migration, Durable Object, and Queue pipeline must clear this audit gate prior to promoting code from staging to production environments.

| Subsystem | Audit Item | Verification Command / Target Standard | Criticality |
| :--- | :--- | :--- | :--- |
| **Routing / Engine** | Zero Cold-Start Top-Level IO | Top-level scope must only define stateless singletons. No top-level `await fetch()` or unmemoized crypto key imports. | P0 - Blocker |
| **Routing / Engine** | Global Exception Trapping | Hono app implements `app.onError((err, c) => ...)` returning strict RFC 7807 JSON. Raw stack traces stripped in production. | P0 - Blocker |
| **Security** | Secret Hardening | `wrangler.toml` contains zero plaintext credentials. Zero environment secrets stored in source control. Verified via Git pre-commit scan. | P0 - Blocker |
| **Security** | TLS & Header Hardening | Enforce HSTS (`max-age=63072000; includeSubDomains; preload`), `X-Content-Type-Options: nosniff`, and secure CORS origin whitelisting. | P1 - High |
| **D1 Relational** | Schema Version Alignment | D1 migrations applied via automated pipeline before deployment. Run `wrangler d1 migrations list <DB_NAME> --remote`. | P0 - Blocker |
| **D1 Relational** | Index Coverage Verification | Run `EXPLAIN QUERY PLAN` on all hot read queries. Eliminate full-table scans (`SCAN TABLE`) on tables exceeding 1,000 rows. | P1 - High |
| **Durable Objects** | Alarm Idempotency | Alarm handlers must tolerate multiple executions or immediate rescheduling without data corruption. | P0 - Blocker |
| **Durable Objects** | Storage Transaction Size | Ensure single transaction writes do not exceed 128 KB chunks or 2,048 keys per batch call. | P1 - High |
| **Queues** | Dead Letter Queue (DLQ) Hooked | All primary queues must define a downstream DLQ with `max_retries` explicitly declared (minimum 3, maximum 5). | P0 - Blocker |
| **Queues** | Batch Processing Isolation | Consumer worker uses `message.retry()` for transient failures rather than throwing fatal errors that fail the entire batch. | P1 - High |
| **Resource Budgets**| Memory Leak Profiling | Resident heap footprint verified under continuous invocation using Miniflare memory benchmarks (< 32 MB resting). | P1 - High |

---

## 2. Runtime Limits, Resource Guardrails & Allocation Benchmarks

### 2.1 The Edge Hard-Limits Matrix

| Constraint Parameter | Workers Standard (Paid) | Workers Unbound / CPU Boost | Durable Objects |
| :--- | :--- | :--- | :--- |
| **Memory Limit** | 128 MB | Up to 512 MB (configuration dependent) | 128 MB |
| **Wall-Clock Execution** | 30s (HTTP request active) | Dynamic / Client connection lifetime | Unlimited (as long as WebSocket / CPU active) |
| **CPU Time per Request** | 50 ms default | 30,000 ms (Up to 15m for Queue consumers) | 30,000 ms per turn |
| **Subrequests per Request**| 50 | 1,000 | 1,000 |
| **Simultaneous Connections**| 6 | 6 | 32 concurrent outbound fetch calls |
| **Environment Variable Size**| 5 KB total per variable | 5 KB total per variable | 5 KB total per variable |
| **Script Size (Compressed)**| 10 MB (gzip) | 10 MB (gzip) | 10 MB (gzip) |

### 2.2 In-Worker Latency and Memory Guardrail Middleware

Drop this middleware directly into your Hono root pipeline to monitor execution duration, trap runaway CPU consumption, and terminate requests before Cloudflare terminates the worker ungracefully (Error 1101).

```typescript
import { MiddlewareHandler } from "hono";

interface GuardrailOptions {
  maxCpuMs: number;
  warnMemoryBytes: number;
}

export const edgeGuardrails = (options: GuardrailOptions = { maxCpuMs: 40, warnMemoryBytes: 96 * 1024 * 1024 }): MiddlewareHandler => {
  return async (c, next) => {
    const startWall = performance.now();
    
    await next();

    const duration = performance.now() - startWall;
    
    // Inject precision performance headers for downstream metrics
    c.res.headers.set("Server-Timing", `edge;dur=${duration.toFixed(2)}`);

    // Edge-native memory consumption audit (Miniflare / Supported Runtimes)
    // @ts-expect-error - performance.memory is non-standard but populated in v8 edge isolates
    const memUsage = performance.memory ? performance.memory.usedJSHeapSize : null;

    if (memUsage && memUsage > options.warnMemoryBytes) {
      console.warn(JSON.stringify({
        event: "GUARDRAIL_MEMORY_WARNING",
        uri: c.req.url,
        memoryUsedMB: (memUsage / (1024 * 1024)).toFixed(2),
        thresholdMB: (options.warnMemoryBytes / (1024 * 1024)).toFixed(2),
        timestamp: new Date().toISOString()
      }));
    }

    if (duration > options.maxCpuMs) {
      console.warn(JSON.stringify({
        event: "GUARDRAIL_CPU_TIME_EXCEEDED",
        uri: c.req.url,
        durationMs: duration.toFixed(2),
        budgetMs: options.maxCpuMs,
        timestamp: new Date().toISOString()
      }));
    }
  };
};
```

---

## 3. Production CI/CD Pipeline: GitHub Actions Workflows

This enterprise deployment pipeline validates types, executes isolated tests via Miniflare, applies pending D1 migrations idempotently, and executes an atomic blue/green deployment via Wrangler.

### `.github/workflows/deploy-production.yml`

```yaml
name: Production Edge Deployment Pipeline

on:
  push:
    branches:
      - main
  workflow_dispatch:

concurrency:
  group: production-worker-deploy
  cancel-in-progress: false

jobs:
  verify:
    name: Lint, Typecheck & Integration Test
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Source
        uses: actions/checkout@v4

      - name: Install Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'

      - name: Install Dependencies
        run: npm ci

      - name: TypeScript Static Validation
        run: npm run typecheck

      - name: Run Vitest with Miniflare Runtime Emulation
        run: npm run test:ci
        env:
          NODE_ENV: test

  apply-migrations:
    name: Execute D1 Remote Migrations
    needs: verify
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Source
        uses: actions/checkout@v4

      - name: Install Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'

      - name: Install Dependencies
        run: npm ci

      - name: Run D1 Production Migrations
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: d1 migrations apply production-db --remote

  deploy:
    name: Promote Worker to Production
    needs: apply-migrations
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Source
        uses: actions/checkout@v4

      - name: Install Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'

      - name: Install Dependencies
        run: npm ci

      - name: Deploy Worker to Edge Fleet
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: deploy --env production

      - name: Run Synthetic Canary Edge Verification
        run: |
          PROD_URL="https://api.yourdomain.com/healthz"
          STATUS=$(curl -s -o /dev/null -w "%{http_code}" --retry 3 --retry-delay 2 "$PROD_URL")
          if [ "$STATUS" -ne 200 ]; then
            echo "Deployment Verification Failed with status: $STATUS"
            exit 1
          fi
          echo "Production endpoint verified successfully."
```

---

## 4. Local Emulation & Testing Workflows with Miniflare 3 & Vitest

The standard for testing Cloudflare Workers combines Vitest with `@cloudflare/vitest-pool-workers` to instantiate true `workerd` V8 isolates inside unit tests.

### 4.1 `vitest.config.mts`

```typescript
import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        wrangler: {
          configPath: "./wrangler.toml",
          environment: "test",
        },
        miniflare: {
          d1Databases: ["DB"],
          kvNamespaces: ["CACHE_KV"],
          queues: ["TASK_QUEUE"],
        },
      },
    },
  },
});
```

### 4.2 Comprehensive Integration Test Suite: `test/api.spec.ts`

```typescript
import { env, createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { describe, it, expect, beforeAll } from "vitest";
import worker from "../src/index";

describe("Production App End-to-End Suite", () => {
  beforeAll(async () => {
    // Apply local ephemeral D1 schema for testing isolation
    await env.DB.exec(`
      CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        email TEXT NOT NULL,
        created_at INTEGER NOT NULL
      );
    `);
  });

  it("POST /api/users - registers user in D1 and fires off Queue message", async () => {
    const payload = {
      id: "usr_prod_test_01",
      tenant_id: "ten_alpha",
      email: "engineer@enterprise.internal"
    };

    const request = new Request("http://edge.internal/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const ctx = createExecutionContext();
    const response = await worker.fetch(request, env, ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(201);
    
    // Assert D1 Relational State
    const row = await env.DB.prepare("SELECT * FROM users WHERE id = ?")
      .bind(payload.id)
      .first<{ id: string; email: string }>();

    expect(row).toBeDefined();
    expect(row?.email).toBe(payload.email);
  });

  it("GET /api/users/:id - returns cached response and executes within budget", async () => {
    const request = new Request("http://edge.internal/api/users/usr_prod_test_01", {
      method: "GET"
    });

    const ctx = createExecutionContext();
    const response = await worker.fetch(request, env, ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(200);
    const body = await response.json<{ id: string }>();
    expect(body.id).toBe("usr_prod_test_01");
    expect(response.headers.get("Server-Timing")).toContain("edge;dur=");
  });

  it("Handles D1 Connection Faults Gracefully", async () => {
    const badRequest = new Request("http://edge.internal/api/users/non-existent-user", {
      method: "GET"
    });

    const ctx = createExecutionContext();
    const response = await worker.fetch(badRequest, env, ctx);
    await waitOnExecutionContext(ctx);

    expect(response.status).toBe(404);
    const body = await response.json<{ error: { code: string } }>();
    expect(body.error.code).toBe("NOT_FOUND");
  });
});
```

---

## 5. Production Incident Recovery Playbooks (Runbooks)

### Runbook 1: Cloudflare Error 1101 (Worker Threw Exception)

#### Identification
Cloudflare Edge returns standard HTTP 500 with edge-level Error 1101. Origin logs register an unhandled rejection, invalid top-level invocation, or V8 heap exhaustion during request dispatch.

#### Live Diagnostic Command
```bash
# Stream raw runtime errors from production, filtering out non-fatal logs
wrangler tail --env production --format json | jq 'select(.outcome == "exception")'
```

#### Immediate Triage & Mitigation Strategy
1. **Analyze Stack Traces**: Look for `.uncaughtException` in the output from `wrangler tail`.
2. **Detect Out-Of-Memory (OOM)**: If the stack trace returns `Uncaught (in promise) Error: The script will never generate a response`, the isolate exhausted its 128 MB RAM limit.
3. **Roll Back Worker Immediately**:
   ```bash
   # Roll back to the preceding deployment version hash
   wrangler rollback --env production
   ```
4. **Local Reproduction**:
   Inspect heap sizes locally using Miniflare with memory logging enabled:
   ```bash
   npx miniflare dist/index.js --d1 DB --kv CACHE_KV
   ```

---

### Runbook 2: D1 Contention & Concurrency Stalls (Error 10022 / SQLITE_BUSY)

#### Identification
API latencies suddenly elevate from ~15ms to >5,000ms. Endpoints executing transactions return:
`Error: D1_ERROR: database is locked (SQLITE_BUSY)` or `Error 10022: Storage system rate limit exceeded`.

#### Live Diagnostic Command
```bash
wrangler tail --env production --format json | jq 'select(.logs[].message | contains("SQLITE_BUSY"))'
```

#### Remediation Matrix

```
                      Is SQLITE_BUSY observed?
                                |
               +----------------+----------------+
               |                                 |
         Read Heavy Query                Write Heavy Burst
               |                                 |
     Add in-worker Cache-Control        Refactor Write Pattern
     or KV memoization. Route           Route writes to Queue.
     queries using prepared statements  Batch writes up to 100
     with first() instead of all().     statements per transaction.
```

#### Structural Repair Pattern: Batching Writes via Queue
Do not permit concurrent Worker requests to execute single-row `INSERT` operations simultaneously under high load. Route writes through an intermediate Queue that executes batches.

```typescript
// Fix: High-frequency write queue batch processor
export async function processD1BatchQueue(
  batch: MessageBatch<{ id: string; metric: number; timestamp: number }>,
  db: D1Database
): Promise<void> {
  const statements: D1PreparedStatement[] = [];

  for (const message of batch.messages) {
    statements.push(
      db.prepare("INSERT INTO telemetry (id, metric, timestamp) VALUES (?, ?, ?)")
        .bind(message.body.id, message.body.metric, message.body.timestamp)
    );
  }

  try {
    // Executes up to 128 statements in a single atomic SQLite transaction
    await db.batch(statements);
    batch.ackAll();
  } catch (error) {
    console.error("D1 Transaction Batch Failed: ", error);
    // Exponential backoff via queue message retries
    for (const msg of batch.messages) {
      msg.retry();
    }
  }
}
```

---

### Runbook 3: Queue Backpressure Saturation & DLQ Exhaustion

#### Identification
Queue backlog expands continuously. Metrics in the Cloudflare Dashboard reveal `Backlog Message Count` growing while `Concurrent Consumers` hits its peak limit. DLQ starts filling with abandoned events.

#### Live Diagnostic Command
```bash
# Observe queue consumer operations in real-time
wrangler tail your-queue-consumer-worker --env production
```

#### Immediate Triage & Mitigation Strategy
1. **Adjust Consumer Batch Settings**: Increase processing throughput in `wrangler.toml`.
   ```toml
   [[queues.consumers]]
   queue = "production-events"
   max_batch_size = 100      # Scale up from default 10 to maximum 100
   max_batch_timeout = 2     # Process quickly; flush within 2 seconds
   max_retries = 3
   dead_letter_queue = "production-events-dlq"
   max_concurrency = 20      # Increase concurrent consumer instances
   ```
2. **Deploy Configuration Change Immediately**:
   ```bash
   wrangler deploy --env production
   ```
3. **Evacuate the Dead Letter Queue**: Once root-cause logic fixes are deployed, drain the DLQ back to the primary processor using an evacuation script.

```typescript
// scripts/drain-dlq.ts
export async function drainDlq(dlq: Queue, primaryQueue: Queue, batchSize = 50) {
  // Read messages and re-inject to the primary pipeline
  // Executed via a short-lived administrative worker task
}
```

---

### Runbook 4: Durable Object Storage Stalls / Unresponsive Locks

#### Identification
Durable Object instances stop responding to incoming HTTP/RPC frames. Callers experience timeouts or client disconnections after 30 seconds of execution with state locks never releasing.

#### Live Diagnostic Command
```bash
wrangler tail --env production --format json | jq 'select(.event.request.headers["x-do-id"] != null)'
```

#### Root Cause Analysis
A blocking transaction executed indefinitely, or the DO state entered an unresolved Promise inside `blockConcurrencyWhile()`:

```typescript
// FATAL ANTI-PATTERN: DO will hang forever if the external fetch fails to resolve
await this.ctx.blockConcurrencyWhile(async () => {
  const remoteData = await fetch("https://third-party-api.com/sync"); // NEVER DO THIS
  await this.ctx.storage.put("state", await remoteData.json());
});
```

#### Remediation and Recovery
1. **Force Terminate Broken DO Isolates**: Durable Objects are evicted from memory when their current isolate is purged by Cloudflare. Issue an empty deployment to cycle worker isolates worldwide:
   ```bash
   wrangler deploy --env production
   ```
2. **Apply the Fallback Timeout Wrapper**: Refactor all DO state initializers to use strict wall-clock abort timeouts:

```typescript
export async function safeBlockConcurrency<T>(
  ctx: DurableObjectState,
  fn: () => Promise<T>,
  timeoutMs = 5000
): Promise<T> {
  return ctx.blockConcurrencyWhile(async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      return await Promise.race([
        fn(),
        new Promise<T>((_, reject) => {
          controller.signal.addEventListener("abort", () => {
            reject(new Error(`DO Concurrency Block timed out after ${timeoutMs}ms`));
          });
        })
      ]);
    } finally {
      clearTimeout(timer);
    }
  });
}
```

---

## 6. Real-Time Production Log Triage Cheatsheet

Save these battle-tested jq queries for critical incident triage via `wrangler tail`.

### Filter HTTP 5xx Responses
```bash
wrangler tail --env production --format json | jq 'select(.event.response.status >= 500) | {status: .event.response.status, url: .event.request.url, logs: .logs}'
```

### Trace Slow Requests (> 500ms Edge Execution)
```bash
wrangler tail --env production --format json | jq 'select(.event.response.headers["server-timing"] != null) | select((.event.response.headers["server-timing"] | capture("dur=(?<dur>[0-9\\.]+)").dur | tonumber) > 500)'
```

### Inspect Outbound Subrequest Errors
```bash
wrangler tail --env production --format json | jq '.diagnosticsChannelEvents[]? | select(.hasError == true)'
```

### Real-Time In-Worker Memory Usage Monitor
```bash
wrangler tail --env production --format json | jq -r '.logs[]? | select(.message | contains("GUARDRAIL_MEMORY_WARNING")) | .message'
