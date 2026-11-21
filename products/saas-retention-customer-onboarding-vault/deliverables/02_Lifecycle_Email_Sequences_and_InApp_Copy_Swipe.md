# Module 2: Complete Lifecycle Email Sequences & In-App Microcopy Swipes

This module provides production-ready behavioral lifecycle email templates and matching in-app microcopy UI strings. Every asset uses standardized Liquid personalization tags (`{{ user.first_name }}`, `{{ workspace.name }}`, `{{ event.metric_count }}`), pre-configured behavioral trigger rules, fallback parameters, and exact button targets.

---

## 1. Behavioral Event Schema & Tracking Setup

Before deploying these sequences, configure your Customer.io, Klaviyo, Segment, or PostHog tracking to emit these exact event payloads.

### Core User & Workspace Event Taxonomy

| Event Name | Trigger Context | Required Properties | Destination Action |
| :--- | :--- | :--- | :--- |
| `workspace_created` | Signup flow Step 1 finished | `workspace_id`, `created_at`, `plan_type` | Enters Day 0 Pipeline |
| `core_setup_completed` | Connected data source or API | `workspace_id`, `source_type`, `latency_ms` | Suppresses Setup Reminders |
| `first_aha_moment` | Executed primary value action | `workspace_id`, `output_id`, `time_to_value_sec` | Triggers Value Milestone Email |
| `team_invite_sent` | Sent invite to colleague | `workspace_id`, `invitee_role`, `invites_count` | Accelerates Team Expansion |
| `usage_limit_reached` | Account hits 80% of plan limits | `workspace_id`, `metric_name`, `percent_used` | Fires Upgrade Urgency Engine |
| `session_stalled` | 48 hours without core setup | `workspace_id`, `last_step_completed`, `days_left` | Diverts to Friction Crusher Flow |

```json
{
  "event": "first_aha_moment",
  "userId": "usr_998241x",
  "timestamp": "2025-03-30T10:14:00Z",
  "properties": {
    "workspace_id": "ws_alpha_77",
    "workspace_name": "Acme Metrics",
    "feature_used": "automated_pipeline_sync",
    "records_processed": 1420,
    "time_to_setup_seconds": 184,
    "has_invited_team": false,
    "trial_days_remaining": 14
  }
}
```

---

## 2. Day 0 & First-72-Hour Activation Sequences

### Email 01: The Direct Single-Action Welcome
* **Trigger:** `workspace_created` immediately (Delay: 0 minutes).
* **Suppression:** `core_setup_completed == true`.
* **Sender:** `Founder Name <founders@yourdomain.com>`
* **Subject:** Access your {{ workspace.name | default: 'new' }} dashboard
* **Preview Text:** 3 minutes to verify your pipeline.

```liquid
Hey {{ user.first_name | default: 'there' }},

Your workspace for {{ workspace.name | default: 'your team' }} is deployed and live:
https://app.yourdomain.com/workspaces/{{ workspace.id | default: 'default' }}

You have one immediate objective today: connect your first data stream so you aren't looking at an empty dashboard.

We built a 1-click import for your current stack:
https://app.yourdomain.com/onboarding/connect?source=quickstart

If you run into any permission roadblocks, reply directly to this email. It routes straight to our engineering team.

Best,
Alex Vance
Co-Founder, YourSaaS
```

#### Paired In-App Modal Microcopy: Zero-State First Login
* **Component:** Centered Overlay Modal (Cannot be dismissed by clicking backdrop)
* **Header:** `Connect 1 data source to activate your dashboard`
* **Body:** `We cannot analyze metrics without an active connection. Choose your primary platform to populate your production baseline.`
* **Primary Button:** `Connect Source (60 seconds) →`
* **Secondary Action Text:** `I need to invite an engineer to handle keys` (Opens Invite Drawer)

---

