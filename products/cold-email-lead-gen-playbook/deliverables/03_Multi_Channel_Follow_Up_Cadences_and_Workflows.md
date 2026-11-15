# Module 3: Omnichannel Cadences & Automated Follow-Up Sequences

Single-channel outbound is mathematically inefficient. Across benchmarked campaigns targeting mid-market and enterprise B2B buyers, standalone cold email yields an average 1.8% meeting booking rate. Orchestrating cold email with LinkedIn profile touches, native audio drops, targeted video audits, and structured SMS/phone touchpoints increases aggregate prospect engagement to 6.4%.

This module provides two battle-tested, multi-channel cadences:
1. **The 5-Step "High-Velocity Sprint" (10-Day Window)**: Designed for SMB to Mid-Market targets with shorter sales cycles.
2. **The 8-Step "Enterprise Loom/Video Audit Engine" (21-Day Window)**: Designed for Tier-1 accounts, VPs, and C-Suite buyers with strict deliverability firewalls.

Every step includes literal copy, delivery parameters, timing intervals, and condition gates.

---

## 1. System Architecture & Timing Matrix

Operating multi-channel campaigns requires strict synchronization across platforms (Sales Engagement Platforms like Smartlead/Instantly, LinkedIn automation tools like Heyreach/Expandi, and CRM webhooks).

```
[Day 1: Email 1] ──> (No Reply) ──> [Day 2: LinkedIn Visit + Connect]
                                           │
  ┌────────────────────────────────────────┘
  ▼
[Day 5: Email 2 (Threaded)] ──> (No Reply) ──> [Day 7: LinkedIn Voice Note]
                                                        │
  ┌─────────────────────────────────────────────────────┘
  ▼
[Day 10: Email 3 (Negative Reverse Break-Up)] ──> [Archive / Re-queue in 90 Days]
```

### Channel Execution Rules
* **Email Delays:** Always thread Follow-Up 1 and Follow-Up 2 into the original email by maintaining the exact same `Subject` line with an active `Re:` prefix and populated `In-Reply-To` / `References` headers.
* **LinkedIn Spacing:** Never send a connection request on the exact same minute as an email touch. Insert a 12-to-24-hour buffer to mimic manual research.
* **Daily Limits Per Sender Identity:**
  * Cold Email: 30–35 new contacts/day per secondary domain inbox.
  * LinkedIn: 20 connection requests/day; 25 profile views/day; 15 messages/day.

---

## 2. Cadence 1: The 5-Step "High-Velocity Sprint" (10-Day Window)

**Best for:** Founders, Heads of Sales, VPs of Marketing at companies with 20–250 employees.  
**Objective:** Drive pipeline on a single, focused pain trigger within two business weeks.

### Cadence Schedule

| Step | Day | Channel | Action Type | Goal / Trigger Condition |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Day 1 | Cold Email | Email #1: The Trigger-Event Hook | Land in Primary Inbox; introduce specific friction point. |
| **2** | Day 2 | LinkedIn | Profile View + Blank Connection | Establish visual familiarity before sending a pitch. |
| **3** | Day 5 | Cold Email | Email #2: The Threaded Micro-Asset | Provide direct proof without forcing a phone call. |
| **4** | Day 7 | LinkedIn | Voice DM or Custom Text DM | High-touch personal pattern interrupt. |
| **5** | Day 10 | Cold Email | Email #3: The Value-First Break-Up | Negative reverse close; trigger fear of inaction. |

---

### Step 1 (Day 1) — Cold Email: The Trigger-Event Hook

* **Settings:** Send between 08:15 AM and 09:05 AM in prospect’s local timezone.
* **Thread:** New Thread.

```text
Subject: {{company_name}}'s outbound pipeline / Q3

Hi {{first_name}},

Noticed {{company_name}} recently added 4 account executives to the sales team, but your open SDR roles are still unassigned on LinkedIn.

Usually, when SaaS teams scale AE headcount before outbound SDR capacity is built out, pipeline coverage dips below 3.2x quota within 60 days.

We built an outbound data pipeline that gives your existing AEs 40 verified, in-market accounts every Monday morning—without hiring an agency or adding SDR headcount. 

We helped ScaleOps keep AE pipeline coverage at 3.8x during their team expansion last month.

Open to seeing the 3-minute video breakdown of how the workflow is structured?

Best,
Alex Rivera
Head of Outbound Engineering, RevEngine
```

---

### Step 2 (Day 2) — LinkedIn: Profile View + Connection Strategy

