# Module 3: Advanced AI Agent Orchestration & High-Throughput Pipelines

## 1. Architectural Foundations of Durable AI Agents

Building production AI agents requires decoupling nondeterministic LLM evaluation loops from transient network connections. When an LLM executes a plan spanning multiple tool calls, API queries, or database writes, standard HTTP requests fail due to platform timeouts, network partitions, and upstream rate limits.

Durable orchestration transforms recursive agent loops into deterministic, state-hydrated execution graphs.

```
+---------------------------------------------------------------------------------------+
|                                Durable Agent Execution Loop                           |
|                                                                                       |
|  [Incoming Intent]                                                                    |
|         |                                                                             |
|         v                                                                             |
|  +---------------+      +-----------------------+      +---------------------------+  |
|  | step.run:     | ---> | step.run:             | ---> | step.run:                 |  |
|  | Hydrate State |      | Model Plan Generation |      | Tool Execution Dispatcher |  |
|  +---------------+      +-----------------------+      +---------------------------+  |
|         ^                                                            |                |
|         |                     Check Termination Condition            |                |
|         +------------------------------------------------------------+                |
|                                   (Loop: Iteration < Max)                             |
+---------------------------------------------------------------------------------------+
```

### Determinism vs. Non-Determinism Isolation

To guarantee deterministic replay without duplicate LLM costs or phantom tool side effects:
- **Wrap every LLM call in an individual memoized step.** If step 4 fails, replaying the workflow must read steps 1 through 3 from the durable execution log rather than re-billing tokens against your OpenAI/Anthropic quota.
- **Isolate tool executions into dedicated sub-steps.** Never bundle a model call and a database mutation in the same execution boundary.
- **Enforce monotonic state reduction.** Maintain agent scratchpads inside an append-only transaction log serialized across steps.

---

## 2. Blueprint 3.1: Recursive Multi-Turn Agent with Hard Depth Caps (Inngest)

This blueprint implements an autonomous research and remediation agent. It runs iteratively, selects dynamic tools (e.g., executing SQL, querying documentation, issuing GitHub PRs), maintains context state across crashes, and enforces hard recursion boundaries to prevent runaway billing loops.

### Blueprint Architecture

```
[Inngest Trigger: agent/remediation.invoked]
        │
        ├──► step.run("initialize-context")
        │
        ▼
 ┌──► Iteration Check: current_iteration < MAX_ITERATIONS (10)
 │      │
 │      ├──► step.run(`model-inference-${iteration}`)
 │      │       └─ Anthropic Claude 3.5 Sonnet Tool Evaluation
 │      │
 │      ├──► Choice: Stop Token or Tool Call?
 │      │       ├─ Stop Token ──► Break Loop
 │      │       └─ Tool Call  ──► step.run(`execute-tool-${iteration}`)
 │      │
 │      └──► Update Scratchpad & Increment Iteration
 └───┘
        │
        ├──► step.run("finalize-summary")
        ▼
[Execution Complete: Run Saved to Database]
```

### Production Implementation

