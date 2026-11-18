# Module 4: Go-Live Security Checklist, Webhook Debugger & Swipe File

This module is your final defensive perimeter before moving production traffic through Stripe. It provides automated test-clock verification harnesses, cryptographic webhook audits, Strong Customer Authentication (SCA) recovery engines, an edge-case failure triage matrix, and customer-facing recovery communications.

---

## 1. Stripe Test-Clock Simulation Recipes

Never test recurring billing logic against live wall-clock time. The following script provisions an isolated Stripe Test Clock, creates a customer, attaches a metered recurring subscription, and advances time through trial expiration, billing cycles, payment failures, and dunning sequences.

Save this script as `scripts/simulate-billing-lifecycle.ts` and run it via `npx tsx scripts/simulate-billing-lifecycle.ts`.

```typescript
import Stripe from 'stripe';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY as string, {
  apiVersion: '2023-10-16',
  typescript: true,
});

interface SimulationConfig {
  customerEmail: string;
  priceId: string;
  meteredPriceId?: string;
  trialDays: number;
}

async function runBillingLifecycleSimulation(config: SimulationConfig) {
  console.log('🚀 Initializing Stripe Test Clock Simulation...');

  // 1. Create the Test Clock starting at the current Unix timestamp
  const now = Math.floor(Date.now() / 1000);
  const testClock = await stripe.testHelpers.testClocks.create({
    frozen_time: now,
    name: `Lifecycle-Test-${new Date().toISOString()}`,
  });
  console.log(`✅ Test Clock created: ${testClock.id} [Frozen at: ${new Date(now * 1000).toISOString()}]`);

  // 2. Create Customer attached to the Test Clock
  // Using the Stripe test card 'pm_card_chargeCustomerFail' to force dunning failures later,
  // or 'pm_card_visa' for successful initial subscription.
  const customer = await stripe.customers.create({
    email: config.customerEmail,
    payment_method: 'pm_card_visa',
    invoice_settings: {
      default_payment_method: 'pm_card_visa',
    },
    test_clock: testClock.id,
  });
  console.log(`✅ Test Customer created: ${customer.id}`);

  // 3. Create Subscription with a Free Trial
  const subscription = await stripe.subscriptions.create({
    customer: customer.id,
    items: [{ price: config.priceId }],
    trial_period_days: config.trialDays,
    payment_behavior: 'default_incomplete',
    payment_settings: { save_default_payment_method: 'on_subscription' },
    expand: ['latest_invoice.payment_intent'],
  });
  console.log(`✅ Subscription created: ${subscription.id} [Status: ${subscription.status}]`);

  // 4. Advance clock to Trial Expiration (trialDays + 1 hour)
  const trialEndTarget = now + (config.trialDays * 86400) + 3600;
  console.log(`⏳ Advancing clock to Trial Expiration: ${new Date(trialEndTarget * 1000).toISOString()}...`);
  
  let updatedClock = await stripe.testHelpers.testClocks.advance(testClock.id, {
    frozen_time: trialEndTarget,
  });

  await waitForClockAdvancement(updatedClock.id);
  console.log('✅ Clock reached trial expiration. Stripe is generating the first billing cycle invoice.');

  // 5. Swap Payment Method to a failing card to trigger the Dunning Sequence
  await stripe.customers.update(customer.id, {
    invoice_settings: {
      default_payment_method: 'pm_card_chargeCustomerFail',
    },
  });
  console.log('⚠️ Customer default payment method updated to pm_card_chargeCustomerFail.');

  // 6. Advance clock by 30 days to trigger invoice finalization and payment failure
  const renewalTarget = trialEndTarget + (30 * 86400);
  console.log(`⏳ Advancing clock through billing cycle to renewal: ${new Date(renewalTarget * 1000).toISOString()}...`);
  
  updatedClock = await stripe.testHelpers.testClocks.advance(testClock.id, {
    frozen_time: renewalTarget,
  });

  await waitForClockAdvancement(updatedClock.id);

  // 7. Advance time through Smart Retries (Stripe defaults: Day 3, Day 5, Day 7)
  const dunningTarget = renewalTarget + (8 * 86400);
  console.log(`⏳ Advancing clock past dunning window: ${new Date(dunningTarget * 1000).toISOString()}...`);
  
  updatedClock = await stripe.testHelpers.testClocks.advance(testClock.id, {
    frozen_time: dunningTarget,
  });

  await waitForClockAdvancement(updatedClock.id);

  // 8. Fetch final subscription state
  const finalSubscription = await stripe.subscriptions.retrieve(subscription.id);
  console.log(`🏁 Simulation complete.`);
  console.log(`   Final Subscription Status: ${finalSubscription.status}`);
  console.log(`   Check your webhook logs for:`);
  console.log(`   - customer.subscription.trial_will_end`);
  console.log(`   - invoice.created`);
  console.log(`   - invoice.payment_failed`);
  console.log(`   - customer.subscription.updated (past_due)`);
  if (finalSubscription.status === 'canceled') {
    console.log(`   - customer.subscription.deleted`);
  }
}

async function waitForClockAdvancement(clockId: string): Promise<void> {
  let clock = await stripe.testHelpers.testClocks.retrieve(clockId);
  while (clock.status === 'advancing') {
    process.stdout.write('.');
    await new Promise((resolve) => setTimeout(resolve, 2000));
    clock = await stripe.testHelpers.testClocks.retrieve(clockId);
  }
  process.stdout.write('\n');
  if (clock.status === 'internal_failure') {
    throw new Error(`Test clock ${clockId} encountered an internal failure.`);
  }
}

// Execution parameters
runBillingLifecycleSimulation({
  customerEmail: 'billing-simulation-test@yourdomain.com',
  priceId: 'price_1Oxxxxxxxxxxxxxxxxxxxxxx', // Replace with a valid test Price ID
  trialDays: 7,
}).catch((err) => {
  console.error('❌ Simulation failed:', err);
  process.exit(1);
});
```