* **Execution Window:** 24 hours after Step 1.
* **Action:**
  1. View the prospect’s profile using an active user session (ensure your headline clearly states your ICP outcome: *"I build cold outbound engines for B2B tech companies"*).
  2. Send connection request.

#### Connection Request Rules:
* **Option A (Higher Acceptance Rate):** Send **completely blank** (no message). This avoids triggering sales radar and yields an average 38–44% acceptance rate.
* **Option B (Contextual Note - use only if prospect explicitly requests context in their profile):**

```text
Hi {{first_name}} — dropped a note to your inbox yesterday regarding AE outbound coverage at {{company_name}}. Figured I'd connect here as well. No pitch here.
```

---

### Step 3 (Day 5) — Cold Email: Threaded Micro-Asset

* **Settings:** Maintain exact subject line: `Re: {{company_name}}'s outbound pipeline / Q3`. Keep threaded to Step 1.
* **Execution Window:** 72 business hours after Step 1.

```text
Hi {{first_name}},

Following up on this with zero fluff. 

Here is the exact data framework we used with ScaleOps to source 18 sales-accepted opportunities in their first 30 days:

1. Scraping job posts for specific hiring signals (hiring AEs before SDRs).
2. Cross-referencing accounts with active intent on G2/Capterra.
3. Waterfall-enriching mobile numbers and verified personal emails through Clay + Datagma.

I drew up the entire pipeline architecture in a 1-page Mermaid diagram:
https://revengine.io/assets/diagrams/ae-outbound-engine

If this is relevant to {{company_name}} right now, let me know and I'll send over the Notion SOP. If not, no worries at all.

Best,
Alex
```

---

### Step 4 (Day 7) — LinkedIn: Voice Note or Short Direct Message

* **Execution Window:** Day 7 (morning, around 11:30 AM local time).
* **Condition Gate:** Check if connection request was accepted.

#### Path A: Prospect Accepted Connection
Open the LinkedIn Mobile App and record a native 30-second **Audio Note**:

```text
(Transcript to read aloud naturally - do NOT sound scripted):
"Hey {{first_name}}, Alex here. Sent an email to your inbox earlier this week with the outbound data diagram we built for ScaleOps. Just wanted to drop a quick voice note to see if pipeline coverage for the new AEs is a priority for you this quarter, or if you're already handling outbound internally? Either way, hope you're having a solid week."
```

#### Path B: Prospect Has NOT Accepted Connection
Execute an **InMail** (if InMail credits are available) or target via LinkedIn Post Engagement:
* Like their most recent post from the last 30 days.
* Leave a value-first comment (minimum 15 words, adding insight—never pitch in public comments).

---

### Step 5 (Day 10) — Cold Email: Value-First Break-Up (Negative Reverse)

* **Settings:** Threaded to Step 1 and Step 3.
* **Objective:** Give the prospect permission to say "no", stripping away sales pressure to prompt a response.

```text
Hi {{first_name}},

I haven't heard back from you, which usually means one of two things:

1. Outbound pipeline coverage is already fully automated for your new AEs, and you're hitting target numbers consistently.
2. You're swamped with other priorities right now and this isn't on your radar.

If it's #1, congratulations—feel free to use that pipeline diagram internally.

If it's #2, I'll close out your file and stop following up so I don't clutter your inbox. 

If priorities change in Q4, you know where to find me.

Best,
Alex Rivera
```

---

## 3. Cadence 2: The 8-Step "Enterprise Loom/Video Audit Engine" (21-Day Window)

**Best for:** VPs, SVPs, and C-Suite leaders at companies with 250–5,000 employees.  
**Deal Size:** $25,000–$150,000 ARR.  
**Execution Objective:** Use custom, unlisted, hyper-targeted 90-second video tear-downs to bypass gatekeepers and command high-level attention.

### Cadence Schedule

| Step | Day | Channel | Action Type | Objective |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Day 1 | LinkedIn | Profile View + Follow | Soft touch on corporate radars. |
| **2** | Day 2 | Cold Email | Email #1: The Video Audit Hook (No Link) | Secure permission to send the personalized audit. |
| **3** | Day 4 | LinkedIn | Connection Request with Shared Context | Low-friction networking hook. |
| **4** | Day 7 | Cold Email | Email #2: Delivery of Unlisted 90s Audit | Deliver custom asset directly to the inbox. |
| **5** | Day 9 | LinkedIn | Follow-Up DM (Referencing Audit) | Omnichannel confirmation of asset delivery. |
| **6** | Day 13 | Cold Email | Email #3: The Executive Peer Case Study | Social proof highlighting enterprise risks of inaction. |
| **7** | Day 17 | Phone/Voicemail | The 20-Second Direct Reference Voicemail | Pattern interrupt referencing video timestamp. |
| **8** | Day 21 | Cold Email | Email #4: The Operational Break-Up | Formal closure of the record; permission to dismiss. |

