# Module 1: The Micro-SaaS Architectural Framework & Product Scoping Matrix

---

## 1. The Micro-SaaS Idea Qualification Engine (The 4-Pillar Scorecard)

Before committing a single line of code, every software concept must pass the **Micro-SaaS Viability Index (MSVI)**. A viable Micro-SaaS is not an enterprise platform; it is a hyper-focused utility that solves an acute, monetization-ready operational pain point for a clearly defined cohort.

### The MSVI Quantitative Formula

$$MSVI = (Pain \times 0.35) + (Distribution \times 0.25) + (TechnicalVelocity \times 0.20) + (Margin \times 0.20)$$

Each dimension is scored on an integer scale from **1 to 10**. A project must achieve a minimum cumulative score of **7.5 / 10** (75/100) with no individual category falling below **6** to be cleared for production.

```
+----------------------------------------------------------------------------------------------------+
|                                    MSVI EVALUATION MATRIX                                          |
+-------------------+----------------------------------------------------------+---------------------+
| Dimension         | 1-3 (Fatal)              | 4-6 (Marginal)                | 7-10 (Elite)        |
+-------------------+----------------------------------------------------------+---------------------+
| Pain Severity     | "Nice to have";          | Saves intermittent time;      | Halts revenue,      |
| (Weight: 35%)     | novelty utility.         | user can live without it.     | compliance risk,    |
|                   |                          |                               | or breaks workflow. |
+-------------------+----------------------------------------------------------+---------------------+
| Distribution Edge | Cold email to generic    | SEO with KD > 50; saturated   | Owned programmatic  |
| (Weight: 25%)     | audiences; ad-dependent. | directories; generic social.  | loop; niche API repo|
|                   |                          |                               | platform ecosystem. |
+-------------------+----------------------------------------------------------+---------------------+
| Tech Velocity     | Requires multi-model AI, | Custom infra, WebSockets,     | Standard CRUD/API;  |
| (Weight: 20%)     | custom hardware, or heavy| multi-tenant complex DB,      | Ship MVP in < 72    |
|                   | compliance (HIPAA).      | 2-3 week build.               | dev hours.          |
+-------------------+----------------------------------------------------------+---------------------+
| Gross Margin      | High third-party API     | < 75% gross margin; manual    | > 90% gross margin; |
| (Weight: 20%)     | costs (LLM token drain)  | onboarding or data curation   | fully automated     |
|                   | eating > 40% MRR.        | required.                     | self-serve compute. |
+-------------------+----------------------------------------------------------+---------------------+
```

### Automatic Disqualification Rules ("The Redlines")

Regardless of the composite score, instantly abort the project if any of the following apply:
1. **The $29/mo Enterprise Trap**: The product targets mid-market/enterprise buyers requiring SOC2 Type II, SSO (SAML/Okta), and custom procurement cycles, but is priced under $500/month.
2. **The Passive Platform Risk**: The core value proposition relies 100% on an undocumented or hostile third-party API (e.g., scraping LinkedIn or Meta platforms without partner-level API agreements).
3. **High-Frequency Support Overhead**: The product targets non-technical consumers (B2C) where ticket volume exceeds 0.05 tickets per monthly active user (MAU).

---

## 2. The Production Stack Decision Matrix

A solo developer or small team cannot afford infrastructural fragmentation. Every layer of the stack must minimize operational maintenance, prevent vendor lock-in traps, and ensure zero-downtime scaling up to $50,000 MRR on auto-pilot.

### Core Stack Trade-off Matrix

| Layer | Recommended Default | Alternative Option | Selection Criteria | Trade-Offs & Constraints |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend & SSR** | **Next.js 15 (App Router)** | Remix / Vite SPA | Dynamic SEO needs, dashboard complexity, React ecosystem maturity. | High framework churn; Server Actions require strict boundary discipline. |
| **Database & Auth** | **Supabase (PostgreSQL)** | Neon + Clerk | Native Row-Level Security (RLS), auto-generated PostgREST, built-in Auth/Storage. | Direct connection pooling must use Supavisor/PgBouncer to prevent exhaust. |
| **Compute / API Engine** | **Cloudflare Workers** | Fastify on Railway/Fly.io | Low-latency edge execution, static cost model, zero cold-starts. | Fastify is required if running long-lived background jobs (>30s) or Docker runtimes. |
| **Billing & Metering** | **Stripe Billing** | Lemon Squeezy / Paddle | Direct merchant of record, custom metered usage, Stripe Apps ecosystem. | Merchant of Record (MoR) setups like Lemon Squeezy needed if VAT handling is out of scope. |

