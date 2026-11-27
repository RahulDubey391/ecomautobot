# Module 1: Durable Execution Engine & Queuing Architecture Playbook

Durable execution guarantees that your code executes to completion across distributed boundaries, process crashes, serverless execution timeouts, deployment redeploys, and downstream API failures. Unlike traditional message queues that simply pass payloads to workers, durable workflow engines persist execution state at the step level, yielding resilient, replayable, and deterministically auditable distributed state machines.

This playbook establishes the architectural foundation, comparison heuristics, concurrency controls, and failure recovery primitives required to operate durable workflows and background queues at enterprise scale.

---

## 1. The Core Paradigms of Durable Execution

Durable systems solve the dual-write problem, the timeout ceiling, and cascading microservice failures through two distinct models: **Replay-Based Execution** and **Task-Checkpointed Orchestration**.

```
REPLAY-BASED (Inngest / Temporal)
Worker Memory: [ Step 1: Memoized Result ] -> [ Step 2: Memoized Result ] -> [ Step 3: Executing... ]
- Code executes from top to bottom on every wake.
- Yields cached values for previously completed steps.
- Suspends process execution via HTTP/generator suspensions when reaching incomplete steps.

TASK-CHECKPOINTED (Trigger.dev v3 / BullMQ)
Queue Engine -> Worker Process -> Run Task Phase -> Commit State -> Exit/Next Task
- Each step is an isolated, scheduled unit of work dispatched through an orchestration broker.
- Trigger.dev v3 executes tasks inside isolated container/process runtimes with direct checkpointing.
- BullMQ coordinates atomic steps via Redis hashes, streams, and sorted sets with custom consumer loops.
```

### 1.1 The Golden Rules of Workflow Determinism

When using engines that rely on event replay or step memoization (such as Inngest), function code outside of step boundaries **must be strictly deterministic**. Violating determinism causes the engine to throw non-deterministic state errors, corrupt execution graphs, or re-run destructive side-effects.

```
+------------------------------------+---------------------------------------+
| ANTI-PATTERN: Non-Deterministic    | PRODUCTION PATTERN: Deterministic     |
+------------------------------------+---------------------------------------+
| const uuid = crypto.randomUUID();  | const uuid = await step.run('id', ()  |
|                                    |   => crypto.randomUUID());            |
+------------------------------------+---------------------------------------+
| const now = new Date();            | const now = await step.run('ts', ()   |
|                                    |   => new Date().toISOString());       |
+------------------------------------+---------------------------------------+
| const data = await fetch(url);     | const data = await step.run('fetch',  |
|                                    |   () => fetch(url).then(r => r.json()));|
+------------------------------------+---------------------------------------+
| let count = 0;                     | const count = await step.run('calc',  |
| count += externalMutation();       |   () => externalMutation());          |
+------------------------------------+---------------------------------------+
```

1. **Side-Effect Encapsulation**: Any network call, database mutation, file I/O, or random value generation must live inside a tracked step wrapper (e.g., `step.run()`, `task.run()`, or an isolated BullMQ job processor).
2. **Deterministic Inputs**: Rely solely on the initial event payload or memoized step outputs. Never evaluate global, mutable, in-memory state across step boundaries.
3. **Environment Parity**: Workflow logic must not branch based on runtime server environmental parameters (e.g., local process environment variables that can differ between blue-green deployment slices) within step orchestrations.

---

## 2. Comparative Engine Matrix

Evaluate and choose engines based on operational overhead, state store ownership, execution boundaries, and billing models:

| Operational Dimension | Inngest (v3) | Trigger.dev (v3) | BullMQ (v5) | Upstash QStash |
| :--- | :--- | :--- | :--- | :--- |
| **Architecture Type** | Step-level durable execution engine | Real-time background task & orchestration engine | Redis-backed distributed message queue | Serverless HTTP/Webhook pub/sub scheduler |
| **State Storage** | Hosted Inngest Cloud or Self-Hosted Inngest Server (PostgreSQL/Redis) | Hosted Trigger Cloud or Self-Hosted (PostgreSQL) | Self-managed Redis (v6.2+ / v7+) or DragonFly | Serverless Upstash Redis backend (Managed) |
| **Execution Context** | Serverless endpoints (Next.js, Vercel, AWS Lambda, Node.js HTTP servers) | Dedicated worker VMs / long-running Node.js processes | Long-running Node.js/Bun containers (Docker, ECS, Kubernetes) | Arbitrary public HTTP endpoints / Webhooks |
| **Max Run Duration** | Arbitrary (steps can suspend for up to 1 year; individual steps capped by host HTTP limit) | Uncapped (up to days inside long-running task processes) | Uncapped (bounded by Redis job lock renewal and worker lifecycle) | Up to 15 minutes per HTTP webhook attempt |
| **Latency Overhead** | ~50ms–150ms step suspension round-trip | < 20ms real-time task startup | < 5ms task dequeue latency (Redis in-memory) | ~100ms–250ms HTTP webhook dispatch |
| **Concurrency Primitives** | Virtual concurrency keys, debouncing, throttling, batching | Task-level, queue-level, and parent/child concurrency limits | Worker-level concurrency, grouped rate-limiters via Redis Lua | Basic rate limiting per target endpoint or token |
| **Local Dev Experience** | Dedicated local Dev Server (Docker or CLI binary) with web UI | Native CLI (`npx trigger.dev@latest dev`) with remote synchronization | Requires local Redis instance; custom UI requires Bull-Board integration | CLI / Local proxy tunnels (ngrok/localtunnel) |
| **Best-Fit Use Case** | Multi-day stateful flows, AI orchestration pipelines, human-in-the-loop | Long-running AI fine-tuning, complex micro-tasks, heavy compute | High-throughput events (10k+ ops/sec), micro-tasks, cost-sensitive infra | Decoupled webhook dispatching, simple scheduled crons, serverless dispatch |

### Decision Framework Heuristic

```
[Need to run background work]
   │
   ├── Are you orchestrating multi-step, state-dependent workflows, AI pipelines, or human-in-the-loop approvals?
   │     ├── Yes ── Do you run serverless (Vercel, AWS Lambda) and prefer zero infrastructure?
   │     │           ├── Yes ──> INNGEST
   │     │           └── No  ──> TRIGGER.DEV v3 (Dedicated worker processes, no timeout ceiling)
   │     │
   │     └── No  ── Do you require sub-millisecond to 5ms latency at 10,000+ jobs/sec on bare-metal/Kubernetes?
   │                 ├── Yes ──> BULLMQ (Self-managed Redis clusters, highest throughput/dollar ratio)
   │                 └── No  ── Do you just need to dispatch scheduled HTTP calls or retry failed serverless webhooks?
   │                             └──> UPSTASH QSTASH (Pure serverless HTTP push, no worker infrastructure)
```

---

## 3. Idempotency, Concurrency, and Debouncing Primitives

Every durable workflow engine requires deterministic deduplication. At enterprise scale, failures occur precisely between step execution and acknowledgment, creating at-least-once message delivery realities.

### 3.1 Idempotency Key Composition

An idempotency key must uniquely identify the business transaction over a bounded time window without leaking user-specific internal memory state:

$$\text{Idempotency Key} = \text{SHA256}(\text{TenantID} + ":" + \text{OperationType} + ":" + \text{EntityID} + ":" + \text{PayloadFingerprint})$$

---

### 3.2 Production Implementation: BullMQ Distributed Lock & Atomic Idempotency

This implementation guarantees that identical jobs cannot be enqueued or processed concurrently, utilizing an atomic Redis Lua transaction for strict idempotency guarantees.