```typescript
// src/inngest/functions/agentRemediation.ts
import { Inngest, NonRetriableError } from "inngest";
import Anthropic from "@anthropic-ai/sdk";

export const inngest = new Inngest({ id: "enterprise-agent-engine" });
const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY! });

const MAX_ITERATIONS = 10;

interface ToolDefinition {
  name: string;
  description: string;
  input_schema: Anthropic.Tool.InputSchema;
}

interface AgentState {
  ticketId: string;
  query: string;
  messages: Anthropic.MessageParam[];
  iterations: number;
  completed: boolean;
  finalResolution: string | null;
}

const TOOLS: ToolDefinition[] = [
  {
    name: "query_database",
    description: "Execute a read-only SQL query against the system state database.",
    input_schema: {
      type: "object",
      properties: {
        sql: { type: "string", description: "Read-only SELECT SQL statement." }
      },
      required: ["sql"]
    }
  },
  {
    name: "patch_configuration",
    description: "Submit a configuration patch to fix degraded customer nodes.",
    input_schema: {
      type: "object",
      properties: {
        nodeId: { type: "string" },
        patchPayload: { type: "string" }
      },
      required: ["nodeId", "patchPayload"]
    }
  }
];

async function executeInternalTool(name: string, input: Record<string, unknown>): Promise<string> {
  switch (name) {
    case "query_database": {
      const sql = String(input.sql);
      if (!sql.trim().toUpperCase().startsWith("SELECT")) {
        throw new NonRetriableError("Safety Violation: Non-SELECT queries are strictly prohibited.");
      }
      return JSON.stringify({ status: "healthy", nodeId: "node-prd-048", latency_ms: 1240 });
    }
    case "patch_configuration": {
      return JSON.stringify({
        applied: true,
        nodeId: input.nodeId,
        previousState: "degraded",
        currentState: "operational"
      });
    }
    default:
      throw new NonRetriableError(`Unknown tool invocation attempt: ${name}`);
  }
}

export const autonomousRemediationAgent = inngest.createFunction(
  {
    id: "autonomous-system-remediation",
    retries: 3,
    concurrency: {
      limit: 5,
      key: "event.data.ticketId"
    }
  },
  { event: "agent/remediation.invoked" },
  async ({ event, step }) => {
    let state = await step.run("initialize-context", async (): Promise<AgentState> => {
      return {
        ticketId: event.data.ticketId,
        query: event.data.query,
        messages: [{ role: "user", content: event.data.query }],
        iterations: 0,
        completed: false,
        finalResolution: null
      };
    });

    while (!state.completed && state.iterations < MAX_ITERATIONS) {
      const currentIteration = state.iterations;

      const modelResponse = await step.run(
        `inference-cycle-${currentIteration}`,
        async () => {
          return await anthropic.messages.create({
            model: "claude-3-5-sonnet-20241022",
            max_tokens: 4096,
            tools: TOOLS,
            messages: state.messages
          });
        }
      );

      if (modelResponse.stop_reason === "tool_use") {
        const toolUseBlocks = modelResponse.content.filter(
          (block): block is Anthropic.ToolUseBlock => block.type === "tool_use"
        );

        const toolResults: Anthropic.ToolResultBlockParam[] = [];

        for (const toolUse of toolUseBlocks) {
          const toolOutput = await step.run(
            `tool-${toolUse.name}-iter-${currentIteration}-${toolUse.id}`,
            async () => {
              return await executeInternalTool(
                toolUse.name,
                toolUse.input as Record<string, unknown>
              );
            }
          );

          toolResults.push({
            type: "tool_result",
            tool_use_id: toolUse.id,
            content: toolOutput
          });
        }

        state = await step.run(`reduce-state-tool-${currentIteration}`, async () => {
          return {
            ...state,
            iterations: currentIteration + 1,
            messages: [
              ...state.messages,
              { role: "assistant", content: modelResponse.content },
              { role: "user", content: toolResults }
            ]
          };
        });
      } else {
        const textBlock = modelResponse.content.find((block) => block.type === "text");
        const resolution = textBlock ? textBlock.text : "Task completed without detailed text output.";

        state = await step.run(`reduce-state-terminal-${currentIteration}`, async () => {
          return {
            ...state,
            iterations: currentIteration + 1,
            completed: true,
            finalResolution: resolution,
            messages: [
              ...state.messages,
              { role: "assistant", content: modelResponse.content }
            ]
          };
        });
        break;
      }
    }

    if (!state.completed && state.iterations >= MAX_ITERATIONS) {
      await step.run("enforce-safety-cutoff", async () => {
        // Circuit breaker: Maximum recursive context depth reached
        return {
          status: "ESCALATION_TRIGGERED",
          reason: `Exceeded hard loop ceiling of ${MAX_ITERATIONS} iterations.`
        };
      });
      throw new NonRetriableError("Circuit breaker tripped: Agent iteration ceiling exceeded.");
    }

    return await step.run("persist-final-resolution", async () => {
      return {
        ticketId: state.ticketId,
        cycles: state.iterations,
        resolution: state.finalResolution
      };
    });
  }
);
```

---

## 3. Blueprint 3.2: 72-Hour Human-in-the-Loop (HITL) Approval Engine (Trigger.dev v3)

Long-running workflows frequently require explicit user interaction before executing dangerous or high-cost operations (e.g., executing a $100,000 ACH sweep or running irreversible migrations). 

This blueprint implements a 72-hour durable pause using Trigger.dev v3, with real-time webhook token verification, timeout escalation, and compensating rollbacks.