### Email 02: The Setup Drop-Off Interceptor
* **Trigger:** 4 hours after `workspace_created`.
* **Suppression Filter:** `core_setup_completed == true` OR `first_aha_moment == true`.
* **Sender:** `Platform Support <support@yourdomain.com>`
* **Subject:** Quick question about your integration
* **Preview Text:** Stuck on the API connection or permissions?

```liquid
Hey {{ user.first_name | default: 'there' }},

I noticed you created {{ workspace.name | default: 'your account' }} a few hours ago, but you haven't completed the final connection step yet.

Usually, this means one of two things happened:
1. You hit an unexpected permissions or API credential error.
2. You got pulled into a meeting and ran out of time.

If it's #1: Here is our 90-second connection documentation:
https://docs.yourdomain.com/quickstart/permissions

If it's #2: Pick up directly where you left off here:
https://app.yourdomain.com/onboarding/resume?token={{ user.resume_token }}

Need us to white-glove the setup? Reply with your current integration target and we will send the exact permissions policy required.

— Sarah Jenkins, Customer Architecture
```

---

### Email 03: The "Aha!" Value Unlock (Self-Serve Path)
* **Trigger:** `core_setup_completed == true` (Delay: 10 minutes).
* **Suppression Filter:** `first_aha_moment == true`.
* **Sender:** `Alex Vance <founders@yourdomain.com>`
* **Subject:** Your data is synced. Here is your first output.
* **Preview Text:** See the initial baseline analysis for {{ workspace.name }}.

```liquid
{{ user.first_name | default: 'Hey' }},

Good news: The sync for {{ workspace.name | default: 'your workspace' }} completed successfully. We pulled in your initial records and mapped your schema.

To run your first production analysis:
1. Go to your Workbench: https://app.yourdomain.com/workbench
2. Select your default template: "{{ workspace.default_template | default: 'Core Performance Audit' }}"
3. Click "Generate Report"

Click here to view your initial findings:
https://app.yourdomain.com/reports/live?ref=email_activation_step3

Most teams uncover 2 to 3 critical optimization blind spots on this first run. Let me know what your report flags.

Alex
```

---

### Email 04: The Multi-Seat Force Multiplier
* **Trigger:** `first_aha_moment == true` (Delay: 24 hours).
* **Suppression Filter:** `workspace.seat_count > 1`.
* **Sender:** `YourSaaS Growth Team <team@yourdomain.com>`
* **Subject:** Don't run {{ workspace.name | default: 'this tool' }} as a solo silo
* **Preview Text:** Add your team members to share automated alert workflows.

```liquid
Hey {{ user.first_name | default: 'there' }},

Yesterday you generated your first live output on {{ workspace.name | default: 'your account' }}.

Right now, you are the only user receiving system alerts and performance flags. If you step away from your desk, your coverage stops.

Add your engineering or operations teammates so alerts route to the right owners instantly:
https://app.yourdomain.com/settings/team/invites?src=activation_single_player_nudge

Team workspaces resolve data anomalies 4.2x faster than single-user accounts. 

You can invite up to {{ workspace.allowed_trial_seats | default: '5' }} team members at no extra cost during your trial period.

Best,
The YourSaaS Team
```

#### Paired In-App Microcopy: Slide-In Toast Notification
* **Placement:** Bottom-right viewport (Fired when user completes their 2nd standalone report)
* **Title:** `Bring your team into the loop`
* **Body:** `You've run 2 reports as a single player. Invite your operators to automate resolution handoffs.`
* **Primary Button:** `Add Colleague`
* **Secondary Action:** `Dismiss`

---

## 3. The Stalled User Recovery Engine

Deploy this sequence when an account goes dark between Days 2 and 7 without reaching the verified activation metric.

```
[Day 0: Workspace Created] ──(48 hrs no event: core_setup_completed)──> [Email 05: The "Escape Hatch"]
                                                                               │
                                                      ┌────────────────────────┴────────────────────────┐
                                            (User Clicks/Logs In)                             (Still No Activity: 72 hrs)
                                                      │                                                 │
                                           [App: Guided Onboarding]                           [Email 06: Plaintext Intervention]
                                                                                                        │
                                                                                              (Still No Activity: 48 hrs)
                                                                                                        │
                                                                                              [Email 07: Unblock Concierge]
```