---

## 2. Production Signature Verification & Cryptographic Audit

Stripe webhooks are vulnerable to replay attacks, payload tampering, and timing attacks if not validated with cryptographic precision.

### The Zero-Vulnerability Raw Buffer Verification Middleware

Common frameworks (Express, Fastify, Next.js) often parse request bodies into JSON before they reach signature verifiers. This alters byte ordering, normalizes whitespace, and breaks signature computation.

Here is the hardened, timing-safe webhook listener for Node.js using raw buffer validation:

```typescript
import express, { Request, Response } from 'express';
import Stripe from 'stripe';
import crypto from 'crypto';

const app = express();
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY as string, {
  apiVersion: '2023-10-16',
});

const WEBHOOK_SECRET = process.env.STRIPE_WEBHOOK_SECRET as string;
const TOLERANCE_SECONDS = 300; // 5-minute replay prevention window

app.post(
  '/api/v1/stripe/webhook',
  express.raw({ type: 'application/json' }), // Retain exact binary buffer
  async (req: Request, res: Response) => {
    const sigHeader = req.headers['stripe-signature'];

    if (!sigHeader || typeof sigHeader !== 'string') {
      console.error('Security Alert: Missing stripe-signature header.');
      return res.status(400).send('Missing signature header.');
    }

    // 1. Manual Cryptographic Audit & Validation Step
    // While stripe.webhooks.constructEvent handles this, understanding the
    // underlying timing-safe check is required to verify custom gateway layers.
    try {
      const parts = sigHeader.split(',');
      const timestampPart = parts.find((p) => p.startsWith('t='));
      const signatureParts = parts.filter((p) => p.startsWith('v1='));

      if (!timestampPart || signatureParts.length === 0) {
        throw new Error('Malformed signature header format.');
      }

      const timestamp = parseInt(timestampPart.split('=')[1], 10);
      const currentTimestamp = Math.floor(Date.now() / 1000);

      // Defend against replay attacks
      if (Math.abs(currentTimestamp - timestamp) > TOLERANCE_SECONDS) {
        console.error(`Replay attack detected. Drift: ${currentTimestamp - timestamp} seconds.`);
        return res.status(400).send('Webhook timestamp outside allowed tolerance window.');
      }

      // Timing-safe verification wrapper
      const event = stripe.webhooks.constructEvent(
        req.body, // Must be the raw Buffer
        sigHeader,
        WEBHOOK_SECRET,
        TOLERANCE_SECONDS
      );

      // 2. Handle Idempotent Routing
      await routeWebhookEvent(event);

      return res.status(200).json({ received: true });
    } catch (err: any) {
      console.error(`Webhook Signature Verification Failed: ${err.message}`);
      return res.status(400).send(`Webhook Error: ${err.message}`);
    }
  }
);

async function routeWebhookEvent(event: Stripe.Event) {
  // Pass to idempotent domain event handler
  console.log(`Processing validated event: ${event.id} [${event.type}]`);
}

export default app;
```

### Signature Verification Security Audit Checklist

| Check | Pass Condition | Failure Action |
| :--- | :--- | :--- |
| **Raw Buffer Preservation** | The exact HTTP request body buffer is fed directly to `constructEvent()`. No `body-parser` or `express.json()` ran beforehand. | Webhook fails with `SignatureVerificationError: No signatures found matching the expected signature for payload`. |
| **Timestamp Drift (Tolerance)** | Event timestamp (`t=`) falls within `|t_now - t_event| <= 300` seconds. | Immediate 400 rejection; log IP and payload as a potential replay attack attempt. |
| **Secret Rotation Readiness** | System can evaluate signatures using an active secret AND a secondary rolled secret simultaneously. | Set up array-based secret validation during secret rotation cycles. |
| **Timing Attack Mitigation** | Signature comparison uses `crypto.timingSafeEqual` over binary buffers, not string `===`. | Prevents side-channel timing analysis that infers valid HMAC signatures byte-by-byte. |
| **Multi-Endpoint Isolation** | Connect/Platform endpoints do not share signature secrets with Direct account endpoints. | Platform and Connect events will throw unparseable signature exceptions if multiplexed. |
| **TLS/SSL Direct Termination** | Reverse proxies (Cloudflare, AWS ALB) must forward the raw body unaltered and preserve Host headers. | Disable automatic minification, JSON pretty-printing, or payload reshaping at proxy level. |

---

## 3. SCA/3D-Secure Compliance & Off-Session Authentication

Strong Customer Authentication (SCA) mandates under PSD2/3DS2 require customer intervention when recurring payments hit merchant-initiated transaction (MIT) triggers, high-risk scoring, or bank mandates. Failing to handle off-session friction drops customer renewals abruptly.

### Production Radar Rules for SaaS Recurring Subscriptions

Configure these exact rules within **Stripe Radar > Rules** to balance conversion against fraud:

1. **Rule: Allow Recurring Merchant-Initiated Payments**
   * *Action:* Allow
   * *Condition:* `:is_off_session: = true AND :is_subscription: = true`
2. **Rule: Force 3DS on High-Risk Initial Checkouts**
   * *Action:* Request 3D Secure
   * *Condition:* `:is_off_session: = false AND :risk_level: = 'elevated'`
3. **Rule: Block Extreme Risk Immediately**
   * *Action:* Block
   * *Condition:* `:risk_score: > 85`
4. **Rule: Challenge Non-SCA Supported Cards on International Purchases**
   * *Action:* Request 3D Secure
   * *Condition:* `! :card_supports_3ds: = false AND :card_country: != :account_country:`

### Off-Session Authentication Webhook Pipeline

When an off-session renewal payment encounters SCA requirements, Stripe marks the invoice as `past_due` and flips the PaymentIntent status to `requires_action`. You must instantly email the customer a direct authentication link.

```typescript
import Stripe from 'stripe';

export async function handleInvoicePaymentActionRequired(
  event: Stripe.InvoicePaymentActionRequiredEvent,
  stripe: Stripe,
  mailer: { sendMail: (opts: any) => Promise<void> }
) {
  const invoice = event.data.object;

  if (!invoice.customer || !invoice.payment_intent) {
    throw new Error(`Invoice ${invoice.id} is missing customer or PaymentIntent references.`);
  }

  // 1. Retrieve the PaymentIntent to inspect required 3DS steps
  const paymentIntentId =
    typeof invoice.payment_intent === 'string'
      ? invoice.payment_intent
      : invoice.payment_intent.id;

  const paymentIntent = await stripe.paymentIntents.retrieve(paymentIntentId);

  if (paymentIntent.status !== 'requires_action') {
    console.log(`PaymentIntent ${paymentIntentId} no longer requires action. Skipping email.`);
    return;
  }

  // 2. Fetch customer details
  const customerId =
    typeof invoice.customer === 'string' ? invoice.customer : invoice.customer.id;
  const customer = await stripe.customers.retrieve(customerId);

  if (customer.deleted) {
    console.warn(`Customer ${customerId} is deleted. Aborting notification.`);
    return;
  }

  const customerEmail = customer.email;
  if (!customerEmail) {
    throw new Error(`Customer ${customerId} has no verified email address on file.`);
  }

  // 3. Extract the Hosted Invoice Authentication URL
  // Stripe automatically injects 3DS confirmation into invoice.hosted_invoice_url
  const authenticationUrl = invoice.hosted_invoice_url;

  if (!authenticationUrl) {
    throw new Error(`Invoice ${invoice.id} does not contain a valid hosted_invoice_url.`);
  }

  // 4. Send Immediate 3DS Action Notification
  await mailer.sendMail({
    to: customerEmail,
    subject: 'Action Required: Confirm your subscription payment',
    template: 'sca-authentication-required',
    context: {
      customerName: customer.name || 'Valued Customer',
      invoiceAmount: (invoice.amount_due / 100).toFixed(2),
      currency: invoice.currency.toUpperCase(),
      authLink: authenticationUrl,
      expiresAt: new Date(paymentIntent.created * 1000 + 86400 * 1000).toLocaleString(),
    },
  });

  console.log(`✅ SCA authentication link dispatched to ${customerEmail} for Invoice ${invoice.id}`);
}
```

---

## 4. Edge-Case Failure Rubrics & Root-Cause Debugger

When recurring billing fails, subtle concurrency bugs or lifecycle state mismatches can cascade through your system. Use this triage table for fast root-cause identification and remediation.

| Symptom / Stripe Error | Exact Blast Radius | Root Cause Analysis | Immediate Resolution Runbook |
| :--- | :--- | :--- | :--- |
| **`invoice.marked_uncollectible`** | Billing halts; subscription remains stuck in `past_due`; customer gets free access if unhandled. | Dunning cycle exhausted all Smart Retries without customer intervention. Stripe marks invoice uncollectible according to Automatic Collection settings. | 1. Update internal tenant status to `SUSPENDED`.<br>2. Call `stripe.subscriptions.cancel(sub_id)` if auto-cancellation is not configured in Dashboard.<br>3. Invalidate user API keys and session tokens. |
| **`card_error: authentication_required`** | Payment failure during background renewal. Invoices flip to `open` with status `past_due`. | European/UK PSD2 regulations requiring SCA/3DS2 on an off-session recurring renewal card. | 1. Catch `invoice.payment_action_required`.<br>2. Route customer directly to `invoice.hosted_invoice_url`.<br>3. Do NOT downgrade the account immediately; apply a 72-hour grace period. |
| **Concurrent Event Race Condition**<br>(`customer.subscription.created` arrives AFTER `customer.subscription.deleted`) | Account is canceled in Stripe, but active in your local database, restoring access indefinitely. | Network transport latency causing out-of-order delivery of webhooks from Stripe's distributed fleet. | 1. Compare the incoming event's `data.object.current_period_end` or `created` timestamp against stored state.<br>2. Use monotonic database versioning (`UPDATE tenants SET status = $1, version = version + 1 WHERE id = $2 AND version < $3`). |
| **Duplicate Invoices for Single Billing Cycle** | Customer gets billed 2x-3x in a single month; support ticket storm; immediate dispute threats. | Application server issued multiple calls to `stripe.invoices.pay()` or non-idempotent line item additions (`stripe.invoiceItems.create`). | 1. Attach `Idempotency-Key: invoice_item_${customerId}_${cycleId}_${featureId}` to every invoice item call.<br>2. Query pending invoice items before writing new ones.<br>3. Immediately issue a refund via `stripe.refunds.create({ charge: chargeId })`. |
| **`invoice.payment_failed` with Zero-Decimal Currency Drift** | Charge fails or charges an amount off by a factor of 100 (e.g., ¥1,000 charged as ¥100,000 or rejected). | Code divides/multiplies by 100 indiscriminately across all currencies. Currencies like JPY, KRW, and UGX have zero decimals. | 1. Implement a decimal normalizer based on Stripe's currency matrix.<br>2. Use `new Intl.NumberFormat` with correct currency specs.<br>3. Never hardcode `/ 100` without currency whitelist checks. |
| **Silent Usage Drift on Metered Subscriptions** | Customer invoiced for $0 despite thousands of API calls, or billed for stale metrics. | Application pushed meter records using timestamps outside the subscription’s `current_period_start` and `current_period_end` boundaries. | 1. Validate `record.timestamp >= sub.current_period_start AND record.timestamp <= sub.current_period_end`.<br>2. For aggregated usage, invoke `stripe.subscriptionItems.createUsageRecord` using `action: 'set'` instead of `'increment'` during reconciliation reconcilers. |
| **Webhook Delivery Timeouts (HTTP 504 / 502)** | Stripe drops webhook deliveries and temporarily disables the webhook endpoint. | Endpoint processes intensive business logic (e.g., generating PDFs, sending emails via SMTP) synchronously before returning HTTP 200. | 1. Push raw event to Redis/SQS queue immediately.<br>2. Return `res.status(200).json({ received: true })` within 500ms.<br>3. Process state changes asynchronously via worker jobs. |

---

## 5. Customer-Facing Dunning & Payment Recovery Swipe File

These battle-tested templates are optimized to recover failed charges while protecting your sender reputation and brand equity. They use clean, plain-text styling to maximize inbox placement across corporate mail filters.

### Template 1: Soft Decline / Temporary Bank Hold (Day 0)
**Subject:** Issue processing your payment for {{ company_name }}  
**Preheader:** Please confirm your payment details to avoid uninterrupted service.  
**Trigger:** `invoice.payment_failed` where `failure_code` = `insufficient_funds` or `try_again_later`.

```text
Hi {{ first_name }},

We were unable to process your scheduled subscription payment of {{ invoice_amount }} for your {{ company_name }} {{ plan_name }} account.

Most often, this is simply due to a temporary hold, an international fraud alert from your bank, or a daily processing limit.

What you should do:
1. Ensure your card has sufficient funds and is authorized for online recurring charges.
2. Update or confirm your card details here:
   {{ hosted_invoice_url }}

We will automatically re-attempt the charge in 48 hours. Your account remains fully active during this time, so your workflows will continue running without interruption.

If you have any questions, reply directly to this email.

Best,
{{ signature_name }}
{{ company_name }}
```

---

### Template 2: Hard Decline / Expired Card (Day 3)
**Subject:** Action required: Your payment method failed for {{ company_name }}  
**Preheader:** Please update your payment method to keep your account active.  
**Trigger:** Second failure or `failure_code` = `expired_card` / `do_not_honor`.

```text
Hi {{ first_name }},

Our attempts to charge your card on file for your {{ company_name }} account ({{ plan_name }}) were unsuccessful.

Invoice: #{{ invoice_number }}
Amount: {{ invoice_amount }} {{ currency }}
Status: Past Due

Your current payment details could not be processed by your bank. To ensure your workspaces and active services are not disrupted, please update your billing method today:

Update Payment Method:
{{ hosted_invoice_url }}

If you need this invoice updated with specific corporate tax or billing information (VAT, GST, PO Number), you can add it directly through that link.

Thank you for your prompt attention to this.

Best,
{{ signature_name }}
{{ company_name }}
```

---

