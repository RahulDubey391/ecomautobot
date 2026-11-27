# Module 2: 50+ Production Blueprints, Step Functions & Worker Configurations

---

## 1. Multi-Step LLM Batch Pipeline with Self-Healing Retries (Inngest v3)

This blueprint processes high-volume document batches through chunking, parallel LLM analysis, schema validation with Zod, and automatic fallback to a smaller, faster model when rate limits (HTTP 429) or context limits (HTTP 400) are encountered.

```typescript
import { Inngest } from "inngest";
import { z } from "zod";
import OpenAI from "openai";

export const inngest = new Inngest({ id: "document-processing-service" });

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY!,
});

const AnalysisSchema = z.object({
  summary: z.string().min(20),
  keyEntities: z.array(z.string()),
  sentimentScore: z.number().min(-1).max(1),
  actionItems: z.array(z.string()),
});

type DocumentAnalysis = z.infer<typeof AnalysisSchema>;

interface DocumentBatchEvent {
  data: {
    batchId: string;
    documents: Array<{
      id: string;
      rawText: string;
    }>;
  };
}

export const processDocumentBatch = inngest.createFunction(
  {
    id: "process-document-batch",
    retries: 3,
    concurrency: {
      limit: 5,
      key: "event.data.batchId",
    },
    throttle: {
      limit: 50,
      period: "1m",
    },
  },
  { event: "documents/batch.submitted" },
  async ({ event, step }) => {
    const { batchId, documents } = event.data as DocumentBatchEvent["data"];

    // Step 1: Chunk documents deterministically
    const chunkedDocuments = await step.run("chunk-documents", async () => {
      return documents.map((doc) => {
        const words = doc.rawText.split(/\s+/);
        const chunkSize = 800;
        const chunks: string[] = [];
        for (let i = 0; i < words.length; i += chunkSize) {
          chunks.push(words.slice(i, i + chunkSize).join(" "));
        }
        return { docId: doc.id, chunks };
      });
    });

    // Step 2: Fan-out analysis per document with rate-limit self-healing
    const analysisResults: Array<{ docId: string; analysis: DocumentAnalysis }> = [];

    for (const doc of chunkedDocuments) {
      const result = await step.run(`analyze-doc-${doc.docId}`, async () => {
        const aggregatedText = doc.chunks.join("\n\n--- CHUNK BREAK ---\n\n");
        let model = "gpt-4o";
        let responsePayload: string | null = null;

        try {
          const completion = await openai.chat.completions.create({
            model,
            response_format: { type: "json_object" },
            messages: [
              {
                role: "system",
                content:
                  "Extract structured metadata. Output JSON matching: { summary: string, keyEntities: string[], sentimentScore: number, actionItems: string[] }",
              },
              { role: "user", content: aggregatedText },
            ],
            temperature: 0.2,
          });
          responsePayload = completion.choices[0].message.content;
        } catch (err: any) {
          // Fallback to gpt-4o-mini if rate-limited or payload overloaded
          if (err?.status === 429 || err?.status === 400) {
            model = "gpt-4o-mini";
            const fallbackCompletion = await openai.chat.completions.create({
              model,
              response_format: { type: "json_object" },
              messages: [
                {
                  role: "system",
                  content:
                    "Extract structured metadata concisely. Output JSON matching schema: { summary: string, keyEntities: string[], sentimentScore: number, actionItems: string[] }",
                },
                { role: "user", content: aggregatedText.slice(0, 12000) },
              ],
              temperature: 0.1,
            });
            responsePayload = fallbackCompletion.choices[0].message.content;
          } else {
            throw err;
          }
        }

        if (!responsePayload) {
          throw new Error(`Empty LLM response for document ${doc.docId}`);
        }

        const parsed = AnalysisSchema.parse(JSON.parse(responsePayload));
        return { docId: doc.docId, analysis: parsed };
      });

      analysisResults.push(result);
    }

    // Step 3: Fan-in aggregation and persistence
    const batchSummary = await step.run("persist-and-aggregate", async () => {
      const totalEntities = new Set(
        analysisResults.flatMap((r) => r.analysis.keyEntities)
      ).size;
      const avgSentiment =
        analysisResults.reduce((acc, r) => acc + r.analysis.sentimentScore, 0) /
        analysisResults.length;

      return {
        batchId,
        processedCount: analysisResults.length,
        uniqueEntitiesFound: totalEntities,
        averageSentimentScore: Number(avgSentiment.toFixed(3)),
        completedAt: new Date().toISOString(),
      };
    });

    return batchSummary;
  }
);
```

