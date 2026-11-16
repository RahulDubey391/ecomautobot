# Module 2: 25+ Production PRDs, Database Schemas & API Integration Blueprints

This module contains copy-paste architectural specifications, database schemas, and integration engines designed for production deployments. Every specification includes concrete implementations, explicit schemas, deterministic error handling, and security controls.

---

## 1. Architectural PRD: AI Automation Wrapper

### 1.1 Metadata & Service Level Objectives (SLOs)
* **Document Version:** `2.4.0`
* **Target System:** Distributed Async LLM Pipeline with Streaming Delivery
* **Availability SLO:** 99.95% uptime (< 21.9 minutes downtime/month)
* **Latency SLOs:**
  * Time to First Token (TTFT): $\le 650\text{ ms}$ (p95)
  * End-to-End Execution (Buffered Fallback): $\le 4,200\text{ ms}$ (p99)
* **Durability Target:** 100% trace retention on failure; zero unlogged silent fallbacks

### 1.2 Pipeline State Machine
Requests move through an explicit state machine with persistent transitions logged to an unlogged transition table for post-mortem debugging.

```
       [ INCOMING REQUEST ]
                 │
                 ▼
        [ TOKEN VALIDATION ]
                 │
                 ├── (Invalid / Quota Exceeded) ──► [ REJECT 402/429 ]
                 │
                 ▼
        [ DISPATCH WORKER ]
                 │
                 ▼
       [ PRIMARY: OPENAI ] ─── (Timeout > 3500ms / 5xx) ───┐
                 │                                         │
                 ├─────────────┐                           ▼
                 │ Success     │ Stream Interrupted  [ SECONDARY: ANTHROPIC ]
                 ▼             ▼                           │
        [ CLIENT STREAM ]  [ RECONNECT BUFFER ]            ├── (Timeout / 5xx)
                 │                                         │
                 │                                         ▼
                 │                                  [ TERTIARY: MISTRAL ]
                 │                                         │
                 │                                         ├── (Total Failure)
                 │                                         │          │
                 ▼                                         ▼          ▼
         [ LOG & METER ]                           [ PARSE ERROR ]  [ DEAD LETTER ]
```

### 1.3 Concrete Fallback & Execution Matrix

| Tier | Provider | Model ID | Timeout (Connect / Read) | Trigger Condition |
| :--- | :--- | :--- | :--- | :--- |
| **Primary** | OpenAI | `gpt-4o-2024-08-06` | $400\text{ ms}$ / $3,500\text{ ms}$ | Default route |
| **Secondary** | Anthropic | `claude-3-5-sonnet-20240620` | $500\text{ ms}$ / $4,000\text{ ms}$ | HTTP 429, 500, 502, 503, 504, or primary TTFT > $1,200\text{ ms}$ |
| **Tertiary** | Groq (Llama) | `llama-3.1-70b-versatile` | $250\text{ ms}$ / $2,000\text{ ms}$ | Anthropic API connection timeout or regional outage |
| **Fallback** | Cached / Deterministic | Static Mock Template | $0\text{ ms}$ | All upstream providers exhausted |

### 1.4 Hardened LLM Completion & Resilient Router (TypeScript)

This module handles automatic upstream failover, response normalization, and structured output parsing.

