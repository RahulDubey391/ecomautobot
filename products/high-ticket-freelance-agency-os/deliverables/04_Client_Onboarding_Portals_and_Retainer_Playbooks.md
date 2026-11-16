# Module 4: Client Onboarding Portals, Retainer Retention & Upsell Swipes

---

## 1. The Client Onboarding Engine & Notion Portal Blueprint

A premium onboarding experience establishes authority immediately after contract execution. When high-ticket clients ($20,000 to $100,000+) encounter disorganized onboarding, scope creep and micro-management begin in week one. 

Below is the complete architectural blueprint and copy-paste database schema for the **Client Operations Hub** in Notion.

### Notion Portal Information Architecture

```
[Client Operations Hub: {{client.company_name}} x {{consultant.company_name}}]
├── 01_Project Dashboard (Read/Write)
│   ├── Sprint Tracker (Board View: Backlog, In Progress, Review, Blocked, Deployed)
│   ├── Milestone Roadmap (Timeline View: Grouped by Phase)
│   └── Weekly Status Updates (Gallery View: Weekly Loom + Markdown recaps)
├── 02_Technical Vault (Restricted Permissions: Workspace Admin Only)
│   ├── Environment Credentials & Vault Links (1Password/Bitwarden embeds)
│   ├── Architecture Decision Records (ADRs)
│   └── API Documentation & Schema Registry
├── 03_Commercial & Legal (Read Only)
│   ├── Master Services Agreement (Signed PDF)
│   ├── Active Statement of Work (SOW-{{project.sow_number}})
│   └── Paid Invoices & Receipt Archive (Stripe Invoicing link)
└── 04_Communication & Governance (Read Only)
    ├── Escalation Matrix & Contact SLAs
    └── Change Order Requests (Notion Form View)
```

### Notion Database Schemas

To manually construct or script via Notion API, implement these explicit fields:

#### Database 1: Sprint Deliverables & Tasks (`db_tasks`)

| Property Name | Property Type | Options / Configuration Details |
| :--- | :--- | :--- |
| `Task Name` | Title | Unique deliverable identifier (e.g., `FEAT-102: Auth0 JWT Middleware`) |
| `Status` | Status | `Backlog`, `Ready for Dev`, `In Progress`, `PR Review`, `QA/Staging`, `Done` |
| `Milestone` | Relation | Linked to `db_milestones` |
| `Assignee` | People | Lead Engineer / Client Reviewer |
| `Priority` | Select | `P0 - Blocker` (Red), `P1 - High` (Orange), `P2 - Standard` (Blue) |
| `Sprint` | Select | `Sprint 1`, `Sprint 2`, `Sprint 3`, `Sprint 4` |
| `Target Deploy` | Date | Specific release deadline |
| `PR / Commit Link` | URL | GitHub/GitLab Pull Request URL |
| `Acceptance Criteria` | Text | Gherkin-formatted requirements (`Given / When / Then`) |

#### Database 2: Weekly Status Updates (`db_status_reports`)

| Property Name | Property Type | Options / Configuration Details |
| :--- | :--- | :--- |
| `Report Title` | Title | Format: `Sprint {{number}} Ending {{YYYY-MM-DD}}` |
| `Period` | Date | Sprint Start Date → Sprint End Date |
| `Health Status` | Select | `On Track` (Green), `At Risk` (Yellow), `Blocked` (Red) |
| `Budget Burn` | Number | Format: Currency (`$0,000.00`), Tracks actual spend to date |
| `Executive Video` | URL | Loom / Claap 3-minute executive video walkthrough link |
| `Client Action Items`| Multi-select | `API Keys Pending`, `PR Sign-Off Needed`, `DNS Cutover Approved` |

#### Database 3: Technical Decision Records (`db_adrs`)

| Property Name | Property Type | Options / Configuration Details |
| :--- | :--- | :--- |
| `ADR Number` | Title | Format: `ADR-001: PostgreSQL over MongoDB for Core Billing Engine` |
| `Status` | Select | `Proposed`, `Accepted`, `Superseded`, `Rejected` |
| `Deciders` | Multi-select | Core engineering stakeholders involved |
| `Date Logged` | Date | Date decision was ratified |
| `Impact Scope` | Select | `Database`, `Infrastructure`, `Security`, `API Contract`, `Frontend` |