---

## 2. Distributed Video Transcoding & Fan-Out/Fan-In (Trigger.dev v3)

This blueprint accepts a source video in S3, generates renditions across multiple resolutions (`1080p`, `720p`, `480p`, `360p`) in parallel child tasks, generates an HLS master manifest, and updates database records upon completion.

```typescript
import { task, wait } from "@trigger.dev/sdk/v3";
import { S3Client, PutObjectCommand, HeadObjectCommand } from "@aws-sdk/client-s3";
import { exec } from "child_process";
import { promisify } from "util";
import * as fs from "fs";
import * as path from "path";

const execAsync = promisify(exec);
const s3 = new S3Client({ region: process.env.AWS_REGION! });

interface TranscodeTaskPayload {
  videoId: string;
  sourceS3Key: string;
  sourceBucket: string;
  destinationBucket: string;
}

interface RenditionSpec {
  resolution: string;
  bitrate: string;
  width: number;
  height: number;
}

const RENDITIONS: RenditionSpec[] = [
  { resolution: "1080p", bitrate: "4500k", width: 1920, height: 1080 },
  { resolution: "720p", bitrate: "2200k", width: 1280, height: 720 },
  { resolution: "480p", bitrate: "800k", width: 854, height: 480 },
  { resolution: "360p", bitrate: "400k", width: 640, height: 360 },
];

export const transcodeRenditionTask = task({
  id: "transcode-rendition",
  retry: {
    maxAttempts: 2,
    factor: 2,
    minTimeoutInMs: 1000,
  },
  run: async (payload: {
    videoId: string;
    sourceLocalPath: string;
    rendition: RenditionSpec;
    destinationBucket: string;
  }) => {
    const { videoId, sourceLocalPath, rendition, destinationBucket } = payload;
    const outputDir = path.join("/tmp", videoId, rendition.resolution);
    fs.mkdirSync(outputDir, { recursive: true });

    const outputPath = path.join(outputDir, "output.m3u8");
    const segmentPath = path.join(outputDir, "segment_%03d.ts");

    const ffmpegCmd = [
      "ffmpeg -y -i",
      `"${sourceLocalPath}"`,
      `-vf scale=w=${rendition.width}:h=${rendition.height}:force_original_aspect_ratio=decrease`,
      `-c:a aac -ar 48000 -b:a 128k`,
      `-c:v h264 -profile:v main -crf 20 -b:v ${rendition.bitrate} -maxrate ${rendition.bitrate} -bufsize ${rendition.bitrate}`,
      `-hls_time 6 -hls_playlist_type vod -hls_segment_filename "${segmentPath}"`,
      `"${outputPath}"`,
    ].join(" ");

    await execAsync(ffmpegCmd);

    const generatedFiles = fs.readdirSync(outputDir);
    for (const file of generatedFiles) {
      const fileData = fs.readFileSync(path.join(outputDir, file));
      const s3Key = `transcoded/${videoId}/${rendition.resolution}/${file}`;
      await s3.send(
        new PutObjectCommand({
          Bucket: destinationBucket,
          Key: s3Key,
          Body: fileData,
          ContentType: file.endsWith(".m3u8")
            ? "application/vnd.apple.mpegurl"
            : "video/MP2T",
        })
      );
    }

    return {
      resolution: rendition.resolution,
      manifestS3Key: `transcoded/${videoId}/${rendition.resolution}/output.m3u8`,
      bandwidth: parseInt(rendition.bitrate) * 1000,
      width: rendition.width,
      height: rendition.height,
    };
  },
});

export const videoPipelineOrchestrator = task({
  id: "video-transcoding-pipeline",
  run: async (payload: TranscodeTaskPayload) => {
    const { videoId, sourceS3Key, sourceBucket, destinationBucket } = payload;
    const localSourcePath = path.join("/tmp", `${videoId}_source.mp4`);

    // Ensure source exists
    await s3.send(
      new HeadObjectCommand({ Bucket: sourceBucket, Key: sourceS3Key })
    );

    // Download source to scratch disk
    await execAsync(
      `aws s3 cp s3://${sourceBucket}/${sourceS3Key} ${localSourcePath}`
    );

    // Fan-out across all target resolutions
    const renditionRuns = await Promise.all(
      RENDITIONS.map((rendition) =>
        transcodeRenditionTask.triggerAndWait({
          videoId,
          sourceLocalPath: localSourcePath,
          rendition,
          destinationBucket,
        })
      )
    );

    const completedRenditions = renditionRuns
      .filter((run) => run.ok)
      .map((run) => run.output);

    if (completedRenditions.length === 0) {
      throw new Error(`All transcoding passes failed for videoId: ${videoId}`);
    }

    // Fan-in: Generate Master Playlist
    let masterPlaylist = "#EXTM3U\n#EXT-X-VERSION:3\n";
    for (const ren of completedRenditions) {
      masterPlaylist += `#EXT-X-STREAM-INF:BANDWIDTH=${ren.bandwidth},RESOLUTION=${ren.width}x${ren.height}\n`;
      masterPlaylist += `${ren.resolution}/output.m3u8\n`;
    }

    const masterKey = `transcoded/${videoId}/master.m3u8`;
    await s3.send(
      new PutObjectCommand({
        Bucket: destinationBucket,
        Key: masterKey,
        Body: Buffer.from(masterPlaylist, "utf-8"),
        ContentType: "application/vnd.apple.mpegurl",
      })
    );

    // Clean up scratch source
    if (fs.existsSync(localSourcePath)) {
      fs.unlinkSync(localSourcePath);
    }

    return {
      videoId,
      status: "COMPLETED",
      masterPlaylistUrl: `s3://${destinationBucket}/${masterKey}`,
      renditionsAvailable: completedRenditions.map((r) => r.resolution),
    };
  },
});
```

---

## 3. Stripe Billing Reconciliation & Dunning Step Function (Inngest v3)

Handles `invoice.payment_failed` webhooks, initiates a 14-day progressive dunning flow, and suspends tenant workspaces if payment is not recovered.

```typescript
import { Inngest } from "inngest";
import Stripe from "stripe";