```typescript
// File: src/lib/llm/resilient-router.ts
import OpenAI from "openai";
import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";

export const GenerationOutputSchema = z.object({
  analysis: z.string().min(10),
  suggestedActions: z.array(z.string().min(3)).max(5),
  confidenceScore: z.number().min(0).max(1),
  metadata: z.record(z.string(), z.unknown()),
});

export type GenerationOutput = z.infer<typeof GenerationOutputSchema>;

interface ExecutionContext {
  tenantId: string;
  requestId: string;
  prompt: string;
  systemContext: string;
}

export class ResilientLLMRouter {
  private openai: OpenAI;
  private anthropic: Anthropic;

  constructor() {
    this.openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY!, timeout: 3500 });
    this.anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY!, timeout: 4000 });
  }

  public async execute(context: ExecutionContext): Promise<{
    data: GenerationOutput;
    provider: "openai" | "anthropic" | "cache_fallback";
    latencyMs: number;
  }> {
    const startTime = performance.now();

    // 1. Primary Attempt: OpenAI Structured Outputs
    try {
      const response = await this.openai.beta.chat.completions.parse({
        model: "gpt-4o-2024-08-06",
        messages: [
          { role: "system", content: context.systemContext },
          { role: "user", content: context.prompt },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: "automation_output",
            strict: true,
            schema: {
              type: "object",
              properties: {
                analysis: { type: "string" },
                suggestedActions: { type: "array", items: { type: "string" } },
                confidenceScore: { type: "number" },
                metadata: { type: "object", additionalProperties: true },
              },
              required: ["analysis", "suggestedActions", "confidenceScore", "metadata"],
              additionalProperties: false,
            },
          },
        },
      });

      const parsed = response.choices[0]?.message.parsed;
      if (!parsed) throw new Error("NULL_OPENAI_RESPONSE_BODY");

      return {
        data: GenerationOutputSchema.parse(parsed),
        provider: "openai",
        latencyMs: Math.round(performance.now() - startTime),
      };
    } catch (primaryError: any) {
      console.warn(`[ROUTER_FAILOVER] Primary failed: ${primaryError.message}. Routing to Secondary.`);
    }

    // 2. Secondary Attempt: Anthropic Tool Use Fallback
    try {
      const toolSchema = {
        name: "record_automation_output",
        description: "Record structured output response from prompt execution",
        input_schema: {
          type: "object" as const,
          properties: {
            analysis: { type: "string" },
            suggestedActions: { type: "array", items: { type: "string" } },
            confidenceScore: { type: "number" },
            metadata: { type: "object" },
          },
          required: ["analysis", "suggestedActions", "confidenceScore", "metadata"],
        },
      };

      const response = await this.anthropic.messages.create({
        model: "claude-3-5-sonnet-20240620",
        max_tokens: 1024,
        system: context.systemContext,
        tools: [toolSchema],
        tool_choice: { type: "tool", name: "record_automation_output" },
        messages: [{ role: "user", content: context.prompt }],
      });

      const toolUseBlock = response.content.find((block) => block.type === "tool_use");
      if (!toolUseBlock || toolUseBlock.type !== "tool_use") {
        throw new Error("ANTHROPIC_FAILED_TOOL_CALL");
      }

      return {
        data: GenerationOutputSchema.parse(toolUseBlock.input),
        provider: "anthropic",
        latencyMs: Math.round(performance.now() - startTime),
      };
    } catch (secondaryError: any) {
      console.error(`[ROUTER_OUTAGE] Secondary failed: ${secondaryError.message}. Emitting fallback.`);
    }

    // 3. Graceful Deterministic Fallback
    return {
      data: {
        analysis: "Automated analysis temporarily unavailable due to upstream connectivity limits.",
        suggestedActions: ["Retry task manually", "Check platform status page"],
        confidenceScore: 0.0,
        metadata: { fallback: true, executionContext: context.requestId },
      },
      provider: "cache_fallback",
      latencyMs: Math.round(performance.now() - startTime),
    };
  }
}
```

---

## 2. PostgreSQL Multi-Tenant Schema with Hard RLS

This relational architecture enforces strict logical data isolation at the database layer using native PostgreSQL Row Level Security (RLS). Connection pooling (via PgBouncer/Supabase) is fully supported through transaction-scoped session configuration variables.

```
       ┌────────────────┐
       │ organizations  │
       └───────┬────────┘
               │ 1
               │
               │ N
       ┌───────┴────────┐          ┌────────────────┐
       │  memberships   │◄─────────┤     users      │
       └───────┬────────┘ N      1 └────────────────┘
               │
               │ Context: app.current_tenant_id
               ▼
┌──────────────────────────────┐
│  projects / resources / logs  │ ◄─── Enforced by PostgreSQL RLS
└──────────────────────────────┘
```

### 2.1 Complete DDL & RLS Migration Script