```
+---------------------------------------------------------------------------------------+
|                       72-Hour Human-in-the-Loop Approval Lifecycle                    |
|                                                                                       |
|  [Initiate Transfer]                                                                  |
|         │                                                                             |
|         ▼                                                                             |
|  [Stage Ledger Entry] ──► [Generate Token & Dispatch Notification]                    |
|                                     │                                                 |
|                                     ▼                                                 |
|                      +-----------------------------+                                  |
|                      | wait.forEvent("wire.review")|                                  |
|                      | Max Duration: 72 Hours      |                                  |
|                      +-----------------------------+                                  |
|                                     │                                                 |
|                    ┌────────────────┴────────────────┐                                |
|             Received within 72h?               Timed Out?                             |
|                    │                                 │                                |
|        ┌───────────┴───────────┐                     ▼                                |
|    Approved                 Rejected            [Expire Staged Entry]                 |
|        │                       │                     │                                |
|        ▼                       ▼                     ▼                                |
|  [Execute Wire]         [Unlock Ledger]         [Alert Compliance]                    |
+---------------------------------------------------------------------------------------+
```

### Production Implementation

```typescript
// src/trigger/tasks/financialApprovals.ts
import { task, wait } from "@trigger.dev/sdk/v3";
import crypto from "crypto";

export interface WireRequestPayload {
  transactionId: string;
  sourceAccountId: string;
  destinationRoutingNumber: string;
  destinationAccountNumber: string;
  amountCents: number;
  originatorEmail: string;
  complianceTier: "STANDARD" | "HIGH_RISK";
}

export interface ReviewSubmittedEvent {
  decision: "APPROVED" | "REJECTED";
  reviewerUserId: string;
  signatureToken: string;
  reason?: string;
}

export const financialWireWorkflow = task({
  id: "financial-wire-orchestrator",
  retry: {
    maxAttempts: 2
  },
  run: async (payload: WireRequestPayload) => {
    // 1. Stage the ledger entry to hold the balance
    const holdRecord = await stageLedgerHold(payload.transactionId, payload.amountCents);

    // 2. Generate a tamper-proof review token
    const reviewToken = crypto.randomBytes(32).toString("hex");
    const tokenHash = crypto.createHash("sha256").update(reviewToken).digest("hex");

    await persistReviewIntent({
      transactionId: payload.transactionId,
      tokenHash,
      expiresAt: new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString()
    });

    // 3. Dispatch multi-channel notification with verification URL
    await dispatchComplianceAlert({
      transactionId: payload.transactionId,
      amountCents: payload.amountCents,
      actionUrl: `https://compliance.internal.bank/review/${payload.transactionId}?token=${reviewToken}`
    });

    // 4. Suspend execution durably for up to 72 hours
    const reviewEvent = await wait.forEvent<ReviewSubmittedEvent>(
      "wire.transfer.reviewed",
      `review-${payload.transactionId}`,
      {
        timeout: "72h"
      }
    );

    // 5. Check if execution timed out
    if (!reviewEvent) {
      await releaseLedgerHold(holdRecord.holdId, "EXPIRED_TIMEOUT");
      await dispatchEscalation({
        transactionId: payload.transactionId,
        reason: "Manual review SLA breached. Transfer automatically cancelled."
      });

      return {
        status: "CANCELLED_TIMEOUT",
        transactionId: payload.transactionId,
        resolvedAt: new Date().toISOString()
      };
    }

    // 6. Cryptographic validation of the external review action
    const incomingHash = crypto.createHash("sha256").update(reviewEvent.signatureToken).digest("hex");
    if (incomingHash !== tokenHash) {
      await releaseLedgerHold(holdRecord.holdId, "SECURITY_VIOLATION");
      throw new Error(`Invalid authorization signature detected for transaction ${payload.transactionId}`);
    }

    // 7. Route terminal decision branches
    if (reviewEvent.decision === "REJECTED") {
      await releaseLedgerHold(holdRecord.holdId, "EXPLICITLY_REJECTED");
      return {
        status: "REJECTED",
        transactionId: payload.transactionId,
        reviewerId: reviewEvent.reviewerUserId,
        reason: reviewEvent.reason ?? "No reason provided"
      };
    }

    // 8. Execute the wire transfer via payment gateway
    const settlementResult = await dispatchFedwireSettlement({
      transactionId: payload.transactionId,
      routing: payload.destinationRoutingNumber,
      account: payload.destinationAccountNumber,
      amount: payload.amountCents,
      reviewerId: reviewEvent.reviewerUserId
    });

    await commitLedgerHold(holdRecord.holdId, settlementResult.paymentReferenceId);

    return {
      status: "SETTLED",
      transactionId: payload.transactionId,
      settlementId: settlementResult.paymentReferenceId,
      settledAt: new Date().toISOString()
    };
  }
});