```typescript
// bullmq-idempotent-worker.ts
import { Worker, Queue, Job, QueueOptions, WorkerOptions } from 'bullmq';
import Redis from 'ioredis';
import crypto from 'crypto';

const redisConnection = new Redis(process.env.REDIS_URL || 'redis://127.0.0.1:6379', {
  maxRetriesPerRequest: null,
  enableReadyCheck: false,
});

export const PAYMENT_QUEUE_NAME = 'payment-processing-v1';

export interface PaymentJobPayload {
  tenantId: string;
  orderId: string;
  amountCents: number;
  currency: string;
  paymentMethodToken: string;
}

export interface PaymentJobResult {
  transactionId: string;
  processedAt: string;
  status: 'COMPLETED' | 'ALREADY_PROCESSED';
}

export const paymentQueue = new Queue<PaymentJobPayload, PaymentJobResult>(PAYMENT_QUEUE_NAME, {
  connection: redisConnection,
  defaultJobOptions: {
    attempts: 5,
    backoff: {
      type: 'exponential',
      delay: 2000,
    },
    removeOnComplete: { count: 1000 },
    removeOnFail: { count: 5000 },
  },
});

/**
 * Computes an invariant idempotency key across payload elements.
 */
export function generatePaymentIdempotencyKey(payload: PaymentJobPayload): string {
  const serialized = `${payload.tenantId}:${payload.orderId}:${payload.amountCents}:${payload.currency}`;
  return crypto.createHash('sha256').update(serialized).digest('hex');
}

/**
 * Enqueues a job while preventing duplicate active or waiting payloads.
 */
export async function enqueueIdempotentPayment(payload: PaymentJobPayload): Promise<Job<PaymentJobPayload, PaymentJobResult>> {
  const jobId = generatePaymentIdempotencyKey(payload);
  
  // Custom Redis Lua script to set an idempotency TTL reservation
  const reservationScript = `
    local key = KEYS[1]
    local jobId = ARGV[1]
    local ttl = ARGV[2]
    
    if redis.call('EXISTS', key) == 1 then
      return 0
    else
      redis.call('SET', key, jobId, 'EX', ttl)
      return 1
    end
  `;

  const lockKey = `idempotency:lock:${jobId}`;
  const lockAcquired = await redisConnection.eval(reservationScript, 1, lockKey, jobId, 86400);

  if (!lockAcquired) {
    const existingJob = await paymentQueue.getJob(jobId);
    if (existingJob) {
      return existingJob;
    }
  }

  return await paymentQueue.add('process-payment', payload, {
    jobId: jobId, // BullMQ native deduplication inside the active state boundary
  });
}

// Worker Definition with strict concurrency limits and step-safety
export const paymentWorker = new Worker<PaymentJobPayload, PaymentJobResult>(
  PAYMENT_QUEUE_NAME,
  async (job: Job<PaymentJobPayload, PaymentJobResult>) => {
    const idempotencyRecordKey = `idempotency:completed:${job.id}`;
    
    // Check if the operation completed in a previously retried, timed-out attempt
    const cachedRecord = await redisConnection.get(idempotencyRecordKey);
    if (cachedRecord) {
      return {
        transactionId: cachedRecord,
        processedAt: new Date().toISOString(),
        status: 'ALREADY_PROCESSED',
      };
    }

    // Process downstream step
    const transactionId = `txn_${crypto.randomUUID()}`;
    
    // Emulate atomic operation
    await job.updateProgress(50);

    // Atomically persist completion marker valid for 7 days
    await redisConnection.set(idempotencyRecordKey, transactionId, 'EX', 604800);

    return {
      transactionId,
      processedAt: new Date().toISOString(),
      status: 'COMPLETED',
    };
  },
  {
    connection: redisConnection,
    concurrency: 10,
    limiter: {
      max: 100,
      duration: 1000, // Maximum 100 payments processed per second across this worker process
    },
  }
);
```

---

### 3.3 Production Implementation: Inngest Dynamic Concurrency & Debouncing

Inngest handles concurrency through virtual keys. This blueprint coordinates inbound generative AI processing requests: it debounces frequent rapid edits from a single user while enforcing a global concurrency limit of 5 parallel requests per tenant and an account-wide limit of 50.

```typescript
// inngest-pipeline.ts
import { Inngest } from 'inngest';

export const inngest = new Inngest({ 
  id: 'enterprise-core-engine',
  eventKey: process.env.INNGEST_EVENT_KEY,
});

export const dynamicAiPipeline = inngest.createFunction(
  {
    id: 'process-document-ai-pipeline',
    // Debounce triggers within 3 seconds for the same document to absorb high-frequency edits
    debounce: {
      key: 'event.data.documentId',
      period: '3s',
      timeout: '30s',
    },
    // Multi-tier concurrency enforcement
    concurrency: [
      {
        scope: 'account',
        key: 'event.data.tenantId',
        limit: 5, // Max 5 parallel executions per specific enterprise tenant
      },
      {
        scope: 'env',
        limit: 50, // Global ceiling for this environment
      }
    ],
    // Rate limit as absolute backstop for downstream APIs
    rateLimit: {
      key: 'event.data.tenantId',
      limit: 120,
      period: '1m',
    },
    idempotency: 'event.data.tenantId + "-" + event.data.documentId + "-" + event.data.versionHash',
  },
  { event: 'docs/document.updated' },
  async ({ event, step }) => {
    // Step 1: Deterministic state extraction
    const documentData = await step.run('fetch-document-payload', async () => {
      return {
        id: event.data.documentId,
        content: `Extracted content for document: ${event.data.documentId}`,
        checksum: event.data.versionHash,
      };
    });

    // Step 2: External call with automatic retry & exponential backoff
    const embedding = await step.run('generate-vector-embeddings', async () => {
      // Calls to vector providers (e.g., OpenAI, Voyage)
      return {
        vectorLength: 1536,
        model: 'text-embedding-3-small',
        status: 'EMBEDDINGS_GENERATED',
      };
    });

    // Step 3: Sleep primitive without holding serverless memory execution alive
    await step.sleep('stabilization-pause', '10s');

    // Step 4: Final mutation
    const finalResult = await step.run('persist-vector-indexes', async () => {
      return {
        persisted: true,
        documentId: documentData.id,
        embeddingStatus: embedding.status,
      };
    });

    return finalResult;
  }
);
```