### Email 05: The "Technical Escape Hatch"
* **Trigger:** 48 hours elapsed since signup.
* **Segment Criteria:** `core_setup_completed == false`.
* **Sender:** `Engineering Support <eng@yourdomain.com>`
* **Subject:** Did our setup break on your environment?
* **Preview Text:** Let us review your configuration logs.

```liquid
Hey {{ user.first_name | default: 'there' }},

Our logs show that you initiated your workspace setup on {{ user.created_at | date: "%B %d" }} but never received your first data payload.

90% of the time, this is caused by one of three local configuration blocks:
- Firewall or strict egress rules blocking our webhook endpoint.
- Read-only permissions missing on the target schema.
- Expired OAuth tokens during session authorization.

Would you like one of our implementation engineers to review your error logs with you?

You can grab a 10-minute setup screen-share here:
https://cal.yourdomain.com/yoursaas-eng/onboarding-triage?email={{ user.email }}

Prefer to self-debug? Use our CLI Diagnostics tool:
`curl -sSL https://get.yourdomain.com/test-connection.sh | bash`

We're here to help you get this across the finish line.

David K.
Solutions Engineering, YourSaaS
```

---

### Email 06: The Friction Elimination Plaintext
* **Trigger:** 72 hours elapsed since signup.
* **Segment Criteria:** `core_setup_completed == false`.
* **Sender:** `Alex Vance <alex@yourdomain.com>`
* **Subject:** Quick check: Should I close your workspace?
* **Preview Text:** Cleaning up inactive trial environments for this week.

```liquid
{{ user.first_name | default: 'Hey' }},

I see your workspace ({{ workspace.name }}) is still pending initialization. 

I don't want to clutter your inbox if you've decided to postpone this project or go in another direction.

If you are simply swamped right now, no stress. Your sandbox will stay reserved for another 11 days.

If you hit a technical roadblock and want me to manually configure your account, just hit reply and paste the integration you're trying to set up. I'll personally send back the exact configuration steps.

Alex Vance
CEO, YourSaaS
```

---

### Email 07: The Pre-Built Sample Environment
* **Trigger:** 5 days elapsed since signup.
* **Segment Criteria:** `core_setup_completed == false`.
* **Sender:** `Product Education <education@yourdomain.com>`
* **Subject:** Don't have time to sync? Test with our sandbox data.
* **Preview Text:** Explore a fully populated enterprise account without connecting your data.

```liquid
Hey {{ user.first_name | default: 'there' }},

Connecting real production systems takes time, approvals, and security reviews.

If you don't have the bandwidth to run an integration today, you can still evaluate our platform. We just launched a fully populated Mock Sandbox workspace:

https://app.yourdomain.com/sandbox/demo-login?auth_token={{ user.sandbox_access_token }}

This sandbox includes:
- 150,000 synthetic transaction records pre-loaded.
- 4 pre-configured automated alerts and incident triggers.
- Live team collaboration threads and exportable audit reports.

Click the link above to test drive the core interface without connecting any of your data assets.

Best,
The YourSaaS Product Team
```

#### Paired In-App Microcopy: Empty Dashboard Rescue Banner
* **Trigger Condition:** User lands on `/dashboard` and `data_points_count == 0`.
* **Component:** Global Sticky Alert Banner (Warning Yellow).
* **Text:** `No production data found. You are currently viewing an empty state.`
* **CTA Button 1:** `Populate with Demo Data` (Runs background script generating dummy entities).
* **CTA Button 2:** `Resume Setup Guide →`

---

## 4. Usage-Based Milestones & Momentum Drivers

These sequences trigger strictly off product metrics, locking in the habit loop when users experience quantifiable progress.

### Email 08: First Value Milestone Celebration
* **Trigger:** `first_aha_moment == true` AND `event.metric_count >= 100` (Delay: Immediate).
* **Sender:** `The YourSaaS Team <notifications@yourdomain.com>`
* **Subject:** Boom: You just processed your first 100 records
* **Preview Text:** Here is your aggregate performance summary.

```liquid
{{ user.first_name | default: 'Hey' }},

Milestone reached: Your workspace, {{ workspace.name }}, just completed its 100th automated pipeline operation.

Here is what you've unlocked so far:
- Total runtime saved: ~{{ workspace.saved_hours | default: '3.5' }} engineering hours
- Critical pipeline errors caught: {{ workspace.anomalies_detected | default: '0' }}
- System status: 100% operational

View your full milestone telemetry breakdown here:
https://app.yourdomain.com/analytics/milestones?id=100_runs

What's next? Turn on automated recurring reports so your team receives daily metrics without logging in:
https://app.yourdomain.com/settings/schedules/create

Keep up the great momentum,
The YourSaaS Automation Engine
```

---

### Email 09: The 80% Quota Soft-Ceiling Notice
* **Trigger:** `usage_limit_reached == true` (Condition: `percent_used >= 80` AND `plan_type == 'trial'`).
* **Sender:** `Billing Alerts <billing@yourdomain.com>`
* **Subject:** [Notice] {{ workspace.name }} has consumed 80% of trial capacity
* **Preview Text:** Avoid pipeline pauses by selecting your tier.

```liquid
Hey {{ user.first_name | default: 'there' }},

Your workspace has processed {{ workspace.current_usage }} of your {{ workspace.max_usage }} allocated trial units (80.4% of your limit).

Because your usage is accelerating, you are on track to exhaust your sandbox capacity within the next 48 to 72 hours.

When your limit is reached:
- Inbound webhooks will be queued (not dropped) for 24 hours.
- Automated Slack/Email alerts will temporarily pause.
- Export functionality will lock until the account tier is confirmed.

To ensure uninterrupted service for {{ workspace.name }}, lock in your production plan now:
https://app.yourdomain.com/billing/upgrade?src=quota_80_percent

Questions about volume tiers or need a custom allocation? Hit reply to connect directly with our billing team.

Best,
YourSaaS Billing Operations
```

#### Paired In-App Microcopy: Meter Bar & Contextual Alert
* **Component:** Global Navigation Progress Meter.
* **Label:** `Trial Consumption: 80% Used`
* **Meter Fill State:** Amber (#F59E0B) transitioning to Red at 95%.
* **Hover Tooltip Copy:** `You have used {{ workspace.current_usage }} of your {{ workspace.max_usage }} operations. Upgrade now to ensure background processing is not paused.`
* **CTA Link:** `Upgrade Limits →`

---

### Email 10: The Weekly Executive Digest
* **Trigger:** Scheduled CRON (Fires Mondays at 08:00 AM workspace-local time).
* **Segment Criteria:** `workspace.is_active == true`.
* **Sender:** `System Digest <reports@yourdomain.com>`
* **Subject:** Weekly Digest: {{ workspace.name }} performance [{{ 'now' | date: '%b %d' }}]
* **Preview Text:** {{ workspace.total_events_week }} actions processed this past week.

```liquid
Hey {{ user.first_name | default: 'there' }},

Here is how {{ workspace.name }} performed between {{ 'now' | date: "%B %d" | advance_days: -7 }} and {{ 'now' | date: "%B %d" }}:

SUMMARY METRICS:
- Total Operations Executed: {{ workspace.total_events_week | default: '0' }} ({{ workspace.events_velocity_change | default: '+0%' }} vs previous week)
- System Errors Prevented: {{ workspace.errors_resolved_week | default: '0' }}
- Active Operators: {{ workspace.active_users_week | default: '1' }} team members

TOP PERFORMING WORKFLOW:
"{{ workspace.top_workflow_name | default: 'Primary Sync' }}" ran {{ workspace.top_workflow_count | default: '0' }} times with zero failures.

RECOMMENDED OPTIMIZATION:
{{ workspace.optimization_tip | default: 'Your workspace has not configured an automated Slack webhook destination. Adding one drops incident response times by 55%.' }}

Access your executive dashboard here:
https://app.yourdomain.com/reports/weekly?week={{ 'now' | date: "%W" }}

Have a productive week,
The YourSaaS Intelligence System
```

---

## 5. Trial Expiration & Urgency Escalation Systems

This 4-part series triggers as the evaluation window closes, systematically transitioning users from product exploration to commercial conversion.

```
[Day T-3: Expiration Warning] ────> [Day T-1: Access Lockout Safeguard]
               │                                      │
               ▼                                      ▼
    In-App: Sticky Footer Banner           In-App: Modal Interstitial
               │                                      │
               ▼                                      ▼
[Day T-0: Trial Complete]     ────> [Day T+3: Data Deprecation Notice]
```

### Email 11: The T-3 Days Value Summary
* **Trigger:** Exactly 72 hours before `workspace.trial_expires_at`.
* **Sender:** `Alex Vance <alex@yourdomain.com>`
* **Subject:** 3 days left on the {{ workspace.name }} trial
* **Preview Text:** Your configuration, historic data, and pipelines will pause on Friday.

```liquid
{{ user.first_name | default: 'Hey' }},

Your 14-day evaluation of YourSaaS ends in exactly 3 days.

Here is what your workspace has built since {{ workspace.created_at | date: "%B %d" }}:
- {{ workspace.data_sources_connected }} production data connections configured.
- {{ workspace.total_reports_generated }} custom reports delivered to your team.
- {{ workspace.hours_automated }} hours saved across {{ workspace.seat_count }} registered users.

On {{ workspace.trial_expires_at | date: "%A, %B %d" }}, your background processing jobs will freeze, and API sync endpoints will return 402 Payment Required status codes.

To prevent your operational workflows from pausing, select your subscription tier here:
https://app.yourdomain.com/billing/checkout?src=trial_t3

Need to run an extension to finish your security audit or get procurement approval? Reply to this email with how many days you need, and I will gladly extend your window.

Alex
```

---

### Email 12: The T-1 Day "Imminent Pause" Warning
* **Trigger:** Exactly 24 hours before `workspace.trial_expires_at`.
* **Sender:** `Billing Operations <billing@yourdomain.com>`
* **Subject:** [Action Required] {{ workspace.name }} will pause tomorrow
* **Preview Text:** Final 24 hours to secure your automated pipelines.

```liquid
Hey {{ user.first_name | default: 'there' }},

This is a final operational notice: Your trial expires tomorrow, {{ workspace.trial_expires_at | date: "%B %d at %I:%M %p %Z" }}.

If a payment method is not added before this deadline:
1. Automated syncs will be suspended.
2. Webhook events sent to your ingest URL will fail.
3. Your team invites and access tokens will be temporarily locked.

Select your plan to ensure continuous uptime:
https://app.yourdomain.com/billing/checkout?src=trial_t1_lockout

It takes less than 60 seconds to lock in your tier. You will not lose any configuration, historical data, or API keys.

— YourSaaS Infrastructure Team
```

#### Paired In-App Modal: Day T-1 Interstitial Screen
* **Component:** Full-screen blocking modal on login.
* **Header:** `Your evaluation access expires in 24 hours`
* **Subheader:** `Your live integrations will pause tomorrow unless an active subscription is selected.`
* **Plan Picker Cards:**
  * Card 1: **Starter** | $99/mo | Up to 3 seats | *Select Starter*
  * Card 2: **Pro (Most Popular)** | $249/mo | Up to 10 seats + Webhooks | *Select Pro*
* **Footer Bypass Link:** `I understand my integrations will pause tomorrow. Continue to Dashboard →`

---

### Email 13: Day T-0: The Grace Period Notice
* **Trigger:** At `workspace.trial_expires_at` timestamp.
* **Sender:** `Alex Vance <alex@yourdomain.com>`
* **Subject:** Your workspace has been paused
* **Preview Text:** We have archived your configuration for a 48-hour grace period.

```liquid
{{ user.first_name | default: 'Hey' }},

