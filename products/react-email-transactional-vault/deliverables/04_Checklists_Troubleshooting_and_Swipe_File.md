# Module 4: Master Checklists, Audit Rubrics & Reference Swipe File

This module contains production-grade infrastructure configurations, verification rubrics, cross-client rendering fixes, and complete copy swipe assets. Implement these technical specifications directly to secure a 99%+ deliverability profile and render cleanly across legacy and modern mail user agents (MUAs).

---

## 1. DNS Authentication & Protocol Runbook

To guarantee inbox placement across Google Workspace, Microsoft 365, and Yahoo Mail, configure the exact DNS records below. Replace `acmeplatform.com` with your top-level domain and `mail.acmeplatform.com` with your chosen sending subdomain.

### 1.1 Complete DNS Configuration Matrix

| Type | Host / Name | Value / Destination | TTL | Priority / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **TXT** | `mail.acmeplatform.com` | `v=spf1 include:_spf.resend.com ~all` | 3600 | SPF configuration for dedicated sending subdomain. |
| **CNAME** | `resend._domainkey.mail.acmeplatform.com` | `dkim.resend.com.` | 3600 | Primary 2048-bit DKIM selector managed via Resend. |
| **CNAME** | `resend2._domainkey.mail.acmeplatform.com` | `dkim2.resend.com.` | 3600 | Secondary DKIM selector for seamless key rotation. |
| **TXT** | `_dmarc.acmeplatform.com` | `v=DMARC1; p=reject; rua=mailto:dmarc-rua@acmeplatform.com; ruf=mailto:dmarc-ruf@acmeplatform.com; fo=1; adkim=s; aspf=r; pct=100` | 3600 | Apex domain DMARC record enforcing strict DKIM and relaxed SPF. |
| **TXT** | `default._bimi.acmeplatform.com` | `v=BIMI1; l=https://static.acmeplatform.com/brand/bimi-logo.svg; a=https://static.acmeplatform.com/brand/cert.pem` | 3600 | BIMI record pointing to verified SVG-P/S logo and VMC certificate. |
| **MX** | `mail.acmeplatform.com` | `feedback-smtp.resend.com.` | 3600 | Priority: 10. Required for bounce handling and RFC compliance. |

---

### 1.2 DMARC Policy Progression Runbook

Do not deploy `p=reject` immediately on a legacy domain with active email streams. Follow this 4-phase rollout to avoid dropping legitimate operational traffic.

```
PHASE 1: MONITORING (Days 1–14)
└── Record: v=DMARC1; p=none; rua=mailto:dmarc-rua@acmeplatform.com; sp=none; fo=1;
    ├── Action: Ingest aggregate XML reports using an analyzer (e.g., Postmark DMARC, Valimail).
    └── Goal: Identify shadow IT, marketing platforms, and internal services sending on your domain.

PHASE 2: ISOLATION & SPF/DKIM ALIGNMENT (Days 15–30)
└── Record: v=DMARC1; p=none; rua=mailto:dmarc-rua@acmeplatform.com; sp=none; aspf=r; adkim=s;
    ├── Action: Migrate transactional systems to verified subdomains (mail.acmeplatform.com).
    └── Goal: Ensure all sending sources pass DMARC via DKIM alignment.

PHASE 3: QUARANTINE ESCALATION (Days 31–45)
└── Week 5: v=DMARC1; p=quarantine; pct=25; rua=mailto:dmarc-rua@acmeplatform.com;
└── Week 6: v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-rua@acmeplatform.com;
    ├── Action: Divert spoofed and unaligned traffic to recipient Spam/Junk folders.
    └── Goal: Verify zero false-positive drop reports from legitimate customers.

PHASE 4: ENFORCEMENT & BIMI READY (Day 46+)
└── Record: v=DMARC1; p=reject; pct=100; rua=mailto:dmarc-rua@acmeplatform.com; ruf=mailto:dmarc-ruf@acmeplatform.com; fo=1;
    ├── Action: Instruct recipient mail servers to outright reject unauthenticated payloads.
    └── Goal: Absolute domain spoofing protection and eligibility for verified BIMI visual indicators.
```

