# Module 3: Advanced Workflows, Real-World Case Studies & Blueprints

Welcome to Module 3 of **The Transactional Email & React Email Vault**. This module moves beyond visual design and basic single-send configurations. It contains the production architectures, database schemas, and distributed delivery pipelines required to run mission-critical transactional email at scale using Next.js 15, Resend, Svix, and Redis.

---

## 1. Next.js 15 Server Actions Integration

Using Next.js 15 Server Actions for transactional dispatch avoids exposing API keys to the client, enforces server-side runtime isolation, and integrates with React 19's `useActionState` hook for optimistic UI updates.

### End-to-End Type-Safe Server Action

Below is the complete implementation of a production-ready authentication action that validates user input with Zod, checks suppression status, renders a React Email template to an HTML string, and dispatches via Resend with typed error boundaries.

Create `actions/send-magic-link.ts`:

```typescript
'use server';

import { z } from 'zod';
import { Resend } from 'resend';
import * as React from 'react';
import { renderAsync } from '@react-email/render';
import MagicLinkEmail from '@/emails/magic-link';
import { checkSuppressionStatus } from '@/lib/suppression';

const resend = new Resend(process.env.RESEND_API_KEY);

const SendMagicLinkSchema = z.object({
  email: z.string().email({ message: 'Invalid enterprise email address.' }).toLowerCase().trim(),
  redirectUrl: z.string().url({ message: 'Invalid redirection endpoint target.' }),
});

export type ActionState = {
  success: boolean;
  message: string;
  errors?: Record<string, string[]>;
  data?: { messageId: string };
};

export async function sendMagicLinkAction(
  prevState: ActionState | null,
  formData: FormData
): Promise<ActionState> {
  const rawData = {
    email: formData.get('email'),
    redirectUrl: formData.get('redirectUrl'),
  };

  const validationResult = SendMagicLinkSchema.safeParse(rawData);

  if (!validationResult.success) {
    return {
      success: false,
      message: 'Validation failed. Please correct the errors below.',
      errors: validationResult.error.flatten().fieldErrors,
    };
  }

  const { email, redirectUrl } = validationResult.data;

  try {
    // 1. Check local suppression list before hitting Resend API
    const isSuppressed = await checkSuppressionStatus(email);
    if (isSuppressed) {
      // Return a 200-equivalent success response to prevent email enumeration attacks
      return {
        success: true,
        message: 'If the email exists and is eligible, a login link has been sent.',
      };
    }

    // 2. Generate cryptographically secure one-time verification token
    const token = crypto.randomUUID();
    const magicLink = `${redirectUrl}?token=${token}&email=${encodeURIComponent(email)}`;

    // 3. Pre-render React Email to HTML string
    const emailHtml = await renderAsync(
      React.createElement(MagicLinkEmail, {
        magicLink,
        recipientEmail: email,
        ipAddress: '192.168.1.1', // Pull from headers() in production
        userAgent: 'Chrome on macOS',
      })
    );

    // 4. Dispatch via Resend with structured tags and headers
    const { data: resendData, error: resendError } = await resend.emails.send({
      from: 'Enterprise Auth <auth@transactional.yourdomain.com>',
      to: [email],
      subject: 'Authenticate your enterprise session',
      html: emailHtml,
      headers: {
        'X-Entity-Ref-ID': token,
      },
      tags: [
        { name: 'category', value: 'authentication' },
        { name: 'environment', value: process.env.NODE_ENV || 'production' },
      ],
    });

    if (resendError) {
      console.error('[Resend Error]:', {
        name: resendError.name,
        message: resendError.message,
      });
      return {
        success: false,
        message: 'Delivery service reported a failure. Please try again later.',
      };
    }

    return {
      success: true,
      message: 'Verification email sent successfully.',
      data: { messageId: resendData?.id ?? '' },
    };
  } catch (error) {
    console.error('[Fatal Dispatch Error]:', error);
    return {
      success: false,
      message: 'An unexpected internal error occurred while processing the request.',
    };
  }
}
```

### Magic Link Email Component

Create `emails/magic-link.tsx`:

```tsx
import * as React from 'react';
import {
  Body,
  Button,
  Container,
  Head,
  Heading,
  Hr,
  Html,
  Link,
  Preview,
  Section,
  Text,
} from '@react-email/components';

interface MagicLinkEmailProps {
  magicLink: string;
  recipientEmail: string;
  ipAddress?: string;
  userAgent?: string;
}

export default function MagicLinkEmail({
  magicLink,
  recipientEmail,
  ipAddress = 'Unknown IP',
  userAgent = 'Unknown Device',
}: MagicLinkEmailProps) {
  return (
    <Html>
      <Head />
      <Preview>Your single-use sign-in link for Vault Enterprise</Preview>
      <Body style={mainStyle}>
        <Container style={containerStyle}>
          <Heading style={headingStyle}>Sign-in Request</Heading>
          <Text style={textStyle}>
            A sign-in link was requested for <strong>{recipientEmail}</strong>.
          </Text>
          <Section style={btnContainerStyle}>
            <Button style={buttonStyle} href={magicLink}>
              Authenticate Session
            </Button>
          </Section>
          <Text style={subtextStyle}>
            This link is valid for 15 minutes. If you did not make this request, you can safely ignore this email.
          </Text>
          <Hr style={dividerStyle} />
          <Section style={auditStyle}>
            <Text style={auditTextStyle}>Request Metadata:</Text>
            <Text style={auditTextStyle}>IP Address: {ipAddress}</Text>
            <Text style={auditTextStyle}>Device: {userAgent}</Text>
          </Section>
          <Hr style={dividerStyle} />
          <Text style={footerStyle}>
            Security System Notification • 100 Enterprise Way, Suite 400, San Francisco, CA 94105
          </Text>
        </Container>
      </Body>
    </Html>
  );
}

const mainStyle = {
  backgroundColor: '#f8fafc',
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  padding: '40px 0',
};

const containerStyle = {
  backgroundColor: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: '8px',
  margin: '0 auto',
  maxWidth: '560px',
  padding: '40px',
};

const headingStyle = {
  color: '#0f172a',
  fontSize: '24px',
  fontWeight: '600',
  lineHeight: '32px',
  margin: '0 0 16px',
};

const textStyle = {
  color: '#334155',
  fontSize: '15px',
  lineHeight: '24px',
  margin: '0 0 24px',
};

const btnContainerStyle = {
  margin: '28px 0',
  textAlign: 'center' as const,
};

const buttonStyle = {
  backgroundColor: '#0f172a',
  borderRadius: '6px',
  color: '#ffffff',
  fontSize: '15px',
  fontWeight: '600',
  padding: '12px 28px',
  textDecoration: 'none',
  display: 'inline-block',
};

const subtextStyle = {
  color: '#64748b',
  fontSize: '13px',
  lineHeight: '20px',
  margin: '0 0 24px',
};

const dividerStyle = {
  borderColor: '#e2e8f0',
  margin: '24px 0',
};

const auditStyle = {
  backgroundColor: '#f1f5f9',
  borderRadius: '4px',
  padding: '12px 16px',
};

const auditTextStyle = {
  color: '#475569',
  fontSize: '12px',
  lineHeight: '18px',
  margin: '0',
};

const footerStyle = {
  color: '#94a3b8',
  fontSize: '12px',
  lineHeight: '18px',
  margin: '0',
  textAlign: 'center' as const,
};
```

---

## 2. Inbound Webhook Pipeline with Svix Signature Verification

Resend uses the Svix library to cryptographically sign all inbound webhook notifications. Never trust unverified HTTP requests to your webhook routes. Unverified requests expose your database to replay attacks, false bounce assertions, and arbitrary state mutations.

### Webhook Route Handler

Create `app/api/webhooks/resend/route.ts`:

```typescript
import { headers } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';
import { Webhook } from 'svix';
import { prisma } from '@/lib/prisma';

// Secret from Resend Dashboard -> Webhooks -> Signing Secret
const WEBHOOK_SECRET = process.env.RESEND_WEBHOOK_SECRET;

interface ResendWebhookPayload {
  type:
    | 'email.sent'
    | 'email.delivered'
    | 'email.delivery_delayed'
    | 'email.bounced'
    | 'email.complained'
    | 'email.opened'
    | 'email.clicked';
  created_at: string;
  data: {
    created_at: string;
    email_id: string;
    from: string;
    to: string[];
    subject: string;
    bounce?: {
      message: string;
      code: string;
      sub_code?: string;
      type: 'hard_bounce' | 'soft_bounce' | 'undetermined';
    };
    click?: {
      ipAddress: string;
      link: string;
      userAgent: string;
      timestamp: string;
    };
  };
}

export async function POST(req: NextRequest) {
  if (!WEBHOOK_SECRET) {
    console.error('FATAL: RESEND_WEBHOOK_SECRET environment variable is missing.');
    return NextResponse.json({ error: 'Server configuration error' }, { status: 500 });
  }

  // Extract raw body for verification (do NOT use req.json() first)
  const payload = await req.text();
  const headerList = await headers();

  const svixId = headerList.get('svix-id');
  const svixTimestamp = headerList.get('svix-timestamp');
  const svixSignature = headerList.get('svix-signature');

  if (!svixId || !svixTimestamp || !svixSignature) {
    return NextResponse.json(
      { error: 'Missing required Svix cryptographic headers' },
      { status: 400 }
    );
  }

  const wh = new Webhook(WEBHOOK_SECRET);
  let evt: ResendWebhookPayload;

  try {
    evt = wh.verify(payload, {
      'svix-id': svixId,
      'svix-timestamp': svixTimestamp,
      'svix-signature': svixSignature,
    }) as ResendWebhookPayload;
  } catch (err) {
    console.error('Webhook signature verification failed:', err);
    return NextResponse.json(
      { error: 'Invalid cryptographic signature' },
      { status: 400 }
    );
  }

  const { type, data } = evt;
  const targetEmail = data.to[0]?.toLowerCase().trim();

  try {
    // Audit Trail: Record every webhook event raw payload
    await prisma.emailDeliveryLog.create({
      data: {
        messageId: data.email_id,
        recipient: targetEmail,
        eventType: type,
        rawPayload: JSON.parse(payload),
      },
    });

    switch (type) {
      case 'email.bounced': {
        const bounceType = data.bounce?.type || 'hard_bounce';
        const bounceCode = data.bounce?.code || '5.0.0';
        const bounceReason = data.bounce?.message || 'Unknown delivery failure';

        // Add to suppression list if it is a hard bounce
        if (bounceType === 'hard_bounce') {
          await prisma.suppressionList.upsert({
            where: { email: targetEmail },
            update: {
              reason: 'HARD_BOUNCE',
              metadata: { bounceCode, bounceReason, date: new Date().toISOString() },
            },
            create: {
              email: targetEmail,
              reason: 'HARD_BOUNCE',
              metadata: { bounceCode, bounceReason, date: new Date().toISOString() },
            },
          });
        }
        break;
      }

      case 'email.complained': {
        // Immediate, non-negotiable suppression on spam complaint
        await prisma.suppressionList.upsert({
          where: { email: targetEmail },
          update: {
            reason: 'SPAM_COMPLAINT',
            metadata: { date: new Date().toISOString() },
          },
          create: {
            email: targetEmail,
            reason: 'SPAM_COMPLAINT',
            metadata: { date: new Date().toISOString() },
          },
        });
        break;
      }

      case 'email.delivered': {
        await prisma.transactionalMessage.updateMany({
          where: { providerId: data.email_id },
          data: { status: 'DELIVERED', deliveredAt: new Date() },
        });
        break;
      }

      default:
        // Handle informational events (opened, clicked, sent) without suppression
        break;
    }

    return NextResponse.json({ received: true });
  } catch (dbError) {
    console.error('Database write failed during webhook ingestion:', dbError);
    // Return 500 so Resend/Svix retries delivery with exponential backoff
    return NextResponse.json(
      { error: 'Internal processing failure' },
      { status: 500 }
    );
  }
}
```

---

## 3. Automated Bounce, Suppression & Complaint Management

Deliverability relies on sending only to valid, active inboxes. If your hard bounce rate exceeds **2.0%** or your spam complaint rate exceeds **0.1%** (1 complaint per 1,000 sent emails), major providers (Google, Yahoo, Microsoft) will route your domain's traffic directly to spam folders or block it entirely.

### PostgreSQL Suppression & Event Architecture

Run the following SQL migration on your database to create the delivery and suppression infrastructure:

```sql
-- Create enum for suppression causes
CREATE TYPE suppression_reason AS ENUM (
  'HARD_BOUNCE',
  'SPAM_COMPLAINT',
  'MANUAL_UNSUBSCRIBE',
  'ADMINISTRATIVE_BLOCK'
);

-- Production Suppression Registry
CREATE TABLE IF NOT EXISTS suppression_list (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(320) NOT NULL UNIQUE,
  reason suppression_reason NOT NULL,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX idx_suppression_email ON suppression_list (LOWER(email));

-- Delivery Audit Log
CREATE TABLE IF NOT EXISTS email_delivery_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id VARCHAR(100) NOT NULL,
  recipient VARCHAR(320) NOT NULL,
  event_type VARCHAR(50) NOT NULL,
  raw_payload JSONB NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX idx_delivery_log_recipient ON email_delivery_log (recipient);
CREATE INDEX idx_delivery_log_message_id ON email_delivery_log (message_id);
```

### Pre-Flight Delivery Check Library

Create `lib/suppression.ts`:

```typescript
import { prisma } from '@/lib/prisma';

/**
 * Checks whether an email address is present in the suppression list.
 * Must be executed prior to any outbound transactional or marketing dispatch.
 */
export async function checkSuppressionStatus(email: string): Promise<boolean> {
  const normalizedEmail = email.toLowerCase().trim();

  const record = await prisma.suppressionList.findUnique({
    where: { email: normalizedEmail },
    select: { id: true, reason: true },
  });

  return Boolean(record);
}

/**
 * Manually adds an email to the suppression list (e.g., on user unsubscribe).
 */
export async function suppressRecipient(
  email: string,
  reason: 'HARD_BOUNCE' | 'SPAM_COMPLAINT' | 'MANUAL_UNSUBSCRIBE' | 'ADMINISTRATIVE_BLOCK',
  metadata: Record<string, unknown> = {}
): Promise<void> {
  const normalizedEmail = email.toLowerCase().trim();

  await prisma.suppressionList.upsert({
    where: { email: normalizedEmail },
    update: {
      reason,
      metadata,
      updatedAt: new Date(),
    },
    create: {
      email: normalizedEmail,
      reason,
      metadata,
    },
  });
}
```

### Bounce Classification Reference

| Event Type | Sub-Type | Action Taken | Retention in Queue | Deliverability Risk |
| :--- | :--- | :--- | :--- | :--- |
| **Hard Bounce** | `5.1.1` (Bad destination mailbox) | Permanent Suppression | Drop immediately | **Critical**: High volume triggers global blacklisting. |
| **Hard Bounce** | `5.1.2` (Bad destination host) | Permanent Suppression | Drop immediately | **Critical**: Indicates dead domains. |
| **Soft Bounce** | `4.2.2` (Mailbox full) | Allow retries (Max 3) | Exponential retry (24h window) | **Low**: Transitory recipient-side issue. |
| **Soft Bounce** | `4.4.1` (Connection timed out) | Allow retries (Max 5) | Jittered retry (12h window) | **Low**: Network/firewall issue. |
| **Spam Complaint**| `Feedback Loop (FBL)` | Immediate Permanent Suppression | Drop and wipe pending queues | **Fatal**: Keep below 0.1% to preserve reputation. |

---

## 4. High-Volume Idempotency & Queue Architecture

High-throughput systems (such as end-of-month billing or marketing notifications) can trigger rate limits or produce duplicate sends when workers retry failed requests. To avoid double-charging or sending duplicate emails, use **idempotency keys** and **distributed queue throttling**.

```
[ Application / Server Actions ]
               │
               ▼
   [ Distributed Lock Check ]  ◄── (Redis SETNX with TTL)
               │
       (Lock Acquired)
               │
               ▼
     [ Push to Queue ]
               │
               ▼
    [ Worker Concurrency ]     ◄── (Rate Limit: 50 req/sec)
               │
               ▼
    [ Resend API Call ]        ◄── (With Idempotency-Key Header)
```

### Upstash Redis / Redis Idempotent Queue Dispatcher

Create `lib/queue/dispatcher.ts`:

```typescript
import { Redis } from '@upstash/redis';
import { Resend } from 'resend';

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL!,
  token: process.env.UPSTASH_REDIS_REST_TOKEN!,
});

const resend = new Resend(process.env.RESEND_API_KEY);

interface TransactionalJob {
  id: string; // The Idempotency Key (e.g., invoice_id:version:timestamp)
  to: string;
  subject: string;
  html: string;
  category: string;
}

export class IdempotentEmailDispatcher {
  private static LOCK_TTL_SECONDS = 86400; // 24 hours

  /**
   * Dispatches an email with strict idempotency guarantees.
   * If the key was processed within the TTL, duplicate requests are rejected.
   */
  public static async dispatch(job: TransactionalJob): Promise<{ success: boolean; deduplicated: boolean; id?: string }> {
    const lockKey = `idempotency:email:${job.id}`;

    // SETNX (set if not exists) with 24-hour expiration
    const acquired = await redis.set(lockKey, 'PROCESSING', {
      nx: true,
      ex: this.LOCK_TTL_SECONDS,
    });

    if (!acquired) {
      console.warn(`[Duplicate Dropped] Idempotency key collision for key: ${job.id}`);
      return { success: true, deduplicated: true };
    }

    try {
      // resend-node accepts idempotency headers directly in the configuration object
      const { data, error } = await resend.emails.send({
        from: 'Vault Billing <billing@transactional.yourdomain.com>',
        to: job.to,
        subject: job.subject,
        html: job.html,
        headers: {
          'Idempotency-Key': job.id,
        },
        tags: [{ name: 'job_id', value: job.id }, { name: 'category', value: job.category }],
      });

      if (error) {
        // Clear lock on infrastructure failure to allow legitimate retries
        await redis.del(lockKey);
        throw new Error(`Resend API rejection: ${error.message}`);
      }

      // Mark the key as successfully processed
      await redis.set(lockKey, `COMPLETED:${data?.id}`, { ex: this.LOCK_TTL_SECONDS });

      return { success: true, deduplicated: false, id: data?.id };
    } catch (err) {
      // Release lock on runtime execution failure
      await redis.del(lockKey);
      throw err;
    }
  }
}
```

### BullMQ / Redis Worker Consumer Pattern

Create `workers/email-consumer.ts`:

```typescript
import { Worker, Job } from 'bullmq';
import { IdempotentEmailDispatcher } from '@/lib/queue/dispatcher';

interface JobData {
  idempotencyKey: string;
  email: string;
  subject: string;
  html: string;
  category: string;
}

const connection = {
  host: process.env.REDIS_HOST || 'localhost',
  port: parseInt(process.env.REDIS_PORT || '6379', 10),
  password: process.env.REDIS_PASSWORD,
};

export const emailWorker = new Worker<JobData>(
  'transactional-emails',
  async (job: Job<JobData>) => {
    const { idempotencyKey, email, subject, html, category } = job.data;

    const result = await IdempotentEmailDispatcher.dispatch({
      id: idempotencyKey,
      to: email,
      subject,
      html,
      category,
    });

    return result;
  },
  {
    connection,
    concurrency: 20, // Process 20 jobs concurrently
    limiter: {
      max: 50, // Resend standard rate limit
      duration: 1000, // per 1 second (50 emails/sec)
    },
  }
);

emailWorker.on('failed', (job, err) => {
  console.error(`[Job Failed] ID: ${job?.id}, Error: ${err.message}`);
});
```

---

## 5. Real-World Case Study: B2B Enterprise SaaS Onboarding Workflow

The following blueprint models a real-world onboarding workflow. It shows how authentication, team invites, and payment confirmation are chained using state machines, webhooks, and fallback mechanisms.

```
+-------------------------------------------------------------------------------------------------------------+
|                                  ENTERPRISE ONBOARDING STATE MACHINE                                        |
+-------------------------------------------------------------------------------------------------------------+
                                                       │
                                        [ Trigger: Signup Initiated ]
                                                       │
                                                       ▼
                                            Send Magic Link Email
                                                       │
                                  ┌────────────────────┴────────────────────┐
                          (Within 15 Min)                           (Expired)
                                  │                                         │
                                  ▼                                         ▼
                       Account Provisioned                         Purge Pending State
                                  │
                                  ▼
                         Send "Welcome to Vault"
                                  │
                                  ▼
                     [ Wait: Team Invite Issued? ]
                                  │
                  ┌───────────────┴───────────────┐
             (YES: Member Added)           (NO: After 48 Hours)
                  │                               │
                  ▼                               ▼
       Dispatch Invite to Member        Send Workspace Activation Nudge
                  │                               │
                  ▼                               ▼
         Recipient Accepts?             User Upgrades to Enterprise Plan?
         ┌────────┴────────┐                      │
        YES                NO                     ▼
         │                 │         Send VAT Invoice / Payment Receipt
         ▼                 ▼                      │
   Add to Team     Send Reminder                  ▼
   Supabase DB    (72-hour delay)       Enroll in High-Priority Support
```

### Complete Implementation: Multi-Step Notification Orchestrator

Create `lib/workflows/onboarding.ts`:

```typescript
import { Resend } from 'resend';
import * as React from 'react';
import { renderAsync } from '@react-email/render';
import WelcomeEmail from '@/emails/welcome-onboarding';
import InvoiceReceiptEmail from '@/emails/invoice-receipt';
import { prisma } from '@/lib/prisma';
import { checkSuppressionStatus } from '@/lib/suppression';

const resend = new Resend(process.env.RESEND_API_KEY);

export class OnboardingWorkflowOrchestrator {
  /**
   * Step 1: Send the primary welcome email after initial account creation.
   */
  public static async triggerWelcome(userId: string): Promise<void> {
    const user = await prisma.user.findUnique({
      where: { id: userId },
      select: { email: true, name: true, organizationId: true },
    });

    if (!user) throw new Error(`User with ID ${userId} does not exist.`);

    const isSuppressed = await checkSuppressionStatus(user.email);
    if (isSuppressed) {
      console.warn(`[Suppressed] Recipient ${user.email} is in suppression list.`);
      return;
    }

    const emailHtml = await renderAsync(
      React.createElement(WelcomeEmail, {
        name: user.name || 'Team Member',
        dashboardUrl: `https://vault.yourdomain.com/dashboard?org=${user.organizationId}`,
      })
    );

    const { data, error } = await resend.emails.send({
      from: 'Vault Onboarding <onboarding@transactional.yourdomain.com>',
      to: [user.email],
      subject: 'Welcome to Vault: Your Setup Roadmap',
      html: emailHtml,
      tags: [
        { name: 'workflow', value: 'onboarding' },
        { name: 'step', value: 'welcome' },
        { name: 'user_id', value: userId },
      ],
    });

    if (error) {
      throw new Error(`Welcome dispatch failed: ${error.message}`);
    }

    await prisma.user.update({
      where: { id: userId },
      data: { welcomeEmailSentAt: new Date() },
    });
  }

  /**
   * Step 2: Send payment receipts and invoices after an enterprise upgrade.
   */
  public static async triggerInvoiceReceipt(invoiceId: string): Promise<void> {
    const invoice = await prisma.invoice.findUnique({
      where: { id: invoiceId },
      include: { user: true },
    });

    if (!invoice) throw new Error(`Invoice ${invoiceId} not found.`);

    const isSuppressed = await checkSuppressionStatus(invoice.user.email);
    if (isSuppressed) return;

    const emailHtml = await renderAsync(
      React.createElement(InvoiceReceiptEmail, {
        customerName: invoice.user.name || 'Valued Customer',
        invoiceNumber: invoice.number,
        amountPaid: invoice.amountFormatted,
        billingDate: invoice.createdAt.toLocaleDateString('en-US', {
          year: 'numeric',
          month: 'long',
          day: 'numeric',
        }),
        downloadUrl: `https://vault.yourdomain.com/invoices/${invoice.id}/download`,
      })
    );

    await resend.emails.send({
      from: 'Vault Finance <invoices@transactional.yourdomain.com>',
      to: [invoice.user.email],
      subject: `Payment Receipt: Invoice #${invoice.number}`,
      html: emailHtml,
      headers: {
        'Idempotency-Key': `invoice-send:${invoice.id}`,
      },
      tags: [
        { name: 'workflow', value: 'billing' },
        { name: 'invoice_id', value: invoice.id },
      ],
    });

    await prisma.invoice.update({
      where: { id: invoiceId },
      data: { status: 'PAID_RECEIPT_SENT' },
    });
  }
}
```

---

## 6. Deliverability Blueprint: Automated IP Warming & DNS Verification

New sending domains must warm their sending volume gradually over a 30-day window to build trust with spam filters. Spiking from 0 to 100,000 emails on a new domain or IP address will flag spam filters and result in throttling or blocks.

### 30-Day IP / Sending Domain Warming Schedule

| Day Window | Max Daily Volume | Target Audience Segment | Max Sending Rate (req/sec) |
| :--- | :--- | :--- | :--- |
| **Day 1–