Your trial has officially completed, and background sync operations for {{ workspace.name }} are now paused.

We understand software procurement can get delayed by internal approvals. To protect your hard work, we placed your workspace in an inactive **Safe Harbor Grace Period**:

- Your integrations, models, and schema configurations are securely preserved.
- We will retain your historical logs for 14 days before queueing them for operational deletion.

To unpause your pipelines and restore immediate access, activate your workspace below:
https://app.yourdomain.com/billing/reactivate?ws={{ workspace.id }}

If you decided not to move forward, could you reply with a single sentence telling me why? Whether it was pricing, missing features, or bad UX, your raw feedback helps our team improve.

Thank you for testing us out,
Alex Vance
```

---

### Email 14: Day T+3 Post-Trial Safe Harbor Sunset
* **Trigger:** 72 hours *after* `workspace.trial_expires_at`.
* **Sender:** `Data Operations <data-ops@yourdomain.com>`
* **Subject:** Data retention policy notice for {{ workspace.name }}
* **Preview Text:** Scheduled deletion of inactive schemas in 7 days.

```liquid
Hey {{ user.first_name | default: 'there' }},

Per our automated data retention policies, inactive trial accounts are queued for cold storage purge 10 days post-expiration.

For {{ workspace.name }}, this purge is scheduled for:
{{ 'now' | date: "%B %d" | advance_days: 7 }}

If you reactivate your subscription prior to this date, your schemas, pipelines, and historical analytics will be instantly restored to production status:
https://app.yourdomain.com/billing/reactivate?ws={{ workspace.id }}&src=data_sunset

If you need a copy of your historical metrics exported into a CSV archive before deletion, log in below and download your compliance export:
https://app.yourdomain.com/settings/compliance/export

Best,
The YourSaaS Engineering Team
```

---

## 6. Inactive Win-Back & Sunset Workflows

For accounts that completed their trial, churned, or abandoned the platform 30 to 60 days ago.

### Email 15: The "Major Feature Release" Reactivation Loop
* **Trigger:** Manual Segment Campaign targeting churned/expired accounts (30–60 days inactive).
* **Sender:** `Product Engineering <updates@yourdomain.com>`
* **Subject:** We completely rebuilt the {{ feature.name }} engine
* **Preview Text:** The performance updates you asked for are now live.

```liquid
Hey {{ user.first_name | default: 'there' }},

When you evaluated YourSaaS earlier this year, our platform struggled with slow synchronization times on massive schemas. 

You and several other teams told us this was a dealbreaker. We listened.

Over the last 6 weeks, our engineering team completely overhauled our sync engine. Here is what changed:
- 10x Ingestion Speeds: Schemas with 1M+ rows now sync in under 4 minutes.
- Native Snowflake & BigQuery Reverse ETL: Zero custom scripts required.
- Granular Role-Based Access Controls: Full support for enterprise enterprise permissions.

We want to give you a chance to see the difference firsthand. 

I've credited your account with a fresh 14-day Pro Trial (no credit card required):
https://app.yourdomain.com/auth/claim-reactivation?token={{ user.reactivation_token }}

Log in and run a test with our new ingestion engine.

Best,
Marcus Brody
Head of Product, YourSaaS
```

---

### Email 16: The Decoupled Sunset/Permission to Close
* **Trigger:** 60 days of zero logins / churned status.
* **Sender:** `Alex Vance <alex@yourdomain.com>`
* **Subject:** Permission to delete your account data?
* **Preview Text:** Confirming deletion of {{ workspace.name }} records.

```liquid
{{ user.first_name | default: 'Hey' }},

I am conducting our quarterly compliance sweep and scrubbing inactive workspaces from our production databases.