---

### 3.4 Production Implementation: Trigger.dev v3 Concurrency & Realtime Throttling

Trigger.dev v3 runs long-duration task loops natively in separated runtimes with isolated queue configurations.

```typescript
// trigger-task.ts
import { task, queue } from "@trigger.dev/sdk/v3";

// Create an isolated sub-queue with strict concurrency and rate limiting
export const heavyComputeQueue = queue({
  name: "heavy-video-processing",
  concurrencyLimit: 2, // Only 2 parallel video processing tasks simultaneously
});

export const processVideoTask = task({
  id: "transcode-and-extract-audio",
  queue: heavyComputeQueue,
  retry: {
    maxAttempts: 4,
    factor: 2,
    minTimeoutInMs: 1000,
    maxTimeoutInMs: 30000,
    randomize: true, // Jitter
  },
  run: async (payload: { videoUrl: string; videoId: string; quality: string }, { ctx }) => {
    // Realtime metadata updates pushed directly to the Trigger.dev dashboard
    await ctx.log(`Starting transcode task for video: ${payload.videoId}`, {
      quality: payload.quality,
    });

    // Execute long-running computational phase
    const transcodeResult = await (async () => {
      // Simulating heavy native execution block
      return {
        outputPath: `s3://media-bucket/processed/${payload.videoId}/master.m3u8`,
        framesProcessed: 14400,
      };
    })();

    await ctx.log("Transcoding finished. Uploading indexes.", { result: transcodeResult });

    return {
      success: true,
      result: transcodeResult,
      runId: ctx.run.id,
    };
  },
});
```

---

## 4. Enterprise Rate Limiting & Throttling Topologies

When building systems that coordinate upstream bursts against downstream rate-limited platforms (e.g., OpenAI, Stripe, Salesforce, GitHub), your architecture must buffer spikes, manage token consumption, and avoid synchronous retry exhaustion.

```
Upstream Event Surge (10,000 req/sec)
                  │
                  ▼
┌────────────────────────────────────────┐
│     DURABLE QUEUE / INGESTION BUS      │
│  - Events serialized to disk/Redis     │
│  - Fast ACK returned to caller (202)   │
└────────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────┐
│      RATE LIMITING ENGINE              │
│  - Sliding Window Log (Tenant-level)   │
│  - Token Bucket (Downstream APIs)      │
└────────────────────────────────────────┘
                  │
      ┌───────────┴───────────┐
      │ Allowed               │ Quota Exceeded (HTTP 429)
      ▼                       ▼
┌──────────────┐     ┌───────────────────────────────────┐
│ Run Step /   │     │ ENGINE SUSPEND / RE-QUEUE         │
│ Worker Job   │     │ BullMQ: Worker.rateLimitExceeded  │
└──────────────┘     │ Inngest: step.sleepUntil()        │
                     │ Trigger: Dynamic retry-after delay│
                     └───────────────────────────────────┘
```

### 4.1 Token Bucket vs. Sliding Window Log Comparison

```
TOKEN BUCKET:
- Best for bursty traffic with strict downstream limits (e.g., 50 requests/sec allowed).
- Fixed capacity; tokens regenerate at constant rate.
- Low memory usage: Stores 2 values (timestamp, remaining tokens).