### Architectural Flow Diagram

```
[ Client Application (Next.js 15 App Router) ]
                     |
       +-------------+-------------+
       |                           |
  (Auth / RLS)               (Edge API Calls)
       |                           |
       v                           v
[ Supabase PostgreSQL ]    [ Cloudflare Worker / Fastify ]
  - Row Level Security       - Heavy compute / webhooks
  - Extensions: pgvector     - Rate limiting (Upstash Redis)
  - Supavisor Connection     - Background task queuing
       ^                           |
       |                           v
       +------------------- [ Stripe Billing API ]
                            (Webhooks / Metering)
```

---

## 3. Production Foundation Configs & Schemas

### 3.1 Production Environment Definition (`.env.example`)

Copy and paste this environment blueprint to ensure parity between local, preview, and production environments:

```bash
# --- APP CONFIGURATION ---
NODE_ENV="production"
NEXT_PUBLIC_APP_URL="https://app.yourdomain.com"
NEXT_PUBLIC_API_URL="https://api.yourdomain.com"

# --- DATABASE (SUPABASE POSTGRESQL POOLED) ---
DATABASE_URL="postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?pgbouncer=true"
DIRECT_URL="postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres"

# --- SUPABASE AUTH & API ---
NEXT_PUBLIC_SUPABASE_URL="https://[PROJECT-REF].supabase.co"
NEXT_PUBLIC_SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
SUPABASE_SERVICE_ROLE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# --- STRIPE BILLING INFRASTRUCTURE ---
STRIPE_SECRET_KEY="sk_live_..."
STRIPE_WEBHOOK_SECRET="whsec_..."
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY="pk_live_..."
STRIPE_PRO_MONTHLY_PRICE_ID="price_..."
STRIPE_PRO_YEARLY_PRICE_ID="price_..."

# --- CACHING & RATE LIMITING (UPSTASH) ---
UPSTASH_REDIS_REST_URL="https://[REGION].upstash.io"
UPSTASH_REDIS_REST_TOKEN="AX..."

# --- LOGGING & TELEMETRY ---
NEXT_PUBLIC_SENTRY_DSN="https://...@ingest.sentry.io/..."
```

---

### 3.2 Canonical Supabase SQL Schema with Row-Level Security (RLS)

This schema handles users, multitenant organizations, customer subscription state synchronization via Stripe, and audit logging. Run this migration directly in the Supabase SQL editor:

```sql
-- Enable necessary extensions
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- Enum for subscription state tracking
create type subscription_status as enum (
  'trialing',
  'active',
  'canceled',
  'incomplete',
  'incomplete_expired',
  'past_due',
  'unpaid'
);

-- Profiles Table (Linked directly to Supabase Auth)
create table public.profiles (
  id uuid references auth.users on delete cascade primary key,
  email text not null unique,
  full_name text,
  avatar_url text,
  stripe_customer_id text unique,
  created_at timestamptz default timezone('utc'::text, now()) not null,
  updated_at timestamptz default timezone('utc'::text, now()) not null
);

-- Subscriptions Table
create table public.subscriptions (
  id text primary key, -- stripe subscription ID
  user_id uuid references public.profiles(id) on delete cascade not null,
  status subscription_status not null,
  price_id text not null,
  quantity integer default 1,
  cancel_at_period_end boolean default false not null,
  current_period_start timestamptz not null,
  current_period_end timestamptz not null,
  created_at timestamptz default timezone('utc'::text, now()) not null,
  updated_at timestamptz default timezone('utc'::text, now()) not null
);

-- Workspaces / Tenants Table
create table public.workspaces (
  id uuid default gen_random_uuid() primary key,
  name text not null,
  slug text not null unique,
  owner_id uuid references public.profiles(id) on delete cascade not null,
  created_at timestamptz default timezone('utc'::text, now()) not null
);

-- Workspace Members Join Table
create table public.workspace_members (
  workspace_id uuid references public.workspaces(id) on delete cascade not null,
  user_id uuid references public.profiles(id) on delete cascade not null,
  role text check (role in ('owner', 'admin', 'member')) not null default 'member',
  primary key (workspace_id, user_id)
);

-- Enable RLS
alter table public.profiles enable row level security;
alter table public.subscriptions enable row level security;
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;

-- ROW LEVEL SECURITY POLICIES

-- Profiles: Users can view and update only their own profile
create policy "Users can view own profile" 
  on public.profiles for select 
  using (auth.uid() = id);

create policy "Users can update own profile" 
  on public.profiles for update 
  using (auth.uid() = id);

-- Subscriptions: Users can read their own billing records
create policy "Users can view own subscriptions" 
  on public.subscriptions for select 
  using (auth.uid() = user_id);

-- Workspaces: Members can view workspaces they belong to
create policy "Members can view their workspaces" 
  on public.workspaces for select 
  using (
    exists (
      select 1 from public.workspace_members
      where workspace_members.workspace_id = workspaces.id
      and workspace_members.user_id = auth.uid()
    )
  );

-- Workspace Members: Scoped read access
create policy "Members can view workspace rosters" 
  on public.workspace_members for select 
  using (
    exists (
      select 1 from public.workspace_members as self
      where self.workspace_id = workspace_members.workspace_id
      and self.user_id = auth.uid()
    )
  );

-- Profile provisioning webhook trigger from auth.users
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    new.email,
    new.raw_user_meta_data->>'full_name',
    new.raw_user_meta_data->>'avatar_url'
  );
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
```

---

### 3.3 Fastify Production Engine with Zod & Raw Stripe Webhook Processing

When offloading high-throughput operations from Next.js, this Fastify engine guarantees predictable latency, automatic input validation, and secure webhook verification.

```typescript
// server.ts
import Fastify, { FastifyInstance } from 'fastify';
import rawBody from 'fastify-raw-body';
import { z } from 'zod';
import Stripe from 'stripe';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY as string, {
  apiVersion: '2024-06-20',
});

const app: FastifyInstance = Fastify({
  logger: {
    level: process.env.NODE_ENV === 'production' ? 'info' : 'debug',
  },
});

// Register raw body plugin for cryptographic webhook validation
await app.register(rawBody, {
  field: 'rawBody',
  global: false,
  encoding: 'utf8',
  runFirst: true,
});

// Schema Definitions
const IngestionPayloadSchema = z.object({
  workspaceId: z.string().uuid(),
  event: z.string().min(1).max(64),
  metadata: z.record(z.any()),
});

// Type derivation
type IngestionPayload = z.infer<typeof IngestionPayloadSchema>;

// Authenticated Business Logic Route
app.post<{ Body: IngestionPayload }>(
  '/v1/telemetry/ingest',
  async (request, reply) => {
    const parseResult = IngestionPayloadSchema.safeParse(request.body);

    if (!parseResult.success) {
      return reply.status(400).send({
        error: 'INVALID_PAYLOAD',
        details: parseResult.error.flatten(),
      });
    }

    const { workspaceId, event, metadata } = parseResult.data;

    // Process ingestion (e.g., publish to queue, save to analytics database)
    request.log.info({ workspaceId, event }, 'Event successfully ingested');

    return reply.status(202).send({ status: 'queued', id: crypto.randomUUID() });
  }
);

// High-Security Stripe Webhook Endpoint
app.post(
  '/webhooks/stripe',
  { config: { rawBody: true } },
  async (request, reply) => {
    const signature = request.headers['stripe-signature'];

    if (!signature || typeof signature !== 'string') {
      return reply.status(400).send({ error: 'Missing stripe-signature header' });
    }

    let event: Stripe.Event;

    try {
      event = stripe.webhooks.constructEvent(
        request.rawBody as string,
        signature,
        process.env.STRIPE_WEBHOOK_SECRET as string
      );
    } catch (err: any) {
      request.log.error(`Webhook signature verification failed: ${err.message}`);
      return reply.status(400).send({ error: `Webhook Error: ${err.message}` });
    }

    switch (event.type) {
      case 'customer.subscription.updated':
      case 'customer.subscription.deleted': {
        const subscription = event.data.object as Stripe.Subscription;
        request.log.info(`Syncing subscription: ${subscription.id}`);
        // Database update logic implemented here
        break;
      }
      default:
        request.log.warn(`Unhandled event type: ${event.type}`);
    }

    return reply.status(200).send({ received: true });
  }
);

const start = async () => {
  try {
    const port = Number(process.env.PORT) || 8080;
    await app.listen({ port, host: '0.0.0.0' });
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

start();
```