### Client-Facing Workspace Copy

Paste this directly into the root page of the Notion Portal:

```markdown
# Welcome to the Engineering Operations Hub

**Client:** {{client.company_name}}  
**Lead Consultancy:** {{consultant.company_name}}  
**Primary Architect:** {{consultant.lead_name}} ({{consultant.lead_email}})  
**Target Delivery Window:** {{project.start_date}} – {{project.end_date}}  

---

### Operating Principles
1. **Asynchronous by Default:** All architectural updates, pull requests, and status queries live in this portal. We minimize ad-hoc meetings to protect engineering velocity.
2. **Weekly Cadence:** A compiled sprint video report is published to **01_Project Dashboard > Weekly Status Updates** every Friday by 3:00 PM EST. 
3. **Emergency Escalations:** For complete production outages (P0), see our **Escalation Matrix** in section 04.

---

### Quick Access
- 🚀 **[Active Sprint Board](link_to_view):** Track real-time progress of all ongoing deliverables.
- 🔐 **[Credential Drop](link_to_1password):** Secure 1Password link for sharing production/staging credentials. Never paste secrets directly into Notion.
- 📑 **[Commercial Portal](link_to_billing):** Access paid receipts, change orders, and active SOW documentation.
```

---

## 2. The Zero-Touch Automated Onboarding Sequence & Checklist

When closing high-ticket work, the clock starts the millisecond the contract is executed and the initial deposit clears. Manual back-and-forth for credentials damages credibility. Automate the intake pipeline using the pipeline specifications below.

```
+-----------------------------------------------------------------------------------+
|                            TRIGGER: Stripe Checkout                               |
|                     Event: checkout.session.completed                             |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                        Webhook Listener (Make / Zapier)                           |
|        Filters: payment_status == "paid" AND metadata.type == "sow_deposit"       |
+------------------------------------------+----------------------------------------+
                                           |
                    +----------------------+----------------------+
                    |                      |                      |
                    v                      v                      v
        +-----------------------+ +------------------+ +--------------------+
        |  Step 1: Notion API   | |  Step 2: Slack   | | Step 3: Google Workspace|
        |  Clone Template Portal| |  Create Channel  | | Create Drive Folder |
        |  Set Guest Read/Write | |  Invite Client   | | Set Permissions    |
        +-----------------------+ +------------------+ +--------------------+
                    |                      |                      |
                    +----------------------+----------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                      Step 4: Transactional Email (Postmark)                       |
|               Send Complete Kickoff Package with Magic Login Token                |
+-----------------------------------------------------------------------------------+
```

### The 72-Hour Intake Checklist

| Timeframe | Owner | Action Item | Deliverable / Verification Link |
| :--- | :--- | :--- | :--- |
| **Hour 0–2** | System | Execute webhook: Provision Notion Portal, Slack, and Drive. | Automated email sent containing Portal Magic Link. |
| **Hour 2–24** | Client | Complete Technical Access Form (1Password vault invite). | AWS IAM / GCP, GitHub/GitLab org, Sentry, Cloudflare. |
| **Hour 24–48** | Consultant | Verify, clone, build, and deploy staging "Hello World". | Successful build verification via CI/CD pipeline. |
| **Hour 48–72** | Both | Execute 45-Minute Alignment Session (Agenda below). | Agreed Definition of Done & Sprint 1 scope locked. |

### Technical Access Requirements Checklist

Provide this checklist to the client inside the 1Password / Vault share request:

```markdown
### Critical Infrastructure Access Checklist
Please invite the technical lead account (`{{consultant.tech_admin_email}}`) with the exact permissions below:

- [ ] **GitHub / GitLab:** Add as `Member` with `Maintainer` role on target repositories:
  - Repository 1: `{{client.repo_name_1}}`
  - Repository 2: `{{client.repo_name_2}}`
- [ ] **Cloud Infrastructure (AWS / GCP / Azure):**
  - AWS: Create an IAM user named `dev-consultant-{{consultant.short_code}}` with `ReadOnlyAccess` + Scoped `PowerUserAccess` to designated project stacks (CloudFormation / Terraform).
  - GCP: Assign `Viewer` + `Cloud Build Editor` + `Cloud Run Developer` on project ID: `{{client.gcp_project_id}}`.
- [ ] **Error Monitoring & Analytics:**
  - Datadog / Sentry / New Relic: Invite with `Developer` role to read logs and issue alerts.
- [ ] **Third-Party Services:**
  - Stripe: Invite to `Developers` team role (No access to bank payouts or financial history required).
  - Auth0 / Firebase: Add as `Editor` to project tenant.
- [ ] **DNS Provider (Cloudflare / Route53):**
  - Scoped access to modify `CNAME`, `A`, and `TXT` records for staging domains.
```

### Production Kickoff Email Template

```markdown
To: {{client.primary_contact_email}}
From: {{consultant.lead_email}}
Subject: Kickoff & Technical Infrastructure Setup: {{project.name}}

Hi {{client.first_name}},

The initial deposit for SOW-{{project.sow_number}} has cleared. The build pipeline and infrastructure setup for {{client.company_name}} is now underway.

We operate with zero friction and high velocity. To hit our target deployment date of {{project.target_delivery_date}}, we must complete our technical provisioning within the next 48 hours.

### Step 1: Access Your Notion Operations Hub
All documentation, live sprint boards, pull request links, and weekly asynchronous status updates will live here:
👉 **[Access the {{client.company_name}} Notion Portal]({{portal.notion_magic_url}})**

### Step 2: Secure Technical Access Exchange
Never send credentials, secrets, or keys over Slack or standard email. Please use the secure 1Password vault invite below to share the items identified in our Technical Access Checklist:
👉 **[Secure 1Password Credential Vault]({{portal.onepassword_invite_url}})**

Required within 48 hours:
1. GitHub / GitLab Repository Access (`{{consultant.github_handle}}`)
2. AWS/GCP Staging Environment IAM invitations
3. Third-Party API Sandbox keys (Stripe, Twilio, SendGrid, etc.)

### Step 3: Our Kickoff Call
We have an alignment session scheduled for:
📅 **Date:** {{project.kickoff_datetime}}
🔗 **Google Meet / Zoom:** {{project.kickoff_meeting_link}}

**Agenda:**
- Review of SOW-{{project.sow_number}} Technical Milestones (15 min)
- Validation of credential access, build scripts, and local developer environment (15 min)
- Sprint 1 backlog lock and sprint sign-off criteria (15 min)

If you have any questions before our call, drop them directly into the `#proj-{{client.slack_slug}}` channel we have provisioned for you.

Looking forward to building.

Best regards,

{{consultant.lead_name}}  
Principal Architect, {{consultant.company_name}}  
{{consultant.lead_email}} | {{consultant.phone}}
```

---

## 3. Project-to-Retainer Conversion Playbook & Closing Scripts

The fatal error most tech consultants make is pitching a retainer during the final week of a project. By that point, the client is mentally checking off the deliverable and reallocating remaining budget. 

Retainer seeding must begin at the **75% Milestone Completion Point** via the **Risk Mitigation & Velocity Maintenance** framework.

```
                    PROJECT LIFECYCLE (Weeks 1 - 8)
Week 1             Week 4             Week 6              Week 8
  |------------------|------------------|-------------------|
Intake &        Core Build         The "Seed"         The Conversion
Provisioning    Underway        (75% Mark / Demo)       (Handoff Call)
                                        |                   |
                                        v                   v
                               Identify Ongoing      Present Tiered 
                               Vulnerabilities,      Agreements with
                               CI/CD Maintenance,    Zero-Downtime
                               & Phase 2 Scope       Guarantees
