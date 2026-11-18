# Module 3: Advanced Proration, Seat-Based Billing & Churn Flows

Handling mid-cycle subscription changes, dynamic seat adjustments, and involuntary churn requires strict adherence to double-entry accounting principles and deterministic state machine design. This module provides the exact mathematical framework, production TypeScript transition engines, preview services, and multi-tier dunning automations needed to manage mid-cycle billing without financial discrepancies or race conditions.

---

## 1. Mid-Cycle Proration Architecture & Financial Mechanics

When a customer upgrades, downgrades, or modifies seat allocations mid-cycle, Stripe calculates proration using second-level timestamp precision:

$$\text{Proration Factor} = \frac{T_{\text{remaining}}}{T_{\text{period}}} = \frac{t_{\text{period\_end}} - t_{\text{event}}}{t_{\text{period\_end}} - t_{\text{period\_start}}}$$

$$\text{Proration Credit} = -1 \times (\text{Price}_{\text{old}} \times \text{Quantity}_{\text{old}} \times \text{Proration Factor})$$

$$\text{Proration Charge} = \text{Price}_{\text{new}} \times \text{Quantity}_{\text{new}} \times \text{Proration Factor}$$

$$\text{Net Due Now} = \max(0, \text{Proration Credit} + \text{Proration Charge})$$

If $\text{Net Due Now} < 0$, the remaining balance becomes a negative customer balance credited against future invoices.

### Transition Behavior Matrix

| Transition Scenario | Proration Setting | Invoice Timing | Stripe Collection Method | Customer UX Expectation |
| :--- | :--- | :--- | :--- | :--- |
| **Upgrade Tier (e.g., Growth to Enterprise)** | `always_invoice` | Immediate (`create_prorations`) | `charge_automatically` | Instant access; immediate debit of prorated delta. |
| **Add Seats Mid-Cycle** | `always_invoice` | Immediate (`create_prorations`) | `charge_automatically` | Instant seat provisioning; immediate charge for remainder of billing cycle. |
| **Remove Seats Mid-Cycle** | `create_prorations` | Next Period Anchor | Applied to next invoice | Seat deprovisioned; credit balance applied to future invoice. |
| **Downgrade Tier (e.g., Enterprise to Growth)** | `none` | Cycle End Anchor (`cancel_at_period_end` or schedule) | Next billing cycle | Customer retains higher tier until cycle finishes; no refund/credit calculated. |
| **Seat Reduction with Negative Net** | `always_invoice` | Immediate (`create_prorations`) | Invoice created with $0 balance; excess credited to Stripe Customer Balance | Immediate reconciliation; credit reflects on billing dashboard. |

---

## 2. Real-Time Proration Preview Engine

Never let a customer execute an upgrade or seat expansion without inspecting the exact invoice impact first. The following service retrieves a zero-side-effect preview of the invoice that Stripe will generate upon modification.