// Mock implementations of domain boundary adapters
async function stageLedgerHold(txId: string, amount: number) {
  return { holdId: `hld_${crypto.randomUUID()}`, txId, amount, status: "STAGED" };
}
async function persistReviewIntent(record: { transactionId: string; tokenHash: string; expiresAt: string }) {
  return { saved: true, record };
}
async function dispatchComplianceAlert(meta: { transactionId: string; amountCents: number; actionUrl: string }) {
  return { delivered: true, timestamp: Date.now() };
}
async function releaseLedgerHold(holdId: string, reason: string) {
  return { holdId, status: "RELEASED", reason };
}
async function commitLedgerHold(holdId: string, settlementRef: string) {
  return { holdId, status: "COMMITTED", settlementRef };
}
async function dispatchEscalation(detail: { transactionId: string; reason: string }) {
  return { alertSent: true };
}
async function dispatchFedwireSettlement(data: Record<string, unknown>) {
  return { paymentReferenceId: `FEDWIRE_${crypto.randomUUID().slice(0, 8).toUpperCase()}` };
}
```

---

## 4. High-Throughput Distributed Deduplication & Throttling

High-throughput systems inevitably face duplicated messages, out-of-order events, and traffic spikes that can exhaust downstream systems. Applying the wrong deduplication strategy leads to race conditions, dropped jobs, or memory leaks.

### Deduplication and Rate-Limiting Strategies

| Pattern | Scope | Latency Penalty | False Drop Risk | Storage Overhead | Best Use Case |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BullMQ Native Job ID Deduplication** | Pre-queue ingestion | <1ms (Redis native) | High, if Job IDs expire before downstream duplicates arrive | Negligible (`O(1)` per job entry) | Webhook deliveries with unique headers (`X-Delivery-ID`) |
| **Sliding Window Token Bucket (Lua)** | Worker pre-execution | ~2-5ms (Atomic execution) | Zero (Throttled, not dropped) | Moderate (Ordered set per tenant) | Protecting rate-limited external APIs (Stripe, GitHub) |
| **Content-Hash Lock (Distributed)** | Pre-queue | 5-10ms | Medium (Payload mutations drop dedupe) | Low (`TTL`-bound cache entries) | Accidental double-clicks on idempotent forms |

```
High-Throughput Deduplication & Concurrency Architecture

[Incoming Webhook Ingestion]
             │
             ├──► Hash Payload Components: SHA256(WorkspaceID + Method + DeterministicJSON(Body))
             │
             ▼
   [Redis Atomic Lua Script]
             │
     Is Fingerprint Cached?
             ├─── YES ──► Log Cache Hit ──► Short-circuit 200 OK (Drop Execution)
             └─── NO  ──► SET NX with TTL
                                │
                                ▼
                   [BullMQ Enqueue: Unique Job ID]
                                │
                                ▼
     [Worker Level: Sliding Window Concurrency Controller]
                                │
             Is Tenant Allowed by Rate-Limit Window?
             ├─── YES ──► Process Job Durably
             └─── NO  ──► Delay / Re-queue Job with Exponential Backoff
```

---

## 5. Blueprint 3.3: High-Throughput Pipeline with Atomic Deduplication (BullMQ + Redis Lua)

This blueprint processes high-volume webhook bursts. It prevents duplicate execution using atomic Redis Lua scripts, throttles processing by tenant, and tracks deduplication stats across high-concurrency Node.js clusters.

### Custom Atomic Lua Deduplication Script

```lua
-- File: src/redis/scripts/dedupeLock.lua
-- KEYS[1]: Deduplication key (e.g. dedupe:event:hash)
-- ARGV[1]: Job fingerprint (unique payload hash)
-- ARGV[2]: TTL in seconds (e.g. 86400)
local key = KEYS[1]
local fingerprint = ARGV[1]
local ttl = tonumber(ARGV[2])

local exists = redis.call("EXISTS", key)

if exists == 1 then
    -- Record hit frequency
    redis.call("HINCRBY", key, "hits", 1)
    return 0 -- Duplicate detected, do not enqueue
else
    redis.call("HSET", key, "fingerprint", fingerprint, "hits", 1, "created_at", redis.call("TIME")[1])
    redis.call("EXPIRE", key, ttl)
    return 1 -- Unique job, proceed
end
```

### Production Implementation

```typescript
// src/queues/ingestionPipeline.ts
import { Queue, Worker, QueueEvents, Job } from "bullmq";
import Redis from "ioredis";
import crypto from "crypto";
import fs from "fs";
import path from "path";

