# Module 4: Resiliency Audit Checklists, Dead Letter Queue Triage & Cheat Sheet

---

## 1. Production Readiness Audit Rubric

Use this battle-tested rubric to evaluate your background job processors and durable execution engines before deploying them to production. Any job processor scoring below 85% or failing any single "Critical" tier check must not be promoted to production.

### 1.1 The Six Pillars of Durable Execution

| Dimension | Verification Item | Severity | Verification Method |
| :--- | :--- | :--- | :--- |
| **1. Idempotency** | Every step/job handler relies on a natural or deterministic synthetic key (`orderId:stepName:attempt`). | **CRITICAL** | Code review; verify no side-effect executes without an idempotency guard (e.g., Redis `SET NX`, DB unique constraint). |
| **1. Idempotency** | State checks occur inside the same atomic database transaction as the business write. | **CRITICAL** | Integration test: Trigger identical concurrent payloads; verify exactly one state modification. |
| **1. Idempotency** | External side effects (Stripe, Twilio, Resend) inject the idempotency key directly into the 3rd-party API client. | **HIGH** | Outgoing payload inspection via mock/proxy. |
| **2. Concurrency** | Global, per-queue, and per-tenant concurrency limits are enforced to prevent downstream saturation. | **CRITICAL** | Load test: Flood system with 10,000 tasks for a single tenant; verify tenant limit holds and does not starve neighbors. |
| **2. Concurrency** | In-flight execution limits match worker instance memory headroom (avoiding Node.js thread pool starvation). | **HIGH** | Benchmark: Measure event-loop lag (`libuv`) under max concurrency; must remain $< 50\text{ms}$. |
| **3. Backoff & Retries** | Retries utilize full jitter exponential backoff ($T_{\text{wait}} = \text{random}(0, \min(M, B \times 2^{\text{attempt}}))$). | **HIGH** | Inspect backoff configuration. Verify multiplier, base interval, and maximum delay ceiling. |
| **3. Backoff & Retries** | Non-transient errors (HTTP `400`, `401`, `403`, `422`, JSON parse errors) fail immediately without retrying. | **CRITICAL** | Unit test: Inject a validation error; assert attempts terminate at attempt count 1 and move to DLQ. |
| **4. State & Checkpoints** | State transitions are persisted at distinct step boundaries (Durable Steps / Event sourcing). | **CRITICAL** | Chaos test: Kill worker container midway through multi-step pipeline; restart worker; verify pipeline resumes from last step. |
| **4. State & Checkpoints** | Job payload size is bounded ($< 256\text{KB}$). Large payloads use reference-passing via object storage (S3/GCS pointer). | **HIGH** | Payload validation schema; reject direct base64/binary payloads at queue boundary. |
| **5. Observability** | Distributed trace context (`traceparent`, `tracestate`) propagates across queue dispatch, execution, and step boundaries. | **HIGH** | Trace audit: Confirm Datadog or OpenTelemetry traces show single continuous waterfall across network boundaries. |
| **5. Observability** | Queues emit metrics for: Active Jobs, Waiting Jobs, Delayed Jobs, Failed Jobs, Stalled Jobs, and Lag Duration. | **CRITICAL** | Prometheus/Datadog scrape verification: Metric alerts must fire on synthetic queue saturation. |
| **6. Blast Radius** | High-volume operational jobs (e.g., webhooks) run on isolated infrastructure separate from critical path tasks. | **HIGH** | Architecture review: Ensure independent queue names, Redis instances, and compute deployment targets. |

### 1.2 Sign-off Certification Checklist

```markdown
[ ] 1. Idempotency Keys: Enforced on all non-idempotent operations via UUIDv5 or deterministic hash.
[ ] 2. Stalled Job Protection: `stalledInterval` and `maxStalledCount` configured correctly (BullMQ default 30s verified).
[ ] 3. Worker Graceful Shutdown: `SIGTERM` / `SIGINT` triggers `worker.close()`, drains in-flight jobs within orchestration budget (e.g., Kubernetes `terminationGracePeriodSeconds` set to worker timeout + 15s).
[ ] 4. Lock Duration: Job lock duration comfortably exceeds the p99.9 execution duration of individual steps.
[ ] 5. Rate Limits: Upstream API quotas mapped directly to worker rate-limit configs (e.g., BullMQ token-bucket limiter).
[ ] 6. Zero Payload Bloat: Blobs, data URLs, large arrays offloaded to S3. Only URIs/IDs passed in job payloads.
[ ] 7. Dead Letter Queue: Automatic routing to DLQ after exhaustion of retry attempts with failure reason preserved.
[ ] 8. Alerting Active: Alerts configured for Queue Depth > Threshold, Unhandled Rejections, DLQ Item Added.
```