```typescript
// services/billing/proration-preview.service.ts
import Stripe from 'stripe';

export interface ProrationPreviewRequest {
  stripeCustomerId: string;
  subscriptionId: string;
  newPriceId: string;
  newQuantity: number;
  prorationDate?: number; // Epoch seconds
}

export interface ProrationPreviewResult {
  amountDue: number; // In cents
  creditAmount: number; // In cents
  chargeAmount: number; // In cents
  prorationDate: number;
  currency: string;
  lineItems: Array<{
    description: string;
    amount: number;
    isProration: boolean;
  }>;
}

export class ProrationPreviewService {
  constructor(private readonly stripe: Stripe) {}

  public async getProrationPreview(
    params: ProrationPreviewRequest
  ): Promise<ProrationPreviewResult> {
    const { stripeCustomerId, subscriptionId, newPriceId, newQuantity } = params;
    
    // Pin the timestamp to prevent drift between preview and execution
    const prorationDate = params.prorationDate || Math.floor(Date.now() / 1000);

    const subscription = await this.stripe.subscriptions.retrieve(subscriptionId);
    
    // Locate the primary subscription item (plan/seats)
    const primaryItem = subscription.items.data[0];
    if (!primaryItem) {
      throw new Error(`Subscription ${subscriptionId} has no billable line items.`);
    }

    // Generate upcoming invoice preview with overridden state
    const upcomingInvoice = await this.stripe.invoices.createPreview({
      customer: stripeCustomerId,
      subscription: subscriptionId,
      subscription_details: {
        items: [
          {
            id: primaryItem.id,
            price: newPriceId,
            quantity: newQuantity,
          },
        ],
        proration_date: prorationDate,
        proration_behavior: 'create_prorations',
      },
    });

    let creditAmount = 0;
    let chargeAmount = 0;

    const lineItems = upcomingInvoice.lines.data.map((line) => {
      const isProration = line.parent?.type === 'invoice_item_proration' || 
                          (line.description?.toLowerCase().includes('proration') ?? false);
      
      if (line.amount < 0) {
        creditAmount += Math.abs(line.amount);
      } else {
        chargeAmount += line.amount;
      }

      return {
        description: line.description || 'Prorated adjustment',
        amount: line.amount,
        isProration,
      };
    });

    return {
      amountDue: upcomingInvoice.amount_due,
      creditAmount,
      chargeAmount,
      prorationDate,
      currency: upcomingInvoice.currency,
      lineItems,
    };
  }
}
```

---

## 3. Production Mid-Cycle Subscription Transition Engine

This execution engine handles both immediate upgrades and scheduled downgrades, applying atomic idempotency keys and metadata tracing.

```typescript
// services/billing/subscription-transition.engine.ts
import Stripe from 'stripe';
import { db } from '@/lib/db'; // Your Prisma/Drizzle/Kysely database client
import { subscriptions, auditLogs } from '@/lib/db/schema';
import { eq } from 'drizzle-orm';

export interface ExecuteTransitionParams {
  organizationId: string;
  subscriptionId: string;
  targetPriceId: string;
  targetQuantity: number;
  prorationDate?: number;
  idempotencyKey: string;
}

export class SubscriptionTransitionEngine {
  constructor(private readonly stripe: Stripe) {}

  public async executeTransition(params: ExecuteTransitionParams): Promise<{
    status: 'succeeded' | 'scheduled' | 'requires_action';
    invoiceId?: string;
    clientSecret?: string;
  }> {
    const {
      organizationId,
      subscriptionId,
      targetPriceId,
      targetQuantity,
      prorationDate = Math.floor(Date.now() / 1000),
      idempotencyKey,
    } = params;

    // 1. Fetch current subscription state
    const currentSub = await this.stripe.subscriptions.retrieve(subscriptionId);
    const primaryItem = currentSub.items.data[0];

    if (!primaryItem) {
      throw new Error(`Target subscription ${subscriptionId} contains no items.`);
    }

    const currentPriceId = primaryItem.price.id;
    const currentQuantity = primaryItem.quantity || 1;

    // 2. Fetch prices to determine upgrade vs downgrade
    const [currentPriceObj, targetPriceObj] = await Promise.all([
      this.stripe.prices.retrieve(currentPriceId),
      this.stripe.prices.retrieve(targetPriceId),
    ]);

    const isDowngrade = (targetPriceObj.unit_amount || 0) < (currentPriceObj.unit_amount || 0) ||
      ((targetPriceObj.unit_amount || 0) === (currentPriceObj.unit_amount || 0) && targetQuantity < currentQuantity);

    if (isDowngrade) {
      // 3A. Downgrades execute at the end of the current period to prevent clawbacks
      await this.handleDowngrade(subscriptionId, primaryItem.id, targetPriceId, targetQuantity, idempotencyKey);
      
      await db.update(subscriptions)
        .set({
          pendingPriceId: targetPriceId,
          pendingQuantity: targetQuantity,
          changeScheduledAt: new Date(),
        })
        .where(eq(subscriptions.stripeSubscriptionId, subscriptionId));

      return { status: 'scheduled' };
    }

    // 3B. Upgrades execute immediately with proration and explicit invoice finalization
    const updatedSub = await this.stripe.subscriptions.update(
      subscriptionId,
      {
        items: [
          {
            id: primaryItem.id,
            price: targetPriceId,
            quantity: targetQuantity,
          },
        ],
        proration_behavior: 'always_invoice',
        proration_date: prorationDate,
        payment_behavior: 'error_if_incomplete',
        expand: ['latest_invoice.payment_intent'],
      },
      { idempotencyKey }
    );

    const latestInvoice = updatedSub.latest_invoice as Stripe.Invoice | null;
    const paymentIntent = latestInvoice?.payment_intent as Stripe.PaymentIntent | null;

    if (paymentIntent && paymentIntent.status === 'requires_action') {
      return {
        status: 'requires_action',
        invoiceId: latestInvoice?.id,
        clientSecret: paymentIntent.client_secret || undefined,
      };
    }

    // 4. Update internal database state
    await db.transaction(async (tx) => {
      await tx.update(subscriptions)
        .set({
          stripePriceId: targetPriceId,
          quantity: targetQuantity,
          status: updatedSub.status,
          updatedAt: new Date(),
        })
        .where(eq(subscriptions.stripeSubscriptionId, subscriptionId));

      await tx.insert(auditLogs).values({
        organizationId,
        action: 'SUBSCRIPTION_UPGRADED',
        details: JSON.stringify({
          oldPriceId: currentPriceId,
          newPriceId: targetPriceId,
          oldQuantity: currentQuantity,
          newQuantity: targetQuantity,
          prorationDate,
          invoiceId: latestInvoice?.id,
        }),
        createdAt: new Date(),
      });
    });

    return {
      status: 'succeeded',
      invoiceId: latestInvoice?.id,
    };
  }

  private async handleDowngrade(
    subscriptionId: string,
    subscriptionItemId: string,
    targetPriceId: string,
    targetQuantity: number,
    idempotencyKey: string
  ): Promise<void> {
    // Utilize Subscription Schedules to accurately transition at the cycle boundary
    let schedules = await this.stripe.subscriptionSchedules.list({
      subscription: subscriptionId,
      limit: 1,
    });

    let schedule: Stripe.SubscriptionSchedule;

    if (schedules.data.length === 0) {
      schedule = await this.stripe.subscriptionSchedules.create(
        { from_subscription: subscriptionId },
        { idempotencyKey: `sched_create_${idempotencyKey}` }
      );
    } else {
      schedule = schedules.data[0];
    }

    const currentPhase = schedule.phases[0];

    await this.stripe.subscriptionSchedules.update(
      schedule.id,
      {
        end_behavior: 'release',
        phases: [
          {
            items: currentPhase.items.map((item) => ({
              price: item.price as string,
              quantity: item.quantity,
            })),
            start_date: currentPhase.start_date,
            end_date: currentPhase.end_date,
          },
          {
            items: [
              {
                price: targetPriceId,
                quantity: targetQuantity,
              },
            ],
            iterations: 1,
          },
        ],
      },
      { idempotencyKey: `sched_update_${idempotencyKey}` }
    );
  }
}
```

---

## 4. Seat Allocation State Machine & Schema

To track seats, licenses, and mid-cycle increments without causing data drift between the operational database and Stripe, use the following database schema.

```sql
-- DDL for PostgreSQL / Supabase / Neon
CREATE TYPE subscription_status AS ENUM (
  'trialing',
  'active',
  'past_due',
  'canceled',
  'unpaid',
  'incomplete',
  'in_grace_period'
);

CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  stripe_customer_id VARCHAR(255) NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  stripe_subscription_id VARCHAR(255) NOT NULL UNIQUE,
  stripe_price_id VARCHAR(255) NOT NULL,
  status subscription_status NOT NULL DEFAULT 'active',
  allocated_seats INT NOT NULL DEFAULT 1,
  pending_price_id VARCHAR(255),
  pending_seats INT,
  current_period_start TIMESTAMPTZ NOT NULL,
  current_period_end TIMESTAMPTZ NOT NULL,
  grace_period_ends_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE seat_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_email VARCHAR(255) NOT NULL,
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, user_email)
);

CREATE INDEX idx_subscriptions_org ON subscriptions(organization_id);
CREATE INDEX idx_seat_assignments_org ON seat_assignments(organization_id);
```

### Deterministic Seat Allocation Guard

```typescript
// services/billing/seat-manager.service.ts
import { db } from '@/lib/db';
import { subscriptions, seat_assignments } from '@/lib/db/schema';
import { eq, sql } from 'drizzle-orm';
import { SubscriptionTransitionEngine } from './subscription-transition.engine';

export class SeatManagerService {
  constructor(private readonly transitionEngine: SubscriptionTransitionEngine) {}

  public async assignSeat(organizationId: string, email: string): Promise<void> {
    await db.transaction(async (tx) => {
      // 1. Lock subscription row to prevent concurrent assignment race conditions
      const [sub] = await tx
        .select()
        .from(subscriptions)
        .where(eq(subscriptions.organizationId, organizationId))
        .for('update');

      if (!sub) throw new Error('No subscription found for organization.');

      // 2. Count current consumed seats
      const [{ count }] = await tx
        .select({ count: sql<number>`count(*)::int` })
        .from(seat_assignments)
        .where(eq(seat_assignments.organizationId, organizationId));

      if (count >= sub.allocatedSeats) {
        // Automatically expand seats by 1
        const newAllocatedSeats = sub.allocatedSeats + 1;
        
        await this.transitionEngine.executeTransition({
          organizationId,
          subscriptionId: sub.stripeSubscriptionId,
          targetPriceId: sub.stripePriceId,
          targetQuantity: newAllocatedSeats,
          idempotencyKey: `auto_seat_${organizationId}_${newAllocatedSeats}_${Date.now()}`,
        });

        await tx
          .update(subscriptions)
          .set({ allocatedSeats: newAllocatedSeats })
          .where(eq(subscriptions.id, sub.id));
      }

      // 3. Assign the seat
      await tx.insert(seat_assignments).values({
        organizationId,
        userEmail: email,
      });
    });
  }
}
```

---

## 5. Automated Smart Dunning & Retry Schedule Configuration

Involuntary churn occurs when legitimate subscriptions terminate due to network declines, card expirations, or temporary balance shortfalls.

### The 4-Tier Recovery Timeline

```
T0: Payment Fails
    ├── Stripe Status: past_due
    ├── DB Status: in_grace_period (Grace Period: 7 days)
    ├── App UX: Soft-fail banner; full access retained
    └── Automation: Webhook sends "Payment Failure Action Required" email

T+3 Days: Smart Retry #1
    ├── Result: Failed
    └── Automation: In-app takeover warning (non-blocking modal)

T+5 Days: Smart Retry #2
    ├── Result: Failed
    └── Automation: Escalation email to account billing contact + fallback card prompt

T+7 Days: Grace Period Expires
    ├── DB Status: past_due (Access Restricted)
    ├── App UX: Hard paywall modal blocking dashboard access (Read-Only/Payment view only)
    └── Stripe Action: Subscription remains past_due OR moves to unpaid

T+14 Days: Final Retry (Stripe Smart Retries)
    ├── Result: Failed
    └── Stripe Action: Subscription canceled (Status: canceled)
```

### Stripe Billing Dashboard Configuration Parameters

Ensure the following configuration is set in the Stripe Dashboard (**Settings > Billing > Automatic collection**):

```yaml
Retry Schedule:
  Strategy: Custom Smart Retries (Machine Learning optimized)
  Maximum Attempts: 4 retries
  Retry Duration: Within 2 weeks

Customer Emails:
  Send emails when card payments fail: OFF (Bypass default Stripe emails to prevent branding mismatch)
  Manage failed payments using: Custom Webhook Orchestration (Provided below)

Invoice Status After Exhaustion:
  Action: "Mark the subscription as unpaid" (DO NOT set to "Cancel the subscription" to retain grace recovery options)
```

---

## 6. Payment Recovery Webhook Controller & In-App Grace Periods

The following controller processes invoice payment failures, sets deterministic grace period boundaries, and revokes access only after the grace period expires.

```typescript
// controllers/stripe-dunning-webhook.controller.ts
import { Request, Response } from 'express';
import Stripe from 'stripe';
import { db } from '@/lib/db';
import { subscriptions, organizations } from '@/lib/db/schema';
import { eq } from 'drizzle-orm';
import { Resend } from 'resend';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY as string, {
  apiVersion: '2024-06-20',
});
const resend = new Resend(process.env.RESEND_API_KEY);

const GRACE_PERIOD_DAYS = 7;

export async function handleStripeDunningWebhooks(req: Request, res: Response) {
  const sig = req.headers['stripe-signature'] as string;
  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(
      req.body,
      sig,
      process.env.STRIPE_DUNNING_WEBHOOK_SECRET as string
    );
  } catch (err: any) {
    return res.status(400).send(`Webhook Signature Verification Error: ${err.message}`);
  }

  switch (event.type) {
    case 'invoice.payment_failed': {
      const invoice = event.data.object as Stripe.Invoice;
      await handlePaymentFailed(invoice);
      break;
    }

    case 'invoice.paid': {
      const invoice = event.data.object as Stripe.Invoice;
      await handlePaymentSucceeded(invoice);
      break;
    }

    case 'customer.subscription.deleted': {
      const subscription = event.data.object as Stripe.Subscription;
      await handleSubscriptionCanceled(subscription);
      break;
    }
  }

  return res.status(200).json({ received: true });
}

async function handlePaymentFailed(invoice: Stripe.Invoice) {
  const subscriptionId = invoice.subscription as string;
  if (!subscriptionId) return;

  const [existingSub] = await db
    .select()
    .from(subscriptions)
    .where(eq(subscriptions.stripeSubscriptionId, subscriptionId));

  if (!existingSub) return;

  // Calculate Grace Period Boundary
  const gracePeriodEnd = existingSub.gracePeriodEndsAt || 
    new Date(Date.now() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000);

  // Update subscription to in_grace_period
  await db
    .update(subscriptions)
    .set({
      status: 'in_grace_period',
      gracePeriodEndsAt: gracePeriodEnd,
      updatedAt: new Date(),
    })
    .where(eq(subscriptions.stripeSubscriptionId, subscriptionId));

  // Retrieve customer email
  const customer = await stripe.customers.retrieve(invoice.customer as string);
  if (customer.deleted || !customer.email) return;

  // Retrieve payment intent to extract hosted invoice or update link
  const paymentIntent = invoice.payment_intent 
    ? await stripe.paymentIntents.retrieve(invoice.payment_intent as string)
    : null;

  const failureReason = paymentIntent?.last_payment_error?.message || 'Card declined';
  const hostedInvoiceUrl = invoice.hosted_invoice_url;

  // Send recovery email via transactional provider (Resend)
  await resend.emails.send({
    from: 'Billing Support <billing@saasplatform.com>',
    to: customer.email,
    subject: `Action Required: Payment failed for ${customer.name || 'your workspace'}`,
    html: `
      <h2>Payment Method Update Required</h2>
      <p>We were unable to process payment for your latest invoice (${(invoice.amount_due / 100).toFixed(2)} ${invoice.currency.toUpperCase()}).</p>
      <p><strong>Reason:</strong> ${failureReason}</p>
      <p>Your workspace is currently in an active grace period until <strong>${gracePeriodEnd.toLocaleDateString()}</strong>. To prevent service disruption, please update your payment details:</p>
      <p><a href="${hostedInvoiceUrl}" style="background-color: #000; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 4px;">Update Payment Method</a></p>
      <p>If you have any questions, reply directly to this email.</p>
    `,
  });
}

async function handlePaymentSucceeded(invoice: Stripe.Invoice) {
  const subscriptionId = invoice.subscription as string;
  if (!subscriptionId) return;

  // Restore active status and clear grace period boundaries
  await db
    .update(subscriptions)
    .set({
      status: 'active',
      gracePeriodEndsAt: null,
      updatedAt: new Date(),
    })
    .where(eq(subscriptions.stripeSubscriptionId, subscriptionId));
}

async function handleSubscriptionCanceled(subscription: Stripe.Subscription) {
  await db
    .update(subscriptions)
    .set({
      status: 'canceled',
      gracePeriodEndsAt: null,
      updatedAt: new Date(),
    })
    .where(eq(subscriptions.stripeSubscriptionId, subscription.id));
}
```

---

## 7. Middleware: Grace Period & Authorization Enforcement

Enforce hard access blocks dynamically without running slow roundtrips to Stripe. Check database-backed state on protected API routes and UI dashboards.

```typescript
// middleware/billing-access-guard.ts
import { Request, Response, NextFunction } from 'express';
import { db } from '@/lib/db';
import { subscriptions } from '@/lib/db/schema';
import { eq } from 'drizzle-orm';

export interface AuthenticatedWorkspaceRequest extends Request {
  organizationId?: string;
}

export async function verifyActiveSubscription(
  req: AuthenticatedWorkspaceRequest,
  res: Response,
  next: NextFunction
) {
  const orgId = req.organizationId;
  if (!orgId) {
    return res.status(401).json({ error: 'Unauthenticated' });
  }

  const [sub] = await db
    .select()
    .from(subscriptions)
    .where(eq(subscriptions.organizationId, orgId));

  if (!sub) {
    return res.status(403).json({
      code: 'SUBSCRIPTION_NOT_FOUND',
      error: 'Organization has no billing configuration.',
    });
  }

  const now = new Date();

  // 1. Direct active or trialing access
  if (sub.status === 'active' || sub.status === 'trialing') {
    return next();
  }

  // 2. Evaluate Grace Period
  if (sub.status === 'in_grace_period') {
    if (sub.gracePeriodEndsAt && now < sub.gracePeriodEndsAt) {
      // Allow access, attach warning headers for client layout banners
      res.setHeader('X-Billing-Status', 'in_grace_period');
      res.setHeader('X-Grace-Period-End', sub.gracePeriodEndsAt.toISOString());
      return next();
    }

    // Grace period has elapsed: downgrade state to past_due
    await db
      .update(subscriptions)
      .set({ status: 'past_due' })
      .where(eq(subscriptions.id, sub.id));
  }

  // 3. Past Due / Unpaid / Canceled: Block access
  return res.status(402).json({
    code: 'PAYMENT_REQUIRED',
    error: 'Your subscription is past due and access is locked. Please update your payment method to restore access.',
    status: sub.status,
  });
}
```

---

## 8. High-Converting Dunning Email Templates & Recovery LLM System Prompt

### Transactional Email #1: Sent at T0 (Day 0 Failure)

```markdown
Subject: Urgent: Payment failed for {{workspace_name}}

Hi {{first_name}},

We were unable to process your payment of {{currency_symbol}}{{amount_due}} for your {{product_name}} subscription using your {{card_brand}} ending in {{card_last4}}.

Your account remains fully functional, but we have initiated a 7-day grace period ending on {{grace_period_end_date}}.

To avoid service disruption for your team:
-> [Update Payment Details]({{hosted_invoice_url}})

Common reasons for this failure include:
- Bank fraud triggers on recurring SaaS transactions
- The card has expired or reached daily credit limits
- Zip code / Billing Address mismatches

Update your billing details securely using the link above. Our system will immediately retry the charge and clear the grace period flag.

Best,  
The Billing Team at {{company_name}}
```

### Transactional Email #2: Sent at T+5 Days (Escalated Warning)

```markdown
Subject: Final Notice: Your access to {{workspace_name}} will lock in 48 hours

Hi {{first_name}},

This is our final reminder regarding the outstanding balance of {{currency_symbol}}{{amount_due}} for {{workspace_name}}. 

Your 7-day grace period expires on **{{grace_period_end_date}}**.

If a valid payment method is not on file before then, your account will enter locked mode:
1. Team members will lose write access to workspaces and APIs.
2. Background tasks and automated exports will pause.
3. Your data will remain preserved, but dashboard access will be restricted to billing settings.

Resolve this immediately:
-> [Pay Outstanding Invoice & Update Card]({{hosted_invoice_url}})

If you need this invoice routed to Accounts Payable or need a PO reference added, reply directly to this email with your PO details.

Best,  
The Billing Team at {{company_name}}
```

### Autonomous AI Billing Recovery System Prompt

Use this prompt inside automated customer support tools (e.g., Zendesk AI, Intercom Copilot, custom LangChain pipelines) when customers reply directly to dunning emails:

```text
You are the Autonomous Billing Operations Specialist for a high-growth SaaS platform.
Your objective is to help customers whose accounts are past due resolve their billing issues, prevent churn, and collect overdue payments safely.

INPUT PARAMETERS:
- Customer Name: {{customer_name}}
- Organization: {{org_name}}
- Status: {{subscription_status}}
- Grace Period End Date: {{grace_period_end}}
- Outstanding Invoices: {{outstanding_invoices_array}}
- Secure Payment Update URL: {{hosted_invoice_url}}

BEHAVIORAL DIRECTIVES:
1. Never compromise security: Never request credit card numbers, CVVs, or full bank account info via text or chat. Always guide them to the {{hosted_invoice_url}}.
2. If the customer indicates their company requires ACH, Wire Transfer, or an explicit W-9/Vendor Form:
   - Provide the download link for the platform's standardized W-9 form: https://assets.platform.com/legal/w9-latest.pdf.
   - Instruct them that we can switch them to manual invoicing (ACH/Wire Net 30) if their annual spend exceeds $5,000 ARR.
3. If the customer asks for a grace period extension:
   - You are authorized to grant a ONE-TIME extension of up to 5 business days if they state they are updating their card or waiting on AP.
   - Execute the action tag: [ACTION: EXTEND_GRACE_PERIOD, DAYS: 5].
4. Tone: Empathetic, direct, technically competent, professional. Zero corporate jargon.

OUTPUT FORMAT:
Generate a concise, helpful response addressing the user's specific reason for failure followed by actionable links.
```

---

## 9. Deployment Verification Checklist

Run this operational validation plan across staging and production before activating automated seat billing and proration handling:

- [ ] **Stripe Clock Simulation**: Advance time using [Stripe Test Clocks](https://stripe.com/docs/billing/testing/test-clocks) to test transitions at $T+0$, $T+3$, $T+5$, and $T+7$ days.
- [ ] **Proration Line-Item Exactness**: Verify `getProrationPreview()` output matches the exact debit on the Stripe test customer account to the cent.
- [ ] **Database Race Conditions**: Run concurrent seat assignment tests using tools like `k6` to verify rows are locked (`FOR UPDATE`) and licenses cannot be oversold without triggering seat increments.
- [ ] **Negative Invoice Generation**: Confirm that downgrading mid-cycle does not attempt to charge cards, but instead updates customer credit balances accurately.
- [ ] **Idempotency Guard**: Trigger duplicate webhook payloads for `invoice.payment_failed` and confirm that emails are sent once and database updates maintain consistent state without resetting grace period clocks.
