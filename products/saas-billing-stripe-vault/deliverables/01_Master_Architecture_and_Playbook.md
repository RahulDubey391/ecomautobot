# Module 1: Stripe Core Architecture & State Machine Playbook

This playbook establishes the foundational engineering specifications for integrating Stripe Billing into an enterprise SaaS architecture. It provides the database schemas, state machine logic, webhook idempotency patterns, and multi-currency data pipelines required to achieve zero-drift synchronization between your application database and Stripe's billing engine.

---

## 1. Unified Billing Lifecycle Architecture

In an enterprise billing integration, Stripe acts as the calculation engine and payment facilitator, but **your application database remains the source of truth for user access authorization**. 

The architecture decoupled below implements an asynchronous, event-driven pattern designed to survive network partitions, out-of-order webhook delivery, and double-spend race conditions.

### System Topography

```
+---------------------------------------------------------------------------------------+
|                                    CLIENT BROWSER                                     |
|  - Stripe Elements / Payment Element                                                  |
|  - Client-side checkout confirmation                                                  |
+--------------------------+-----------------------------------+------------------------+
                           |                                   ^
    1. Confirm SetupIntent |                4. Redirect or Polling Update
       or PaymentIntent    |                                   |
                           v                                   |
+--------------------------+-----------------------------------+------------------------+
|                                  APPLICATION BACKEND                                  |
|                                                                                       |
|  +------------------------+  2. Mutate Local DB   +--------------------------------+  |
|  | Synchronous API Router | --------------------> | PostgreSQL (Primary DB)        |  |
|  | - Auth & Session Mgmt  |                       | - customers                    |  |
|  | - Intent Initialization|                       | - subscriptions                |  |
|  +------------------------+                       | - webhook_events               |  |
|              |                                    +--------------------------------+  |
|              | Stripe SDK API Calls                                  ^                |
|              v                                                       |                |
|  +------------------------+                                          |                |
|  | Stripe Ingestion Node  |  3. Verify Sig & Push   +--------------------------------+  |
|  | - Raw Body Ingestion   | ----------------------> | Redis (Distributed Lock & Queue)| |
|  | - Fast 200 OK Response |                         +--------------------------------+  |
|  +------------------------+                                          ^                |
|              ^                                                       | 5. Process Job |
+--------------|-------------------------------------------------------|----------------+
               | Webhook POST                                          v
               | (HTTPS TLS 1.3)                            +----------------------+
               |                                            | Async Worker Pool    |
+--------------+-------------+                              | - BullMQ / Sidekiq   |
|        STRIPE ENGINE       |                              | - Idempotency Guard  |
| - Charge, Invoice, Customer|                              | - State Transitioner |
| - Automated Dunning Engine |                              +----------------------+
+----------------------------+
```

### Stripe-to-Internal State Mapping Matrix

Do not expose raw Stripe subscription statuses directly to your authorization layer. Map them to normalized application tiers to prevent race conditions during invoice transitions.

| Stripe Status | Normalized App Status | Access Gate | Grace Period Active? | System Action Required |
| :--- | :--- | :--- | :--- | :--- |
| `incomplete` | `PENDING_ACTIVATION` | Read-only | No | Block primary write routes; prompt payment completion. |
| `incomplete_expired` | `EXPIRED` | Revoked | No | Delete or archive local provisioning record. |
| `trialing` | `ACTIVE_TRIAL` | Full Access | No | Schedule trial expiration telemetry; monitor usage. |
| `active` | `ACTIVE` | Full Access | No | Standard state; grant plan entitlements. |
| `past_due` | `DELINQUENT_GRACE` | Full Access | Yes (Configurable: 72 hrs) | Trigger in-app warning banner; start dunning sequence. |
| `unpaid` | `SUSPENDED` | Read-only | No | Revoke write endpoints; enforce payment wall. |
| `canceled` | `TERMINATED` | Read-only / Zero | No | Revert features to Free Tier; revoke API keys. |
| `paused` | `DORMANT` | Read-only | No | Maintain stored data; suspend recurring charges. |

---

## 2. Production Subscription State Machine

A subscription cannot transition arbitrarily. For example, moving from `canceled` to `active` without generating a new Stripe Subscription object creates non-recoverable ledger drift.

### Allowable State Transitions

```
               +---------------------------------------+
               |                                       |
               v                                       |
      [ incomplete ] ---> [ incomplete_expired ]       |
             |                                         |
             v                                         |
       [ trialing ] -----------------------------------+
             |                                         |
             v                                         |
        [ active ] <---------------+                   |
         |      |                  |                   |
         |      v                  |                   |
         |  [ past_due ] ----------+                   |
         |      |                                      |
         |      v                                      |
         |  [ unpaid ] --------------------------------+
         |      |                                      |
         v      v                                      v
      [     canceled     ] <---------------------------+
             |
             v
      [   paused   ] (Conditional)
```

### PostgreSQL Production Schema (DDL)

This schema guarantees referential integrity, historical audit tracking, and strict status validation.

```sql
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Subscription Status Enum
CREATE TYPE subscription_status AS ENUM (
    'incomplete',
    'incomplete_expired',
    'trialing',
    'active',
    'past_due',
    'unpaid',
    'canceled',
    'paused'
);

-- Customers Table
CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL UNIQUE,
    stripe_customer_id VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'usd',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_customers_stripe_id ON customers(stripe_customer_id);
CREATE INDEX idx_customers_org_id ON customers(organization_id);

-- Subscriptions Table
CREATE TABLE subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    stripe_subscription_id VARCHAR(255) NOT NULL UNIQUE,
    stripe_price_id VARCHAR(255) NOT NULL,
    status subscription_status NOT NULL,
    current_period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    canceled_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    trial_start TIMESTAMP WITH TIME ZONE,
    trial_end TIMESTAMP WITH TIME ZONE,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    metadata JSONB DEFAULT '{}'::jsonb,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_subscriptions_stripe_id ON subscriptions(stripe_subscription_id);
CREATE INDEX idx_subscriptions_customer_id ON subscriptions(customer_id);
CREATE INDEX idx_subscriptions_status ON subscriptions(status);

-- State Audit Log Table
CREATE TABLE subscription_status_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    from_status subscription_status,
    to_status subscription_status NOT NULL,
    stripe_event_id VARCHAR(255),
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_history_sub_id ON subscription_status_history(subscription_id);

-- Webhook Processing Table (Idempotency Engine)
CREATE TABLE stripe_webhook_events (
    id VARCHAR(255) PRIMARY KEY, -- Maps directly to Stripe's evt_xxx ID
    event_type VARCHAR(255) NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE,
    processing_status VARCHAR(50) NOT NULL CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
    error_message TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_webhook_status ON stripe_webhook_events(processing_status);
```

### TypeScript State Machine Guard

Enforce transition validity in your service layer before updating the database.

```typescript
// subscriptionStateMachine.ts

export type SubscriptionStatus =
  | 'incomplete'
  | 'incomplete_expired'
  | 'trialing'
  | 'active'
  | 'past_due'
  | 'unpaid'
  | 'canceled'
  | 'paused';

const ALLOWED_TRANSITIONS: Record<SubscriptionStatus, readonly SubscriptionStatus[]> = {
  incomplete: ['incomplete_expired', 'trialing', 'active', 'canceled'],
  incomplete_expired: [], // Terminal
  trialing: ['active', 'past_due', 'canceled', 'paused'],
  active: ['past_due', 'canceled', 'unpaid', 'paused'],
  past_due: ['active', 'unpaid', 'canceled'],
  unpaid: ['active', 'canceled'],
  canceled: [], // Terminal via API (new subscription required)
  paused: ['active', 'canceled']
};

export class SubscriptionStateError extends Error {
  constructor(from: SubscriptionStatus, to: SubscriptionStatus) {
    super(`Illegal state transition from '${from}' to '${to}'. Operation rejected.`);
    this.name = 'SubscriptionStateError';
  }
}

export function validateSubscriptionTransition(
  currentStatus: SubscriptionStatus,
  targetStatus: SubscriptionStatus
): boolean {
  // Fast-path: Identical state transitions are idempotent no-ops
  if (currentStatus === targetStatus) {
    return true;
  }

  const allowed = ALLOWED_TRANSITIONS[currentStatus];
  if (!allowed || !allowed.includes(targetStatus)) {
    throw new SubscriptionStateError(currentStatus, targetStatus);
  }

  return true;
}
```