export const inngest = new Inngest({ id: "billing-reconciliation-engine" });
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2024-06-20",
});

interface InvoiceFailedEvent {
  data: {
    invoiceId: string;
    customerId: string;
    attemptCount: number;
    amountDue: number;
    currency: string;
  };
}

export const stripeDunningWorkflow = inngest.createFunction(
  {
    id: "stripe-dunning-and-reconciliation",
    retries: 5,
    cancelOn: [
      {
        event: "stripe/invoice.payment_succeeded",
        match: "data.invoiceId",
      },
    ],
  },
  { event: "stripe/invoice.payment_failed" },
  async ({ event, step }) => {
    const { invoiceId, customerId, amountDue, currency } =
      event.data as InvoiceFailedEvent["data"];

    // Phase 1: Immediate Grace Period & Email Notification
    await step.run("send-first-dunning-notice", async () => {
      const customer = await stripe.customers.retrieve(customerId);
      if (customer.deleted) throw new Error("Customer deleted");

      const portalSession = await stripe.billingPortal.sessions.create({
        customer: customerId,
        return_url: `${process.env.APP_BASE_URL}/billing`,
      });

      await fetch(`${process.env.EMAIL_API_URL}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          to: customer.email,
          subject: "Urgent: Payment failed for your subscription",
          template: "payment-failed-first-notice",
          variables: {
            portalUrl: portalSession.url,
            amount: (amountDue / 100).toFixed(2),
            currency: currency.toUpperCase(),
          },
        }),
      });

      return { noticeNumber: 1, sentAt: new Date().toISOString() };
    });

    // Wait 3 days before retrying payment card charge
    await step.sleep("wait-for-first-retry-window", "3d");

    // Phase 2: First Automated Retry & Second Notice
    const firstRetryResult = await step.run("attempt-first-charge-retry", async () => {
      try {
        const paidInvoice = await stripe.invoices.pay(invoiceId);
        return { status: paidInvoice.status };
      } catch (err: any) {
        return { status: "failed", code: err?.code || "unknown_error" };
      }
    });

    if (firstRetryResult.status === "paid") {
      return { resolution: "PAID_ON_FIRST_RETRY", invoiceId };
    }

    await step.run("send-second-dunning-notice", async () => {
      const customer = await stripe.customers.retrieve(customerId);
      if (customer.deleted) return;

      const portalSession = await stripe.billingPortal.sessions.create({
        customer: customerId,
        return_url: `${process.env.APP_BASE_URL}/billing`,
      });

      await fetch(`${process.env.EMAIL_API_URL}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          to: customer.email,
          subject: "Final Notice: Your service will be downgraded in 4 days",
          template: "payment-failed-urgent-notice",
          variables: { portalUrl: portalSession.url },
        }),
      });
    });

    // Wait 4 more days (Day 7 overall)
    await step.sleep("wait-for-second-retry-window", "4d");

    // Phase 3: Final Card Attempt
    const finalRetry = await step.run("attempt-final-charge-retry", async () => {
      try {
        const invoice = await stripe.invoices.pay(invoiceId);
        return { status: invoice.status };
      } catch (err) {
        return { status: "failed" };
      }
    });

    if (finalRetry.status === "paid") {
      return { resolution: "PAID_ON_FINAL_RETRY", invoiceId };
    }

    // Phase 4: Demote Account Access & Void Uncollectible Invoice
    const reconciliationOutcome = await step.run("suspend-workspace", async () => {
      // Mark invoice uncollectible
      await stripe.invoices.markUncollectible(invoiceId);

      // Lock tenant database permissions
      const response = await fetch(
        `${process.env.INTERNAL_API_URL}/tenants/suspend`,
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${process.env.INTERNAL_SERVICE_TOKEN}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ stripeCustomerId: customerId, reason: "DUNNING_EXHAUSTED" }),
        }
      );

      if (!response.ok) {
        throw new Error(`Failed to suspend workspace for customer ${customerId}`);
      }

      return { suspended: true, suspendedAt: new Date().toISOString() };
    });

    return {
      resolution: "SUSPENDED_UNPAID",
      invoiceId,
      customerId,
      reconciliationOutcome,
    };
  }
);
```

---

## 4. Enterprise Webhook Ingestion Engine with Jitter & DLQ (BullMQ v5)

This blueprint contains an express/hono edge receiver verifying HMAC-SHA256 signatures, pushing to a BullMQ queue configured with exponential backoff and decorrelated jitter, and handling permanent dead-letter drops with structured audit storage.

```typescript
import { Queue, Worker, Job, QueueEvents } from "bullmq";
import Redis from "ioredis";
import * as crypto from "crypto";