Our records indicate you haven't logged into {{ workspace.name }} in over 60 days.

Can I go ahead and permanently purge your configurations, API keys, and collected data?

- If YES: You don't need to do anything. Your records will automatically cycle out of our system by {{ 'now' | date: "%B %d" | advance_days: 5 }}.
- If NO: If you plan on picking this project back up next quarter, click here to prevent deletion and lock your configurations:
https://app.yourdomain.com/settings/keep-alive?token={{ user.keep_alive_token }}

Either way, thank you for checking out our platform.

Alex Vance
CEO
```

---

## 7. Complete In-App Microcopy Swipe Vault

Copy and paste these exact text assets directly into your frontend codebases, component libraries, or headless CMS platforms (Appcues, Chameleon, Pendo).

```
┌────────────────────────────────────────────────────────┐
│  Component: Onboarding Checklist Container             │
├────────────────────────────────────────────────────────┤
│  Title: Getting Started with YourSaaS [ 2 / 4 Done ]  │
│                                                        │
│  [✓] 1. Create your account                            │
│  [✓] 2. Connect primary data source                   │
│  [ ] 3. Run your first baseline analysis   [ Run → ]   │
│  [ ] 4. Invite an operator to your team    [ Invite ]  │
└────────────────────────────────────────────────────────┘
```

### UI Component Matrix: Activation Strings

| UI Placement | Visual State / Trigger | Headline String | Body Copy Micro-String | CTA Primary | CTA Secondary |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Empty State** | User opens Report Tab without any sync setup | `No reports generated yet` | `Connect your data pipelines to trigger your first automated analysis. It takes less than 2 minutes.` | `Connect Pipeline →` | `Load Demo Data` |
| **Empty State** | Team Members directory with 1 seat | `You are flying solo` | `Distributed teams catch configuration anomalies 4x faster. Add your teammates to automate incident notifications.` | `Invite Colleagues` | `View Role Types` |
| **Inline Tooltip** | Hovering over disabled "Run Sync" button | `Sync Unavailable` | `You must add at least 1 validated API credential before executing an on-demand sync.` | `Add Credentials` | None |
| **Sticky Banner** | Trial has 2 days remaining | `2 days remaining on your trial` | `Upgrade to a paid tier today to avoid paused webhooks and scheduled jobs.` | `Upgrade Tier` | `Dismiss` |
| **Input Error State** | Invalid API Token format on Setup | `Invalid Key Format` | `That token does not match the standard 'sk_live_...' prefix. Verify your permissions in your source console.` | `View Docs` | None |
| **Toast Toast** | Core Action Executed Successfully | `Analysis Complete!` | `Your dashboard metrics have been updated to reflect your latest data sync.` | `View Audit Log` | `Close` |
| **Confirmation Drawer** | User attempts to downgrade plan | `Wait—downgrading pauses pipelines` | `Switching to Free will instantly shut down your active webhooks and lock {{ workspace.seat_count }} seats.` | `Keep My Plan` | `Confirm Downgrade` |

### Code Implementation: Global Checklist Component Configuration

```typescript
export const onboardingChecklistConfig = {
  id: "workspace_activation_checklist",
  title: "Complete your production deployment",
  totalSteps: 4,
  dismissable: false,
  steps: [
    {
      id: "step_account_verified",
      title: "Confirm workspace credentials",
      description: "Secure your root account with two-factor authorization.",
      isCompleted: true, // Handled at Auth0 level
      ctaText: "Completed",
      ctaUrl: null,
    },
    {
      id: "step_connect_pipeline",
      title: "Connect your first data source",
      description: "Connect to Stripe, Segment, or a direct Postgres database.",
      isCompleted: false,
      ctaText: "Connect Source →",
      ctaUrl: "/settings/integrations/new",
    },
    {
      id: "step_generate_output",
      title: "Execute automated audit",
      description: "Run your first operational query to populate your production baseline.",
      isCompleted: false,
      ctaText: "Run Audit",