---

### 1.3 SPF Lookup Limit Hardening (RFC 7208)

The DNS specification limits SPF evaluation to **10 external DNS lookups**. Exceeding this limit causes a `PermError`, forcing modern mail filters to treat the message as unauthenticated.

#### The Problematic Un-Flattened Record (12 Lookups = PermError)
```dns
v=spf1 include:_spf.google.com include:_spf.resend.com include:spf.protection.outlook.com include:servers.mcsv.net include:mailgun.org ~all
```

#### The Production-Engineered Solution
1. **Segregate Sending Domains:** Route high-volume transactional flows to a distinct subdomain (`mail.acmeplatform.com`) and enterprise workspace communication to the apex (`acmeplatform.com`).
2. **Flatten Subnet Blocks:** When multiple vendors must share a domain, resolve the vendor includes into direct CIDR blocks:

```dns
mail.acmeplatform.com. IN TXT "v=spf1 ip4:44.202.169.0/24 ip4:54.240.0.0/18 include:_spf.resend.com -all"
```

*Note: Use hard-fail (`-all`) on dedicated transactional subdomains where every authorized outbound IP is strictly registered.*

---

## 2. 25-Point Deliverability & Anti-Spam Pre-Flight Audit Rubric

Every template deployed to production must clear this rubric. A single `Blocker` failure mandates a release hold.

| # | Category | Audit Point | Acceptance Criteria | Severity |
| :--- | :--- | :--- | :--- | :--- |
| **01** | Auth | SPF Alignment | Envelope-From (Return-Path) domain matches the `From:` header domain or aligns via SPF. | **Blocker** |
| **02** | Auth | DKIM Signature | 2048-bit RSA key; `d=` tag matches sender domain; verification status returns `pass`. | **Blocker** |
| **03** | Auth | DMARC Policy | Domain resolves valid `v=DMARC1` record with active aggregate `rua` reporting. | **Blocker** |
| **04** | Headers | RFC 8058 Compliance | Contains valid `List-Unsubscribe: <https://...>, <mailto:...>` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`. | **Blocker** |
| **05** | Headers | Sender Identity | Friendly name format strictly adheres to: `Acme Platform <security@acmeplatform.com>`. No raw unmapped addresses. | **Warning** |
| **06** | Headers | Reply-To Path | Valid inbound target specified. No unmonitored `noreply@` configurations without auto-responder handlers. | **Warning** |
| **07** | Headers | Message-ID Uniqueness | Fully-qualified domain present in Message-ID (e.g., `<uuid@mail.acmeplatform.com>`). | **Blocker** |
| **08** | Code | MIME Structure | Payload must be `multipart/alternative` containing strictly aligned `text/plain` and `text/html` versions. | **Blocker** |
| **09** | Code | CSS Inlining | Zero linked external stylesheets (`<link rel="stylesheet">`). All rules inlined or nested in safe `<style>` tags. | **Blocker** |
| **10** | Code | Total HTML File Weight | Compiled HTML body size is `< 100 KB` to completely avoid Gmail clipping (`[Message clipped] View entire message`). | **Blocker** |
| **11** | Code | Table Architecture | Tabular data explicitly defines `role="presentation"`, `cellpadding="0"`, `cellspacing="0"`, and `border="0"`. | **Warning** |
| **12** | Links | Tracking Domain SSL | Custom Click Tracking Domain (CNAME) resolves over valid TLS/SSL certificates without mixed-content warnings. | **Blocker** |
| **13** | Links | Link Protocol Consistency | Zero plain HTTP links. Every anchor tag implements explicit HTTPS schemes (`https://`). | **Blocker** |
| **14** | Links | Public Shorteners | Zero presence of bit.ly, tinyurl, or generic shorteners. URL shorteners trigger immediate spam filtering. | **Blocker** |
| **15** | Links | Raw URL Anchor Texts | Anchor text must NOT be a written URL (e.g., `<a href="https://acme.com/a">https://acme.com/b</a>` triggers phishing filters). | **Blocker** |
| **16** | Media | Image Alt Attributes | 100% of `<img>` tags declare informative `alt="..."` descriptions or empty `alt=""` for decorative assets. | **Warning** |
| **17** | Media | Explicit Dimensions | Height and width explicitly declared as HTML attributes and style props on every image to prevent rendering jumps. | **Warning** |
| **18** | Media | Image Hosting Domain | Images served from an isolated, reliable CDN on HTTPS (e.g., `https://static.acmeplatform.com/...`). | **Warning** |
| **19** | Text | Text-to-HTML Ratio | Body payload contains at least 40% meaningful text content relative to underlying HTML markup structure. | **Warning** |
| **20** | Text | High-Risk Keywords | Body and Subject scrubbed of high-frequency spam triggers (e.g., "100% FREE", "GUARANTEED RETURN", "ACT NOW"). | **Blocker** |
| **21** | Legal | Physical Address | Valid physical postal address clearly rendered in the footer layout per CAN-SPAM / GDPR / CASL. | **Blocker** |
| **22** | Dark Mode | High Contrast Ratios | Dark theme foreground and background text combinations maintain minimum WCAG 2.1 AA ratio of 4.5:1. | **Blocker** |
| **23** | Dark Mode | Image Alpha Channels | Dark-colored logos use transparent PNGs with a subtle white halo/outline, or explicit dark mode SVG swapping. | **Warning** |
| **24** | Quality | SpamAssassin Score | Target payload scores `< 1.0` when tested through direct SpamAssassin linting engines. | **Blocker** |
| **25** | System | Idempotency Keys | Sending service passes deterministic idempotency keys to Resend API to prevent duplicate deliveries on retry. | **Blocker** |