---

### Step 1 (Day 1) — LinkedIn: Account Warming
* Do not message or pitch.
* Navigate to the target buyer’s LinkedIn profile.
* Click the **"Follow"** button (or "Connect" without a note if follow is unavailable).
* If the prospect published or commented on a post within the last 7 days: Leave an intelligent observation.

---

### Step 2 (Day 2) — Cold Email: The Video Audit Teaser (Permission Hook)

* **Deliverability Strategy:** Do not include a video link in Email 1. Cold links/embedded players in first-touch emails trip spam filters (Google Workspace and Microsoft Defender). Ask for permission first to maintain primary inbox delivery.

```text
Subject: {{first_name}} / your team's SOC2 compliance page

Hi {{first_name}},

Was reviewing {{company_name}}'s public compliance documentation this morning while auditing security postures for enterprise fintech platforms.

Noticed two critical vulnerabilities in the way your sub-processors are mapped that could present flags during enterprise procurement audits (specifically for Fortune 500 bank evaluations).

I recorded a 90-second screen capture running through the exact code blocks and how we remediated this for SecurePay last quarter.

Would you be open to me sending the link over?

Best,
Jordan Vance
Principal Security Architect, TrustShield
```

---

### Step 3 (Day 4) — LinkedIn: Contextual Connection Request

* **Timing:** Morning, 48 hours after Email 1.
* **Character Count:** Under 200 characters.

```text
Hi {{first_name}} — sent an email to your inbox Tuesday about a mapping discrepancy on {{company_name}}'s sub-processor page. Thought I'd connect here as well. Hope the week is going smoothly.
```

---

### Step 4 (Day 7) — Cold Email: Delivery of the 90-Second Custom Audit

* **Settings:** Threaded into original email conversation.
* **Asset Requirement:** An unlisted Loom or Vidyard video.

#### The 90-Second Loom Video Production Script:
* **00:00–00:15 (The Pattern Interrupt):** Have the prospect’s website or specific technical document open on your screen. Do not show your face full screen; show their asset.
  > *"Hi {{first_name}}, Jordan here from TrustShield. I'm looking directly at your vendor documentation page on {{company_name}}.com..."*
* **00:15–00:45 (The Teardown):** Highlight the exact line, graphic, or operational gap.
  > *"Right here under your API sub-processor routing, you have AWS us-east-1 listed without the secondary failover path noted. When a procurement security team at an enterprise buyer runs their automated DDQ, this flags an immediate Tier-2 risk score..."*
* **00:45–01:15 (The Solution/Social Proof):**
  > *"What we did for SecurePay was deploy an automated zero-trust documentation sync that updates these failover architectures dynamically via our API..."*
* **01:15–01:30 (Low-Friction Call to Action):**
  > *"I don't expect you to take my word for it. Check out the link below the video. If you'd like the full remediation script, let me know and I'll send the raw file."*

#### Email Delivery Copy:

```text
Hi {{first_name}},

Didn't hear back, but didn't want this to sit unresolved while you're in active enterprise cycles. 

I uploaded the 90-second teardown to a private link for you:
https://share.vidyard.com/watch/{{prospect_custom_video_id}}

Direct breakdown:
- 0:14: The exact sub-processor misconfiguration.
- 0:48: How this triggers automated procurement rejections.
- 1:12: The 3-line remediation framework.

If you want the raw YAML file to patch this internally, just let me know and I'll send it over.

Best,
Jordan
```

---

### Step 5 (Day 9) — LinkedIn: Executive Follow-Up DM

* **Condition Gate:** Prospect has accepted your connection request.
* **Execution:** Direct message.

```text
Hi {{first_name}} — sent over the sub-processor audit video to your inbox on Thursday. In case it got buried under executive traffic, here is the direct link (90 seconds, no pitch): 

https://share.vidyard.com/watch/{{prospect_custom_video_id}}

Curious if this is already on your engineering roadmap for the current quarter?
```

---

### Step 6 (Day 13) — Cold Email: Enterprise Peer Case Study

* **Settings:** Threaded to existing email sequence.

```text
Hi {{first_name}},

When Datadrive hit 350 employees, their Head of Security, Marcus Chen, was handling enterprise security questionnaires manually—taking 14 business days per deal and stalling enterprise sales velocity.

Within 45 days of deploying TrustShield:
- Questionnaire completion dropped from 14 days to under 4 hours.
- Deal slippage tied to security reviews dropped by 74%.
- They cleared enterprise procurement with J.P. Morgan without a single manual revision.

I put together a 2-page operational study showing how their infrastructure mirrors {{company_name}}'s current setup:
https://trustshield.internal/case-studies/datadrive-architecture

Worth a brief conversation, or is this being resolved through internal engineering?

Best,
Jordan Vance
```

---

### Step 7 (Day 17) — Phone Call / Direct Voicemail Script

* **Execution Window:** Tuesday or Thursday afternoon, 02:00 PM to 04:30 PM prospect local time.
* **Phone Call Protocol:** If they answer, use the Permission-Based Opener. If voicemail, leave this exact 20-second message:

```text
"Hi {{first_name}}, Jordan Vance calling with TrustShield. I sent an unlisted video audit to your email last Thursday regarding the sub-processor security gap on {{company_name}}'s site. 

Reference the 0:48 second mark regarding enterprise procurement reviews. 

My direct number is 415-555-0198. Again, Jordan Vance with TrustShield, 415-555-0198. Dropped a note to your inbox as well."
```

---

### Step 8 (Day 21) — Cold Email: The Operational Break-Up

* **Settings:** Threaded to existing email sequence.
* **Tone:** Professional, objective, closing the loop.

```text
Hi {{first_name}},

I've reached out a few times regarding {{company_name}}'s enterprise compliance documentation and the video audit I shared on the 7th.

Given that I haven't heard back, I'm assuming that enterprise procurement friction isn't a pressing issue for your team right now, or you're handling this through another initiative.

I'm officially closing your file on our end. 

If this becomes a bottleneck for you down the line, feel free to reach back out. 

Wishing you and the {{company_name}} team continued success.

Best regards,
Jordan Vance
Principal Security Architect, TrustShield
```

---

## 4. Advanced Dynamic Variable Dictionary & Liquid Syntax

To execute these multi-channel sequences across hundreds of prospects without breaking personal context, your sales engine must deploy structured Liquid formatting. Use this reference dictionary and logic architecture.

### Variable Mapping Reference Table

| Variable Token | Example Extracted Value | Fallback Condition (If Null) | Use Case |
| :--- | :--- | :--- | :--- |
| `{{first_name}}` | Sarah | "there" | Greeting line personalization |
| `{{company_name}}` | CloudScale | "your team" | Organization reference |
| `{{job_title}}` | VP of Engineering | "leadership team" | Operational authority targeting |
| `{{hiring_signal}}` | adding 4 account executives | scaling your team | Specific trigger event context |
| `{{competitor_reference}}`| Datadrive | industry leaders | Relevant social proof |
| `{{video_id}}` | a8f7b2c9e1 | null (skip step) | Unlisted video routing |

### Liquid Logic Engineering

Place these exact snippets directly inside your sales engagement platform (Instantly, Smartlead, or Clay) to handle incomplete data without operational errors.

#### Dynamic Trigger-Event Sentence:
```liquid
{% if prospect.custom_fields.hiring_signal != blank %}
Noticed {{company_name}} recently experienced {{prospect.custom_fields.hiring_signal}}, which typically impacts execution speed.
{% else %}
Noticed {{company_name}} has been expanding headcount across core teams over the past few months.
{% endif %}
```

#### First Name Capitalization & Fallback Sanitization:
```liquid
Hi {% if prospect.first_name != blank %}{{ prospect.first_name | strip | capitalize }}{% else %}there{% endif %},
```

#### Dynamic Industry Peer Case Study Selector:
```liquid
{% if prospect.industry == "Fintech" %}
We helped SecurePay reduce enterprise procurement review cycles from 14 days down to 4 hours.
{% elsif prospect.industry == "Healthcare" %}
We helped HealthFlow clear HIPAA-compliant vendor reviews with hospital networks 60% faster.
{% else %}
We helped ScaleOps reduce enterprise sales-cycle delays by 74% in their first 45 days.
{% endif %}
```

---

## 5. Automation Webhook Payload: Clay to Smartlead & Heyreach

To run this omnichannel flow without manual data entry, use this webhook architecture. The system orchestrates an email sequence inside Smartlead and simultaneously cues LinkedIn automation in Heyreach/Expandi.

### Webhook JSON Payload (`POST` to Automation Middleware)

```json
{
  "event_type": "prospect_qualified_for_cadence",
  "timestamp": "2024-10-24T14:32:00Z",
  "cadence_id": "cadence_omni_8step_enterprise",
  "prospect": {
    "first_name": "Marcus",
    "last_name": "Chen",
    "email": "mchen@datadrive-example.com",
    "linkedin_url": "https://www.linkedin.com/in/marcuschen-security-leader",
    "company_name": "Datadrive",
    "domain": "datadrive-example.com",
    "title": "Head of Information Security",
    "custom_variables": {
      "video_id": "vid_9942a00c7e2b",
      "hiring_signal": "posting 6 senior engineering roles",
      "industry_peer": "SecurePay",
      "pain_point_trigger": "sub-processor mapping"
    }
  },
  "channel_routing": {
    "email_sender_account": "jordan.vance@trustshield-security.io",
    "linkedin_sender_account_id": "li_seat_88291",
    "delay_step_2_hours": 24,
    "delay_step_3_hours": 72
  }
}
```

### Automation Middleware Routing Logic (Make.com / Zapier / Custom Node.js)

```
[Webhook Received]
       │
       ├─► [Smartlead Module]: Add Lead to Campaign "Enterprise Video Cadence"
       │         └─ Status: Active (Step 1 fires on schedule)
       │
       └─► [Delay Module]: 24 Hours
                 │
                 └─► [Heyreach API Module]: Add Lead to Campaign "Enterprise LinkedIn Flow"
                           └─ Map LinkedIn URL
                           └─ Set Sequence: Step 1 (Profile View) -> Wait 48h -> Step 2 (Connect)
```

---

## 6. Pre-Flight Omnichannel Deployment Checklist

Never launch a multi-channel sequence without verifying every checkpoint below. A failure at any step will cause domain burning, API sequence desynchronization, or embarrassing personalization failures.

```markdown
### Deliverability & Domain Health
- [ ] SPF records explicitly include all active sending IP networks (`v=spf1 include:_spf.google.com ~all`).
- [ ] DKIM 2048-bit keys signed, verified, and passing on all secondary domains.
- [ ] DMARC policy configured (`v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc@yourprimarydomain.com`).
- [ ] Custom Tracking Domain (CTD) configured with active CNAME, validated with SSL active.
- [ ] Daily warmup running for a minimum of 21 consecutive days per inbox; warmup pool reply score > 98%.

### Data Integrity & Variable Hygiene
- [ ] Lead list scrubbed through email verification (NeverBounce, ZeroBounce, or MillionVerifier).
- [ ] Invalid and "Catch-All / Unverifiable" emails filtered out of cold campaigns.
- [ ] Company names sanitized: Removed legal identifiers ("Inc.", "LLC", "Corp.", "GmbH", "Co.").
- [ ] First names sanitized: Removed special characters, trailing spaces, and secondary titles (e.g., "John (MBA)").
- [ ] All custom Liquid fallback tags tested by running a 10-record mock CSV import through the parser.

### Multi-Channel Synchronization
- [ ] Unsubscribe mechanisms active: Functional header unsubscribe configured or standardized opt-out statement included.
- [ ] LinkedIn profile configured with matching professional identity, company branding, and primary value prop headline.
- [ ] Webhook triggers verified with active test payloads between CRM, Clay, and Outreach/Smartlead engines.
- [ ] Auto-stop logic active: System pauses ALL channels (Email, LinkedIn, SMS) immediately upon receiving a reply on ANY single channel.
```

---

## 7. Troubleshooting Matrix: Omnichannel Cadence Bottlenecks

| Symptom | Root Cause | Immediate Remediation |
| :--- | :--- | :--- |
| **High Open Rate (>65%), Zero Replies (<1%)** | Weak Call to Action; friction is too high; value proposition is vague or irrelevant. | Switch from asking for a meeting ("Are you free Tuesday at 2?") to a low-friction resource offer ("Open to seeing the 90-second video?"). |
| **Low Open Rate (<30%)** | Deliverability failure; domain reputation degraded; spam trigger words in subject lines. | Pause sending. Run deliverability audit via MXToolbox/Mail-Tester. Disable open-tracking pixels for 7 days to rebuild reputation. |
| **High LinkedIn Connection Drop (<15%)** | Profile appears overly sales-oriented; connection note is too long or pitches upfront. | Send connection requests **blank** (no text note). Change headline to an objective role description rather than a sales pitch. |
| **Video Audits Ignored (Zero Clicks)** | Video link sent in Email 1 triggering spam filters, or context was missing before sharing the link. | Ask for permission in Email 1 before sending the link. In Email 2, use a high-contrast hyperlinked snapshot showing their specific assets. |
| **Leads Complain of Multi-Channel Spam** | Timing intervals are too compressed; channels are firing at the exact same hour. | Increase spacing to a minimum of 24–48 hours between platform switches. Validate that webhook auto-stop flags trigger within 60 seconds of any prospect reply. |