```sql
-- Migration: 001_core_multi_tenant_rls.sql
BEGIN;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "citext";

-- 1. Organizations (Tenants)
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug CITEXT UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    stripe_customer_id VARCHAR(255) UNIQUE,
    subscription_status VARCHAR(50) NOT NULL DEFAULT 'trialing',
    plan_tier VARCHAR(50) NOT NULL DEFAULT 'starter',
    max_seats INT NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_organizations_slug ON organizations (slug);
CREATE INDEX idx_organizations_stripe ON organizations (stripe_customer_id);

-- 2. Users (Global platform accounts)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email CITEXT UNIQUE NOT NULL,
    encrypted_password VARCHAR(255),
    full_name VARCHAR(255),
    is_superadmin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_users_email ON users (email);

-- 3. Tenant Memberships & RBAC
CREATE TYPE user_role AS ENUM ('owner', 'admin', 'member', 'viewer');

CREATE TABLE memberships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role user_role NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT uq_organization_user UNIQUE (organization_id, user_id)
);

CREATE INDEX idx_memberships_org_user ON memberships (organization_id, user_id);
CREATE INDEX idx_memberships_user ON memberships (user_id);

-- 4. Projects (Tenant-Scoped Resource)
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_projects_tenant ON projects (organization_id);
CREATE INDEX idx_projects_config_gin ON projects USING GIN (configuration);

-- 5. Audit Log (Append-Only Event Ledger)
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id UUID NOT NULL,
    ip_address INET,
    user_agent TEXT,
    changes JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_audit_logs_tenant_created ON audit_logs (organization_id, created_at DESC);

-- =========================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- =========================================================================

-- Enable RLS on Tenant-Isolated Tables
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Helper Function: Read active tenant from dynamic session configuration
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_tenant_id', true), '')::UUID;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Organizations Policy: Only visible if tenant matches current_tenant_id
CREATE POLICY tenant_isolation_organizations ON organizations
    FOR ALL
    USING (id = current_tenant_id());

-- Memberships Policy: Only visible if membership belongs to active tenant
CREATE POLICY tenant_isolation_memberships ON memberships
    FOR ALL
    USING (organization_id = current_tenant_id());

-- Projects Policy: Full isolation per active tenant context
CREATE POLICY tenant_isolation_projects ON projects
    FOR ALL
    USING (organization_id = current_tenant_id())
    WITH CHECK (organization_id = current_tenant_id());

-- Audit Logs Policy: Append-only by tenant, no client deletions
CREATE POLICY tenant_isolation_audit_logs_select ON audit_logs
    FOR SELECT
    USING (organization_id = current_tenant_id());

CREATE POLICY tenant_isolation_audit_logs_insert ON audit_logs
    FOR INSERT
    WITH CHECK (organization_id = current_tenant_id());

-- Auto-update timestamps trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = TIMEZONE('utc', NOW());
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER tr_organizations_updated_at BEFORE UPDATE ON organizations FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
CREATE TRIGGER tr_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
CREATE TRIGGER tr_memberships_updated_at BEFORE UPDATE ON memberships FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();
CREATE TRIGGER tr_projects_updated_at BEFORE UPDATE ON projects FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

COMMIT;
```

### 2.2 Application Connection Wrapper (Prisma & Raw pg)

Every query executed on behalf of a tenant must declare its context. Here is the transaction-safe execution wrapper:

```typescript
// File: src/lib/db/tenant-context.ts
import { Pool, PoolClient } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 20,
  idleTimeoutMillis: 30000,
});

export async function withTenantContext<T>(
  tenantId: string,
  callback: (client: PoolClient) => Promise<T>
): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    // Set transaction-local tenant context (prevents connection leak across pool reuses)
    await client.query(`SET LOCAL app.current_tenant_id = $1`, [tenantId]);
    
    const result = await callback(client);
    
    await client.query('COMMIT');
    return result;
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
```

---

## 3. Stripe Usage-Based Metered Billing Engine

### 3.1 Metering Schema Specification

The ledger uses optimistic concurrency control alongside an idempotent write log. Every metered execution is recorded locally first, then reported upstream via the Stripe Meter Events API.

```sql
-- Migration: 002_stripe_metering_ledger.sql
BEGIN;

CREATE TYPE meter_sync_status AS ENUM ('pending', 'delivered', 'failed', 'reconciled');

CREATE TABLE billing_usage_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    stripe_customer_id VARCHAR(255) NOT NULL,
    event_name VARCHAR(100) NOT NULL, -- matches Stripe Meter event_name (e.g. 'ai_pipeline_invocations')
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    quantity INT NOT NULL CHECK (quantity > 0),
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    sync_status meter_sync_status NOT NULL DEFAULT 'pending',
    stripe_event_id VARCHAR(255),
    error_message TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    synced_at TIMESTAMPTZ
);

CREATE INDEX idx_usage_sync_status ON billing_usage_events (sync_status) WHERE sync_status = 'pending';
CREATE INDEX idx_usage_customer_time ON billing_usage_events (stripe_customer_id, recorded_at);

COMMIT;
```

### 3.2 Production Usage Meter Service (TypeScript / Stripe v2 Meter API)

