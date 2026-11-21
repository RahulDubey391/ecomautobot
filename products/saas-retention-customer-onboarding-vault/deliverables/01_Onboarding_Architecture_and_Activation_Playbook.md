# Module 1: The Core Activation Framework & Product-Led Onboarding

User onboarding is not a UX tour, a product walkthrough, or a sequence of tooltips designed to point out interface chrome. It is an algorithmic path to value realization. 

If a user signs up for your SaaS and fails to reach the core value proposition within their first session, your 30-day retention curve collapses asymptotically toward zero. This module provides the operational frameworks, database schemas, instrumentation queries, and UX architectures required to compress Time-to-Value (TTV) to under 180 seconds, engineer predictable "AHA" moments, and implement progressive profiling engines that maximize conversion without introducing cognitive fatigue.

---

## 1. The Mathematical Engine of User Activation

Activation must be treated as a mathematical state change, not a subjective sentiment. A user is activated if and only if they complete a deterministic sequence of actions correlated with long-term retention at a statistically significant threshold ($p < 0.01$).

### The Activation Triad

Activation comprises three distinct chronological milestones:

```
[ Signup ] ──> ( Setup Moment ) ──> ( AHA Moment ) ──> ( Habit Moment ) ──> [ Retained ]
```

1. **The Setup Moment (Operational Threshold):** The minimum baseline configuration required for the product to function (e.g., inviting 1 teammate, installing an npm package, uploading a single CSV, pointing a DNS record).
2. **The AHA Moment (Cognitive Threshold):** The precise emotional and intellectual inflection point where the user first extracts the core utility promise of the software (e.g., seeing their first live error trace in Datadog, reading an AI-generated summary of their own database, seeing a live Figma cursor).
3. **The Habit Moment (Behavioral Threshold):** The establishment of an organic re-engagement frequency within the natural usage cycle (e.g., creating 3 documents per week for 3 consecutive weeks; querying an analytics dashboard every morning at 09:00).

### Diagnostic Benchmarks Across SaaS Archetypes

| SaaS Archetype | Setup Moment | AHA Moment | Habit Moment | Target Median TTV |
| :--- | :--- | :--- | :--- | :--- |
| **B2B Infrastructure / DevTool** | API Key generation & SDK initialization | First ingest event visible in debugger UI | $\ge 500$ production calls/day across 7 days | $< 180$ seconds |
| **Productivity / Work Management** | Workspace created + 1 integration linked | First task completed or first doc shared | $\ge 3$ active days/week for 2 consecutive weeks | $< 120$ seconds |
| **Data Analytics / BI** | Data source connected (DB or CSV) | First chart render answering a specific query | $\ge 2$ dashboards shared or exported/week | $< 300$ seconds |
| **FinTech / Billing** | Stripe/Plaid connection or KYC check | First invoice generated or payout cleared | Recurring weekly reconciliation cycle | $< 600$ seconds |
| **Marketing Automation / CRM** | Contact list import or tracking pixel setup | First campaign sent to $> 10$ recipients | Automated workflow triggered $> 3\times$/week | $< 420$ seconds |

---

## 2. Zero-Friction Signup & Progressive Profiling Architectures

The conventional wisdom that "fewer fields equal higher conversion" is incomplete. Low friction at signup that results in a generic, non-personalized empty state merely shifts friction into the core application, where drop-offs are permanent.

The objective is to eliminate **Extraneous Physical Friction** (e.g., unnecessary password confirmations, reCAPTCHAs, legacy select boxes) while deliberately introducing **Strategic Cognitive Alignment** (profiling questions that immediately customize the application workspace).

### Friction Audit Framework

```
Total Session Friction = Cognitive Load (Decisions) + Physical Load (Keystrokes/Clicks) - Perceived Imminent Value
```

If `Perceived Imminent Value` falls below the combined load at any point before the AHA moment, the tab is closed.

### Database Architecture: Schema for Stateful Onboarding

To prevent users from becoming trapped in broken onboarding loops across devices or encountering repetitive modals, onboarding state must be decoupled from generic user attributes and persisted in an immutable telemetry table alongside a dynamic state machine.

```sql
-- DDL for PostgreSQL / Supabase
CREATE TYPE onboarding_step_status AS ENUM ('pending', 'in_progress', 'completed', 'skipped', 'failed');

CREATE TABLE public.workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) DEFAULT 'member' NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE public.onboarding_states (
    user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    persona_role VARCHAR(100),
    team_size_bracket VARCHAR(50),
    primary_use_case VARCHAR(100),
    current_step VARCHAR(100) NOT NULL DEFAULT 'workspace_init',
    completed_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_activated BOOLEAN NOT NULL DEFAULT FALSE,
    activated_at TIMESTAMPTZ,
    time_to_value_seconds INTEGER,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE public.onboarding_telemetry_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    step_name VARCHAR(100) NOT NULL,
    action onboarding_step_status NOT NULL,
    time_spent_ms INTEGER,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_telemetry_user_step ON public.onboarding_telemetry_events(user_id, step_name);
```

### The 3-Step Progressive Profiling Engine

Never ask for information you can infer from the user's domain, IP, or behavior. Collect profile data progressively across logical usage checkpoints:

```
Step 1: Identity & Authentication (Email + OAuth only)
            │
            ▼
Step 2: Intent Mapping (Select 1 of 3 concrete outcomes)
            │
            ▼
Step 3: Immediate Workspace Pre-Population (No blank slate)
```

#### Production React/Next.js Dynamic Profiling Component

This component runs entirely on the client, hydrates the onboarding state to the database, applies optimistic UI patterns, and triggers dynamic template instantiation based on user intent.

```tsx
// components/onboarding/ProgressiveProfiler.tsx
'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';

interface ProfilePayload {
  role: string;
  useCase: string;
  teamSize: string;
}

const USE_CASES = [
  {
    id: 'api_monitoring',
    title: 'Monitor Production APIs',
    description: 'Set up synthetic checks, webhook alerts, and uptime SLAs.',
    badge: 'Technical'
  },
  {
    id: 'customer_analytics',
    title: 'Track User Retention',
    description: 'Measure cohorts, conversion funnels, and activation paths.',
    badge: 'Growth'
  },
  {
    id: 'internal_tooling',
    title: 'Build Internal Dashboards',
    description: 'Connect Postgres, Snowflake, or Airtable to instant UIs.',
    badge: 'Operations'
  }
];

export default function ProgressiveProfiler({ userId }: { userId: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState<boolean>(false);
  const [selectedUseCase, setSelectedUseCase] = useState<string>('api_monitoring');
  const [role, setRole] = useState<string>('engineer');
  const [teamSize, setTeamSize] = useState<string>('1-10');

  const handleCompleteProfiling = async () => {
    setLoading(true);
    const startTime = window.performance.now();

    try {
      const response = await fetch('/api/v1/onboarding/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId,
          persona_role: role,
          primary_use_case: selectedUseCase,
          team_size_bracket: teamSize,
          client_timestamp: new Date().toISOString()
        })
      });

      if (!response.ok) throw new Error('Failed to persist onboarding state');

      const endTime = window.performance.now();
      const durationMs = Math.round(endTime - startTime);

      // Track telemetry
      await fetch('/api/v1/telemetry/event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId,
          step_name: 'progressive_profiling',
          action: 'completed',
          time_spent_ms: durationMs,
          metadata: { selectedUseCase, role, teamSize }
        })
      });

      // Route to custom workspace hydrated with selected templates
      router.push(`/dashboard?template=${selectedUseCase}&hydrated=true`);
    } catch (error) {
      console.error('Profiling error:', error);
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-12 px-4 sm:px-6">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-extrabold text-gray-900 tracking-tight">
          Tailor your workspace
        </h1>
        <p className="mt-2 text-sm text-gray-600">
          We will pre-configure your pipelines based on your operational target.
        </p>
      </div>

      <div className="space-y-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            What is your primary deployment objective?
          </label>
          <div className="grid grid-cols-1 gap-4">
            {USE_CASES.map((item) => (
              <div
                key={item.id}
                onClick={() => setSelectedUseCase(item.id)}
                className={`relative flex cursor-pointer rounded-lg border p-4 shadow-sm focus:outline-none transition-all ${
                  selectedUseCase === item.id
                    ? 'border-indigo-600 ring-2 ring-indigo-600 bg-indigo-50/30'
                    : 'border-gray-300 hover:border-gray-400 bg-white'
                }`}
              >
                <div className="flex flex-1 items-center justify-between">
                  <div className="block">
                    <span className="block text-sm font-semibold text-gray-900">
                      {item.title}
                    </span>
                    <span className="block text-xs text-gray-500 mt-1">
                      {item.description}
                    </span>
                  </div>
                  <span className="ml-4 text-xs font-mono bg-gray-100 text-gray-700 px-2.5 py-1 rounded-full">
                    {item.badge}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Your Professional Role
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white py-2 px-3 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm"
            >
              <option value="engineer">Software Engineer</option>
              <option value="product">Product Manager</option>
              <option value="data">Data Scientist / Analyst</option>
              <option value="founder">Founder / Executive</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Company Size
            </label>
            <select
              value={teamSize}
              onChange={(e) => setTeamSize(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white py-2 px-3 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500 sm:text-sm"
            >
              <option value="1">Solo Operator (1)</option>
              <option value="2-10">Early Stage (2-10)</option>
              <option value="11-50">Scaleup (11-50)</option>
              <option value="50+">Enterprise (50+)</option>
            </select>
          </div>
        </div>

        <button
          type="button"
          onClick={handleCompleteProfiling}
          disabled={loading}
          className="w-full flex justify-center py-3 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
        >
          {loading ? 'Initializing Custom Engine...' : 'Launch Workspace'}
        </button>
      </div>
    </div>
  );
}
```

---

## 3. Engineering the Sub-3-Minute Time-to-Value (TTV)

The single greatest point of failure in PLG software is the **"Blank Canvas Paralysis"**. When a user lands on an empty table, empty dashboard, or empty document, cognitive load spikes while motivation drops.

### The "Blank Slate" Eradication Protocol

To guarantee sub-3-minute TTV, execute one of the following architectural strategies:

```
                  ┌─ Strategy A: The Interactive Sandbox
                  │  (Pre-populate real data; user edits rather than creates)
                  │
Empty State ──────┼─ Strategy B: The Instant Integration Ingest
Alternatives      │  (1-Click connect via OAuth pulls in active assets)
                  │
                  └─ Strategy C: The Algorithmic Scaffold
                     (Answer 3 questions; generate complete working system)
```

1. **Synthetic Hydration (The Sandbox Model):** Pre-populate the user's workspace with production-grade mock data tagged as `is_demo: true`. Let them interact, modify, and delete it immediately.
2. **Reverse ETL Ingestion:** During setup, provide a 1-click connect to Google Workspace, GitHub, or Slack. Pull existing team artifacts to immediately display the user's actual operating context.
3. **Template Scaffolding:** Never leave default text inputs blank. If the user creates a "Project," pre-fill sensible defaults based on their industry or selected persona.

### Session Hydration Implementation

When the user enters the application, run an initialization script that verifies whether the workspace has production data. If not, seed high-fidelity mock entities immediately.

```typescript
// lib/onboarding/seedWorkspace.ts
import { SupabaseClient } from '@supabase/supabase-js';

interface SeedConfig {
  workspaceId: string;
  userId: string;
  primaryUseCase: string;
}

export async function seedWorkspaceDefaults(
  supabase: SupabaseClient,
  config: SeedConfig
): Promise<{ success: boolean; seededCount: number }> {
  const { workspaceId, userId, primaryUseCase } = config;

  // Determine mock payload according to use case
  const demoEntities = primaryUseCase === 'api_monitoring' 
    ? [
        { name: 'Production Checkout API', endpoint: 'https://api.domain.com/v1/checkout', status: 200, latency_ms: 142 },
        { name: 'Auth Gateway (OAuth2)', endpoint: 'https://auth.domain.com/token', status: 200, latency_ms: 89 },
        { name: 'Webhooks Ingestion Worker', endpoint: 'https://hooks.domain.com/stripe', status: 504, latency_ms: 1250 }
      ]
    : [
        { name: 'Self-Serve Conversion Flow', endpoint: 'funnel://app.core/signup-to-paid', status: 200, latency_ms: 45 },
        { name: 'Team Invite Loop', endpoint: 'funnel://app.core/invitations', status: 200, latency_ms: 32 }
      ];

  const records = demoEntities.map(entity => ({
    workspace_id: workspaceId,
    created_by: userId,
    title: entity.name,
    target_resource: entity.endpoint,
    last_status_code: entity.status,
    observed_latency: entity.latency_ms,
    is_synthetic_demo: true,
    created_at: new Date().toISOString()
  }));

  const { data, error } = await supabase
    .from('monitored_resources')
    .insert(records)
    .select();

  if (error) {
    console.error('Failed to seed sandbox entities:', error);
    return { success: false, seededCount: 0 };
  }

  // Insert a marker that the user has reached the "Setup Moment" automatically
  await supabase
    .from('onboarding_states')
    .update({ 
      current_step: 'sandbox_hydrated',
      completed_steps: ['workspace_init', 'sandbox_hydrated']
    })
    .eq('user_id', userId);

  return { success: true, seededCount: data.length };
}
```

---

## 4. The AHA Moment Discovery & Verification System

You cannot engineer the AHA moment until you mathematically isolate it from historical cohort data. The AHA moment is the interaction behavior that maximizes the combined metric of **Coverage** (% of retained users who did it) and **Precision** (% of users who did it that retained).

### SQL Analysis Script: Isolating the AHA Event

Run this query against your event-tracking warehouse (PostgreSQL, Snowflake, or BigQuery) to determine which early product actions correlate most strongly with Day-30 retention.

```sql
-- PostgreSQL / Redshift Analytics Query: AHA Moment Correlation Engine
WITH user_cohort AS (
    SELECT 
        u.id AS user_id,
        u.created_at AS signup_date,
        MAX(CASE WHEN a.occurred_at >= u.created_at + INTERVAL '28 days' 
                  AND a.occurred_at <= u.created_at + INTERVAL '35 days' 
                 THEN 1 ELSE 0 END) AS is_retained_d30
    FROM users u
    LEFT JOIN activity_logs a ON u.id = a.user_id
    WHERE u.created_at BETWEEN NOW() - INTERVAL '90 days' AND NOW() - INTERVAL '35 days'
    GROUP BY u.id, u.created_at
),
event_matrix AS (
    SELECT 
        c.user_id,
        c.is_retained_d30,
        -- Event 1: Shared an asset within first 48 hours
        MAX(CASE WHEN e.event_name = 'asset_shared' 
                  AND e.created_at <= c.signup_date + INTERVAL '48 hours' 
                 THEN 1 ELSE 0 END) AS did_share_asset_48h,
        -- Event 2: Invited teammate within first 48 hours
        MAX(CASE WHEN e.event_name = 'team_invite_sent' 
                  AND e.created_at <= c.signup_date + INTERVAL '48 hours' 
                 THEN 1 ELSE 0 END) AS did_invite_team_48h,
        -- Event 3: Created > 3 resources within first 48 hours
        CASE WHEN COUNT(CASE WHEN e.event_name = 'resource_created' 
                              AND e.created_at <= c.signup_date + INTERVAL '48 hours' 
                             THEN 1 END) >= 3 
             THEN 1 ELSE 0 END AS did_create_3_resources_48h
    FROM user_cohort c
    LEFT JOIN product_events e ON c.user_id = e.user_id
    GROUP BY c.user_id, c.is_retained_d30
)
SELECT 
    'Shared Asset Within 48h' AS behavioral_test,
    COUNT(*) AS total_sample_size,
    ROUND(AVG(did_share_asset_48h) * 100, 2) AS population_coverage_pct,
    ROUND(AVG(CASE WHEN did_share_asset_48h = 1 THEN is_retained_d30 ELSE 0 END) / 
          NULLIF(AVG(did_share_asset_48h), 0) * 100, 2) AS precision_retained_pct,
    ROUND(AVG(CASE WHEN did_share_asset_48h = 0 THEN is_retained_d30 ELSE 0 END) / 
          NULLIF(1 - AVG(did_share_asset_48h), 0) * 100, 2) AS control_retained_pct
FROM event_matrix
UNION ALL
SELECT 
    'Invited Teammate Within 48h',
    COUNT(*),
    ROUND(AVG(did_invite_team_48h) * 100, 2),
    ROUND(AVG(CASE WHEN did_invite_team_48h = 1 THEN is_retained_d30 ELSE 0 END) / 
          NULLIF(AVG(did_invite_team_48h), 0) * 100, 2),
    ROUND(AVG(CASE WHEN did_invite_team_48h = 0 THEN is_retained_d30 ELSE 0 END) / 
          NULLIF(1 - AVG(did_invite_team_48h), 0) * 100, 2)
FROM event_matrix
UNION ALL
SELECT 
    'Created 3 Resources Within 48h',
    COUNT(*),
    ROUND(AVG(did_create_3_resources_48h) * 100, 2),
    ROUND(AVG(CASE WHEN did_create_3_resources_48h = 1 THEN is_retained_d30 ELSE 0 END) / 
          NULLIF(AVG(did_create_3_resources_48h), 0) * 100, 2),
    ROUND(AVG(CASE WHEN did_create_3_resources_48h = 0 THEN is_retained_d30 ELSE 0 END) / 
          NULLIF(1 - AVG(did_create_3_resources_48h), 0) * 100, 2)
FROM event_matrix;
```

### AHA Discovery Decision Matrix

Use the resulting data to evaluate which event candidate to select as the primary product-led onboarding target:

| Event Candidate | Coverage (% Pop) | Precision (D30 Ret%) | Lift vs. Baseline | Final Activation Choice |
| :--- | :--- | :--- | :--- | :--- |
| **Shared Asset $\le 48\text{h}$** | $18.4\%$ | $64.2\%$ | $+38.1\%$ | **Rejected:** High precision, but coverage is too narrow. |
| **Created 3 Resources $\le 48\text{h}$** | $62.1\%$ | $52.8\%$ | $+26.7\%$ | **SELECTED:** Strong balance of coverage and lift. |
| **Invited Teammate $\le 48\text{h}$** | $8.2\%$ | $71.0\%$ | $+44.9\%$ | **Secondary:** Move to progressive prompt later. |

---

## 5. AI-Driven Dynamic Onboarding Flow System Prompt

Modern PLG products do not show identical onboarding screens to every user. Use this system prompt in your background personalization worker. The prompt takes the user's role, company size, intent, and raw inputs, then generates a customized onboarding sequence with concrete, tailored copy.

```markdown
You are an expert Principal Product-Led Growth (PLG) Architect and User Onboarding Engineer. 

Your objective is to evaluate a newly signed-up SaaS user's input profile and output an ultra-tailored, zero-friction onboarding configuration in strict JSON format.

### RULES:
1. Every step must contain explicit, non-generic micro-copy matching the user's specific vertical.
2. The sequence must minimize Time-To-Value (TTV) to under 180 seconds.
3. Propose exactly 3-4 linear steps:
   - Step 1: Automated Scaffold / Seed (Zero-effort configuration)
   - Step 2: The Core AHA Action (Primary utility extraction)
   - Step 3: Distribution or Collaboration (Locking in the Habit moment)
4. Do NOT output markdown wrappers around the JSON. Return purely valid, parseable JSON.

### INPUT SCHEMA EXPECTED:
{
  "role": "string",
  "industry": "string",
  "team_size": "string",
  "primary_use_case": "string"
}

### OUTPUT JSON SCHEMA:
{
  "tailored_workspace_title": "string",
  "primary_metric_to_track": "string",
  "suggested_seed_asset_name": "string",
  "steps": [
    {
      "step_index": 1,
      "step_id": "string",
      "target_route": "string",
      "modal_title": "string",
      "modal_instruction": "string",
      "action_cta": "string",
      "estimated_seconds_to_complete": 30
    }
  ],
  "fallback_empty_state_copy": {
    "heading": "string",
    "subtext": "string",
    "primary_button": "string"
  }
}

### EXAMPLE EVALUATION:
User Input:
{
  "role": "Security Engineer",
  "industry": "HealthTech",
  "team_size": "50-200",
  "primary_use_case": "SOC2_compliance_automation"
}

Expected Response:
{
  "tailored_workspace_title": "HIPAA & SOC2 Compliance Pipeline",
  "primary_metric_to_track": "Evidence Collection Pass Rate (%)",
  "suggested_seed_asset_name": "AWS IAM Infrastructure Audit (Sample)",
  "steps": [
    {
      "step_index": 1,
      "step_id": "connect_read_only_cloud",
      "target_route": "/settings/integrations/aws",
      "modal_title": "Attach Read-Only Audit Role",
      "modal_instruction": "Deploy our pre-audited CloudFormation template to verify HIPAA/SOC2 baseline controls automatically.",
      "action_cta": "Deploy to AWS Console",
      "estimated_seconds_to_complete": 60
    },
    {
      "step_index": 2,
      "step_id": "run_initial_gap_analysis",
      "target_route": "/dashboard/audits/first-run",
      "modal_title": "Run Baseline Security Audit",
      "modal_instruction": "Execute an immediate scan across active S3 buckets and IAM roles to detect non-compliant assets.",
      "action_cta": "Generate Audit Report",
      "estimated_seconds_to_complete": 30
    },
    {
      "step_index": 3,
      "step_id": "invite_compliance_stakeholder",
      "target_route": "/settings/team",
      "modal_title": "Share Initial Gap Analysis",
      "modal_instruction": "Loop in your external auditor or CTO with read-only executive summary privileges.",
      "action_cta": "Send Auditor Invite",
      "estimated_seconds_to_complete": 30
    }
  ],
  "fallback_empty_state_copy": {
    "heading": "No Active Security Frameworks Configured",
    "subtext": "Select your target framework below to auto-scaffold evidence monitors.",
    "primary_button": "Initialize SOC2 Controls"
  }
}
```

---

## 6. The Onboarding Launch Checklist & QA Audit

Before shipping any onboarding flow or updating an activation path, verify every criteria on this production readiness checklist.

### Step 1: Telemetry & Event Instrument Verification
- [ ] Every step transition fires both a client-side and a server-side telemetry event.
- [ ] Heartbeat analytics monitor the duration (in milliseconds) spent per step.
- [ ] Drop-off tracking flags exit intent per step (`beforeunload` listener configured).
- [ ] Telemetry events share a consistent schema: `(user_id, session_id, step_id, status, error_code, latency)`.

### Step 2: Empty-State Eradication (Zero Blank Canvases)
- [ ] The dashboard loads with mock, demo, or pre-seeded data on initial signup.
- [ ] Demo records are visually identifiable with an `is_demo` badge or banner.
- [ ] Users can delete all synthetic records with a single click ("Clear demo data").
- [ ] The primary Call-to-Action (CTA) replaces the empty state with a single, linear action.

### Step 3: Progressive Profiling Friction Controls
- [ ] Total input fields during registration are $\le 3$ (strictly Email/Password or Single Sign-On).
- [ ] No redundant confirmation fields (eliminate "Confirm Password").
- [ ] Dropdowns with more than 6 options include inline search/autocomplete.
- [ ] Every question asked explains *why* the product requires the input: `"To customize your templates"`.

### Step 4: Technical Fail-safes & Responsive Architecture
- [ ] Users can refresh the page at any onboarding point without losing data or restarting the flow.
- [ ] The state machine routes the user back to their furthest completed step upon re-login.
- [ ] Modals and checklists are fully functional on viewports down to $375\text{px}$ (mobile responsive).
- [ ] All API requests within onboarding gracefully fall back to default states upon a $5\text{xx}$ error.

### Step 5: Email & Product Trigger Synchronization
- [ ] Welcome emails match the specific persona captured during progressive profiling.
- [ ] If a user reaches the AHA moment in-app, kill the external "How to get started" email sequence.
- [ ] Behavioral triggers automatically fire a "Stuck in Setup" intervention after 24 hours of inactivity.
- [ ] Workspace invitees skip the initial profiling flow and land directly on the shared