const REDIS_CONNECTION = {
  host: process.env.REDIS_HOST || "127.0.0.1",
  port: Number(process.env.REDIS_PORT) || 6379,
  maxRetriesPerRequest: null
};

export const redisClient = new Redis(REDIS_CONNECTION);
const LUA_DEDUPE_SCRIPT = fs.readFileSync(
  path.join(__dirname, "../redis/scripts/dedupeLock.lua"),
  "utf8"
);

// Register dynamic command on ioredis client
redisClient.defineCommand("checkAndSetDedupe", {
  numberOfKeys: 1,
  lua: LUA_DEDUPE_SCRIPT
});

declare module "ioredis" {
  interface RedisCommander<Context> {
    checkAndSetDedupe(
      key: string,
      fingerprint: string,
      ttlSeconds: number,
      callback?: (err: Error | null, result: number) => void
    ): Result<number, Context>;
  }
}

export interface WebhookEventPayload {
  workspaceId: string;
  source: string;
  eventType: string;
  payload: Record<string, unknown>;
  timestamp: number;
}

export const INGESTION_QUEUE_NAME = "tenant-event-ingestion";

export const ingestionQueue = new Queue<WebhookEventPayload>(INGESTION_QUEUE_NAME, {
  connection: redisClient,
  defaultJobOptions: {
    attempts: 5,
    backoff: {
      type: "exponential",
      delay: 1500
    },
    removeOnComplete: { count: 10000, age: 3600 },
    removeOnFail: { count: 50000, age: 86400 * 7 }
  }
});

/**
 * Generate a deterministic SHA256 signature from critical payload dimensions.
 */
export function generatePayloadFingerprint(data: WebhookEventPayload): string {
  const normalized = {
    workspaceId: data.workspaceId,
    source: data.source,
    eventType: data.eventType,
    payload: data.payload
  };
  return crypto.createHash("sha256").update(JSON.stringify(normalized)).digest("hex");
}

/**
 * High-performance enqueue entry point with atomic Redis deduping.
 */
export async function enqueueEventSafely(event: WebhookEventPayload): Promise<{ enqueued: boolean; jobId?: string }> {
  const fingerprint = generatePayloadFingerprint(event);
  const dedupeKey = `dedupe:${event.workspaceId}:${fingerprint}`;

  // 24-hour deduplication TTL window
  const isUnique = await redisClient.checkAndSetDedupe(dedupeKey, fingerprint, 86400);

  if (isUnique === 0) {
    return { enqueued: false };
  }

  const job = await ingestionQueue.add(event.eventType, event, {
    jobId: fingerprint, // Prevents duplicate active jobs inside the queue
    priority: event.source === "system_alert" ? 1 : 10
  });

  return { enqueued: true, jobId: job.id };
}

/**
 * Production worker with rate limiting and per-tenant concurrency control.
 */
export const ingestionWorker = new Worker<WebhookEventPayload>(
  INGESTION_QUEUE_NAME,
  async (job: Job<WebhookEventPayload>) => {
    const { workspaceId, eventType, payload } = job.data;

    // Apply strict concurrency limits on downstream workers
    const activeTenantWorkers = await redisClient.incr(`concurrency:${workspaceId}`);
    try {
      if (activeTenantWorkers > 10) {
        // Delay this job when tenant concurrency is saturated
        await job.moveToDelayed(Date.now() + 2000, job.token);
        return { status: "THROTTLED_CONCURRENCY" };
      }

      await processBusinessLogic(workspaceId, eventType, payload);
      return { status: "PROCESSED", workspaceId, jobId: job.id };
    } finally {
      await redisClient.decr(`concurrency:${workspaceId}`);
    }
  },
  {
    connection: new Redis(REDIS_CONNECTION),
    concurrency: 50,
    limiter: {
      max: 1000,
      duration: 1000 // Global throttle: 1,000 jobs per second across all nodes
    }
  }
);