const connection = new Redis(process.env.REDIS_URL!, {
  maxRetriesPerRequest: null,
});

export interface WebhookJobPayload {
  deliveryId: string;
  source: string;
  rawPayload: Record<string, any>;
  signature: string;
  timestamp: number;
}

// 1. Initialize BullMQ Queue
export const webhookIngestionQueue = new Queue<WebhookJobPayload>(
  "enterprise-webhook-queue",
  {
    connection,
    defaultJobOptions: {
      attempts: 8,
      backoff: {
        type: "custom",
      },
      removeOnComplete: {
        age: 86400, // keep 24 hours
        count: 5000,
      },
      removeOnFail: false, // Never auto-remove failed jobs, retain for DLQ auditing
    },
  }
);

// 2. Custom Backoff Strategy: Full Jitter Exponential Backoff
export const calculateBackoffWithJitter = (attemptsMade: number): number => {
  const baseDelayMs = 1000;
  const maxDelayMs = 1000 * 60 * 30; // 30 minutes cap
  const exponentialLimit = Math.min(maxDelayMs, baseDelayMs * Math.pow(2, attemptsMade));
  // Random jitter between baseDelay and calculated power
  return Math.floor(Math.random() * (exponentialLimit - baseDelayMs) + baseDelayMs);
};

// 3. Worker Implementation
export const webhookWorker = new Worker<WebhookJobPayload>(
  "enterprise-webhook-queue",
  async (job: Job<WebhookJobPayload>) => {
    const { deliveryId, source, rawPayload, signature, timestamp } = job.data;

    // Verify freshness (reject replay attacks older than 5 minutes)
    const currentTime = Date.now();
    if (currentTime - timestamp > 300000) {
      throw new Error(`Replay attack detected: Payload timestamp delta exceeds 300s`);
    }

    // Verify Cryptographic Signature
    const secret = process.env.WEBHOOK_SIGNING_SECRET!;
    const expectedSignature = crypto
      .createHmac("sha256", secret)
      .update(JSON.stringify(rawPayload))
      .digest("hex");

    const signatureBuffer = Buffer.from(signature);
    const expectedBuffer = Buffer.from(expectedSignature);

    if (
      signatureBuffer.length !== expectedBuffer.length ||
      !crypto.timingSafeEqual(signatureBuffer, expectedBuffer)
    ) {
      // Permanent structural failure: do not retry
      throw new Error("UNAUTHORIZED_SIGNATURE_MISMATCH");
    }

    // Route event to internal systems
    const downstreamResponse = await fetch(
      `${process.env.CORE_DISPATCH_URL}/webhooks/consume`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Delivery-Id": deliveryId,
          "X-Source": source,
        },
        body: JSON.stringify(rawPayload),
      }
    );

    if (!downstreamResponse.ok) {
      const errText = await downstreamResponse.text();
      throw new Error(`Downstream HTTP ${downstreamResponse.status}: ${errText}`);
    }

    return { processed: true, deliveryId };
  },
  {
    connection,
    concurrency: 25,
    settings: {
      backoffStrategies: {
        custom: (attemptsMade: number) => calculateBackoffWithJitter(attemptsMade),
      },
    },
  }
);