---

## 2. Memory Leak Diagnosis SOP for Long-Running Node.js Workers

Long-running Node.js worker pools (BullMQ processors, Inngest runner containers, Trigger.dev task agents) are prone to insidious memory leaks that cause `OOMKilled` (Exit Code 137) events under sustained load.

### 2.1 The Four Root Causes in Worker Runtimes

1. **Uncleaned Event Listeners:** Attaching `EventEmitter.on()` handlers inside the job execution path (e.g., database clients, stream pipelines) without matching `removeListener()` calls on completion or failure.
2. **Context Retention via Closures:** Long-lived step function wrappers capturing heavy parent scope variables (like large payload buffers) in asynchronous continuation chains.
3. **Global Metrics / Cache Bloat:** In-memory maps accumulating keys without TTL or eviction (e.g., caching authentication tokens or tracking processed IDs in a module-level `Set`).
4. **Redis / HTTP Socket Leaks:** Instantiating new Redis/HTTP clients per job invocation instead of reusing a shared connection pool, causing socket leakages and unbounded internal buffer allocations.

### 2.2 Diagnosis and Investigation Workflow

```
[ Worker Memory Alarm Triggers (>85% RSS) ]
                   │
                   ▼
[ Step 1: Capture Node.js Metrics via Diagnostics Channel ]
                   │
                   ▼
[ Step 2: Trigger Programmatic On-Demand Heap Snapshot ]
                   │
                   ▼
[ Step 3: Stream Heap Snapshot to Persistent Storage (S3) ]
                   │
                   ▼
[ Step 4: Compare Retained Size via Chrome DevTools / Clinic.js ]
                   │
                   ▼
[ Step 5: Identify Constructor Retainers & Execute Remediation ]
```

### 2.3 Automated Heap Profiler Utility

Integrate this production-ready watcher directly into your worker boot sequence. It monitors memory usage continuously and writes a `.heapsnapshot` to disk (or your monitoring bucket) before the orchestrator kills the pod.

```typescript
// memoryWatcher.ts
import v8 from 'node:v8';
import fs from 'node:fs';
import path from 'node:path';

interface MemoryWatcherOptions {
  heapThresholdPercentage: number; // e.g., 85 for 85%
  checkIntervalMs: number;
  outputDir: string;
}

export function startMemoryWatcher(options: MemoryWatcherOptions): NodeJS.Timeout {
  const { heapThresholdPercentage, checkIntervalMs, outputDir } = options;

  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  let snapshotTaken = false;

  const timer = setInterval(() => {
    const mem = process.memoryUsage();
    const heapStats = v8.getHeapStatistics();
    const heapUsedPercent = (heapStats.used_heap_size / heapStats.heap_size_limit) * 100;

    if (heapUsedPercent >= heapThresholdPercentage && !snapshotTaken) {
      snapshotTaken = true; // Prevent cascading snapshot loops
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const filename = path.join(outputDir, `heap-${process.pid}-${timestamp}.heapsnapshot`);

      console.error(
        `[CRITICAL ALERT] Heap threshold exceeded: ${heapUsedPercent.toFixed(2)}%! ` +
        `RSS: ${(mem.rss / 1024 / 1024).toFixed(2)} MB, ` +
        `Heap Used: ${(mem.heapUsed / 1024 / 1024).toFixed(2)} MB. ` +
        `Writing snapshot to ${filename}...`
      );

      try {
        const snapshotStream = v8.getHeapSnapshot();
        const fileStream = fs.createWriteStream(filename);
        snapshotStream.pipe(fileStream);

        fileStream.on('finish', () => {
          console.error(`[CRITICAL ALERT] Heap snapshot written successfully to ${filename}`);
          // Graceful bail-out: allow your cluster manager (K8s/ECS) to restart the container cleanly
          process.exit(137);
        });
      } catch (err) {
        console.error('[CRITICAL ALERT] Failed to capture heap snapshot:', err);
        process.exit(1);
      }
    } else if (heapUsedPercent < heapThresholdPercentage) {
      snapshotTaken = false; // Reset if memory recovers
    }
  }, checkIntervalMs);

  timer.unref(); // Do not hold the Node.js event loop open
  return timer;
}
```

### 2.4 Controlled Memory-Leak Isolation Test

Execute this script locally to replicate production event-loop leak dynamics and verify that your profiler isolates the offending retainers.

```typescript
// leakReproduction.ts
import { EventEmitter } from 'node:events';
import { Queue, Worker } from 'bullmq';

const connection = { host: '127.0.0.1', port: 6379 };
const queueName = 'leak-audit-queue';

export const globalTelemetryBus = new EventEmitter();
// Artificially increase max listeners to suppress Node.js default warnings
globalTelemetryBus.setMaxListeners(100000);

export const leakQueue = new Queue(queueName, { connection });

// Bad Worker: Attaches listeners to an external event emitter per job without cleanup
export const leakWorker = new Worker(
  queueName,
  async (job) => {
    const localBuffer = Buffer.alloc(1024 * 512, 'x'); // 512 KB payload

    // LEAK ROOT CAUSE: Closure retains localBuffer in listener context
    globalTelemetryBus.on('metric_ping', () => {
      if (localBuffer.length === 0) {
        console.log('noop');
      }
    });

    return { status: 'processed', id: job.id };
  },
  { connection, concurrency: 5 }
);

// Remediation Script:
// Clean up all dynamically attached listeners inside a try/finally block:
/*
export const cleanWorker = new Worker(queueName, async (job) => {
  const localBuffer = Buffer.alloc(1024 * 512, 'x');
  const handler = () => { if (localBuffer.length === 0) console.log('noop'); };
  
  globalTelemetryBus.on('metric_ping', handler);
  try {
    return { status: 'processed', id: job.id };
  } finally {
    globalTelemetryBus.removeListener('metric_ping', handler);
  }
}, { connection, concurrency: 5 });
*/
```

---

## 3. Poison-Pill Payload Resolution Workflows & DLQ Runbooks

A "poison pill" is a job whose payload deterministically crashes the worker execution thread, triggers an uncatchable runtime failure, or exhausts retry policies due to invariant violations.

### 3.1 Taxonomy of Poison-Pill Payloads

```
                                  POISON PILL DETECTED
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
   [Type A: Syntax/Schema]       [Type B: Execution Trap]       [Type C: Domain Invariant]
   - Corrupt JSON structure      - Catastrophic RegEx (ReDoS)   - Entity deleted upstream
   - Type mismatches             - Circular JSON references     - Immutable state conflict
   - Missing required fields     - Infinite loop payloads       - Invalid credit ledger balance
         │                                 │                                 │
         ▼                                 ▼                                 ▼
   Action: Drop or Patch Schema   Action: Patch Code & Replay     Action: Compensate & Tombstone
```

### 3.2 Dead Letter Queue (DLQ) Incident Response SOP

```
SEVERITY LEVEL: SEV-2
INCIDENT TRIGGER: DLQ Depth Monitor > 50 messages OR > 1% total queue throughput.

PHASE 1: CONTAINMENT & ISOLATION
1. Pause the dead-letter consumer or alerting monitor to prevent log flooding.
2. Route incoming matching poison payloads to a staging dead-letter queue via dynamic rule if identifiable.
3. If worker pods are crash-looping (`CrashLoopBackOff`), scale down concurrency immediately to 1 to preserve logs.

PHASE 2: TRIAGE & ROOT-CAUSE ANALYSIS
1. Pull 5 sample payloads from the DLQ (use the CLI tool below).
2. Execute the payload locally against the target step handler using your isolated debugger.
3. Classify failure according to the Taxonomy (Type A, B, or C).

PHASE 3: RESOLUTION
- For Type A (Schema): Write an in-flight mutation script to map old schema to new schema, then replay.
- For Type B (Code Bug): Deploy code hotfix to workers FIRST. Verify patch in staging. Replay DLQ messages.
- For Type C (Invariant): Emit a compensation event, notify the user/admin, mark job as "Tombstoned".

PHASE 4: VERIFICATION
1. Replay 1 message from the DLQ in "Dry Run" mode.
2. Replay 10 messages to production workers. Verify zero crashes.
3. Drain the remaining DLQ with batch size <= 100 jobs/min to protect downstream systems.
```

### 3.3 BullMQ DLQ Inspection, Sanitization, and Replay Tool

This standalone script safely inspects, patches, and replays failed jobs without risking concurrency lockups or cascading worker crashes.

```typescript
// dlqManager.ts
import { Queue, Job } from 'bullmq';
import { z } from 'zod';

const connection = { host: '127.0.0.1', port: 6379 };

interface ReplayOptions {
  queueName: string;
  batchSize: number;
  dryRun: boolean;
  sanitizer?: (rawPayload: unknown) => unknown;
}

export class DeadLetterManager {
  private queue: Queue;

  constructor(queueName: string) {
    this.queue = new Queue(queueName, { connection });
  }

  /**
   * Inspect failed jobs without modifying queue state
   */
  async inspectFailures(limit = 10): Promise<void> {
    const failedJobs = await this.queue.getFailed(0, limit - 1);
    console.log(`\n=== Found ${failedJobs.length} Failed Jobs ===`);

    for (const job of failedJobs) {
      console.log(`------------------------------------------------------------`);
      console.log(`Job ID: ${job.id}`);
      console.log(`Attempts Made: ${job.attemptsMade}`);
      console.log(`Failed Reason: ${job.failedReason}`);
      console.log(`Stack Trace:\n${job.stacktrace.slice(0, 3).join('\n')}`);
      console.log(`Data:`, JSON.stringify(job.data, null, 2));
    }
  }

  /**
   * Safely sanitize and re-queue failed jobs back to 'wait' status
   */
  async replayFailedJobs(options: ReplayOptions): Promise<void> {
    const { batchSize, dryRun, sanitizer } = options;
    const failedJobs = await this.queue.getFailed(0, batchSize - 1);

    console.log(`[DLQ REPLAY] Initiating replay for ${failedJobs.length} jobs. Dry Run: ${dryRun}`);

    let replayedCount = 0;
    let droppedCount = 0;

    for (const job of failedJobs) {
      try {
        let payloadToReplay = job.data;

        if (sanitizer) {
          payloadToReplay = sanitizer(job.data);
        }

        if (dryRun) {
          console.log(`[DRY RUN] Would replay Job ID ${job.id} with payload:`, payloadToReplay);
          replayedCount++;
          continue;
        }

        // Update the job with sanitized payload if modified
        if (sanitizer) {
          await job.updateData(payloadToReplay);
        }

        // Retry the job: moves it from failed to waiting state
        await job.retry();
        console.log(`[REPLAYED] Job ID ${job.id} re-enqueued.`);
        replayedCount++;
      } catch (err) {
        console.error(`[ERROR] Could not process Job ID ${job.id}:`, err);
        droppedCount++;
      }
    }

    console.log(`\n=== DLQ Operation Completed ===`);
    console.log(`Processed: ${replayedCount}`);
    console.log(`Errors/Dropped: ${droppedCount}`);
  }

  async close(): Promise<void> {
    await this.queue.close();
  }
}

// Example Execution Runbook Entry
async function main() {
  const manager = new DeadLetterManager('payment-processing');

  // Step 1: Inspect first 5 errors
  await manager.inspectFailures(5);

  // Define Schema Validator / Patch Strategy
  const ExpectedSchema = z.object({
    orderId: z.string().uuid(),
    amountInCents: z.number().int().positive(),
    currency: z.string().default('USD')
  });

  // Step 2: Replay with inline schema remediation
  await manager.replayFailedJobs({
    queueName: 'payment-processing',
    batchSize: 50,
    dryRun: false, // Flip to false after dryRun audit passes
    sanitizer: (raw: any) => {
      // Remediation logic: Auto-fix string amounts passed by legacy clients
      const fixedAmount = typeof raw.amountInCents === 'string'
        ? parseInt(raw.amountInCents, 10)
        : raw.amountInCents;

      return ExpectedSchema.parse({
        ...raw,
        amountInCents: fixedAmount,
        currency: raw.currency || 'USD'
      });
    }
  });

  await manager.close();
}

if (require.main === module) {
  main().catch(console.error);
}
```

### 3.4 Inngest Failed Event Recovery CLI Commands

Inngest handles execution state inside its engine. When handling events that yield dead-letter or unhandled step failures, use the following operational procedures via the Inngest API/CLI:

```bash
# 1. Fetch failure details for a specific run ID
curl -X GET "https://api.inngest.com/v1/runs/01HV8VNZP9B3..." \
  -H "Authorization: Bearer $INNGEST_SIGNING_KEY"

# 2. Resend the original event that triggered the failed run with patched idempotency
curl -X POST "https://inn.gs/e/$INNGEST_EVENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "billing/subscription.created",
    "data": {
      "subscriptionId": "sub_10928301",
      "replayedAt": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",
      "isReplay": true
    }
  }'

# 3. Rerun a failed step directly via Inngest REST API (bypassing re-execution of completed steps)
curl -X POST "https://api.inngest.com/v1/runs/01HV8VNZP9B3.../rerun" \
  -H "Authorization: Bearer $INNGEST_SIGNING_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "stepId": "charge-card"
  }'
```

---

## 4. Observability Swipe File: OpenTelemetry & Datadog Telemetry

Standard web-framework instrumentation misses asynchronous execution gaps. When a task is enqueued, goes idle in Redis, wakes up on a remote worker, and runs discrete steps across network calls, distributed traces routinely break.

### 4.1 Production OpenTelemetry SDK Setup for Worker Nodes

This configuration handles trace context propagation and links parent dispatch traces to child worker executions.

```typescript
// telemetry.ts
import { NodeSDK } from '@opentelemetry/sdk-node';
import { Resource } from '@opentelemetry/resources';
import { SemanticResourceAttributes } from '@opentelemetry/semantic-conventions';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-grpc';
import { PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics';
import { OTLPMetricExporter } from '@opentelemetry/exporter-metrics-otlp-grpc';
import { HttpInstrumentation } from '@opentelemetry/instrumentation-http';
import { IORedisInstrumentation } from '@opentelemetry/instrumentation-ioredis';
import { trace, context, SpanKind, SpanStatusCode, Tracer } from '@opentelemetry/api';

export const otelSdk = new NodeSDK({
  resource: new Resource({
    [SemanticResourceAttributes.SERVICE_NAME]: process.env.SERVICE_NAME || 'background-worker',
    [SemanticResourceAttributes.SERVICE_VERSION]: process.env.SERVICE_VERSION || '1.0.0',
    [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: process.env.NODE_ENV || 'production',
  }),
  traceExporter: new OTLPTraceExporter({
    url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://otel-collector:4317',
  }),
  metricReader: new PeriodicExportingMetricReader({
    exporter: new OTLPMetricExporter({
      url: process.env.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT || 'http://otel-collector:4317',
    }),
    exportIntervalMillis: 15000,
  }),
  instrumentations: [
    new HttpInstrumentation(),
    new IORedisInstrumentation(),
  ],
});

otelSdk.start();

export const tracer: Tracer = trace.getTracer('durable-workflow-tracer');

/**
 * Tracing Helper to instrument arbitrary background step functions
 */
export async function traceStep<T>(
  stepName: string,
  parentCarrier: Record<string, string> | undefined,
  fn: () => Promise<T>
): Promise<T> {
  const extractedContext = parentCarrier 
    ? trace.getTracer('bullmq').startSpan(stepName, undefined, context.active())
    : undefined;

  return tracer.startActiveSpan(
    stepName,
    {
      kind: SpanKind.CONSUMER,
      attributes: {
        'workflow.step': stepName,
      },
    },
    async (span) => {
      try {
        const result = await fn();
        span.setStatus({ code: SpanStatusCode.OK });
        return result;
      } catch (error: any) {
        span.recordException(error);
        span.setStatus({
          code: SpanStatusCode.ERROR,
          message: error?.message || 'Step execution encountered an error',
        });
        throw error;
      } finally {
        span.end();
      }
    }
  );
}
```

### 4.2 BullMQ Telemetry Instrumentation with Datadog Metrics

This drop-in integration wraps a BullMQ worker to capture runtime execution metrics, stalled events, and step performance with Datadog custom metric dogstatsd protocols.

```typescript
// bullmqDatadogMonitor.ts
import { Worker, Queue, Job } from 'bullmq';
import StatsD from 'hot-shots';

const dogstatsd = new StatsD({
  host: process.env.DD_AGENT_HOST || '127.0.0.1',
  port: 8125,
  prefix: 'jobs.',
  globalTags: { env: process.env.NODE_ENV || 'production', service: 'queue-processor' },
});

export function instrumentBullMQWorker(worker: Worker): void {
  const queueName = worker.name;

  worker.on('active', (job: Job) => {
    dogstatsd.increment('execution.started', 1, [`queue:${queueName}`, `job_name:${job.name}`]);
    // Tag latency between creation and execution start
    const delayDurationMs = Date.now() - job.timestamp;
    dogstatsd.histogram('queue.wait_delay_ms', delayDurationMs, [`queue:${queueName}`, `job_name:${job.name}`]);
  });

  worker.on('completed', (job: Job) => {
    const runtimeMs = Date.now() - (job.processedOn || job.timestamp);
    dogstatsd.increment('execution.completed', 1, [`queue:${queueName}`, `job_name:${job.name}`]);
    dogstatsd.histogram('execution.duration_ms', runtimeMs, [`queue:${queueName}`, `job_name:${job.name}`]);
  });

  worker.on('failed', (job: Job | undefined, err: Error) => {
    dogstatsd.increment('execution.failed', 1, [
      `queue:${queueName}`,
      `job_name:${job?.name || 'unknown'}`,
      `error_type:${err.name || 'Error'}`,
    ]);
  });

  worker.on('stalled', (jobId: string) => {
    dogstatsd.increment('execution.stalled', 1, [`queue:${queueName}`, `stalled_job_id:${jobId}`]);
  });

  worker.on('error', (err: Error) => {
    dogstatsd.increment('worker.system_error', 1, [`queue:${queueName}`, `error:${err.name}`]);
  });
}

/**
 * Polling service to emit queue health depths to Datadog
 */
export function startQueueDepthMetricsReporter(queue: Queue, intervalMs = 10000): NodeJS.Timeout {
  const timer = setInterval(async () => {
    try {
      const counts = await queue.getJobCounts('active', 'wait', 'delayed', 'failed', 'paused');
      
      dogstatsd.gauge('queue.depth.active', counts.active, [`queue:${queue.name}`]);
      dogstatsd.gauge('queue.depth.wait', counts.wait, [`queue:${queue.name}`]);
      dogstatsd.gauge('queue.depth.delayed', counts.delayed, [`queue:${queue.name}`]);
      dogstatsd.gauge('queue.depth.failed', counts.failed, [`queue:${queue.name}`]);
    } catch (err) {
      console.error(`Failed to collect job counts for queue: ${queue.name}`, err);
    }
  }, intervalMs);

  timer.unref();
  return timer;
}
```

### 4.3 Inngest Middleware for Trace Context Injection and Step Timing

Drop this custom middleware into your Inngest client to automatically bridge Inngest executions into your Datadog or OpenTelemetry traces.

```typescript
// inngestTelemetryMiddleware.ts
import { InngestMiddleware } from 'inngest';
import StatsD from 'hot-shots';

const statsd = new StatsD({ prefix: 'inngest.' });

export const telemetryMiddleware = new InngestMiddleware({
  name: 'Observability & Metrics Middleware',
  init() {
    return {
      onFunctionRun({ fn, ctx }) {
        const functionId = fn.id(null as any);
        const startTime = Date.now();
        statsd.increment('function.started', 1, [`function_id:${functionId}`]);

        return {
          transformOutput({ result, step }) {
            const stepName = step?.displayName || 'root';
            statsd.increment('step.executed', 1, [
              `function_id:${functionId}`,
              `step_name:${stepName}`,
            ]);
          },
          beforeExecution() {
            // Can extract and mount trace carriers here
          },
          afterExecution() {
            const duration = Date.now() - startTime;
            statsd.histogram('function.duration_ms', duration, [`function_id:${functionId}`]);
          },
          transformError({ error }) {
            statsd.increment('function.failed', 1, [
              `function_id:${functionId}`,
              `error_class:${(error as any)?.name || 'Error'}`,
            ]);
          },
        };
      },
    };
  },
});
```

---

## 5. Production Alert Rules: Datadog & Prometheus (PromQL)

Copy and apply these alerting policies to trigger targeted incident escalation before queue delays impact end users.

### 5.1 Datadog Monitor Definitions (JSON Format)

#### Alert 1: Unhandled Dead-Letter Queue Surge
```json
{
  "name": "{{#is_alert}}CRITICAL: Dead Letter Queue Spiking - {{queue.name}} {{/is_alert}}{{#is_warning}}WARNING: Dead Letter Queue Rising - {{queue.name}} {{/is_warning}}",
  "type": "query alert",
  "query": "sum(last_5m):sum:jobs.execution.failed{*} by {queue} > 10",
  "message": "Jobs are exhausting retries and entering the DLQ in queue {{queue.name}}.\n\nSOP Runbook: Follow 04_Checklists_Troubleshooting Section 3 to safely inspect and patch the failing payloads.\n\n@pagerduty-tier-1",
  "tags": ["service:background-jobs", "severity:page", "tier:data-platform"],
  "options": {
    "thresholds": {
      "critical": 10.0,
      "warning": 3.0
    },
    "notify_no_data": false,
    "renotify_interval": 30,
    "evaluation_delay": 60
  }
}
```

#### Alert 2: Worker Process Memory Saturation (Near OOM)
```json
{
  "name": "CRITICAL: Background Worker Node Heap Memory Ex