```

### The Retainer Packaging Model

Never bill retainers as "hours per month." High-ticket retainers are sold on **Capacity Access, System Reliability, and Release Velocity.**

| Retainer Tier | Name | Target Price | Core Deliverables / Commitments |
| :--- | :--- | :--- | :--- |
| **Tier 1** | **Infrastructure & SLA Guardianship** | $4,500 / month | - 24/7 P0 Infrastructure Monitoring & Recovery (4-hour SLA)<br>- Core dependency, library, & security patch deployments<br>- Monthly Architecture & Security Audit (Database, AWS/GCP)<br>- Zero active feature development included |
| **Tier 2** | **Continuous Delivery & Feature Velocity** | $8,500 / month | - Everything in Tier 1<br>- Up to 1 Dedicated Engineering Sprint per month (Core features, refactoring)<br>- 1-hour P0 SLA, 4-hour P1 SLA<br>- Weekly status report & architectural consultation |
| **Tier 3** | **Fractional VP of Engineering / Platform Core** | $16,500 / month | - Everything in Tier 2<br>- 2 Dedicated Engineering Sprints per month<br>- Direct architectural leadership & technical interview screening for internal hires<br>- Vendor negotiations (AWS, Datadog, third-party software savings) |

### The Conversion Script (The 75% Mark Demo)

Deliver this script verbatim during the demo where the core functionality of the SOW is proven (usually 2–3 weeks before final cutover):

> **Consultant:** *"Tim, the core payment processing and OAuth engine we scoped in SOW-01 is fully functional on staging. We're on schedule to cut over to production on the 24th.*
>
> *I want to flag something critical as we approach production: Launching this infrastructure is phase one. Maintaining continuous deployment velocity and ensuring zero database or pipeline degradation post-launch is where most companies drop the ball.*
>
> *Once we launch, third-party API dependencies will update, unexpected traffic surges will stress the connection pools, and your internal team shouldn't be context-switching to manage infrastructure when they need to focus on core business operations.*
>
> *We have two options for handling post-launch operations:*
>
> *Option A: We conclude the contract on the 24th. I provide the documentation, package the secrets, and hand the keys over completely. If an outage occurs, an API breaks, or a new deployment fails, you will need to open a formal change order, which requires our standard 14-day scheduling lead time and emergency triage rates ($350/hr).*
>
> *Option B: We roll this engagement seamlessly into our Continuous Delivery Retainer. We maintain direct ownership of the cloud infrastructure, resolve P0 alerts within a one-hour SLA, and run one dedicated sprint every single month so your product roadmap never stalls.*
>
> *I’ve prepared a side-by-side transition outline. Shall I walk you through the coverage tiers so we can guarantee zero downtime after the 24th?"*

### The Written Transition Proposal (Post-Demo Swipe)

Send this email immediately following the demo:

```markdown
To: {{client.primary_contact_email}}
From: {{consultant.lead_email}}
Subject: Post-Launch Transition & Continuity Plan: {{client.company_name}}

Hi {{client.first_name}},

Following our demo today, the core deliverables of SOW-{{project.sow_number}} are on track for production cutover on {{project.cutover_date}}. 

To prevent post-launch operational friction, infrastructure downtime, or product velocity stalls, I have outlined our continuity options below.

### The Problem: Post-Launch Technical Debt & Vulnerability
Now that {{project.name}} is moving into production:
1. **Third-Party API Drift:** Stripe, Auth0, and AWS dependencies update frequently; breaking changes will cause silent pipeline failures if not proactively maintained.
2. **Context Switching:** Diverting your internal team to manage deployments, optimize PostgreSQL queries, and monitor edge functions burns high-value cycles.
3. **Emergency Lead Times:** Under standard terms, post-completion engineering requests carry a 14-day scheduling lead time.

---

### Continuity Retainer Options

#### [Tier 1: Infrastructure & SLA Guardianship] — $4,500 / month
Built for stability. We maintain complete ownership of system health, patch updates, and production uptime.
- **Coverage:** Continuous monitoring, weekly security patching, and dependency updates.
- **SLA:** 4-hour response time for P0 blocking production events.
- **Audits:** Monthly infrastructure cost & query performance optimization.
- *Excludes: New feature builds.*

#### [Tier 2: Continuous Delivery & Feature Velocity] — $8,500 / month *(Recommended)*
Built for roadmaps that cannot pause. Combines system guardianship with steady product expansion.
- **Coverage:** Complete Tier 1 Infrastructure Guardianship.
- **Active Development:** 1 dedicated engineering sprint per month allocated to your backlog (e.g., custom integrations, performance tuning, UI/UX improvements).
- **SLA:** 1-hour response for P0 events; 4-hour response for P1 events.
- **Weekly Reporting:** Asynchronous Loom sprint reviews & real-time board updates.

---

### Implementation Timeline
To ensure zero service interruptions during DNS cutover, we must lock the selection by **{{project.selection_deadline_date}}**. 