async function processBusinessLogic(workspace: string, type: string, data: Record<string, unknown>): Promise<void> {
  // Deterministic operations (e.g., transforming records, dispatching to DB)
  if (Math.random() < 0.001) {
    throw new Error("Intermittent downstream database timeout.");
  }
}
```

---

## 6. Blueprint 3.4: Zero-Downtime Queue Migration (BullMQ to Trigger.dev / Inngest)

Migrating an active production system between queue engines (e.g., moving from BullMQ on self-hosted Redis to Trigger.dev v3 or Inngest Cloud) cannot be done with a hard cutover. In-flight jobs, delayed retries, and high-throughput write streams will drop data unless managed through an orchestrated transition.

### The 4-Phase Migration Lifecycle

```
PHASE 0: Single System          PHASE 1: Dual-Write & Shadow
+-------------------+           +-------------------+
|   Write: BullMQ   |           |   Write: Both     |
|   Read:  BullMQ   |           |   Read:  BullMQ   |
+-------------------+           +-------------------+
                                          │
                                          ▼
PHASE 3: Cutover Complete       PHASE 2: Shift Execution
+-------------------+           +-------------------+
|   Write: Engine B |           |   Write: Both     |
|   Read:  Engine B |           |   Read:  Engine B |
+-------------------+           +-------------------+
```

### Migration Phase Matrix

| Phase | Writing To | Reading From | Migration Gate / Success Metric |
| :--- | :--- | :--- | :--- |
| **0: Baseline** | BullMQ | BullMQ | Verify baseline throughput, error rates, and latency. |
| **1: Dual-Write / Shadow** | BullMQ + Engine B | BullMQ | Engine B writes succeed at >99.999% without increasing ingestion latency. Engine B jobs are dropped or run in dry-run mode. |
| **2: Shift Execution** | BullMQ + Engine B | Engine B (Primary), BullMQ (Draining) | Drain BullMQ delayed retries and active jobs completely. Verify zero parity drift. |
| **3: Complete Cutover**| Engine B | Engine B | Decommission BullMQ workers, stop dual writes, tear down Redis queue infrastructure. |

### Zero-Downtime Dual-Write Router

```typescript
// src/orchestration/migrationRouter.ts
import { Queue } from "bullmq";
import { Inngest } from "inngest";
import { Redis } from "ioredis";

export interface MigrationConfig {
  phase: "PHASE_0_BASELINE" | "PHASE_1_SHADOW" | "PHASE_2_EXECUTION_SHIFT" | "PHASE_3_COMPLETE";
  shadowSamplingRate: number; // 0.0 to 1.0
}

export class ZeroDowntimeDispatcher {
  private bullmqQueue: Queue;
  private inngestClient: Inngest;
  private redis: Redis;
  private configKey = "migration:config:state";

  constructor(bullmqQueue: Queue, inngestClient: Inngest, redis: Redis) {
    this.bullmqQueue = bullmqQueue;
    this.inngestClient = inngestClient;
    this.redis = redis;
  }

  public async getActivePhase(): Promise<MigrationConfig> {
    const raw = await this.redis.get(this.configKey);
    if (!raw) {
      return { phase: "PHASE_0_BASELINE", shadowSamplingRate: 0.0 };
    }
    return JSON.parse(raw) as MigrationConfig;
  }

  public async updatePhase(config: MigrationConfig): Promise<void> {
    await this.redis.set(this.configKey, JSON.stringify(config));
  }

  public async dispatch<T extends Record<string, unknown>>(
    eventName: string,
    payload: T,
    idempotencyKey: string
  ): Promise<{ dispatchedTo: string[] }> {
    const { phase, shadowSamplingRate } = await this.getActivePhase();
    const destinations: string[] = [];

    switch (phase) {
      case "PHASE_0_BASELINE": {
        await this.bullmqQueue.add(eventName, payload, { jobId: idempotencyKey });
        destinations.push("BULLMQ");
        break;
      }

      case "PHASE_1_SHADOW": {
        // Enqueue to primary engine
        await this.bullmqQueue.add(eventName, payload, { jobId: idempotencyKey });
        destinations.push("BULLMQ");

        // Dual-write to target engine for validation
        if (Math.random() < shadowSamplingRate) {
          await this.inngestClient.send({
            name: `shadow/${eventName}`,
            data: payload,
            id: idempotencyKey
          });
          destinations.push("INNGEST_SHADOW");
        }
        break;
      }

      case "PHASE_2_EXECUTION_SHIFT": {
        // Engine B becomes primary. BullMQ receives only shadow/fallback tasks.
        await this.inngestClient.send({
          name: eventName,
          data: payload,
          id: idempotencyKey
        });
        destinations.push("INNGEST_PRIMARY");

        // Keep BullMQ active to process its delayed retry queue
        break;
      }

      case "PHASE_3_COMPLETE": {
        // BullMQ fully bypassed
        await this.inngestClient.send({
          name: eventName,
          data:
