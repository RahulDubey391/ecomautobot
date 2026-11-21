# Module 3: Edge Functions, Background Jobs & Realtime Sync Pipelines

This module provides production-ready implementations for asynchronous processing, external integrations, and real-time state synchronization in multi-tenant Supabase architectures. You will deploy secure webhook endpoints, decouple transactional database operations from slow third-party APIs using native PostgreSQL networking extensions, manage distributed message queues, and enforce tenant isolation across WebSocket subscriptions.

---

## 1. Production Deno TypeScript Webhook Verification Engine

Third-party webhooks are an attack vector for replay attacks and tenant impersonation. This implementation processes Stripe subscription events, verifies the cryptographic signature using standard Web Crypto primitives, and guarantees exactly-once processing using an atomic idempotency ledger in PostgreSQL.

### 1.1 Database Schema: Idempotency & Webhook Audit Ledger

Execute this migration to establish the audit trail and deduplication barrier:

```sql
-- Migration: 20240301000001_create_webhook_idempotency.sql

create table if not exists public.webhook_idempotency (
    event_id text primary key,
    provider text not null,
    tenant_id uuid references public.tenants(id) on delete cascade,
    event_type text not null,
    status text not null check (status in ('processing', 'processed', 'failed')),
    payload jsonb not null,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Index for operational monitoring and stale-job detection
create index idx_webhook_idempotency_tenant_status 
on public.webhook_idempotency(tenant_id, status);

create index idx_webhook_idempotency_created 
on public.webhook_idempotency(created_at desc);

-- Enable RLS: Webhook ledger is strictly inaccessible to client roles
alter table public.webhook_idempotency enable row level security;

-- Only service_role can read or write to this ledger
create policy "Service role manages webhook ledger"
on public.webhook_idempotency
for all
to service_role
using (true)
with check (true);
```

### 1.2 Edge Function: Cryptographic Signature Verification & Pipeline

Deploy this Edge Function to `supabase/functions/stripe-webhook/index.ts`. It reads raw request bytes for HMAC-SHA256 signature verification, claims the event ID atomically in the database, and processes subscription changes within the correct tenant scope.

```typescript
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";
import Stripe from "https://esm.sh/stripe@15.10.0?target=deno";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") ?? "", {
  apiVersion: "2024-04-10",
  httpClient: Stripe.createFetchHttpClient(),
});

const cryptoProvider = Stripe.createSubtleCryptoProvider();

serve(async (req: Request): Promise<Response> => {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  const signature = req.headers.get("stripe-signature");
  const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET");

  if (!signature || !webhookSecret) {
    return new Response(
      JSON.stringify({ error: "Missing signature or webhook secret configuration" }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    );
  }

  const rawBody = await req.text();
  let event: Stripe.Event;

  try {
    event = await stripe.webhooks.constructEventAsync(
      rawBody,
      signature,
      webhookSecret,
      undefined,
      cryptoProvider
    );
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Signature verification failed";
    return new Response(JSON.stringify({ error: `Webhook Error: ${message}` }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Initialize service_role client to bypass RLS for ledger checks and cross-tenant lookups
  const supabaseAdmin = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
      },
    }
  );

  // Attempt atomic ledger insertion to lock the event
  const { error: insertError } = await supabaseAdmin
    .from("webhook_idempotency")
    .insert({
      event_id: event.id,
      provider: "stripe",
      event_type: event.type,
      status: "processing",
      payload: event.data.object,
    });

  if (insertError) {
    // Unique violation (Postgres error 23505) indicates duplicate event delivery
    if (insertError.code === "23505") {
      return new Response(
        JSON.stringify({ received: true, deduplicated: true }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    return new Response(
      JSON.stringify({ error: "Failed to persist event receipt ledger" }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }

  try {
    switch (event.type) {
      case "customer.subscription.created":
      case "customer.subscription.updated": {
        const subscription = event.data.object as Stripe.Subscription;
        await handleSubscriptionSync(supabaseAdmin, subscription, event.id);
        break;
      }
      case "customer.subscription.deleted": {
        const subscription = event.data.object as Stripe.Subscription;
        await handleSubscriptionCancellation(supabaseAdmin, subscription, event.id);
        break;
      }
      default:
        // Mark unhandled events as processed to avoid redelivery loops
        await supabaseAdmin
          .from("webhook_idempotency")
          .update({ status: "processed", updated_at: new Date().toISOString() })
          .eq("event_id", event.id);
    }

    return new Response(JSON.stringify({ received: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Internal processing error";
    
    // Record explicit failure state for dead-letter processing
    await supabaseAdmin
      .from("webhook_idempotency")
      .update({
        status: "failed",
        error_message: message,
        updated_at: new Date().toISOString(),
      })
      .eq("event_id", event.id);

    return new Response(
      JSON.stringify({ error: "Processing failed", details: message }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
});

async function handleSubscriptionSync(
  supabase: any,
  subscription: Stripe.Subscription,
  eventId: string
) {
  const customerId = typeof subscription.customer === "string" 
    ? subscription.customer 
    : subscription.customer.id;

  // Retrieve tenant ID mapped to Stripe Customer ID
  const { data: tenant, error: tenantError } = await supabase
    .from("tenants")
    .select("id")
    .eq("stripe_customer_id", customerId)
    .single();

  if (tenantError || !tenant) {
    throw new Error(`Tenant resolution failure for Stripe Customer: ${customerId}`);
  }

  const priceId = subscription.items.data[0]?.price.id;
  const status = subscription.status;
  const currentPeriodEnd = new Date(subscription.current_period_end * 1000).toISOString();

  // Update subscription data and attach tenant_id to the idempotency record
  const { error: updateTenantError } = await supabase
    .from("tenants")
    .update({
      subscription_status: status,
      subscription_plan_id: priceId,
      current_period_end: currentPeriodEnd,
      updated_at: new Date().toISOString(),
    })
    .eq("id", tenant.id);

  if (updateTenantError) {
    throw new Error(`Tenant update failed: ${updateTenantError.message}`);
  }

  await supabase
    .from("webhook_idempotency")
    .update({
      tenant_id: tenant.id,
      status: "processed",
      updated_at: new Date().toISOString(),
    })
    .eq("event_id", eventId);
}

async function handleSubscriptionCancellation(
  supabase: any,
  subscription: Stripe.Subscription,
  eventId: string
) {
  const customerId = typeof subscription.customer === "string" 
    ? subscription.customer 
    : subscription.customer.id;

  const { data: tenant, error: tenantError } = await supabase
    .from("tenants")
    .select("id")
    .eq("stripe_customer_id", customerId)
    .single();

  if (tenantError || !tenant) {
    throw new Error(`Tenant resolution failure for Stripe Customer: ${customerId}`);
  }

  await supabase
    .from("tenants")
    .update({
      subscription_status: "canceled",
      updated_at: new Date().toISOString(),
    })
    .eq("id", tenant.id);

  await supabase
    .from("webhook_idempotency")
    .update({
      tenant_id: tenant.id,
      status: "processed",
      updated_at: new Date().toISOString(),
    })
    .eq("event_id", eventId);
}
```

---

## 2. The `pg_net` + `pg_cron` Asynchronous Dispatch Pattern

Directly calling external APIs (e.g., Slack notifications, customer webhooks, CRM sync) inside PostgreSQL triggers creates blocking transactions, connection pool exhaustion, and vulnerability to network latency. The `pg_net` extension decouples operations by executing non-blocking HTTP requests directly from the database engine.

```
+-------------------------------------------------------------------------------+
|                           DATABASE TRANSACTION BOUNDARY                       |
|                                                                               |
|   1. Mutation Event         2. Trigger Execution       3. Enqueue Webhook     |
|   +------------------+      +-------------------+      +------------------+   |
|   | UPDATE projects  | ---> | on_project_update | ---> | INSERT INTO      |   |
|   | SET status='done'|      +-------------------+      | webhook_outbox   |   |
|   +------------------+                                 +------------------+   |
+------------------------------------------------------------------|------------+
                                                                   |
                                              Cron Poll: Every 10s | (pg_cron)
                                                                   v
+-------------------------------------------------------------------------------+
|                            pg_net ASYNCHRONOUS ENGINE                         |
|                                                                               |
|   6. Result Ingestion       5. HTTP POST Request       4. Outbox Worker       |
|   +------------------+      +-------------------+      +------------------+   |
|   | UPDATE outbox    | <--- | External Server   | <--- | net.http_post()  |   |
|   | SET status='sent'|      | (Tenant Endpoint) |      | (Non-blocking)   |   |
|   +------------------+      +-------------------+      +------------------+   |
+-------------------------------------------------------------------------------+
```

### 2.1 Outbox & Dead Letter Queue (DLQ) Schema

This schema implements the Transactional Outbox pattern with retry budgets and exponential backoff tracking:

```sql
-- Migration: 20240301000002_pg_net_outbox_queue.sql

create extension if not exists "pg_net" with schema extensions;
create extension if not exists "pg_cron" with schema extensions;

create table if not exists public.webhook_outbox (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id) on delete cascade,
    destination_url text not null,
    event_type text not null,
    payload jsonb not null,
    headers jsonb not null default '{}'::jsonb,
    status text not null default 'pending' check (status in ('pending', 'processing', 'delivered', 'failed', 'dead_letter')),
    attempts int not null default 0,
    max_attempts int not null default 5,
    next_retry_at timestamptz not null default now(),
    last_error text,
    pg_net_request_id bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_webhook_outbox_processing 
on public.webhook_outbox(status, next_retry_at) 
where status in ('pending', 'processing');

create index idx_webhook_outbox_tenant 
on public.webhook_outbox(tenant_id, created_at desc);

alter table public.webhook_outbox enable row level security;

-- Client applications cannot view or alter transactional outbox records
create policy "Service role outbox access only"
on public.webhook_outbox
for all
to service_role
using (true)
with check (true);
```

### 2.2 Trigger Function: Enqueueing Outbound Webhooks

When an audited domain event occurs, the record is placed into the outbox within the same database transaction:

```sql
create or replace function public.enqueue_tenant_event_webhook()
returns trigger
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
    v_target_url text;
    v_payload jsonb;
begin
    -- Extract tenant's registered webhook URL from configuration table
    select webhook_url into v_target_url
    from public.tenant_configurations
    where tenant_id = new.tenant_id;

    if v_target_url is not null then
        v_payload := jsonb_build_object(
            'event', TG_ARGV[0],
            'table', TG_TABLE_NAME,
            'schema', TG_TABLE_SCHEMA,
            'record', row_to_json(new),
            'timestamp', extract(epoch from now())
        );

        insert into public.webhook_outbox (
            tenant_id,
            destination_url,
            event_type,
            payload,
            headers
        ) values (
            new.tenant_id,
            v_target_url,
            TG_ARGV[0],
            v_payload,
            jsonb_build_object(
                'Content-Type', 'application/json',
                'X-Tenant-Signature', encode(hmac(v_payload::text, 'hardened-tenant-secret', 'sha256'), 'hex')
            )
        );
    end if;

    return new;
end;
$$;
```

### 2.3 Dispatch Worker Function via `pg_net`

The dispatch worker processes pending outbox events, fires non-blocking HTTP requests, stores the asynchronous request handle (`net_request_id`), and schedules exponential backoff retries:

```sql
create or replace function public.dispatch_outbox_webhooks()
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
    r record;
    v_request_id bigint;
begin
    -- Row-level locking ensures parallel cron workers do not duplicate dispatches
    for r in
        select id, tenant_id, destination_url, headers, payload, attempts
        from public.webhook_outbox
        where status in ('pending', 'failed')
          and next_retry_at <= now()
          and attempts < max_attempts
        order by next_retry_at asc
        limit 50
        for update skip locked
    loop
        begin
            -- Fire asynchronous HTTP POST using pg_net
            select net.http_post(
                url := r.destination_url,
                body := r.payload,
                headers := r.headers::jsonb,
                timeout_milliseconds := 5000
            ) into v_request_id;

            update public.webhook_outbox
            set status = 'processing',
                attempts = attempts + 1,
                pg_net_request_id = v_request_id,
                updated_at = now()
            where id = r.id;

        exception when others then
            -- Handle network interface failures inside the engine
            update public.webhook_outbox
            set status = case when attempts + 1 >= max_attempts then 'dead_letter' else 'failed' end,
                attempts = attempts + 1,
                last_error = SQLERRM,
                next_retry_at = now() + (power(2, attempts + 1) * interval '30 seconds'),
                updated_at = now()
            where id = r.id;
        end;
    end loop;
end;
$$;
```

### 2.4 Asynchronous Response Reconciliation Engine

`pg_net` processes HTTP requests outside the SQL engine thread. This cron worker reconciles HTTP statuses from `net._http_response` back into the outbox:

```sql
create or replace function public.reconcile_pg_net_responses()
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
    r record;
begin
    for r in
        select 
            o.id,
            o.attempts,
            o.max_attempts,
            resp.status_code,
            resp.error_msg
        from public.webhook_outbox o
        join net._http_response resp on o.pg_net_request_id = resp.id
        where o.status = 'processing'
    loop
        if r.status_code >= 200 and r.status_code < 300 then
            update public.webhook_outbox
            set status = 'delivered',
                updated_at = now()
            where id = r.id;
        else
            update public.webhook_outbox
            set status = case when r.attempts >= r.max_attempts then 'dead_letter' else 'failed' end,
                last_error = coalesce(r.error_msg, 'HTTP Status: ' || r.status_code::text),
                next_retry_at = now() + (power(2, r.attempts) * interval '60 seconds'),
                updated_at = now()
            where id = r.id;
        end if;
    end loop;
end;
$$;

-- Schedule outbox processing every 10 seconds via pg_cron
select cron.schedule(
    'process-webhook-outbox',
    '10 seconds',
    'select public.dispatch_outbox_webhooks();'
);

-- Schedule reconciliation sweep every 30 seconds
select cron.schedule(
    'reconcile-webhook-responses',
    '30 seconds',
    'select public.reconcile_pg_net_responses();'
);
```

---

## 3. High-Throughput Event Processing with Supabase Queues (`pgmq`)

When workloads require strictly managed queues with visibility timeouts, guaranteed ordering, and multi-consumer concurrency, use the Postgres Message Queue (`pgmq`) extension.

### 3.1 Initializing Tenant Queue Topologies

Run this initialization pattern to establish dedicated tenant queues or a partitioned global message bus:

```sql
-- Migration: 20240301000003_pgmq_initialization.sql

create extension if not exists "pgmq" with schema extensions;

-- Establish a shared multi-tenant queue
select pgmq.create('tenant_data_sync_queue');

-- Create an audit table for tracking failed, expired, or archived messages
create table if not exists public.queue_dead_letters (
    id bigserial primary key,
    queue_name text not null,
    msg_id bigint not null,
    tenant_id uuid not null references public.tenants(id) on delete cascade,
    read_ct int not null,
    enqueued_at timestamptz not null,
    payload jsonb not null,
    diagnostic_context text not null,
    archived_at timestamptz not null default now()
);

alter table public.queue_dead_letters enable row level security;
create policy "Service role dead-letter access" on public.queue_dead_letters
for all to service_role using (true) with check (true);
```

### 3.2 SQL Producer Interface

Enqueuing events strictly enforces the inclusion of `tenant_id` to maintain data isolation across consuming workers:

```sql
create or replace function public.enqueue_tenant_task(
    p_tenant_id uuid,
    p_task_type text,
    p_parameters jsonb
)
returns bigint
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
    v_message_id bigint;
    v_message jsonb;
begin
    -- Validate tenant existence and status
    if not exists (
        select 1 from public.tenants 
        where id = p_tenant_id and subscription_status in ('active', 'trialing')
    ) then
        raise exception 'Tenant % is inactive or does not exist', p_tenant_id;
    end if;

    v_message := jsonb_build_object(
        'tenant_id', p_tenant_id,
        'task_type', p_task_type,
        'parameters', p_parameters,
        'enqueued_at', extract(epoch from now())
    );

    -- Send message with a default visibility delay of 0 seconds
    select pgmq.send(
        queue_name := 'tenant_data_sync_queue',
        msg := v_message,
        delay := 0
    ) into v_message_id;

    return v_message_id;
end;
$$;
```

### 3.3 Batch Processing Deno Edge Function Worker

This consumer function runs on an automated schedule (via HTTP trigger or external monitor), processing messages in batches with visibility timeout enforcement:

```typescript
// supabase/functions/queue-consumer/index.ts

import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.43.4";

interface QueueMessagePayload {
  tenant_id: string;
  task_type: string;
  parameters: Record<string, unknown>;
  enqueued_at: number;
}

interface PgmqMessage {
  msg_id: number;
  read_ct: number;
  enqueued_at: string;
  vt: string;
  message: QueueMessagePayload;
}

serve(async (req: Request): Promise<Response> => {
  // Enforce administrative bearer authorization
  const authHeader = req.headers.get("Authorization");
  const expectedSecret = Deno.env.get("CRON_SECRET");

  if (!authHeader || authHeader !== `Bearer ${expectedSecret}`) {
    return new Response(JSON.stringify({ error: "Unauthorized worker invocation" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    { auth: { persistSession: false, autoRefreshToken: false } }
  );

  const BATCH_SIZE = 25;
  const VISIBILITY_TIMEOUT_SECONDS = 60;
  const MAX_RETRIES = 3;

  // Read a batch of messages from the queue with an active visibility timeout
  const { data: messages, error: readError } = await supabase.rpc(
    "pgmq_read_batch_wrapper",
    {
      p_queue_name: "tenant_data_sync_queue",
      p_visibility_time: VISIBILITY_TIMEOUT_SECONDS,
      p_qty: BATCH_SIZE,
    }
  );

  if (readError) {
    return new Response(JSON.stringify({ error: readError.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!messages || messages.length === 0) {
    return new Response(JSON.stringify({ status: "idle", processed: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  const processingResults = await Promise.allSettled(
    messages.map(async (rawMsg: PgmqMessage) => {
      const { msg_id, read_ct, message } = rawMsg;

      // Handle poison pill messages exceeding retry budget
      if (read_ct > MAX_RETRIES) {
        await handlePoisonPill(supabase, rawMsg, "Retry budget exceeded");
        return { msg_id, status: "dead_lettered" };
      }

      // Execute tenant-isolated task
      await processTenantTask(supabase, message);

      // Successfully processed: Delete message from the queue
      const { error: archiveError } = await supabase.rpc("pgmq_delete_wrapper", {
        p_queue_name: "tenant_data_sync_queue",
        p_msg_id: msg_id,
      });

      if (archiveError) {
        throw new Error(`Failed to delete message ${msg_id}: ${archiveError.message}`);
      }

      return { msg_id, status: "acknowledged" };
    })
  );

  return new Response(
    JSON.stringify({
      status: "completed",
      batch_size: messages.length,
      results: processingResults,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } }
  );
});

async function processTenantTask(supabase: any, payload: QueueMessagePayload) {
  const { tenant_id, task_type, parameters } = payload;

  switch (task_type) {
    case "AGGREGATE_METRICS": {
      const { error } = await supabase.rpc("calculate_tenant_aggregates", {
        p_tenant_id: tenant_id,
        p_start_date: parameters.start_date,
      });
      if (error) throw error;
      break;
    }
    case "PURGE_EXPIRED_SESSIONS": {
      const { error } = await supabase
        .from("tenant_user_sessions")
        .delete()
        .eq("tenant_id", tenant_id)
        .lt("expires_at", new Date().toISOString());
      if (error) throw error;
      break;
    }
    default:
      throw new Error(`Unrecognized task type: ${task_type}`);
  }
}

async function handlePoisonPill(
  supabase: any,
  rawMsg: PgmqMessage,
  reason: string
) {
  // Move to dead letters audit table
  await supabase.from("queue_dead_letters").insert({
    queue_name: "tenant_data_sync_queue",
    msg_id: rawMsg.msg_id,
    tenant_id: rawMsg.message.tenant_id,
    read_ct: rawMsg.read_ct,
    enqueued_at: rawMsg.enqueued_at,
    payload: rawMsg.message,
    diagnostic_context: reason,
  });

  // Remove from processing queue to unblock workers
  await supabase.rpc("pgmq_delete_wrapper", {
    p_queue_name: "tenant_data_sync_queue",
    p_msg_id: rawMsg.msg_id,
  });
}
```

### 3.4 SQL RPC Wrappers for pgmq Function Access

Edge Functions cannot directly invoke pgmq extension commands without schema-qualified security definer wrappers:

```sql
create or replace function public.pgmq_read_batch_wrapper(
    p_queue_name text,
    p_visibility_time int,
    p_qty int
)
returns table (
    msg_id bigint,
    read_ct int,
    enqueued_at timestamptz,
    vt timestamptz,
    message jsonb
)
language plpgsql
security definer
set search_path = extensions, public
as $$
begin
    return query select * from pgmq.read(p_queue_name, p_visibility_time, p_qty);
end;
$$;

create or replace function public.pgmq_delete_wrapper(
    p_queue_name text,
    p_msg_id bigint
)
returns boolean
language plpgsql
security definer
set search_path = extensions, public
as $$
begin
    return pgmq.delete(p_queue_name, p_msg_id);
end;
$$;
```

---

## 4. Multi-Tenant Realtime Presence & Broadcast Sync Engine

Cross-tenant data exposure over WebSockets occurs when clients subscribe to unscoped topics, or when authorization tokens fail to enforce tenant boundaries during WebSocket handshakes. The following architecture secures Realtime channels through custom claims and row-level authorization.

```
       +---------------------------------------------------------+
       |               FRONTEND CLIENT INSTANCE                  |
       |  (User: alice@tenant-corp.com | Tenant: 'tenant-corp')  |
       +---------------------------------------------------------+
                                    |
          1. Connect with JWT       |  Channel Subscription Request:
             (tenant_id claim)      |  "room:tenant-corp:doc-8812"
                                    v
       +---------------------------------------------------------+
       |                SUPABASE REALTIME ENGINE                 |
       +---------------------------------------------------------+
                                    |
          2. Execute Handshake RLS  |  SELECT check on:
             Validation             |  public.tenant_realtime_channel_access
                                    v
       +---------------------------------------------------------+
       |                 POSTGRESQL VALIDATION                   |