// 4. Dead Letter Queue Handler on Total Exhaustion
webhookWorker.on("failed", async (job: Job<WebhookJobPayload> | undefined, err: Error) => {
  if (!job) return;

  if (job.attemptsMade >= (job.opts.attempts || 8)) {
    await connection.hset(
      `dlq:enterprise-webhooks:${job.data.deliveryId}`,
      {
        deliveryId: job.data.deliveryId,
        source: job.data.source,
        payload: JSON.stringify(job.data.rawPayload),
        failedReason: err.message,
        stackTrace: err.stack || "",
        attemptsMade: job.attemptsMade.toString(),
        droppedAt: new Date().toISOString(),
      }
    );

    // Alert incident response webhook
    await fetch(process.env.OPSGENIE_ALERT_WEBHOOK_URL!, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: `Webhook processing moved to DLQ: ${job.data.deliveryId}`,
        details: { error: err.message, attempts: job.attemptsMade },
      }),
    });
  }
});
```

---

## 5. Fan-Out / Fan-In Aggregation Worker (BullMQ + Redis Coordination)

This pattern slices large datasets (e.g., 50,000 customers for tax calculation) into batches, fans out jobs across distributed worker pools, tracks progress atomically with Redis hashes, and triggers a single reconciliation job when the entire batch is verified complete.

```typescript
import { Queue, Worker, Job } from "bullmq";
import Redis from "ioredis";

const redis = new Redis(process.env.REDIS_URL!, { maxRetriesPerRequest: null });

const CHUNK_QUEUE_NAME = "tax-fanout-chunk-queue";
const AGGREGATE_QUEUE_NAME = "tax-fanin-aggregate-queue";

export const chunkQueue = new Queue(CHUNK_QUEUE_NAME, { connection: redis });
export const aggregateQueue = new Queue(AGGREGATE_QUEUE_NAME, { connection: redis });

interface ChunkJobPayload {
  masterBatchId: string;
  chunkIndex: number;
  totalChunks: number;
  records: Array<{ customerId: string; subtotal: number; state: string }>;
}

interface AggregateJobPayload {
  masterBatchId: string;
  totalChunks: number;
}

// 1. Dispatcher: Slices and Enqueues
export async function dispatchBatch(
  masterBatchId: string,
  records: Array<{ customerId: string; subtotal: number; state: string }>
) {
  const CHUNK_SIZE = 500;
  const totalChunks = Math.ceil(records.length / CHUNK_SIZE);

  // Initialize tracking ledger in Redis
  await redis
    .multi()
    .set(`batch:${masterBatchId}:total`, totalChunks)
    .set(`batch:${masterBatchId}:completed`, 0)
    .del(`batch:${masterBatchId}:results`)
    .exec();

  const jobs = [];
  for (let i = 0; i < totalChunks; i++) {
    const chunk = records.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    jobs.push({
      name: `chunk-${i}`,
      data: {
        masterBatchId,
        chunkIndex: i,
        totalChunks,
        records: chunk,
      } as ChunkJobPayload,
      opts: {
        attempts: 3,
        backoff: { type: "exponential", delay: 2000 },
      },
    });
  }

  await chunkQueue.addBulk(jobs);
}