SLIDING WINDOW LOG:
- Best for strict audit boundaries (e.g., 5,000 queries per calendar hour per tenant).
- Logs individual transaction timestamps inside Redis sorted sets.
- High memory usage: Stores every event timestamp in the current window.
```

### 4.2 Distributed Circuit Breaker Pattern

External dependencies frequently experience degraded states (502/503/504 errors) rather than hard downtime. The distributed circuit breaker prevents all worker threads from repeatedly attacking a degraded target, tripping after a defined failure threshold and switching to an instant-fail or fast-sleep route.

```typescript
// circuit-breaker.ts
import Redis from 'ioredis';

export type CircuitState = 'CLOSED' | 'OPEN' | 'HALF_OPEN';

export interface CircuitBreakerOptions {
  failureThreshold: number;
  recoveryTimeoutMs: number;
  samplingDurationMs: number;
}

export class DistributedCircuitBreaker {
  private redis: Redis;
  private serviceKey: string;
  private opts: CircuitBreakerOptions;

  constructor(redis: Redis, serviceKey: string, opts: CircuitBreakerOptions) {
    this.redis = redis;
    this.serviceKey = serviceKey;
    this.opts = opts;
  }

  private getKey(suffix: string): string {
    return `circuit:${this.serviceKey}:${suffix}`;
  }

  public async getState(): Promise<CircuitState> {
    const forcedState = await this.redis.get(this.getKey('state'));
    if (forcedState === 'OPEN') {
      const openSince = await this.redis.get(this.getKey('open_time'));
      if (openSince && Date.now() - parseInt(openSince, 10) > this.opts.recoveryTimeoutMs) {
        return 'HALF_OPEN';
      }
      return 'OPEN';
    }
    return 'CLOSED';
  }

  public async recordSuccess(): Promise<void> {
    const state = await this.getState();
    if (state === 'HALF_OPEN') {
      // Transition back to normal operations
      const multi = this.redis.multi();
      multi.del(this.getKey('state'));
      multi.del(this.getKey('open_time'));
      multi.del(this.getKey('failures'));
      await multi.exec();
    }
  }

  public async recordFailure(): Promise<CircuitState> {
    const failuresKey = this.getKey('failures');
    const failures = await this.redis.incr(failuresKey);
    
    if (failures === 1) {
      await this.redis.pexpire(failuresKey, this.opts.samplingDurationMs);
    }

    if (failures >= this.opts.failureThreshold) {
      const multi = this.redis.multi();
      multi.set(this.getKey('state'), 'OPEN');
      multi.set(this.getKey('open_time'), Date.now().toString());
      multi.del(failuresKey);
      await multi.exec();
      return 'OPEN';
    }

    return 'CLOSED';
  }

  public async execute<T>(fn: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
    const state = await this.getState();
    if (state === 'OPEN') {
      return await fallback();
    }

    try {
      const result = await fn();
      await this.recordSuccess();
      return result;
    } catch (error) {
      await this.recordFailure();
      throw error;
    }
  }
}
```

---

## 5. Failure Domains, Poison Pills, and Dead-Letter Queues (DLQ)

Failures in durable workflow systems must be categorized accurately. Treating all exceptions identically causes severe head-of-line blocking or cascading queue failures.

### 5.1 Failure Taxonomy

```
                   FAILURE DETECTED
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
    TRANSIENT ERROR                 FATAL ERROR
  - HTTP 429 (Rate Limit)         - Validation failure (Zod)
  - HTTP 503 (Target unavailable) - Malformed JSON payload
  - Network Socket Hangup         - Invalid authentication keys
  - DB Deadlock (PGRST / 40P01)   - Corrupted data schema
          │                               │
          ▼                               ▼
    RETRY ENGINE                  FAIL IMMEDIATELY
  - Exponential Backoff           - Zero retries (Attempts = 1)
  - Full Jitter Algorithm         - Route directly to DLQ
  - Check Circuit Breaker         - Emit alert metrics to Sentry/PagerDuty
```

### 5.2 Full Jitter Exponential Backoff Implementation

When a downstream system experiences a transient drop, multiple workers back off simultaneously. Retrying using a standard mathematical exponential formula ($2^n$) causes synchronous spikes (thundering herds). Full jitter decorrelates retry storms by applying uniform distribution.

```typescript
// backoff.ts
export interface JitterOptions {
  baseDelayMs: number;
  maxDelayMs: number;
}

/**
 * Calculates exponential backoff with Full Jitter.
 * Formula: Sleep = rand(0, min(maxDelay, baseDelay * 2 ^ attempt))
 */