---

## 4. The 1-Page Production PRD Formula

*Execution Rule: A specification document must never exceed the bounds of what can be designed, implemented, and tested in under 14 calendar days. If a feature does not directly support conversion, retention, or core value delivery, it is deferred.*

### 1-Page PRD Blueprint: "SyncPulse" (Real-World Reference Implementation)

#### 1. Core Problem & User Persona
* **Target ICP**: Technical Founders and DevRel Leads operating open-source ecosystems.
* **Pain Point**: Missing critical user bug reports and customer feature requests across GitHub Issues, Discord servers, and Discourse forums.
* **Quantified Loss**: 6-12 hours per week spent manually triaging community channels; critical enterprise churn caused by unresolved platform bugs lost in chat noise.

#### 2. The Single Value Loop (MVP Scope)
1. User connects GitHub Org and Discord Bot via OAuth.
2. System ingests messages from `#support` and `#feedback` channels.
3. Edge classifier runs intent-detection: ignores noise, maps bugs/features directly into structured GitHub Issues with automatic labeling.
4. Alerts the workspace owner via daily email summary.

#### 3. Out-of-Scope (Strict Non-Goals)
* No real-time bi-directional Slack messaging (Discord & GitHub only).
* No native ticket-management system (GitHub Issues is the system of record).
* No multi-tier enterprise roles (flat role permissions: Owner & Member only).

#### 4. Complete API & Data Surface Area

```
POST /api/v1/integrations/discord/install   -> Authorize and store Discord bot credentials.
POST /api/v1/integrations/github/install    -> Authorize GitHub App, bind to workspace.
GET  /api/v1/rules                          -> List active AI classification rules.
POST /api/v1/rules                          -> Set trigger thresholds and target repos.
POST /api/v1/webhooks/discord               -> Ingest payload, pass to Upstash queue.
```

```
Table: sync_rules
- id: uuid (PK)
- workspace_id: uuid (FK -> workspaces.id)
- discord_channel_id: text
- target_github_repo: text
- confidence_threshold: numeric (default: 0.85)
- is_active: boolean (default: true)
- created_at: timestamptz
```

#### 5. Metering, Pricing, & Paywalls
* **Hobby Tier ($0/month)**: 1 Discord Channel, 1 GitHub Repo, 100 classifications/month.
* **Pro Tier ($49/month)**: Unlimited channels, 5 GitHub Repos, 5,000 classifications/month.
* **Paywall Enforcement**: When monthly usage reaches 100% of allocation, edge proxy returns HTTP 402 with code `PAYMENT_REQUIRED`, intercepting inbound webhook payloads until the plan is upgraded via Stripe Checkout.

---

## 5. The "Spec-to-Code" Autonomous Development System Prompt

Use this system prompt in Claude 3.5 Sonnet, GPT-4o, or your IDE's coding assistant (Cursor/Windsurf) to reliably transform the 1-page PRD into clean, deployable code while avoiding common LLM anti-patterns (such as invent-your-own auth, missing RLS, or untested mocks).