// 2. Child Worker: Processes Subsets
export const chunkWorker = new Worker<ChunkJobPayload>(
  CHUNK_QUEUE_NAME,
  async (job: Job<ChunkJobPayload>) => {
    const { masterBatchId, chunkIndex, totalChunks, records } = job.data;

    let chunkTaxSum = 0;
    for (const record of records) {
      // Deterministic state tax rules
      const rate = record.state === "CA" ? 0.0825 : record.state === "NY" ? 0.08875 : 0.05;
      chunkTaxSum += record.subtotal * rate;
    }

    // Atomic tallying and completion tracking using Lua Script
    const luaScript = `
      local batchId = KEYS[1]
      local chunkSum = ARGV[1]
      local totalChunks = tonumber(redis.call('get', 'batch:' .. batchId .. ':total'))

      redis.call('rpush', 'batch:' .. batchId .. ':results', chunkSum)
      local completed = redis.call('incr', 'batch:' .. batchId .. ':completed')

      if completed == totalChunks then
        return 1
      else
        return 0
      end
    `;

    const isLastChunk = await redis.eval(
      luaScript,
      1,
      masterBatchId,
      chunkTaxSum.toFixed(4)
    );

    // If this execution completed the entire set, queue the parent fan-in job
    if (isLastChunk === 1) {
      await aggregateQueue.add("finalize-tax-run", {
        masterBatchId,
        totalChunks,
      } as AggregateJobPayload);
    }

    return { chunkIndex, processed: records.length, chunkTaxSum };
  },
  { connection: redis, concurrency: 10 }
);

// 3. Parent Worker: Final Fan-in Aggregator
export const aggregateWorker = new Worker<AggregateJobPayload>(
  AGGREGATE_QUEUE_NAME,
  async (job: Job<AggregateJobPayload>) => {
    const { masterBatchId, totalChunks } = job.data;

    const rawResults = await redis.lrange(`batch:${masterBatchId}:results`, 0, -1);
    if (rawResults.length !== totalChunks) {
      throw new Error(
        `Desynchronization: expected ${totalChunks} chunks in Redis, found ${rawResults.length}`
      );
    }

    const grandTotalTax = rawResults
      .map(parseFloat)
      .reduce((acc, val) => acc + val, 0);

    // Persist final aggregated run
    await redis.set(
      `batch:${masterBatchId}:final`,
      JSON.stringify({
        masterBatchId,
        grandTotalTax: Number(grandTotalTax.toFixed(2)),
        chunksProcessed: rawResults.length,
        finishedAt: new Date().toISOString(),
      })
    );

    // Clean up temporary keys
    await redis.del(
      `batch:${masterBatchId}:total`,
      `batch:${masterBatchId}:completed`,
      `batch:${masterBatchId}:results`
    );

    return { masterBatchId, grandTotalTax: Number(grandTotalTax.toFixed(2)) };
  },
  { connection: redis, concurrency: 2 }
);
```

---

## 6. Framework Implementation Comparison Matrix

| Parameter / Requirement | BullMQ v5 | Inngest v3 | Trigger.dev v3 |
| :--- | :--- | :--- | :--- |
| **State Storage Layer** | Redis / Redis Cluster | Managed Cloud / Self-hosted Event Log | PostgreSQL Engine / Managed Cloud |
| **Step Execution Ceiling** | Single process run per job (must manage internal sub-queues) | Indefinite duration via durable deterministic steps | Up to 24+ hours uninterrupted compute per run |
| **Backoff Configuration** | Custom code, exponential, fixed, jitter algorithms | Fully managed automatic backoff per step | Per-task retry policy with factor and timeout caps |
| **Sleep/Wait Capability** | Requires Redis delayed queue tracking | `step.sleep(name, duration)` or `step.waitForEvent(...)` | `wait.for({ seconds })` / `wait.until()` durable primitives |
| **Cold Start Performance** | Microseconds (persistent worker polling) | Minimal (HTTP endpoint webhook invocation) | Serverless task container startup (~200ms) |
| **Local Development** | Docker run Redis + local Node instances | Inngest Dev Server CLI (`npx inngest-cli dev`) | Trigger Dev CLI Session (`npx trigger.dev dev`) |
| **Concurrency Controls** | Worker-level limits + Redis rate-limiting locks | Group/Key-level throttles and concurrency limits | Unified concurrency limits scoped by queue/task/key |

---

## 7. Production Configuration Schemas

### 7.1. BullMQ Worker Production Options Object

```typescript
import { WorkerOptions } from "bullmq";

export const productionWorkerOptions: WorkerOptions = {
  concurrency: 50,
  lockDuration: 60000, // 60 seconds to prevent early lock drop under high GC
  lockRenewTime:
