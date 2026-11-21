# Module 4: Master Retention Scorecard, Audit Checklists & Feature Adoption Systems

This module provides the diagnostic architectures, telemetry schemas, and post-launch discovery playbooks required to isolate onboarding failure points and systematically drive secondary feature adoption.

---

## 1. Master SaaS Retention Scorecard & Diagnostic Framework

Retention problems present as top-line revenue issues, but their root causes live inside activation cohort behavior. Use the following metrics, benchmarks, and SQL models to audit your retention curve.

### 1.1 Retention Metric Benchmarks by Model

| Metric | B2B Product-Led (Self-Serve) | B2B Sales-Led (Enterprise) | B2C / Prosumer SaaS | Calculation Formula |
| :--- | :--- | :--- | :--- | :--- |
| **Day 1 Retention** | 40% – 55% | N/A (Project-based) | 30% – 45% | `(Active Users Day 1 / Total Signups Day 0) * 100` |
| **Day 7 Retention** | 25% – 35% | 60% – 75% | 15% – 25% | `(Active Users Day 7 / Total Signups Day 0) * 100` |
| **Day 30 Retention** | 15% – 25% | 70% – 85% | 8% – 15% | `(Active Users Day 30 / Total Signups Day 0) * 100` |
| **Day 90 Retention** | 12% – 20% | 75% – 90% | 5% – 10% | `(Active Users Day 90 / Total Signups Day 0) * 100` |
| **Net Revenue Retention (NRR)** | 105% – 120% | 115% – 140% | 85% – 100% | `[(Beginning ARR + Expansion - Contraction - Churn) / Beginning ARR] * 100` |
| **Gross Revenue Retention (GRR)** | 85% – 90% | 90% – 95% | 65% – 75% | `[(Beginning ARR - Contraction - Churn) / Beginning ARR] * 100` |
| **Quick Ratio** | > 4.0 | > 3.0 | > 2.0 | `(New ARR + Expansion ARR) / (Contraction ARR + Churn ARR)` |

### 1.2 Retention Curve Diagnostic Framework

To assess whether your retention curve flattens parallel to the x-axis (indicating product-market fit and sustainable onboarding) or decays to zero, run this diagnostic sequence:

```
Step 1: Segment Cohort by Activation Milestone
        ├── Cohort A: Completed "Aha!" Moment within 24h
        └── Cohort B: Did not complete "Aha!" Moment within 24h

Step 2: Plot N-Day Unbounded Retention Curve
        ├── Healthy Curve: Drops steeply D0-D3, stabilizes by D7, completely flat D14-D90
        ├── Leaky Bucket Curve: Constant negative slope from D0 to D90 (Never flattens)
        └── Delayed Drop Curve: Stable D0-D14, steep drop at D15 or D30 (Trial expiration shock)

Step 3: Execute Root Cause Analysis
        ├── If Leaky Bucket -> Value proposition gap or wrong user acquisition channel
        ├── If Delayed Drop -> Artificial urgency failure, lack of team onboarding, paywall friction
        └── If Low Day 1 (<30%) -> Setup friction, empty state failure, broken sign-up verification
```

### 1.3 Production SQL: N-Day Cohort Retention (PostgreSQL / Snowflake Compatible)

This query groups users into weekly acquisition cohorts and calculates exact N-day retention rates for Days 0, 1, 7, 14, 30, and 60.

```sql
WITH user_cohorts AS (
    SELECT
        user_id,
        DATE_TRUNC('week', created_at) AS cohort_week,
        created_at AS signup_timestamp
    FROM users
    WHERE created_at >= NOW() - INTERVAL '12 weeks'
),
user_activities AS (
    SELECT
        e.user_id,
        DATE(e.timestamp) AS activity_date,
        u.signup_timestamp,
        u.cohort_week
    FROM events e
    INNER JOIN user_cohorts u ON e.user_id = u.user_id
    WHERE e.timestamp >= u.signup_timestamp
    GROUP BY e.user_id, DATE(e.timestamp), u.signup_timestamp, u.cohort_week
),
cohort_sizes AS (
    SELECT
        cohort_week,
        COUNT(DISTINCT user_id) AS total_users
    FROM user_cohorts
    GROUP BY cohort_week
),
activity_intervals AS (
    SELECT
        cohort_week,
        user_id,
        activity_date - DATE(signup_timestamp) AS day_number
    FROM user_activities
)
SELECT
    c.cohort_week,
    s.total_users,
    ROUND(COUNT(DISTINCT CASE WHEN a.day_number = 0 THEN a.user_id END) * 100.0 / s.total_users, 2) AS day_0_pct,
    ROUND(COUNT(DISTINCT CASE WHEN a.day_number = 1 THEN a.user_id END) * 100.0 / s.total_users, 2) AS day_1_pct,
    ROUND(COUNT(DISTINCT CASE WHEN a.day_number = 7 THEN a.user_id END) * 100.0 / s.total_users, 2) AS day_7_pct,
    ROUND(COUNT(DISTINCT CASE WHEN a.day_number = 14 THEN a.user_id END) * 100.0 / s.total_users, 2) AS day_14_pct,
    ROUND(COUNT(DISTINCT CASE WHEN a.day_number = 30 THEN a.user_id END) * 100.0 / s.total_users, 2) AS day_30_pct,
    ROUND(COUNT(DISTINCT CASE WHEN a.day_number = 60 THEN a.user_id END) * 100.0 / s.total_users, 2) AS day_60_pct
FROM activity_intervals a
JOIN cohort_sizes s ON a.cohort_week = s.cohort_week
JOIN (SELECT DISTINCT cohort_week FROM user_cohorts) c ON a.cohort_week = c.cohort_week
GROUP BY c.cohort_week, s.total_users
ORDER BY c.cohort_week DESC;
```

---

## 2. Onboarding Drop-Off Diagnostic Audit Rubric

Use this 10-step scorecard to audit your sign-up-to-activation funnel. Score your product against each criterion to pinpoint drop-offs.

### 2.1 Funnel Diagnostic Audit Matrix

| Step | Funnel Milestone | Metric Measured | Healthy Benchmark | Red Flag Threshold | Diagnostic / Remediation Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **01** | Landing Page to Sign-up Form | Form Click / Page View | 5% – 12% | < 3% | Value proposition unaligned with ad/SEO traffic. Remove navigation links from landing page. |
| **02** | Sign-up Form to Submit | Form Submissions / Form Views | 65% – 80% | < 50% | Reduce form fields. Strip phone number, company size, and billing inputs from step 1. |
| **03** | Email Verification (if forced) | Verified Accounts / Signups | 85% – 95% | < 70% | High spam folder placement or deliverability lag. Switch to passwordless OTP or deferred email verification. |
| **04** | Workspace Initialization | Workspaces Created / Verified | 95% – 99% | < 90% | Technical timeout or unnecessary configuration questions. Move configuration steps inside workspace UI. |
| **05** | Welcome / Setup Survey | Completed Surveys / Started | 75% – 85% | < 60% | Survey fatigue. Maximize at 3 questions. Add an explicit "Skip" link in upper right corner. |
| **06** | Primary Data Ingestion | First Upload, Sync, or Entry | 40% – 60% | < 25% | Integration barrier or blank canvas paralysis. Offer 1-click sample/mock data population. |
| **07** | Core Feature Configuration | Setting Configured / Data Ingested | 50% – 70% | < 35% | UI complexity. Replace blank configurations with pre-populated production templates. |
| **08** | "Aha!" Value Experience | First Output Derived / Shared | 35% – 50% | < 20% | High time-to-value (TTV). Trigger guided highlight tours or automated default setups. |
| **09** | Team Collaboration / Invite | Invites Sent / Activated Workspaces | 20% – 40% | < 10% | Missing viral loop. Introduce shared workspace features that require a colleague's input to complete. |
| **10** | Habituation Return (Day 2) | Sessions on Day 2 / Day 0 Signups | 30% – 45% | < 20% | Email loop broken. Trigger transactional recap email detailing state changes within workspace. |

### 2.2 Time-To-Value (TTV) Friction Audit Checklist

Run your onboarding flow against this binary audit. Any **"FAILED"** response indicates an immediate remediation requirement.

```
[ ] PASS | FAIL : 1. Social Sign-on Available (Google, GitHub, Microsoft)
    Remediation: Implement OAuth 2.0 social sign-ons to eliminate manual typing and password managers.

[ ] PASS | FAIL : 2. Zero-Click Mock Data Option Available
    Remediation: If the core UI relies on data tables, charts, or feeds, supply a "Pre-fill with Demo Data" toggle.

[ ] PASS | FAIL : 3. Email Verification Deferred Until After First Core Value Moment
    Remediation: Allow users to experience product UI immediately; block only export, invitation, or publishing actions until verified.

[ ] PASS | FAIL : 4. Contextual Guidance Over Full-Screen Modals
    Remediation: Replace 5-step modal takeovers with unobtrusive, step-by-step hotspot callouts that anchor to UI elements.

[ ] PASS | FAIL : 5. Dynamic Checklist Present in View
    Remediation: Display a 3- to 4-step checklist showing progress (`1 of 4 completed`) anchored to bottom-left/right of workspace.

[ ] PASS | FAIL : 6. Sub-180-Second Path to Value (Median TTV < 3 Minutes)
    Remediation: Audit time required from landing page hit to core asset creation. Cut all intermediate screens until TTV < 180s.
```

---

## 3. Production Analytics Tracking Schema (PostHog & Mixpanel)

Inconsistent event naming breaks downstream retention funnels. Enforce this strict **Object-Action** standard across your product, backend, and marketing stack.

### 3.1 Global Naming Rules & Reserved Property Standard

1. **Event Names**: Always use `snake_case` in `[object]_[action]` format (e.g., `workspace_created`, `dashboard_exported`).
2. **Property Names**: Always use `snake_case` (e.g., `billing_tier`, `source_channel`).
3. **Never send dynamic values in Event Names**: Use properties instead (e.g., Use `button_clicked` with property `button_name: "save"`, **NOT** `save_button_clicked`).

### 3.2 Canonical JSON Tracking Schema

Save this JSON definition as your team's canonical schema contract:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SaaSEventsSchema",
  "type": "object",
  "definitions": {
    "UserIdentityProperties": {
      "type": "object",
      "properties": {
        "user_id": { "type": "string", "format": "uuid" },
        "email": { "type": "string", "format": "email" },
        "account_created_at": { "type": "string", "format": "date-time" },
        "pricing_tier": { "type": "string", "enum": ["free", "starter", "pro", "enterprise"] },
        "workspace_id": { "type": "string", "format": "uuid" },
        "workspace_role": { "type": "string", "enum": ["owner", "admin", "member", "viewer"] }
      },
      "required": ["user_id", "email", "pricing_tier", "workspace_id"]
    },
    "UserSignedUpEvent": {
      "type": "object",
      "properties": {
        "event": { "type": "string", "const": "user_signed_up" },
        "properties": {
          "type": "object",
          "properties": {
            "signup_method": { "type": "string", "enum": ["password", "google", "github", "sso"] },
            "referral_source": { "type": "string" },
            "utm_source": { "type": "string" },
            "utm_medium": { "type": "string" },
            "utm_campaign": { "type": "string" }
          },
          "required": ["signup_method"]
        }
      }
    },
    "WorkspaceCreatedEvent": {
      "type": "object",
      "properties": {
        "event": { "type": "string", "const": "workspace_created" },
        "properties": {
          "type": "object",
          "properties": {
            "workspace_id": { "type": "string", "format": "uuid" },
            "team_size": { "type": "string", "enum": ["1", "2-5", "6-20", "21-50", "50+"] },
            "use_case": { "type": "string" }
          },
          "required": ["workspace_id", "team_size", "use_case"]
        }
      }
    },
    "CoreActionCompletedEvent": {
      "type": "object",
      "properties": {
        "event": { "type": "string", "const": "core_action_completed" },
        "properties": {
          "type": "object",
          "properties": {
            "action_type": { "type": "string" },
            "time_to_complete_seconds": { "type": "integer" },
            "is_first_time": { "type": "boolean" },
            "data_source_type": { "type": "string", "enum": ["manual", "sample", "csv_import", "api"] }
          },
          "required": ["action_type", "is_first_time", "data_source_type"]
        }
      }
    },
    "InviteSentEvent": {
      "type": "object",
      "properties": {
        "event": { "type": "string", "const": "invite_sent" },
        "properties": {
          "type": "object",
          "properties": {
            "invites_count": { "type": "integer", "minimum": 1 },
            "invited_roles": { "type": "array", "items": { "type": "string" } },
            "trigger_location": { "type": "string", "enum": ["onboarding_checklist", "settings_page", "collaboration_prompt"] }
          },
          "required": ["invites_count", "trigger_location"]
        }
      }
    },
    "PaywallViewedEvent": {
      "type": "object",
      "properties": {
        "event": { "type": "string", "const": "paywall_viewed" },
        "properties": {
          "type": "object",
          "properties": {
            "trigger_feature": { "type": "string" },
            "current_plan": { "type": "string" },
            "target_plan": { "type": "string" },
            "source_surface": { "type": "string", "enum": ["locked_feature_click", "limit_reached_banner", "settings_billing"] }
          },
          "required": ["trigger_feature", "source_surface"]
        }
      }
    }
  }
}
```

### 3.3 Production Telemetry Wrapper (TypeScript / Node.js)

Implement this wrapper class across client and server environments to maintain tracking consistency, inject system context, and prevent property drift:

```typescript
// telemetry.ts
import posthog from 'posthog-js'; // Or 'mixpanel-browser'

export interface TelemetryContext {
  userId: string;
  workspaceId: string;
  pricingTier: 'free' | 'starter' | 'pro' | 'enterprise';
  environment: 'production' | 'staging' | 'development';
}

export interface CoreActionEventProperties {
  actionType: string;
  timeToCompleteSeconds: number;
  isFirstTime: boolean;
  dataSourceType: 'manual' | 'sample' | 'csv_import' | 'api';
}

export class TelemetryService {
  private static instance: TelemetryService;
  private context: TelemetryContext | null = null;

  private constructor() {}

  public static getInstance(): TelemetryService {
    if (!TelemetryService.instance) {
      TelemetryService.instance = new TelemetryService();
    }
    return TelemetryService.instance;
  }

  public init(apiKey: string, hostUrl: string): void {
    posthog.init(apiKey, {
      api_host: hostUrl,
      autocapture: false, // Explicit tracking preserves schema hygiene
      capture_pageview: true,
      sanitize_properties: (properties) => {
        // Enforce removal of accidental PII leakage
        delete properties['password'];
        delete properties['credit_card'];
        return properties;
      }
    });
  }

  public identifyUser(context: TelemetryContext, email: string): void {
    this.context = context;
    posthog.identify(context.userId, {
      email: email,
      workspace_id: context.workspaceId,
      pricing_tier: context.pricingTier,
      environment: context.environment,
      identified_at: new Date().toISOString()
    });
    posthog.group('workspace', context.workspaceId, {
      tier: context.pricingTier
    });
  }

  public trackCoreAction(props: CoreActionEventProperties): void {
    this.assertIdentified();
    posthog.capture('core_action_completed', {
      action_type: props.actionType,
      time_to_complete_seconds: props.timeToCompleteSeconds,
      is_first_time: props.isFirstTime,
      data_source_type: props.dataSourceType,
      workspace_id: this.context?.workspaceId,
      pricing_tier: this.context?.pricingTier,
      timestamp: new Date().toISOString()
    });
  }

  public trackPaywallHit(feature: string, surface: string): void {
    this.assertIdentified();
    posthog.capture('paywall_viewed', {
      trigger_feature: feature,
      source_surface: surface,
      workspace_id: this.context?.workspaceId,
      pricing_tier: this.context?.pricingTier
    });
  }

  private assertIdentified(): void {
    if (!this.context) {
      console.warn('TelemetryService: Event dispatched before user identity context initialized.');
    }
  }
}

export const telemetry = TelemetryService.getInstance();
```

---

## 4. Post-Launch Feature Discovery & Adoption Workflow

Onboarding does not terminate at initial account setup. Long-term retention is driven by secondary feature adoption. Deploy this systematic workflow to move users from core feature usage to advanced, retention-sticking features.

### 4.1 Feature Adoption Lifecycle Matrix

```
       [ Stage 1: Unaware ]
                │
                ▼ (Trigger: Contextual In-App Badge / Notification)
      [ Stage 2: Discovered ]
                │
                ▼ (Action: Interactive micro-flow / Sandbox preview)
      [ Stage 3: Activated ]
                │
                ▼ (Condition: Repeated action >= 3x in 14 Days)
    [ Stage 4: Habitualized / Adopted ]
```

| Lifecycle Phase | User State Definition | Intervention Channel | Behavioral Threshold | Primary Success Metric |
| :--- | :--- | :--- | :--- | :--- |
| **1. Unaware** | User has never executed or clicked the feature. | In-App Feature Beacon / Empty State Callout | Zero feature impressions recorded. | Click-through rate on discovery banner (> 15%). |
| **2. Discovered** | Feature clicked or modal viewed, but no completion. | Embedded Interactive Micro-Tour (2 steps max) | 1 click, 0 completions within 48 hours. | Flow initiation rate (> 40%). |
| **3. Activated** | Feature executed 1 time successfully. | Transactional Celebration + Workflow Shortcut | Core output generated once. | Time to 2nd execution (< 5 days). |
| **4. Habitualized** | Feature embedded into operational workflow. | Weekly Digest Inclusion / Power-User Shortcut Tips | Feature executed $\ge$ 3 times over 14 days. | 60-day feature-specific retention (> 50%). |

### 4.2 Automated In-App Discovery Rules Engine (JSON Spec)

Use this declarative rule configuration to program in-app cues via your feature flagging or onboarding tooling (e.g., LaunchDarkly, PostHog Early Access Features, Appcues):

```json
{
  "feature_campaign_id": "discovery_automated_reporting",
  "target_feature_id": "scheduled_reports_v2",
  "qualification_rules": {
    "and": [
      {
        "field": "properties.core_action_completed_count",
        "operator": "greater_than_or_equal",
        "value": 5
      },
      {
        "field": "properties.account_created_at",
        "operator": "older_than_days",
        "value": 7
      },
      {
        "field": "features_used",
        "operator": "not_contains",
        "value": "scheduled_reports_v2"
      },
      {
        "field": "session_properties.current_route",
        "operator": "equals",
        "value": "/analytics/dashboards"
      }
    ]
  },
  "display_limits": {
    "max_impressions_per_user": 2,
    "cooldown_period_hours": 72
  },
  "ui_component": {
    "type": "pinned_hotspot",
    "anchor_element_selector": "#btn-export-schedule",
    "headline": "Automate this report weekly",
    "copy": "Eliminate manual exports. Schedule this view to deliver automatically to your team's Slack or email.",
    "cta_primary": {
      "label": "Set Schedule",
      "action": "open_flow",
      "target_flow_id": "flow_schedule_modal_step1"
    },
    "cta_secondary": {
      "label": "Dismiss",
      "action": "dismiss_beacon"
    }
  }
}
```

### 4.3 Behavioral Re-Engagement Email: Secondary Activation Failure

*Send this transactional template automatically when a user meets the discovery rules (e.g., active on core actions for >7 days) but has never activated the secondary retention-driving feature.*

```
Subject: [First Name], automate your [Core Asset Type] workflows
From: [Founder / Product Lead] <growth@yourdomain.com>
Reply-To: growth@yourdomain.com

Hi [First Name],

You've built [Metric / Count, e.g., 6 dashboards] in [Product Name] over the past couple of weeks. 

Most teams hit a point where manually sharing these updates becomes a drag. You can automate this entirely:

[Feature Name, e.g., Scheduled Dispatch] sends a fresh capture of your [Asset Type] directly to your Slack channel or executive inbox every Monday at 9 AM.

Here is how to set it up in 60 seconds:

1. Open your primary dashboard: [Deep Link to User's Specific Asset]
2. Click the clock icon in the top right corner ("Schedule").
3. Choose your frequency and destination channel.

If you run into questions setting up the webhook or want a hand configuring your parameters, hit reply to this email—I read every response.

[Button: Schedule Your First Report]

Best,
[Founder Name]
Product Lead, [Product Name]
```

### 4.4 Feature Discovery Rollout Checklist

Before releasing any secondary feature to your existing user base, verify the implementation against this launch sequence:

```
[ ] Step 1: Instrument Core Event Telemetry
    Event schema deployed: `[feature]_discovered`, `[feature]_initiated`, `[feature]_completed`.
    Events mapped in tracking software and verified via staging environment telemetry logs.

[ ] Step 2: Establish the Cohort Exclusion Rule
    Ensure power users who previously beta-tested the feature do NOT see introductory tooltips or beacons.

[ ] Step 3: Implement Throttling & Priority Queues
    Prevent display conflicts. Set global UI rules: Max 1 in-app tour or feature announcement per user session.
    Ensure primary activation flows take precedence over secondary discovery campaigns for users < 7 days old.

[ ] Step 4: Configure the Fallback Channel
    If an in-app beacon is dismissed or ignored across 2 sessions, route the user to an asynchronous 
    behavioral email trigger 72 hours later.

[ ] Step 5: Define Sunset Criteria
    Pre-commit to feature adoption criteria: If < 8% of qualified users activate the feature within 
    30 days post-exposure, immediately halt in-app banners and route the UX to an interface simplicity audit.
