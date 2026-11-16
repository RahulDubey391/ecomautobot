# Module 4: Pre-Flight Launch Checklists, Unit Economics & Churn Defense Playbook

---

## 1. 65-Point Pre-Launch Production Hardening Checklist

Execute every check prior to routing production traffic. Do not skip items under the assumption that early stage implies low risk; technical debt incurred during provisioning compounds immediately upon public indexing.

### Infrastructure, DNS & SSL (Items 1–13)
- [ ] **1. Apex to `www` (or inverse) Canonical Redirect:** Configure strict 301 redirects at the edge (Cloudflare Page Rules or Vercel Edge Middleware) to prevent dual-indexing and cookie fragmentation.
- [ ] **2. Wildcard TLS Provisioning:** Deploy automated Let's Encrypt or Cloudflare Universal SSL certificates with auto-renewal enabled at least 30 days prior to expiration.
- [ ] **3. Strict-Transport-Security (HSTS):** Send header `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` on all secure endpoints.
- [ ] **4. Content Security Policy (CSP):** Implement strict CSP headers blocking unauthorized inline scripts and unauthorized API domain queries:
  ```http
  Content-Security-Policy: default-src 'self'; script-src 'self' https://js.stripe.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https://api.stripe.com https://*.supabase.co; frame-src https://js.stripe.com;
  ```
- [ ] **5. Clickjacking Defense:** Set `X-Frame-Options: DENY` or use CSP `frame-ancestors 'none'` on all authenticated surfaces.
- [ ] **6. MIME Sniffing Defense:** Set `X-Content-Type-Options: nosniff` globally.
- [ ] **7. Referrer Policy:** Send `Referrer-Policy: strict-origin-when-cross-origin` to prevent credential and query-param leaks in outgoing request headers.
- [ ] **8. Edge Rate Limiting:** Enforce a baseline edge throttle (e.g., Cloudflare WAF or `@upstash/ratelimit`) set to 100 requests per minute per IP on public API endpoints and 5 requests per minute on `/auth/*`.
- [ ] **9. Origin IP Masking:** Ensure DNS records routing through Cloudflare/Fastly are proxied (orange-clouded); verify the origin web server refuses all traffic not originating from edge proxy CIDR blocks.
- [ ] **10. Dead Route Pruning:** Audit your router/Next.js/Remix app directory to verify no experimental test endpoints (e.g., `/api/test-db`, `/debug`) are exposed to the public build.
- [ ] **11. DNS TTL Calibration:** Lower DNS record TTLs (A/AAAA/CNAME) to 300 seconds (5 minutes) 48 hours prior to launch to allow rapid IP remediation if infrastructure migration is needed.
- [ ] **12. Compression Layer:** Confirm gzip and Brotli (br) compression are active for responses with MIME types `text/*`, `application/javascript`, and `application/json`.
- [ ] **13. Cold Boot Profiling:** Measure Serverless/Edge Function cold-boot duration. Keep cold boot p95 below 900ms by optimizing external module imports and lazy-loading heavy SDKs.

### Authentication, Authorization & Security (Items 14–26)
- [ ] **14. Cross-Site Scripting (XSS) Session Scrubbing:** Store JWTs and session tokens exclusively in `httpOnly`, `Secure`, `SameSite=Lax` cookies. Never write access tokens to `localStorage` or `sessionStorage`.
- [ ] **15. Cross-Site Request Forgery (CSRF) Defenses:** Protect state-changing mutating routes (POST, PUT, PATCH, DELETE) with anti-CSRF double-submit cookies or standard custom headers (`X-Requested-With`) verified on the server.
- [ ] **16. Row-Level Security (RLS) Enforcement:** For Postgres/Supabase deployments, verify RLS is explicitly turned ON for every single production table:
  ```sql
  ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;
  ```
- [ ] **17. Multi-Tenant Leak Check:** Run automated cross-tenant integration tests. Assert that user $A$ with workspace $W_1$ receives a `404 Not Found` (preferred over `403 Forbidden` to prevent object enumeration) when fetching `/api/v1/workspaces/W_2/documents`.
- [ ] **18. Magic Link Anti-Scanner Protection:** Require users to click a secondary "Confirm Login" button on landing from email magic links, preventing enterprise email scanners (Proofpoint, Barracuda) from prematurely consuming single-use tokens.
- [ ] **19. OAuth Redirect URL Whitelisting:** Audit Google, GitHub, and Twitter developer consoles. Ensure allowed callback URLs use exact domain matching with no unvalidated wildcards (e.g., `https://app.yourdomain.com/api/auth/callback/google` only).
- [ ] **20. Password Hashing Specification:** If managing native passwords, enforce Argon2id (memory cost 64MB, time cost 3 iterations) or bcrypt with minimum 12 salt rounds.
- [ ] **21. Password Reset Token Invalidation:** Invalidate all active user sessions instantly upon a successful password reset event.
- [ ] **22. Privilege Escalation Prevention:** Assert that role assignment fields (e.g., `role: "admin"`) are completely omitted from client-updatable profile schemas (Zod/Valibot payload schemas).
- [ ] **23. Audit Trail Logging:** Write irreversible logs recording user administrative actions: logins, member invitations, credential mutations, and API key generations.
- [ ] **24. API Key Rotation Engine:** Hash client API keys with SHA-256 before storage; display unmasked keys exactly once upon creation to the end-user.
- [ ] **25. Re-authentication on Sensitive Actions:** Require fresh credential entry or webauthn confirmation prior to billing modifications, team deletion, or API token generation.
- [ ] **26. Account Deletion Workflow:** Deploy a working GDPR/CCPA-compliant self-service deletion workflow that scrubs user data from all downstream SaaS dependencies (e.g., CRM, analytics, logs) within 30 days.

### Database, Migrations & State (Items 27–39)
- [ ] **27. Schema Version Control Migration Gate:** Integrate Prisma/Drizzle/Kysely migrations into CI/CD deployment pipelines. Enforce that build scripts fail if unapplied migrations exist.
- [ ] **28. Connection Pool Throttling:** Place an external transaction-mode connection pooler (PgBouncer or Supabase Supavisor) between serverless compute and Postgres to avoid socket exhaustion.
- [ ] **29. Database Query Indexing:** Run `EXPLAIN ANALYZE` on every query feeding core dashboard views. Verify no sequential scans occur on tables exceeding 5,000 rows. Add composite indexes on `(tenant_id, created_at DESC)`.
- [ ] **30. Foreign Key Constraints:** Ensure relational tables enforce cascade logic (`ON DELETE CASCADE` or `ON DELETE SET NULL`) to prevent orphaned rows from crashing join queries.
- [ ] **31. Soft-Delete Scoping:** If soft-deletes are implemented via a `deleted_at` timestamp, ensure all unique constraints include `WHERE deleted_at IS NULL` via partial indexes to allow reuse of unique names/slugs.
- [ ] **32. Prepared Statement Caching:** Configure ORM engines to use prepared statements to protect against SQL injection and optimize query-plan reuse.
- [ ] **33. Point-in-Time Recovery (PITR):** Turn on continuous WAL archiving allowing recovery to any minute in the past 7 days minimum.
- [ ] **34. Backup Restoration Dry Run:** Perform an actual restoration from backup to an isolated staging instance. Measure Time-to-Restore (TTR).
- [ ] **35. Production Seed Verification:** Ensure local mocking/seed scripts (`seed.ts`) cannot execute against production databases by conditioning executions on `NODE_ENV === 'development'`.
- [ ] **36. Unbounded Query Clamping:** Enforce hard pagination limits on all API list queries. Explicitly reject or clamp requests where `limit > 100`.
- [ ] **37. Distributed Locking:** Implement Redis distributed locks (Redlock) or Postgres advisory locks around non-idempotent operations like seat-upgrades or credits-depletion routines.
- [ ] **38. Timezone Normalization:** Enforce UTC for all database engines, server environments, and database timestamp columns (`TIMESTAMPTZ` in Postgres). Never store localized strings.
- [ ] **39. Deadlock Timeout Setting:** Set explicit session query timeouts (`statement_timeout = '15s'`) to kill rogue queries before they exhaust database worker capacity.

### Stripe Billing, Metering & Webhooks (Items 40–52)
- [ ] **40. Webhook Raw Body Preservation:** Capture the raw request payload buffer untouched by JSON parsers for Stripe signature validation:
  ```typescript
  const sig = req.headers['stripe-signature'];
  const event = stripe.webhooks.constructEvent(rawBody, sig, webhookSecret);
  ```
- [ ] **41. Webhook Idempotency Handling:** Store incoming Stripe Event IDs (`event.id`) inside an `idempotency_keys` table. Reject duplicates immediately with an HTTP 200 return to prevent double-provisioning.
- [ ] **42. Webhook Event Replay Resistance:** Reject incoming webhook payloads with timestamps (`event.created`) exceeding 5 minutes from system time.
- [ ] **43. Failed Payment Grace Period:** Implement distinct status logic distinguishing between `past_due` and `unpaid`. Do not immediately delete customer data or lock access on a single failure; enter a 7-day grace period.
- [ ] **44. Tier Limit Enforcement:** Check customer limits on the backend API layer prior to handling core actions (e.g., check available credits or team seats on every object creation attempt, not just in UI logic).
- [ ] **45. Automated Proration Handling:** Configure Stripe Subscription updates with `proration_behavior: 'always_invoice'` or `'create_prorations'` depending on whether mid-cycle adjustments require instant charge settlement.
- [ ] **46. Stripe Customer Portal Synchronization:** Route users to the hosted Stripe Billing Customer Portal for credit card updates, invoicing history, and cancellation flows to avoid building custom billing interfaces.
- [ ] **47. Customer ID Double-Mapping Check:** Link the Stripe Customer ID to your internal Workspace or User ID upon creation, with a unique constraint on `stripe_customer_id` in the database.
- [ ] **48. Invoice Finalization Webhook Hooking:** Subscribe to `invoice.paid`, `invoice.payment_failed`, and `customer.subscription.deleted`. Test all three paths using the Stripe CLI:
  ```bash
  stripe trigger invoice.payment_failed
  ```
- [ ] **49. Zero-Dollar Checkout Routing:** If offering trials without a credit card, bypass Stripe API creation entirely until feature limits are hit or the trial expiration triggers. Avoid creating empty/orphaned Stripe customers.
- [ ] **50. Tax Automation Integration:** Enable Stripe Tax within test mode and confirm correct sales tax/VAT line items attach to checkout sessions based on test customer addresses.
- [ ] **51. Dunning Retry Rules:** Configure Smart Retries inside the Stripe Dashboard (Billing > Retry schedule) utilizing machine learning optimization over a custom 2-week window.
- [ ] **52. Currency Normalization:** Ensure internal ledger balances and checkout pricing are modeled in minimal base units (cents, e.g., `$29.00` is stored as integer `2900`).

### Observability, Logging & Legal/GDPR (Items 53–65)
- [ ] **53. Structured Logging Architecture:** Ensure all server stdout outputs are structured JSON containing `timestamp`, `level`, `trace_id`, `user_id`, and `message`.
- [ ] **54. Sentry/Error Tracking Configuration:** Initialize client and server Sentry (or equivalent) instances. Set production `tracesSampleRate` appropriately (e.g., `0.1` for high-traffic apps, `1.0` for early stage).
- [ ] **55. PII Masking in Logs:** Strip passwords, credit card numbers, authorization headers, and session tokens from reaching log aggregators (e.g., Datadog, Axiom, Betterstack).
- [ ] **56. Uptime Heartbeat Monitoring:** Set up external health-check monitors (Better Uptime, Pingdom) querying an endpoint (`/api/health`) that explicitly executes a trivial query against the database and cache.
- [ ] **57. Production Source Maps Security:** Upload source maps to private error monitoring servers during the build step, and verify they are omitted from the public deployment assets.
- [ ] **58. Terms of Service & Privacy Policy:** Place clear links to active, customized Terms of Service and Privacy Policy pages inside the sign-up flow footer. Include definitions of data processors used.
- [ ] **59. Cookie Consent Implementation:** For EU traffic, implement an explicit opt-in mechanism prior to loading non-essential analytics tracking scripts (e.g., Google Analytics, Meta Pixel).
- [ ] **60. Sub-Processor Registry:** Provide a public or accessible index of all sub-processors (AWS, Cloudflare, Supabase, Stripe, Postmark, Sentry).
- [ ] **61. Automated System Alerts:** Configure alerting channels (PagerDuty or high-priority Slack/Discord webhooks) triggered by: 5xx error spikes (>2% over 5m), edge latencies > 2000ms, and webhook failure events.
- [ ] **62. OpenGraph & Meta Tag Verification:** Validate social sharing previews using the Facebook Sharing Debugger and Twitter Card Validator. Ensure `og:image` dimensions are 1200x630px and served over HTTPS.
- [ ] **63. Robots.txt and Sitemap.xml:** Deploy a dynamic `sitemap.xml` containing clean canonical URLs. Ensure `robots.txt` disallows private routes:
  ```txt
  User-agent: *
  Disallow: /api/
  Disallow: /dashboard/
  Disallow: /settings/
  Allow: /
  Sitemap: https://yourdomain.com/sitemap.xml
  ```
- [ ] **64. Transactional Email Deliverability:** Verify DKIM, SPF, and DMARC DNS records for your transactional email provider (Postmark, Resend). Send a test email to `check-auth@verifier.port25.com` or Mail-Tester; achieve a 10/10 score.
- [ ] **65. Panic Button Killswitch:** Deploy an environment variable-driven maintenance mode flag (`MAINTENANCE_MODE=true`) capable of rendering a static service restoration message edge-wide while rejecting new mutating write operations.

---

## 2. The Production Dunning Sequence (Stripe Webhook Driven)

Failed payments represent immediate, unforced churn. Deploy this technical handling architecture alongside the battle-tested copy sequence to automatically reclaim 40%–60% of failed subscription renewals.

### System Architecture & Trigger Logic

```
   Stripe Event: invoice.payment_failed
                    |
                    v
    [Next.js / Express Webhook Handler]
                    |
        +-----------+-----------+
        | Verify Signature      |
        | Extract: customer_id  |
        | Extract: attempt_count|
        +-----------+-----------+
                    |
      Save state to DB: subscriptions.status = 'past_due'
                    |
      Dispatch to Email Engine (Postmark / Resend)
                    |
        +-----------+-----------+
        | attempt_count === 1  --> Trigger Email 1 (Day 0)
        | attempt_count === 2  --> Trigger Email 2 (Day 3)
        | attempt_count === 3  --> Trigger Email 3 (Day 7)
        | attempt_count === 4  --> Trigger Email 4 (Day 14 - Lockout)
        +-----------------------+
```

#### Node.js Production Webhook Integration
```typescript
import { Request, Response } from 'express';
import Stripe from 'stripe';
import { sendDunningEmail } from './mailer';
import { db } from './db';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2023-10-16',
});

export async function handleStripeWebhook(req: Request, res: Response) {
  const sig = req.headers['stripe-signature'] as string;
  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(
      req.body, // Must be raw Buffer
      sig,
      process.env.STRIPE_WEBHOOK_SECRET!
    );
  } catch (err: any) {
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  if (event.type === 'invoice.payment_failed') {
    const invoice = event.data.object as Stripe.Invoice;
    const customerId = invoice.customer as string;
    const attemptCount = invoice.attempt_count;

    // Fetch user context from database via Stripe customer ID
    const user = await db.user.findUnique({
      where: { stripeCustomerId: customerId },
    });

    if (user) {
      // Generate single-click authenticated Stripe billing portal session
      const portalSession = await stripe.billingPortal.sessions.create({
        customer: customerId,
        return_url: `${process.env.APP_URL}/dashboard/billing`,
      });

      await sendDunningEmail({
        to: user.email,
        name: user.firstName,
        attemptCount: attemptCount,
        updateUrl: portalSession.url,
        invoiceAmount: (invoice.amount_due / 100).toFixed(2),
        currency: invoice.currency.toUpperCase(),
      });
    }
  }

  return res.status(200).json({ received: true });
}
```

---

### Email 1: The Transactional Glitch (Day 0 — Immediate)

*   **Trigger:** Dispatched instantly on the first execution of `invoice.payment_failed` (`attempt_count === 1`).
*   **Tone:** Helpful, objective, non-accusatory. Assumes bank-side security flags or card expiration rather than insolvency.
*   **Sender:** `System Updates <notifications@yourdomain.com>`

```markdown
Subject: Quick heads-up: We couldn't process your payment for {{ plan_name }}

Hi {{ customer.first_name }},

We tried to process your renewal payment of {{ invoice.amount }} {{ invoice.currency }} for your {{ product_name }} workspace, but your card issuer declined the transaction.

This usually happens due to routine security checks, an expired card date, or an updated billing address. 

Your account access remains completely uninterrupted right now. However, Stripe will automatically retry the charge in a few days.

To prevent any service disruptions for you and your team, please take 30 seconds to confirm or update your payment details:

--> Update your payment details: {{ invoice.hosted_invoice_url }}

(This link takes you straight to our secure payment gateway—no login credentials required.)

Best,  
The {{ product_name }} Team
```

---

### Email 2: The Service Continuity Advisory (Day 3)

*   **Trigger:** Dispatched on the second failed attempt (`attempt_count === 2`).
*   **Tone:** Clear, slightly more urgent, focus on utility and operational continuity.
*   **Sender:** `{{ founder_name }} at {{ product_name }} <founder@yourdomain.com>`

```markdown
Subject: Issue updating your {{ product_name }} subscription

Hi {{ customer.first_name }},

I'm writing to you directly because our automated payment retry for your {{ product_name }} account just failed for the second time.

Right now, your workspaces, webhooks, and active integrations are still operational. But because the invoice of {{ invoice.amount }} {{ invoice.currency }} remains unresolved, our system has scheduled your account for automated feature restriction on {{ suspension_date }}.

If you'd like to keep things running smoothly without your pipeline pausing, you can securely refresh your billing information on file here:

--> Refresh Billing Info: {{ invoice.hosted_invoice_url }}

If you have already resolved this with your bank and believe this email crossed paths in error, you can safely disregard this message or reply directly to me.

Regards,  
{{ founder_name }}, Founder & CEO  
{{ product_name }}
```

---

### Email 3: Degradation Warning & Feature Lock Schedule (Day 7)

*   **Trigger:** Dispatched on the third failed attempt (`attempt_count === 3`).
*   **Tone:** Firm, risk-oriented, setting absolute deadlines before destructive actions take place.
*   **Sender:** `{{ product_name }} Billing Desk <support@yourdomain.com>`

```markdown
Subject: Final notice: Your {{ product_name }} access will pause in 48 hours

Hi {{ customer.first_name }},

We haven’t been able to process the outstanding balance of {{ invoice.amount }} {{ invoice.currency }} for your {{ product_name }} workspace. 

Because of this, your account is scheduled for immediate service suspension on {{ suspension_date }}.

Here is what happens when your account is suspended:
- API access keys will immediately return 401 Unauthorized errors.
- Background syncs and scheduled processing pipelines will freeze.
- Your team workspace will switch to read-only mode.

You can prevent this freeze entirely by updating your payment method before {{ suspension_date }}:

--> Restore Full Account Standing: {{ invoice.hosted_invoice_url }}

We hold your system configurations and stored data safely for 14 days following suspension before data archival routines engage. 

If your team is evaluating whether to adjust or cancel this seat, please reply directly to this message so we can pause the automated workflow manually.

The {{ product_name }} Team
```

---

### Email 4: Account Lockout & Archive Initiation (Day 14)

*   **Trigger:** Dispatched on the final failed retry event or subscription state transition to `canceled` / `unpaid`.
*   **Tone:** Off-boarding, calm, emphasizing data integrity, easy reactivation path.
*   **Sender:** `{{ founder_name }} <founder@yourdomain.com>`

```markdown
Subject: Account paused: {{ product_name }} workspace downgraded

Hi {{ customer.first_name }},

Following repeated unsuccessful attempts to renew your subscription, your {{ product_name }} account has been officially paused and converted to restricted read-only mode.

Your active endpoints and automations are no longer processing incoming tasks. 

**What happens to your data?**  
All your records, schemas, and workspace configurations are intact and safely secured in our encrypted storage. We will preserve these snapshots for the next 30 days. On {{ deletion_date }}, unmaintained data snapshots are queued for permanent deletion per our compliance lifecycle.

If you ever wish to restart your workspace, you don't have to rebuild anything from scratch. Simply drop in a valid card and your entire environment will restore instantly:

--> Reactivate Workspace Instantly: {{ invoice.hosted_invoice_url }}

Thank you for building with us so far, {{ customer.first_name }}. If you have any feedback on why {{ product_name }} missed the mark for your team, please let me know—I read and reply to every email personally.

Best,  
{{ founder_name }}
```

---

## 3. Micro-SaaS Unit Economics & Margin Calculator Engine

Building sustainably requires calculating gross margins down to the third decimal point. Do not guess your unit economics; calculate your fully burdened marginal cost of service.

### Financial Formulas
$$\text{COGS} = \text{Infrastructure Compute} + \text{Inference/Third-Party APIs} + \text{Transactional Layer} + \text{Payment Gateway Costs}$$

$$\text{Gross Margin \%} = \frac{\text{Net Revenue} - \text{COGS}}{\text{Net Revenue}} \times 100$$

$$\text{Net Revenue Retention (NRR)} = \frac{\text{Starting ARR} + \text{Expansion} - \text{Contraction} - \text{Churn}}{\text{Starting ARR}} \times 100$$

$$\text{CAC Payback Period (Months)} = \frac{\text{CAC}}{\text{ARPU} \times \text{Gross Margin \%}}$$

$$\text{Customer Lifetime Value (LTV)} = \frac{\text{ARPU} \times \text{Gross Margin \%}}{\text{User Churn Rate (Monthly)}}$$

---

### Target Benchmark Matrix (B2B Micro-SaaS)

| Metric | Danger Level | Healthy Minimum | World Class Target |
| :--- | :--- | :--- | :--- |
| **Gross Margin** | $< 65\%$ | $75\% - 85\%$ | $> 88\%$ |
| **Monthly Churn** | $> 8\%$ | $3\% - 5\%$ | $< 1.5\%$ |
| **CAC Payback Period** | $> 14 \text{ months}$ | $6 - 12 \text{ months}$ | $< 3 \text{ months}$ |
| **LTV : CAC Ratio** | $< 2:1$ | $3:1$ | $> 5:1$ |
| **NRR** | $< 90\%$ | $100\% - 105\%$ | $> 120\%$ |

---

### Executable Node.js Unit Economics Engine

Save this file as `calculate-unit-economics.ts`. Run with `npx ts-node calculate-unit-economics.ts`.

```typescript
interface PlanMetrics {
  planName: string;
  pricePerMonth: number;
  monthlyPaidAcquisitionSpend: number;
  newCustomersPerMonth: number;
  monthlyCustomerChurnRate: number; // Decimal (e.g., 0.04 for 4%)
  expansionRevenuePerMonth: number; // Average expansion per user
  
  // Cost of Goods Sold (COGS) Inputs per user per month
  cogs: {
    serverComputeAndDb: number;
    thirdPartyAPIs: number;     // e.g., OpenAI tokens, webhooks
    transactionalEmails: number; // e.g., Postmark/Resend allocations
    paymentProcessingPercent: number; // Usually 0.029 (2.9%)
    paymentProcessingFixed: number;   // Usually 0.30 ($0.30)
  };
}

interface CalculatedEconomics {
  cogsPerUser: number;
  grossProfitPerUser: number;
  grossMarginPercentage: number;
  blendedCAC: number;
  cacPaybackMonths: number;
  ltvMonths: number;
  ltvGross: number;
  ltvToCacRatio: number;
}

function calculateEconomics(input: PlanMetrics): CalculatedEconomics {
  // 1. Calculate direct variable payment costs
  const paymentFee = (input.pricePerMonth * input.cogs.paymentProcessingPercent) + input.cogs.paymentProcessingFixed;
  
  // 2. Sum up total monthly COGS per active customer
  const totalCogs = 
    input.cogs.serverComputeAndDb +
    input.cogs.thirdPartyAPIs +
    input.cogs.transactionalEmails +
    paymentFee;

  // 3. Profitability Metrics
  const grossProfit = input.pricePerMonth - totalCogs;
  const grossMargin = (grossProfit / input.pricePerMonth) * 100;

  // 4. CAC calculation
  const blendedCAC = input.monthlyPaidAcquisitionSpend / input.newCustomersPerMonth;

  // 5. Payback period in months
  const paybackPeriod = blendedCAC / grossProfit;

  // 6. LTV Calculation based on Gross Profit
  const averageCustomerLifespanMonths = 1 / input.monthlyCustomerChurnRate;
  const ltv = grossProfit * averageCustomerLifespanMonths;
  const ltvToCac = ltv / blendedCAC;

  return {
    cogsPerUser: Number(totalCogs.toFixed(2)),
    grossProfitPerUser: Number(grossProfit.toFixed(2)),
    grossMarginPercentage: Number(grossMargin.toFixed(2)),
    blendedCAC: Number(blendedCAC.toFixed(2)),
    cacPaybackMonths: Number(paybackPeriod.toFixed(2)),
    ltvMonths: Number(averageCustomerLifespanMonths.toFixed(1)),
    ltvGross: Number(ltv.toFixed(2)),
    ltvToCacRatio: Number(ltvToCac.toFixed(2)),
  };
}

// Concrete execution example: $49/month AI-augmented SaaS product
const currentProductRun: PlanMetrics = {
  planName: 'Pro Tier ($49/mo)',
  pricePerMonth: 49.00,
  monthlyPaidAcquisitionSpend: 1200.00,
  newCustomersPerMonth: 30,
  monthlyCustomerChurnRate: 0.045, // 4.5% monthly churn
  expansionRevenuePerMonth: 2.50,
  cogs: {
    serverComputeAndDb: 1.20,
    thirdPartyAPIs: 3.80,       // Model calls (LLMs/Vector DB)
    transactionalEmails: 0.15,
    paymentProcessingPercent: 0.029,
    paymentProcessingFixed: 0.30,
  },
};

const results = calculateEconomics(currentProductRun);

console.log(`=== UNIT ECONOMICS REPORT: ${currentProductRun.planName} ===`);
console.log(`Total Direct COGS/User:   $${results.cogsPerUser}`);
console.log(`Gross Profit/User:         $${results.grossProfitPerUser}`);
console.log(`Gross Margin:              ${results.grossMarginPercentage}%`);
console.log(`Blended CAC:               $${results.blendedCAC}`);
console.log(`Payback Period:            ${results.cacPaybackMonths} Months`);
console.log(`Average User Lifespan:     ${results.ltvMonths} Months`);
console.log(`Gross Customer LTV:        $${results.