Please reply with your selected tier (**Tier 1** or **Tier 2**). I will route a simple 1-page Retainer Addendum through DocuSign, set the automated monthly billing cycle, and ensure engineering continuity without skipping a beat.

Best regards,

{{consultant.lead_name}}  
Principal Architect, {{consultant.company_name}}  
{{consultant.lead_email}}
```

---

## 4. The 4-Tier Late-Payment Dunning System

Late payments are not administrative oversights; they are unsecured loans forced upon your business. This 4-tier dunning engine escalates systematically from automated soft notifications to full infrastructure shutdowns and legal recovery.

```
+-----------------------------------------------------------------------------------+
|                           INVOICE DUE DATE (Day 0)                                |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                     Day +1: Soft Reminder / Card Expired                          |
|                     Tone: Purely operational & collaborative                      |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                     Day +7: Firm Grace Period Expiration                          |
|                     Tone: Formal; flags 1.5% late fee imposition                  |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                     Day +14: Technical Stoppage Warning                           |
|                     Action: Work paused; repos/environments restricted           |
+------------------------------------------+----------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                     Day +30: Legal Notice of Default & Collections                |
|                     Action: Formal acceleration; contract breach notice           |
+-----------------------------------------------------------------------------------+
```

### Technical Enforcement Matrix

| Dunning Stage | Days Past Due | Technical & Operational Action Enforced |
| :--- | :--- | :--- |
| **Stage 1** | **Day +1** | System generates internal warning. Work continues unaffected. |
| **Stage 2** | **Day +7** | Pull requests frozen. Code reviews paused. Sprint demos cancelled. Late fee (1.5%) applied to Stripe account. |
| **Stage 3** | **Day +14** | Complete work stoppage. Read/Write access revoked on GitHub/GitLab. Staging environments placed into maintenance sleep. Notion Portal access converted to "Read-Only (Commercial)". |
| **Stage 4** | **Day +30** | Master Services Agreement formally terminated for material breach. All staged artifacts revoked. IP rights transfer withheld under MSA terms. Forwarded to collections/legal counsel. |

---

### Dunning Email Swipes (Word-For-Word)

#### Stage 1: The Automated Soft Notice (Day +1)

```markdown
To: {{client.primary_contact_email}}
Cc: {{client.accounts_payable_email}}
From: billing@{{consultant.domain}}
Subject: Notice: Invoice #{{invoice.number}} Past Due — {{client.company_name}}

Hi {{client.first_name}},

This is an automated operational notification that Invoice #{{invoice.number}} (Amount: {{invoice.amount_due}}), issued on {{invoice.issue_date}}, was due yesterday, {{invoice.due_date}}.

You can review and settle the invoice immediately via our secure Stripe payment gateway:
👉 **[Pay Invoice #{{invoice.number}}]({{invoice.stripe_payment_url}})**

If your corporate card was recently updated or if this payment is queued in an upcoming AP batch, please let us know the scheduled clearing date so we can update our records.

Thank you for your prompt attention.

Best regards,

**Billing Operations Team**  
{{consultant.company_name}}  
billing@{{consultant.domain}}
```

---

#### Stage 2: The Formal Administrative Escalation (Day +7)

```markdown
To: {{client.primary_contact_email}}
Cc: {{client.accounts_payable_email}}
From: {{consultant.lead_email}}
Subject: Urgent: Overdue Account Status — Invoice #{{invoice.number}} (7 Days Past Due)

Hi {{client.first_name}},

We have not yet received payment or confirmation for Invoice #{{invoice.number}} (Amount: {{invoice.amount_due}}), which is now 7 days past due.

Per Section 4.2 of our Master Services Agreement, accounts more than 7 days overdue are subject to a late charge of 1.5% per month (or the maximum allowed by law) assessed on all outstanding balances. To avoid these fees, please remit payment today:

👉 **[Direct Payment Gateway: Invoice #{{invoice.number}}]({{invoice.stripe_payment_url}})**

Our engineering team is actively deployed on Sprint {{sprint.number}}. However, please be advised that our accounting protocol automatically suspends active pull requests and sprint deployments if accounts reach 14 days past due.

Please confirm by return email that this payment has been processed.

Best regards,

{{consultant.lead_name}}  
Principal Architect, {{consultant.company_name}}  
{{consultant.lead_email}}
```

---

#### Stage 3: Notice of Suspension of Services & Access Revocation (Day +14)

```markdown
To: {{client.primary_contact_email}}
Cc: {{client.accounts_payable_email}}, {{consultant.legal_counsel_email}}
From: {{consultant.lead_email}}
Subject: Notice of Service Suspension: Non-Payment of Invoice #{{invoice.number}}

Dear {{client.first_name}},

As of 5:00 PM EST today, Invoice #{{invoice.number}} for the amount of {{invoice.amount_due}} remains unpaid. This balance is now 14 days overdue.

Effective immediately, {{consultant.company_name}} has initiated technical work stoppage procedures under Section 8.3 of our Master Services Agreement:

1. **Sprint Operations Suspended:** All active feature development, infrastructure deployments, and code reviews are completely frozen.
2. **Access Revocation:** Staging deployment environments have been taken offline, and our team’s engineering commitments are unassigned to other billable client queues.
3. **Schedule Impact:** We can no longer guarantee the target delivery cutover date of {{project.target_delivery_date}}. Resuming work once payment clears will require a minimum 5-business-day rescheduling window.

To restore services and bring your account back into good standing, please pay the outstanding balance immediately via the link below:

👉 **[Settle Outstanding Invoice #{{invoice.number}}]({{invoice.stripe_payment_url}})**

Upon verified clearance of the balance, our environments will be restored, and we will issue an updated sprint delivery schedule.

Sincerely,

{{consultant.lead_name}}  
Principal Architect, {{consultant.company_name}}  
{{consultant.lead_email}}
```

---

#### Stage 4: Formal Legal Default & Acceleration Demand (Day +30)

```markdown
To: {{client.primary_contact_email}}
Cc: {{client.accounts_payable_email}}, {{consultant.legal_counsel_email}}
From: {{consultant.lead_email}}
Subject: FORMAL DEMAND: NOTICE OF MATERIAL BREACH & DEFAULT — {{client.company_name}}

VIA ELECTRONIC TRANSMISSION

Dear {{client.first_name}},

This letter serves as a formal **Notice of Default and Material Breach** of the Master Services Agreement and Statement of Work #{{project.sow_number}} executed between {{client.company_name}} and {{consultant.company_name}}, dated {{project.contract_execution_date}}.

Invoice #{{invoice.number}}, totaling {{invoice.amount_due}} (excluding accumulated late fees of {{invoice.late_fees_accumulated}}), is now **30 days past due**. Multiple formal notifications sent on {{dates.sent_stages_1_2_3}} have been met without resolution or payment.

### Legal Notice & Consequences:
1. **Intellectual Property Withheld:** Per Section 11.2 of the signed MSA, full assignment and transfer of intellectual property rights, licenses, and custom software source code are strictly contingent upon *full and final payment*. No rights, licenses, or code ownership have transferred to {{client.company_name}} for deliverables under SOW-{{project.sow_number}}. Any commercial use, compilation, deployment, or distribution of this code by {{client.company_name}} or its agents constitutes willful copyright infringement.
2. **Acceleration of Balance:** In accordance with the default provisions of our agreement, we demand full payment of the total outstanding sum: **{{invoice.total_amount_plus_fees}}**, within five (5) business days—no later than **{{date.5_business_days_out}} at 5:00 PM EST**.
3. **Escalation to Formal Recovery:** If this balance is not received in full by the deadline above, we will immediately transition this account to our legal representation ({{consultant.law_firm_name}}) to file for judicial debt recovery and seek all available statutory damages, interest, and mandatory attorney fees.

You can settle this balance via wire transfer or credit card immediately using our direct clearing link:
👉 **[Remit Final Balance via Stripe]({{invoice.stripe_payment_url}})**

Wire instructions are attached to this message for immediate execution.

Govern yourself accordingly.

Sincerely,

{{consultant.lead_name}}  
Managing Director & Principal Architect, {{consultant.company_name}}  
{{consultant.lead_email}}

**Enclosure:** Wire Transfer Payment Instructions, Copy of Executed MSA & SOW-{{project.sow_number}}, Invoice #{{invoice.number}} Ledger.