export function calculateFullJitterBackoff(attempt: number, opts: JitterOptions): number {
  const { baseDelayMs, maxDelayMs } = opts;
  const calculatedExponential = baseDelayMs * Math.pow(2, attempt);
  const ceiling = Math.min(maxDelayMs, calculatedExponential);
  return Math.floor(Math.random() * (ceiling + 1));
}
```

### 5.3 Dead-Letter Queue (DLQ) Triage Runbook

```
                         POISON PILL ROUTED TO DLQ
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 1. INGESTION INVESTIGATION                                             │
│    - Inspect payload validation failures.                              │
│    - Trace error logs via OpenTelemetry Run ID or BullMQ Job ID.       │
│    - Determine: Is the bug in code or in payload data?                 │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                 ┌──────────────────┴──────────────────┐
                 ▼                                     ▼
      [Bug Identified in Code]              [Corrupted Malicious Data]
                 │                                     │
                 ▼                                     ▼
┌─────────────────────────────────┐   ┌──────────────────────────────────┐
│ 2. WRITE REPAIR PATCH           │   │ 2. PURGE OR ARCHIVE              │
│    - Deploy bugfix to workers.  │   │    - Run manual unwrap script.   │
│    - Keep dead jobs parked.     │   │    - Move to permanent cold S3   │
│    - Run staging regression run.│   │      storage audit bucket.       │
└─────────────────────────────────┘   │    - Acknowledge and discard.    │
                 │                    └──────────────────────────────────┘
                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. REPLAY STRATEGY EXECUTION                                           │
│    - Use BullMQ: dlqQueue.getJobs(['failed']) -> worker.retryJob()     │
│    - Use Inngest: inngest.runs.replay({ runId })                       │
│    - Use Trigger: tasks.replay(runId)                                  │
│    - Process through Rate Limiter to prevent secondary cascade outages.│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Production Readiness Checklist

Before promoting any durable workflow engine or queue worker to production, verify each operational item below:

```markdown
### Infrastructure & Connectivity
- [ ] Redis deployment (BullMQ) runs on Redis v6.2+ with `maxmemory-policy: noeviction` (crucial: memory drops must throw errors rather than evict locks).
- [ ] Network topologies between workers and durable dispatchers have established keep-alive intervals (<60s) to prevent silent TCP teardown by NAT gateways.
- [ ] For Inngest/QStash serverless setups, the signing keys (`INNGEST_SIGNING_KEY`, `QSTASH_TOKEN`) are configured and enforced in production mode to reject unverified HTTP POST callbacks.

### Determinism & Code Integrity
- [ ] Workflow step code contains no external variable evaluations, un-wrapped dynamic dates (`new Date()`), or un-wrapped random ID generations.
- [ ] All step parameters and return payloads are fully JSON-serializable. No unhandled `BigInt`, circular references, symbols, or binary Buffers without base64 conversions.

### Operational Guardrails
- [ ] All external API integrations (LLM calls, third-party webhooks, payments) feature an explicit per-step timeout (e.g., abort signal within 30 seconds).
- [ ] Queue processors have concurrency explicitly constrained to prevent database connection pool exhaustion (e.g., Prisma, PgPool limits < Worker Concurrency * Process Count).
- [ ] Dead-Letter Queues (DLQs) are configured with alerts routed to standard on-call rotations when failure depths exceed 5 items inside a 5-minute window.
```

---

## 7. Engine Comparison & Quick-Selection Cheat Sheet

Use this definitive index to match your stack architecture to the correct implementation blueprint in this vault:

```
IF your app uses...
├── Next.js / Remix / Vercel Serverless
│   ├── And needs complex, multi-day, sleep-and-resume pipelines ────> MODULE 2 (Inngest)
│   └── And needs simple, zero-infra HTTP retries or crons ──────────> MODULE 5 (QStash)
│
├── Dedicated Node.js / Bun Containers (ECS, Kubernetes, Render)
│   ├── And processes tasks requiring GPU / heavy CPU transcode ─────> MODULE 3 (Trigger.dev v3)
│   └── And handles high-frequency event ingestion (>5k ops/sec) ────> MODULE 4 (BullMQ)
│
└── Hybrid Enterprise Platforms
    └── Requiring custom Redis data ownership & internal compliance ─> MODULE 4 (BullMQ)
```

Proceed to **Module 2: Inngest Production Blueprints** to implement your first resilient, serverless-native durable state machines.