### Template 3: 3D Secure / SCA Action Required (Immediate / Real-Time)
**Subject:** [Action Required] Confirm your {{ company_name }} subscription payment  
**Preheader:** Verification requested by your card provider.  
**Trigger:** `invoice.payment_action_required` webhook.

```text
Hi {{ first_name }},

Your bank requires step-up verification before approving the recurring payment for your {{ company_name }} subscription.

Because of this security requirement, we cannot finalize your payment of {{ invoice_amount }} {{ currency }} automatically.

Please approve the transaction through this secure Stripe authorization link:

Authorize Payment:
{{ hosted_invoice_url }}

This link will take you to your card issuer’s secure confirmation flow (SMS code, banking app push, or biometrics). It only takes a few seconds.

Please complete this verification within 24 hours to prevent your account from entering past-due status.

Best,
{{ signature_name }}
{{ company_name }}
```

---

### Template 4: Final Pre-Suspension Notice (Day 10)
**Subject:** Final Notice: Service suspension for {{ company_name }} in 48 hours  
**Preheader:** Your account will be paused due to an unpaid balance.  
**Trigger:** Terminal dunning attempt reached; 48 hours before setting subscription to `canceled` or uncollectible.

```text
Hi {{ first_name }},

We have reached out several times regarding the unpaid balance of {{ invoice_amount }} on your {{ company_name }} account.

We have still been unable to process this payment, and your account is now 10 days past due.

Unless payment is received within the next 48 hours, we will be forced to suspend your access on {{ suspension_date }}.

Once suspended:
- Your API keys and webhooks will be disabled immediately.
- Background worker jobs and team seats will be locked.
- Data export options will remain restricted until the balance is settled.

To prevent any disruption to your service, please resolve this balance now:

Pay Invoice Immediately:
{{ hosted_invoice_url }}

If you are canceling your account or need an alternative payment method (such as an ACH or wire transfer for an annual billing arrangement), reply to this email right away so we can help.

Best,
{{ signature_name }}
{{ company_name }}
```

---

### Template 5: Grace Period Expired / Account Suspended (Post-Mortem)
**Subject:** Your {{ company_name }} account has been suspended  
**Preheader:** Settle your outstanding invoice to restore access instantly.  
**Trigger:** `customer.subscription.deleted` or application-level account suspension.

```text
Hi {{ first_name }},

As we did not receive payment for invoice #{{ invoice_number }} ({{ invoice_amount }} {{ currency }}), your {{ company_name }} workspace has been suspended.

All active background processing, integrations, and member access are currently paused.

We have saved your account settings and historical data. You can restore your service immediately at any time by paying the outstanding balance:

Reactivate Account:
{{ hosted_invoice_url }}

Once your payment is confirmed, your workspace will be restored automatically within 60 seconds.

If you have questions or believe this was an error, reply directly to this email to reach our support team.

Best,
{{ signature_name }}
{{ company_name }}
```

---

## 6. Pre-Flight Go-Live Verification Runbook

Before you deploy your Stripe billing code to production, walk through this checklist step-by-step:

- [ ] **Live Keys Rotated & Secured:** Ensure live keys (`sk_live_...`, `whsec_...`) are stored in an encrypted secrets manager (e.g., AWS Secrets Manager, Infisical, Doppler) and are not present in your codebase or git history.
- [ ] **Webhook Endpoint URL Configured:** Confirm your live webhook URL is configured in the Stripe Dashboard with strict HTTPS enforcement and points to your production domain.
- [ ] **Event Selection Scoped:** Only subscribe to the webhook events your application actually handles. Do not subscribe to `*` in production.
- [ ] **Idempotency Strategy Live:** Ensure all webhook writes query for existing processed event IDs in your database before executing side effects.
- [ ] **Raw Body Parser Intact:** Ensure no upstream proxy or framework middleware alters the raw request body buffer before signature checking.
- [ ] **Fallback Invoices Configured:** Verify that the Stripe Customer Portal or hosted invoice links are accessible so customers can resolve payment errors without developer intervention.
- [ ] **Customer Metadata Linked:** Every Stripe Customer object must have your internal `userId` or `organizationId` stored in its `metadata` to allow cross-system reconciliation if an email address changes.