```markdown
You are an elite Staff Software Engineer and Solo Technical Founder specializing in TypeScript, Next.js 15 (App Router), Supabase (PostgreSQL), and Tailwind CSS.

### YOUR MANDATE:
Generate production-ready, fully functional code based on the provided Product Requirements Document (PRD). Every file must be complete. NEVER emit code containing placeholder comments like `// implement later`, `// add your logic here`, or ellipses (`...`).

### ARCHITECTURAL STANDARDS:
1. Modern Next.js Framework:
   - Use App Router patterns with React Server Components (RSC) where possible.
   - Use Server Actions for mutations; validate all inputs using Zod schemas.
   - Separate data access logic from UI rendering.

2. Database and Security:
   - All Supabase queries must run with authenticated user contexts respecting Row-Level Security (RLS).
   - Never bypass RLS in client-facing endpoints. Do not use the `SUPABASE_SERVICE_ROLE_KEY` except in secure background webhooks or system jobs.
   - Write explicit SQL migrations with full types, constraints, and indices.

3. Type Safety and Error Handling:
   - Provide strict TypeScript declarations without using `any`.
   - Implement robust error boundaries, structured HTTP status codes, and JSON response envelopes matching:
     Success: { "success": true, "data": T }
     Failure: { "success": false, "error": { "code": string, "message": string, "details"?: any } }

4. UI & Styling:
   - Use Tailwind CSS with clean, modern UI patterns (inspired by shadcn/ui).
   - Ensure complete state coverage for every view: Loading, Empty, Error, and Populated.

### EXECUTION SEQUENCE:
When a PRD is provided, construct the software in this exact sequence:
1. SQL Migrations (Tables, Foreign Keys, Indexes, RLS Policies, Triggers).
2. Zod Validation Schemas and TypeScript Domain Interfaces.
3. Data Access Layer / Server Actions with input validation and authentication checks.
4. API Routes / Webhook Handlers (with signature verification).
5. Frontend Pages, Server Components, and UI Forms with loading states.

Acknowledge these instructions and await the PRD.
```

---

## 6. Micro-SaaS Execution & Launch Checklist

Use this operational checklist to execute the launch lifecycle from blank IDE to the first dollar of recurring revenue.

### Phase 1: Qualification & Data Model Validation
- [ ] Calculate MSVI score. Document validation signals confirming score is $\ge 7.5$.
- [ ] Identify 10 potential users and confirm pain severity via direct interviews or observable online activity.
- [ ] Finalize the 1-Page PRD. Explicitly list out-of-scope items to prevent scope creep.
- [ ] Draft database schema (PostgreSQL) and verify foreign keys, cascading deletes, and RLS rules.

### Phase 2: Core Engineering & Infrastructure Scaffolding
- [ ] Initialize Next.js 15 repository with TypeScript, Tailwind CSS, and standard linters.
- [ ] Configure Supabase project, execute initial migrations, and verify RLS policies using local test users.
- [ ] Implement authentication flow (OAuth + Magic Link) and link auth identities to profile tables via database triggers.
- [ ] Build the core "Single Value Loop" feature set.
- [ ] Connect Stripe Billing:
  - [ ] Configure customer portal.
  - [ ] Set up webhook endpoint for `customer.subscription.*` events.
  - [ ] Implement paywall check in middleware or server actions.

### Phase 3: Launch Readiness & Hardening
- [ ] Set up error tracking (Sentry) and business analytics (PostHog).
- [ ] Set up rate-limiting on all public endpoints using Upstash Redis.
- [ ] Verify raw body parsing and cryptographic signature checking on all external webhooks.
- [ ] Run production end-to-end user tests: Registration $\rightarrow$ Free Tier Usage $\rightarrow$ Upgrade Trigger $\rightarrow$ Stripe Checkout $\rightarrow$ Webhook Provisioning $\rightarrow$ Paid Feature Unlocked.
- [ ] Confirm zero TypeScript warnings and successful build: `npm run build`.
- [ ] Point custom domain, configure DNS records (DKIM, SPF, DMARC), and deploy to production infrastructure.