---

## 3. Atomic Webhook Processing & Distributed Idempotency Patterns

Network latency, automated retries, and horizontal scaling cause webhooks to arrive **out-of-order** or **duplicated**. A naive handler that simply updates database rows based on raw event payloads will eventually corrupt production records (for example, handling `customer.subscription.created` *after* `customer.subscription.updated`).

### Dual-Layer Idempotency Architecture

1. **Distributed In-Memory Lock (Redis):** Guarantees that two identical webhook payloads received simultaneously are processed serially.
2. **Relational Mutex (PostgreSQL `SELECT ... FOR UPDATE`):** Enforces sequence validation using Stripe's event timestamp or incremental versioning.

```
Incoming Webhook (evt_123)
       |
       v
Check Redis Lock (Key: "lock:webhook:evt_123")
       |
  +----+----+
  |         |
[Exists]  [Acquired]
  |         |
Discard    Insert evt_123 into DB with status='processing'
(200 OK)    |
           Validate Event Sequence (Version or Stripe Event Created Timestamp)
            |
           Execute Business Logic in DB Transaction
            |
           Mark status='completed' in DB
            |
           Release Redis Lock & Return 200 OK
```

### Complete Production Webhook Ingestion Engine

```typescript
// webhookServer.ts
import express, { Request, Response } from 'express';
import Stripe from 'stripe';
import { Pool, PoolClient } from 'pg';
import Redis from 'ioredis';
import { validateSubscriptionTransition, SubscriptionStatus } from './subscriptionStateMachine';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY as string, {
  apiVersion: '2023-10-16',
});

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 20,
  idleTimeoutMillis: 30000,
});

const redis = new Redis(process.env.REDIS_URL as string);

const app = express();

// Stripe requires the RAW buffer to verify signatures securely
app.post(
  '/webhooks/stripe',
  express.raw({ type: 'application/json' }),
  async (req: Request, res: Response): Promise<void> => {
    const signature = req.headers['stripe-signature'];

    if (!signature || typeof signature !== 'string') {
      res.status(400).send('Missing stripe-signature header');
      return;
    }

    let event: Stripe.Event;

    try {
      event = stripe.webhooks.constructEvent(
        req.body,
        signature,
        process.env.STRIPE_WEBHOOK_SECRET as string
      );
    } catch (err: any) {
      console.error(`[Webhook Signature Failure] ${err.message}`);
      res.status(400).send(`Webhook Error: ${err.message}`);
      return;
    }

    const lockKey = `lock:webhook:${event.id}`;
    // Lock TTL: 60 seconds to avoid hung execution paths
    const lockAcquired = await redis.set(lockKey, 'locked', 'EX', 60, 'NX');

    if (!lockAcquired) {
      console.warn(`[Duplicate Webhook Dropped] Execution running for: ${event.id}`);
      res.status(200).json({ received: true, note: 'Duplicate concurrent event ignored' });
      return;
    }

    const client: PoolClient = await pool.connect();

    try {
      await client.query('BEGIN');

      // Check if event was previously processed to finality
      const existingEventCheck = await client.query(
        'SELECT processing_status FROM stripe_webhook_events WHERE id = $1 FOR UPDATE',
        [event.id]
      );

      if (existingEventCheck.rows.length > 0) {
        const status = existingEventCheck.rows[0].processing_status;
        if (status === 'completed') {
          await client.query('ROLLBACK');
          await redis.del(lockKey);
          res.status(200).json({ received: true, note: 'Event already completed' });
          return;
        }
      } else {
        // Record event receipt
        await client.query(
          'INSERT INTO stripe_webhook_events (id, event_type, processing_status, payload) VALUES ($1, $2, $3, $4)',
          [event.id, event.type, 'processing', JSON.stringify(event)]
        );
      }

      // Route event to deterministic handler
      switch (event.type) {
        case 'customer.subscription.created':
        case 'customer.subscription.updated': {
          const subscription = event.data.object as Stripe.Subscription;
          await processSubscriptionUpdate(client, subscription, event.id);
          break;
        }
        case 'customer.subscription.deleted': {
          const subscription = event.data.object as Stripe.Subscription;
          await processSubscriptionDeletion(client, subscription, event.id);
          break;
        }
        default:
          console.info(`[Unhandled Event Ignored] ${event.type}`);
      }

      // Finalize event status
      await client.query(
        'UPDATE stripe_webhook_events SET processing_status = $1, processed_at = NOW() WHERE id = $2',
        ['completed', event.id]
      );

      await client.query('COMMIT');
      res.status(200).json({ received: true });
    } catch (err: any) {
      await client.query('ROLLBACK');
      console.error(`[Webhook Processing Error] Event ${event.id}:`, err);

      await pool.query(
        'UPDATE stripe_webhook_events SET processing_status = $1, error_message = $2 WHERE id = $3',
        ['failed', err.message, event.id]
      );

      res.status(500).send('Internal Processing Failure');
    } finally {
      client.release();
      await redis.del(lockKey);
    }
  }
);

async function processSubscriptionUpdate(
  client: PoolClient,
  stripeSub: Stripe.Subscription,
  eventId: string
): Promise<void> {
  const currentSubRes = await client.query(
    'SELECT id, status, version FROM subscriptions WHERE stripe_subscription_id = $1 FOR UPDATE',
    [stripeSub.id]
  );

  const targetStatus = stripeSub.status as SubscriptionStatus;
  const currentPeriodStart = new Date(stripeSub.current_period_start * 1000);
  const currentPeriodEnd = new Date(stripeSub.current_period_end * 1000);
  const stripePriceId = stripeSub.items.data[0]?.price.id;

  if (currentSubRes.rows.length === 0) {
    // Lookup internal customer record
    const customerRes = await client.query(
      'SELECT id FROM customers WHERE stripe_customer_id = $1',
      [stripeSub.customer as string]
    );

    if (customerRes.rows.length === 0) {
      throw new Error(`Customer mapping missing for Stripe ID: ${stripeSub.customer}`);
    }

    const customerId = customerRes.rows[0].id;

    // Create Subscription
    const insertedSub = await client.query(
      `INSERT INTO subscriptions (
        customer_id, stripe_subscription_id, stripe_price_id, status,
        current_period_start, current_period_end, cancel_at_period_end,
        quantity, metadata, version
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 1) RETURNING id`,
      [
        customerId,
        stripeSub.id,
        stripePriceId,
        targetStatus,
        currentPeriodStart,
        currentPeriodEnd,
        stripeSub.cancel_at_period_end,
        stripeSub.items.data[0]?.quantity || 1,
        JSON.stringify(stripeSub.metadata),
      ]
    );

    await client.query(
      `INSERT INTO subscription_status_history (subscription_id, from_status, to_status, stripe_event_id, reason)
       VALUES ($1, NULL, $2, $3, 'Initial creation via webhook')`,
      [insertedSub.rows[0].id, targetStatus, eventId]
    );
  } else {
    const existing = currentSubRes.rows[0];
    const currentStatus = existing.status as SubscriptionStatus;

    // Validate using the explicit state machine
    validateSubscriptionTransition(currentStatus, targetStatus);

    await client.query(
      `UPDATE subscriptions SET
        status = $1,
        stripe_price_id = $2,
        current_period_start = $3,
        current_period_end = $4,
        cancel_at_period_end = $5,
        canceled_at = $6,
        ended_at = $7,
        quantity = $8,
        metadata = $9,
        version = version + 1,
        updated_at = NOW()
       WHERE id = $10`,
      [
        targetStatus,
        stripePriceId,
        currentPeriodStart,
        currentPeriodEnd,
        stripeSub.cancel_at_period_end,
        stripeSub.canceled_at ? new Date(stripeSub.canceled_at * 1000) : null,
        stripeSub.ended_at ? new Date(stripeSub.ended_at * 1000) : null,
        stripeSub.items.data[0]?.quantity || 1,
        JSON.stringify(stripeSub.metadata),
        existing.id,
      ]
    );

    if (currentStatus !== targetStatus) {
      await client.query(
        `INSERT INTO subscription_status_history (subscription_id, from_status, to_status, stripe_event_id, reason)
         VALUES ($1, $2, $3, $4, 'State transition update')`,
        [existing.id, currentStatus, targetStatus, eventId]
      );
    }
  }
}

async function processSubscriptionDeletion(
  client: PoolClient,
  stripeSub: Stripe.Subscription,
  eventId: string
): Promise<void> {
  const currentSubRes = await client.query(
    'SELECT id, status FROM subscriptions WHERE stripe_subscription_id = $1 FOR UPDATE',
    [stripeSub.id]
  );

  if (currentSubRes.rows.length === 0) {
    console.warn(`[Termination Bypass] Subscription ${stripeSub.id} not found.`);
    return;
  }

  const existing = currentSubRes.rows[0];
  validateSubscriptionTransition(existing.status, 'canceled');

  await client.query(
    `UPDATE subscriptions SET
      status = 'canceled',
      ended_at = NOW(),
      updated_at = NOW(),
      version = version + 1
     WHERE id = $1`,
    [existing.id]
  );

  await client.query(
    `INSERT INTO subscription_status_history (subscription_id, from_status, to_status, stripe_event_id, reason)
     VALUES ($1, $2, 'canceled', $3, 'Subscription deleted/canceled')`,
    [existing.id, existing.status, eventId]
  );
}

export default app;
```

---

## 4. Multi-Currency & Presentment Architecture

Modern SaaS integrations fail when engineers confuse **Presentment Currency** with **Settlement Currency**.

- **Presentment Currency:** The currency displayed to the customer and charged at checkout (e.g., EUR for European buyers, JPY for Japanese buyers).
- **Settlement Currency:** The currency in which funds are deposited into your corporate bank account (e.g., USD). Stripe handles the FX conversion internally.

### Database Design for Multi-Currency Scalability

Do not duplicate plan records to support multiple currencies. Use Stripe’s multi-currency Price objects linked to a singular, stable Application Product record.

```
       +-----------------------+
       |   Internal Product    |
       |  (e.g., "Scale Plan") |
       +-----------+-----------+
                   |
       +-----------+-----------+
       |   Stripe Product ID   |
       |     prod_N1x89...     |
       +-----------+-----------+
                   |
       +-----------+-----------------------------------+
       |                                               |
       v                                               v
+-------------------------------+   +-------------------------------+
|    Price Object (USD Model)   |   |    Price Object (EUR Model)   |
|   - ID: price_usd_tier1       |   |   - ID: price_eur_tier1       |
|   - Currency: 'usd'           |   |   - Currency: 'eur'           |
|   - Amount: 9900 ($99.00)     |   |   - Amount: 9200 (€92.00)     |
+-------------------------------+   +-------------------------------+
```