---

### 2.1 RFC 8058 One-Click Unsubscribe Implementation

Modern inbox providers (Google & Yahoo) mandate RFC 8058 for high-volume senders. Transactional messages like password resets are exempt, but system notifications, billing summaries, and onboarding digests require these exact headers:

```http
List-Unsubscribe: <https://api.acmeplatform.com/v1/email/unsubscribe?token=d9f82c47a1e2b>, <mailto:unsubscribe@mail.acmeplatform.com?subject=Unsubscribe-d9f82c47a1e2b>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

When the user clicks "Unsubscribe" in their webmail header, the client sends a `POST` request to the HTTPS URI:

```http
POST /v1/email/unsubscribe?token=d9f82c47a1e2b HTTP/1.1
Host: api.acmeplatform.com
Content-Type: application/x-www-form-urlencoded
Content-Length: 26

List-Unsubscribe=One-Click
```

Your server endpoint must handle this `POST` request without requiring authentication or presenting an intermediate confirmation webpage, completing the unsubscription instantly.

---

## 3. Dark Mode Cross-Client Styling Matrix & Rendering Engine

Email clients handle dark mode via three distinct strategies. Understanding these execution models is essential to prevent text invisibility and color distortion.

### 3.1 Client Rendering Strategies

```
┌─────────────────────────┬───────────────────────────────┬────────────────────────────────┐
│ 1. No Color Changes     │ 2. Partial Color Inversion    │ 3. Full / Force Inversion      │
│ (Preserves inline styles│ (Inverts light backgrounds;   │ (Inverts all backgrounds and   │
│ unless media query hit) │  preserves dark elements)     │  flips all text colors blindly)│
├─────────────────────────┼───────────────────────────────┼────────────────────────────────┤
│ • Apple Mail (macOS)    │ • Outlook.com (Web)           │ • Gmail App (Android)          │
│ • Apple Mail (iOS)      │ • Outlook App (iOS & Android) │ • Gmail App (iOS)              │
│                         │ • Gmail (Desktop Web - Dark)  │ • Outlook (Windows MSO Engine) │
└─────────────────────────┴───────────────────────────────┴────────────────────────────────┘
```

### 3.2 The Cross-Client Dark Mode Support Matrix

| Email Client | Engine / Platform | Mode Behavior | Applicable Fix / Hack |
| :--- | :--- | :--- | :--- |
| **Apple Mail** | WebKit (iOS & macOS) | Respects Media Queries fully. | Supports `@media (prefers-color-scheme: dark)`. No destructive force inversions. |
| **Gmail App** | Blink / WebKit (Android/iOS) | Full/Forced Inversion. Ignores `@media` queries in standard styles. | CSS Blend-mode hacks, linear-gradient workarounds, or high-contrast fallback inline styles. |
| **Outlook.com** | Web Browser Engine | Partial Inversion. Converts backgrounds, translates CSS vars. | Target via attributes: `[data-ogsc]` (color) and `[data-ogsb]` (background). |
| **Outlook Desktop** | Word (MSO) Engine (Windows) | Ignores HTML5, CSS media queries, and basic standard flex/grid. | Conditional XML wrappers: `<!--[if mso]>` tables with hardcoded hex backgrounds. |
| **Gmail Web** | Browser Engine (Desktop) | Preserves author styles unless user forces dark browser theme. | Style with high-contrast text that survives background manipulation. |

---

### 3.3 The Universal Production CSS Reset for React Email

Inject this exact CSS payload inside the `<Head>` tag of your React Email root template layout. It targets all major engines, resolves Outlook Web Data Attributes, and prevents Gmail iOS from inverting light text.

```html
<Head>
  <meta name="color-scheme" content="light dark" />
  <meta name="supported-color-schemes" content="light dark" />
  <style>
    {`
      :root {
        color-scheme: light dark;
        supported-color-schemes: light dark;
      }

      /* Base Dark Mode Inversion Styles */
      @media (prefers-color-scheme: dark) {
        .email-body {
          background-color: #0c0d0e !important;
        }
        .surface-card {
          background-color: #16181a !important;
          border-color: #26292b !important;
        }
        .text-primary {
          color: #f1f3f5 !important;
        }
        .text-secondary {
          color: #8c9196 !important;
        }
        .button-primary {
          background-color: #3b82f6 !important;
          color: #ffffff !important;
        }
        /* Asset Swapping */
        .light-mode-logo {
          display: none !important;
        }
        .dark-mode-logo {
          display: block !important;
          max-height: 32px !important;
        }
      }

      /* Outlook Web App (OWA) Dark Mode Targeting */
      [data-ogsc] .email-body {
        background-color: #0c0d0e !important;
      }
      [data-ogsc] .surface-card {
        background-color: #16181a !important;
        border-color: #26292b !important;
      }
      [data-ogsc] .text-primary {
        color: #f1f3f5 !important;
      }
      [data-ogsc] .text-secondary {
        color: #8c9196 !important;
      }
      [data-ogsb] .button-primary {
        background-color: #3b82f6 !important;
      }
      [data-ogsc] .light-mode-logo {
        display: none !important;
      }
      [data-ogsc] .dark-mode-logo {
        display: block !important;
      }
    `}
  </style>
</Head>
```

---

### 3.4 Gmail Forced-Inversion Image Protection Hack

When Gmail forces dark mode on Android and iOS, it can invert dark logos or make black transparent PNGs vanish into dark backgrounds. Use this dual-layer CSS implementation to protect logo assets:

```tsx
import { Img } from "@react-email/components";

export const BrandLogo = () => {
  return (
    <div style={{ display: "inline-block", position: "relative" }}>
      {/* 
        Surround images with an subtle drop-shadow or outline that is invisible on light 
        backgrounds but creates a clean boundary if Gmail forces the canvas black.
      */}
      <Img
        src="https://static.acmeplatform.com/brand/logo-dark-solid.png"
        alt="Acme Platform"
        width={140}
        height={32}
        style={{
          display: "block",
          outline: "none",
          border: "none",
          textDecoration: "none",
          filter: "drop-shadow(0px 0px 1px rgba(255, 255, 255, 0.85))",
        }}
      />
    </div>
  );
};
```

---

## 4. Production Transactional Copy & System Prompt Swipe File

Below are four battle-tested, high-deliverability transactional copy templates followed by an production-ready LLM System Prompt for dynamic generation.

---

### Swipe File 1: Authentication / Magic Link (Zero-Friction Access)

```markdown
From: Acme Platform <auth@mail.acmeplatform.com>
Reply-To: support@acmeplatform.com
Subject: Sign in to Acme Platform (Code: 849-204)
Preview Text: Use your one-time verification link or code to complete sign in. Valid for 15 minutes.

[Header: Acme Platform Logo]

## Verify your sign-in request

We detected a request to sign in to your Acme Platform account associated with alex.turner@enterprise.io.

Use this temporary code to complete the verification flow:

┌──────────────────────────────────────┐
│             849 - 204                │
└──────────────────────────────────────┘

Alternatively, authenticate instantly via this direct authorization button:

[ Sign In to Acme Platform ]
(Target URL: https://acmeplatform.com/api/auth/callback?token=9ab73d8e5f2a1b4c6e8d0f1a3b5c7e9f)

Security Details:
• Timestamp: October 24, 2024 14:32:01 UTC
• IP Address: 198.51.100.42 (San Francisco, CA, US)
• Device / User Agent: Chrome 129.0.0 / macOS Darwin

This verification link expires automatically in 15 minutes and can only be used once. If you did not initiate this authentication request, disregard this email or contact security@acmeplatform.com to terminate active sessions.

---
Acme Platform Inc. • 548 Market St, Suite 32000, San Francisco, CA 94104
Security Alert Infrastructure • Automated notification
```

---

### Swipe File 2: Dunning / Payment Failure (Invoice Grace Period Tier 1)

```markdown
From: Acme Platform Billing <billing@mail.acmeplatform.com>
Reply-To: billing-support@acmeplatform.com
Subject: Action Required: Payment failed for Invoice #INV-83921
Preview Text: We were unable to charge your card ending in 4242. Update your billing details to maintain uninterrupted service.

[Header: Acme Platform Logo]

## Payment Unsuccessful

On October 24, 2024, we attempted to process the scheduled subscription payment for your Acme Platform Enterprise Plan. The payment method on file declined the charge.

Invoice Details:
• Invoice Number: INV-83921-2024
• Amount Due: $499.00 USD
• Failed Payment Method: Visa ending in 4242
• Failure Code: card_declined (insufficient_funds)

Your workspace access remains fully active. We will automatically retry this charge on October 27, 2024. To prevent service disruption, please review and update your payment method:

[ Update Payment Method ]
(Target URL: https://acmeplatform.com/workspaces/acme-corp/billing/payment-methods)

You can also download a copy of the itemized PDF invoice for your finance records directly from your billing portal:
https://acmeplatform.com/workspaces/acme-corp/billing/invoices/INV-83921

If you have questions regarding this charge, reply directly to this email to reach our accounts team.

---
Acme Platform Inc. • 548 Market St, Suite 32000, San Francisco, CA 94104
Billing & Subscription Services
```

---

### Swipe File 3: Security / Suspicious Session Alert

```markdown
From: Acme Security Team <security@mail.acmeplatform.com>
Reply-To: security-ops@acmeplatform.com
Subject: Security Alert: New sign-in detected from unfamiliar location
Preview Text: A new session was established from an unrecognized IP address. Verify this activity now.

[Header: Acme Platform Logo]

## New Sign-In Detected

An active session was established on your Acme account (alex.turner@enterprise.io) from an unrecognized location.

Session Telemetry:
• Time: October 24, 2024 at 09:14:22 UTC
• Location: Frankfurt, Hesse, Germany (Approximate)
• IP Address: 203.0.113.195
• Client Application: Firefox 131.0 on Linux x86_64

Did you authorize this session?

IF THIS WAS YOU:
No action is required. This alert will not trigger again for this device profile.

IF THIS WAS NOT YOU:
Your account credentials may be compromised. Terminate all active sessions and reset your master password immediately via the link below:

[ Terminate All Active Sessions ]
(Target URL: https://acmeplatform.com/account/security/revoke?session_id=sess_9f823a7c81d2)

To secure your workspace, our team recommends enforcing Multi-Factor Authentication (MFA) across your team profiles.

---
Acme Platform Inc. • 548 Market St, Suite 32000, San Francisco, CA 94104
Enterprise Security Operations Center
```

---

### Swipe File 4: Workspace Team Member Invitation

```markdown
From: Sarah Jenkins via Acme Platform <invites@mail.acmeplatform.com>
Reply-To: sarah.jenkins@clientcorp.com
Subject: Sarah Jenkins invited you to collaborate in "Production Core"
Preview Text: Join the Production Core workspace on Acme Platform to access shared infrastructure and deployment pipelines.

[Header: Acme Platform Logo]

## You've been invited to join a workspace

Sarah Jenkins (sarah.jenkins@clientcorp.com) has invited you to collaborate in the **Production Core** workspace on Acme Platform as an **Engineering Member**.

Workspace Details:
• Organization: ClientCorp Global
• Workspace: Production Core
• Role Permissions: Deploy pipelines, configure environment variables, and manage API secrets.

Accept this invitation to link your credentials and access the workspace dashboard:

[ Accept Invitation & Join Workspace ]
(Target URL: https://acmeplatform.com/invitations/accept?token=inv_398a7fbc21d09e&email=alex.turner@enterprise.io)

This invitation was sent directly to alex.turner@enterprise.io and expires on October 31, 2024 (7 days). If you do not know Sarah Jenkins or believe this was sent in error, you can safely ignore this email.

---
Acme Platform Inc. • 548 Market St, Suite 32000, San Francisco, CA 94104
Collaboration & Identity Infrastructure
```

---

### 4.5 LLM System Prompt: Production Transactional Copy Generation

Use this system prompt in automated LLM pipelines (e.g., dynamic alerting, contextual receipts, incident comms) to output clean, deliverability-safe transactional email copy.

```markdown
You are an expert transactional email copywriter and email deliverability architect specializing in high-placement enterprise email communication.

Your task is to write high-converting, accessible, and strictly deliverability-optimized transactional email copy based on incoming structured event data.

CRITICAL RULES AND CONSTRAINTS:
1. DELIVERABILITY SCORING:
   - NEVER use high-risk marketing spam triggers: "100% Free", "Guaranteed", "Act Now", "Limited Time", "Risk-Free", "Buy Now", "Claim Bonus".
   - Keep the Subject Line under 55 characters. It must be informational, accurate, and sober. Include IDs or dynamic contexts when helpful (e.g., "Invoice #1024", "Sign-in verification").
   - Preview Text must be between 40 and 90 characters. It must seamlessly complement the subject line and provide clear context before opening.

2. STRUCTURED SECTIONS REQUIRED IN OUTPUT:
   - Subject Line
   - Preview Text
   - Preheader Spacing Fix (Must indicate spacing implementation)
   - Primary Heading (H1)
   - Core Message Body (Clear, concise, professional)
   - Primary Action CTA (Exact button label and descriptive target URI structure)
   - Supporting Details / Audit Metadata (Key-value pairs for transparency: IP, timestamp, user IDs)
   - Secondary Link / Alternative Path (Plain text alternative for screen readers or broken HTML engines)
   - Footer Compliance Block (Sender legal entity, physical address, and transactional relationship note)

3. TONE & ACCESSIBILITY:
   - Maintain a direct, technical, and respectful tone.
   - Use active voice. Write for scannability using bulleted lists for complex metadata.
   - All CTA button anchor texts must explicitly name the action (NEVER say "Click Here" or "Link"). Use "Sign In to Acme", "View Invoice #INV-123", "Reset Your Password".

OUTPUT FORMAT:
Return pure, valid Markdown only. Do not provide conversational filler or introductory remarks. Execute output strictly inside this format:

### Subject Line:
[Insert Text]

### Preview Text:
[Insert Text]

### Body Copy:
[Insert Markdown Structure]

### Plain Text Version:
[Insert Pure ASCII Text Alternative]