```typescript
// File: src/lib/billing/usage-meter.ts
import Stripe from 'stripe';
import { Pool } from 'pg';
import crypto from 'crypto';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2024-06-20',
  maxNetworkRetries: 3,
});

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

export interface MeterIngestRequest {
  organizationId: string;
  stripeCustomerId: string;
  meterEventName: string;
  quantity: number;
  properties?: Record<string, string | number>;
}

export class StripeMeterEngine {
  /**
   * Records usage locally and dispatches immediately to Stripe with an idempotency key.
   */
  public async recordUsage(entry: MeterIngestRequest): Promise<string> {
    const idempotencyKey = `meter_${entry.organizationId}_${Date.now()}_${crypto.randomBytes(8).toString('hex')}`;

    // 1. Write to local database ledger in PENDING state
    const insertQuery = `
      INSERT INTO billing_usage_events (
        organization_id,
        stripe_customer_id,
        event_name,
        idempotency_key,
        quantity,
        properties,
        sync_status
      ) VALUES ($1, $2, $3, $4, $5, $6, 'pending')
      RETURNING id;
    `;

    const result = await pool.query(insertQuery, [
      entry.organizationId,
      entry.stripeCustomerId,
      entry.meterEventName,
      idempotencyKey,
      entry.quantity,
      JSON.stringify(entry.properties || {}),
    ]);

    const localLedgerId = result.rows[0].id;

    // 2. Transmit to Stripe Meter Event API
    try {
      const meterEvent = await stripe.billing.meterEvents.create({
        event_name: entry.meterEventName,
        payload: {
          value: entry.quantity.toString(),
          stripe_customer_id: entry.stripeCustomerId,
        },
        identifier: idempotencyKey,
        timestamp: Math.floor(Date.now() / 1000),
      });

      // 3. Mark Ledger Record Delivered
      await pool.query(
        `UPDATE billing_usage_events 
         SET sync_status = 'delivered', 
             stripe_event_id = $1, 
             synced_at = NOW() 
         WHERE id = $2`,
        [meterEvent.identifier, localLedgerId]
      );

      return idempotencyKey;
    } catch (err: any) {
      console.error(`[METERING_ERROR] Delivery failed for ledger ID ${localLedgerId}:`, err);

      await pool.query(
        `UPDATE billing_usage_events 
         SET sync_status = 'failed', 
             error_message = $1, 
             retry_count = retry_count + 1 
         WHERE id = $2`,
        [err.message, localLedgerId]
      );

      throw err;
    }
  }

  /**
   * Replay processor invoked via cron to flush pending/failed meter events.
   */
  public async flushFailedEvents(batchLimit: number = 100): Promise<number> {
    const client = await pool.connect();
    let flushedCount = 0;

    try {
      const pendingEvents = await client.query(
        `SELECT * FROM billing_usage_events 
         WHERE sync_status IN ('pending', 'failed') 
           AND retry_count < 5 
         ORDER BY recorded_at ASC 
         LIMIT $1 FOR UPDATE SKIP LOCKED`,
        [batchLimit]
      );

      for (const row of pendingEvents.rows) {
        try {
          await stripe.billing.meterEvents.create({
            event_name: row.event_name,
            payload: {
              value: row.quantity.toString(),
              stripe_customer_id: row.stripe_customer_id,
            },
            identifier: row.idempotency_key,
            timestamp: Math.floor(new Date(row.recorded_at).getTime() / 1000),
          });

          await client.query(
            `UPDATE billing_usage_events 
             SET sync_status = 'delivered', synced_at = NOW(), error_message = NULL 
             WHERE id = $1`,
            [row.id]
          );

          flushedCount++;
        } catch (innerErr: any) {
          await client.query(
            `UPDATE billing_usage_events 
             SET retry_count = retry_count + 1, error_message = $1 
             WHERE id = $2`,
            [innerErr.message, row.id]
          );
        }
      }
    } finally {
      client.release();
    }

    return flushedCount;
  }
}
```

---

## 4. Production Webhook Security & Idempotency Handler

An enterprise-ready webhook endpoint must handle three failure modes:
1. Replay attacks with stale timestamps.
2. Timing attacks via string comparison.
3. Race conditions caused by concurrent webhook deliveries.

```
       [ HTTP POST /api/v1/webhooks/stripe ]
                         │
                         ▼
             [ Read Raw Body Buffer ]
                         │
                         ▼
        [ Check Header: stripe-signature ]
                         │
                         ▼
   [ Verify Tolerance Window: Math.abs(Now - T) <= 300s ]
                         │
                         ▼
        [ Crypto: timingSafeEqual HMAC-SHA256 ]
                         │
                         ├── (Mismatch / Expired) ──► [ REJECT 400 Bad Request ]
                         │
                         ▼
          [ BEGIN DB ISOLATION TX ]
                         │
                         ▼
     [ INSERT event_id INTO processed_webhooks ]
                         │
                         ├── (Conflict: 23505) ────► [ ACK 200 "Already Processed" ]
                         │
                         ▼
             [ PROCESS BUSINESS LOGIC ]
                         │
                         ├── (Exception) ──────────► [ ROLLBACK & RETURN 500 ]
                         │
                         ▼
            [ COMMIT TX & RETURN 200 ]
```

### 4.1 Webhook Storage Engine Schema

```sql
-- Migration: 003_webhook_idempotency.sql
BEGIN;

CREATE TABLE processed_webhooks (
    event_id VARCHAR(255) PRIMARY KEY,
    source VARCHAR(50) NOT NULL, -- e.g. 'stripe', 'clerk', 'github'
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_webhooks_processed_at ON processed_webhooks (processed_at);

COMMIT;
```

### 4.2 Webhook Security Handler (Next.js / Node Route)

```typescript
// File: src/app/api/webhooks/stripe/route.ts
import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';
import { Pool } from 'pg';

const pool = new Pool({ connectionString: process.env.DATABASE_URL });
const WEBHOOK_SECRET = process.env.STRIPE_WEBHOOK_SECRET!;
const TOLERANCE_SECONDS = 300; // 5-minute replay window

function verifyStripeSignature(rawBody: string, signatureHeader: string, secret: string): boolean {
  const parts = signatureHeader.split(',');
  let timestamp: string | null = null;
  const signatures: string[] = [];

  for (const part of parts) {
    const [key, value] = part.split('=');
    if (key === 't') timestamp = value;
    if (key === 'v1') signatures.push(value);
  }

  if (!timestamp || signatures.length === 0) {
    return false;
  }

  // Prevent Replay Attacks: Check timestamp freshness
  const now = Math.floor(Date.now() / 1000);
  const eventTime = parseInt(timestamp, 10);
  if (isNaN(eventTime) || Math.abs(now - eventTime) > TOLERANCE_SECONDS) {
    return false;
  }

  // Compute expected HMAC
  const signedPayload = `${timestamp}.${rawBody}`;
  const hmac = crypto.createHmac('sha256', secret);
  const expectedSignature = hmac.update(signedPayload).digest('hex');

  const expectedBuffer = Buffer.from(expectedSignature, 'utf8');

  // Constant-time string matching to neutralize timing attacks
  return signatures.some((sig) => {
    const sigBuffer = Buffer.from(sig, 'utf8');
    if (sigBuffer.length !== expectedBuffer.length) {
      return false;
    }
    return crypto.timingSafeEqual(sigBuffer, expectedBuffer);
  });
}

export async function POST(req: NextRequest) {
  const signature = req.headers.get('stripe-signature');
  if (!signature) {
    return NextResponse.json({ error: 'Missing stripe-signature header' }, { status: 400 });
  }

  const rawBody = await req.text();

  // 1. Signature Verification
  const isValid = verifyStripeSignature(rawBody, signature, WEBHOOK_SECRET);
  if (!isValid) {
    return NextResponse.json({ error: 'Invalid or expired signature' }, { status: 400 });
  }

  let event: { id: string; type: string; data: { object: any } };
  try {
    event = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ error: 'Malformed payload JSON' }, { status: 400 });
  }

  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // 2. Atomic Deduplication Lock via processed_webhooks
    const dedupeQuery = `
      INSERT INTO processed_webhooks (event_id, source, event_type, payload)
      VALUES ($1, 'stripe', $2, $3)
      ON CONFLICT (event_id) DO NOTHING
      RETURNING event_id;
    `;
    const dedupeRes = await client.query(dedupeQuery, [event.id, event.type, rawBody]);

    // If no row was inserted, this event was already ingested and processed
    if (dedupeRes.rowCount === 0) {
      await client.query('ROLLBACK');
      return NextResponse.json({ status: 'ignored', reason: 'duplicate_event' }, { status: 200 });
    }

    // 3. Deterministic Domain Logic Routing
    switch (event.type) {
      case 'customer.subscription.updated':
      case 'customer.subscription.deleted': {
        const subscription = event.data.object;
        await client.query(
          `UPDATE organizations 
           SET subscription_status = $1, updated_at = NOW() 
           WHERE stripe_customer_id = $2`,
          [subscription.status, subscription.customer]
        );
        break;
      }
      case 'invoice.payment_failed': {
        const invoice = event.data.object;
        await client.query(
          `UPDATE organizations 
           SET subscription_status = 'past_due', updated_at = NOW