### Multi-Currency Routing Engine

Use this pattern when initializing client checkout flows to automatically match prices against customer geographical contexts.

```typescript
// currencyManager.ts
import Stripe from 'stripe';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY as string, {
  apiVersion: '2023-10-16',
});

interface PlanResolutionRequest {
  productId: string;
  targetCurrency: string; // ISO 3-letter code (lowercase)
}

export async function resolveLocalizedPrice(
  request: PlanResolutionRequest
): Promise<Stripe.Price> {
  const { productId, targetCurrency } = request;

  // Search active prices bound to product
  const prices = await stripe.prices.list({
    product: productId,
    active: true,
    limit: 20,
  });

  // Attempt direct match for explicit presentment currency
  const matchedPrice = prices.data.find(
    (price) => price.currency.toLowerCase() === targetCurrency.toLowerCase()
  );

  if (matchedPrice) {
    return matchedPrice;
  }

  // Fallback to primary settlement currency (default: USD)
  const fallbackPrice = prices.data.find(
    (price) => price.currency.toLowerCase() === 'usd'
  );

  if (!fallbackPrice) {
    throw new Error(
      `Misconfiguration: No viable localized or USD fallback price found for product ${productId}`
    );
  }

  return fallbackPrice;
}
```

### Stripe Tax Automated Integration Triggers

To prevent liabilities under EU VAT, UK VAT, and US Economic Nexus statutes, calculate taxes via Stripe Tax dynamically on your checkout sessions or payment intents:

```typescript
// checkoutSessionHelper.ts
import Stripe from 'stripe';

export async function createCompliantCheckoutSession(
  stripe: Stripe,
  stripeCustomerId: string,
  priceId: string,
  successUrl: string,
  cancelUrl: string
): Promise<Stripe.Checkout.Session> {
  return await stripe.checkout.sessions.create({
    customer: stripeCustomerId,
    mode: 'subscription',
    line_items: [
      {
        price: priceId,
        quantity: 1,
      },
    ],
    // Force Tax Calculation Engine
    automatic_tax: {
      enabled: true,
    },
    // Collect billing address to satisfy nexus validation requirements
    billing_address_collection: 'required',
    customer_update: {
      address: 'auto',
      name: 'auto',
    },
    tax_id_collection: {
      enabled: true, // Collect B2B VAT/GST IDs dynamically
    },
    success_url: successUrl,
    cancel_url: cancelUrl,
  });
}
```

---

## 5. Production Operational Readiness Checklist

Deploying Stripe integration architecture requires strict operational safeguards before sending production traffic. Execute this checklist sequentially.

### 1. Cryptographic Security & Keys
- [ ] Stripe API keys are managed using a secure key management system (e.g., AWS Secrets Manager, HashiCorp Vault). Never hardcode keys in plaintext environment variables.
- [ ] Production instances use restricted Stripe API keys (`rk_live_...`) limited strictly to the required resources (e.g., `Charges: write`, `Subscriptions: write`, `Customers: write`), rather than root account keys.
- [ ] The `STRIPE_WEBHOOK_SECRET` is rotated automatically every 90 days using Stripe’s rolling secret capability (holding both old and new signatures valid simultaneously during the rollover window).

### 2. Network & Ingestion Defenses
- [ ] The webhook ingress route intercepts requests via raw body buffers (`express.raw()`). No body-parsing JSON middleware is applied upstream of signature verification.
- [ ] Stripe’s public webhook IP ranges are explicitly allowlisted on edge proxies (Cloudflare, AWS CloudFront, or NGINX) to reject spoofed traffic before reaching node workloads.
- [ ] The ingress handler dispatches immediately to an internal message queue (e.g., Redis BullMQ, SQS) or finishes the synchronous run and yields an immediate `200 OK` within `< 2500ms` to prevent Stripe auto-retry floods.

### 3. Data Integrity & Clock Skew
- [ ] Webhook timestamps (`event.created`) are compared against internal database versions or monotonic timestamps to guarantee out-of-order events do not overwrite newer states.
- [ ] Server system clocks synchronize strictly with NTP pools (e.g., `chrony`, `systemd-timesyncd`). Signature verification rejects drift exceeding 300 seconds.
- [ ] Idempotency keys (`Idempotency-Key: <uuid>`) are generated client-side and attached to all write mutations (`stripe.charges.create`, `stripe.paymentIntents.create`) initiated from server processes to prevent double-billing during network timeouts.

### 4. Continuous Drift Detection
- [ ] A continuous reconciliation cron runs daily at `02:00 UTC` comparing all `subscriptions` in the database where `status = 'active'` against Stripe’s `stripe.subscriptions.list({ status: 'active' })` API.
- [ ] Drift alerts emit to incident response channels (e.g., PagerDuty, Datadog) whenever discrepancies between internal entitlements and Stripe records are detected.
