# Module 2: Ready-to-Use Templates, Prompts & Configurations

This module delivers drop-in, type-safe React Email templates, complete dispatch pipelines, and the exact system prompt harness used to generate dark-mode-resilient transactional emails that render consistently across Apple Mail, Gmail, Outlook 2016–365, and mobile web clients.

---

## 1. Design System Tokens & Base Wrapper

All templates inherit from this foundational layout component. It injects required MSO conditional comments, defines light/dark CSS variables, handles Apple Mail link-color auto-detection, and standardizes spacing.

### `emails/components/BaseLayout.tsx`

```tsx
import * as React from "react";
import {
  Body,
  Container,
  Head,
  Html,
  Preview,
  Section,
  Text,
  Tailwind,
  pixelBorders,
} from "@react-email/components";

interface BaseLayoutProps {
  previewText: string;
  children: React.ReactNode;
  footerText?: string;
}

export const BaseLayout = ({
  previewText,
  children,
  footerText = "Acme Corp, Inc. • 100 Montgomery St, Suite 400, San Francisco, CA 94104",
}: BaseLayoutProps) => {
  return (
    <Html lang="en">
      <Head>
        <meta name="color-scheme" content="light dark" />
        <meta name="supported-color-schemes" content="light dark" />
        <style>{`
          :root {
            color-scheme: light dark;
            supported-color-schemes: light dark;
          }
          @media (prefers-color-scheme: dark) {
            .email-bg { background-color: #0b0f19 !important; }
            .content-card { background-color: #111827 !important; border-color: #1f2937 !important; }
            .primary-text { color: #f9fafb !important; }
            .secondary-text { color: #9ca3af !important; }
            .meta-border { border-color: #374151 !important; }
            .code-box { background-color: #1f2937 !important; color: #f3f4f6 !important; }
          }
          /* Outlook table alignment normalization */
          table { border-collapse: collapse; }
          img { -ms-interpolation-mode: bicubic; }
        `}</style>
      </Head>
      <Preview>{previewText}</Preview>
      <Tailwind
        config={{
          theme: {
            extend: {
              colors: {
                brand: "#0284c7",
                brandDark: "#0369a1",
              },
            },
          },
        }}
      >
        <Body className="email-bg bg-[#f3f4f6] font-sans m-0 p-0 text-[#111827]">
          <Container className="max-w-[580px] mx-auto pt-6 pb-12 px-3">
            {/* Header / Brand Logo */}
            <Section className="py-4 text-center">
              <Text className="text-xl font-bold tracking-tight text-brand m-0">
                ACME<span className="text-[#111827] primary-text">ENGINE</span>
              </Text>
            </Section>

            {/* Main Content Box */}
            <Section className="content-card bg-white border border-solid border-[#e5e7eb] rounded-xl px-8 py-7 shadow-sm">
              {children}
            </Section>

            {/* Footer */}
            <Section className="pt-6 px-4 text-center">
              <Text className="secondary-text text-xs text-[#6b7280] leading-5 m-0">
                {footerText}
              </Text>
              <Text className="secondary-text text-xs text-[#9ca3af] leading-5 mt-2">
                If you did not make this request, you can safely ignore this email.
              </Text>
            </Section>
          </Container>
        </Body>
      </Tailwind>
    </Html>
  );
};
```

---

## 2. Production React Email Templates

### Template 1: Passwordless Magic Link & OTP Verification

Features cross-client copy-pasteable auth codes, single-click CTAs, IP/Device location audit blocks, and fallbacks.

```tsx
import * as React from "react";
import {
  Button,
  Heading,
  Hr,
  Link,
  Section,
  Text,
} from "@react-email/components";
import { BaseLayout } from "./components/BaseLayout";

interface MagicLinkEmailProps {
  magicLinkUrl: string;
  loginCode: string;
  ipAddress: string;
  userAgent: string;
  location: string;
  expiresInMinutes: number;
}

export const MagicLinkEmail = ({
  magicLinkUrl = "https://app.acme.com/auth/verify?token=tok_live_79a8e1b2c3d4",
  loginCode = "842-195",
  ipAddress = "198.51.100.42",
  userAgent = "Brave Browser / macOS Sonoma 14.4",
  location = "Austin, Texas, United States",
  expiresInMinutes = 10,
}: MagicLinkEmailProps) => {
  return (
    <BaseLayout previewText={`Your verification code is ${loginCode}`}>
      <Heading className="primary-text text-2xl font-bold text-[#111827] mt-0 mb-4 tracking-tight">
        Authenticate your session
      </Heading>

      <Text className="primary-text text-sm leading-6 text-[#374151] mb-6">
        We received an authentication request for your Acme Engine account. Click the button below to sign in automatically:
      </Text>

      <Section className="text-center my-6">
        <Button
          className="bg-[#0284c7] hover:bg-[#0369a1] text-white font-semibold text-sm px-6 py-3 rounded-lg no-underline inline-block shadow-sm"
          href={magicLinkUrl}
        >
          Sign in to Dashboard
        </Button>
      </Section>

      <Text className="secondary-text text-xs text-[#6b7280] text-center my-3">
        Or enter this single-use code directly in your application window:
      </Text>

      <Section className="code-box bg-[#f8fafc] border border-dashed border-[#cbd5e1] rounded-lg p-3 text-center my-4">
        <Text className="text-2xl font-mono font-bold tracking-[0.25em] text-[#0f172a] m-0">
          {loginCode}
        </Text>
      </Section>

      <Text className="secondary-text text-xs text-[#6b7280] leading-5 mb-6">
        This link and code will expire in {expiresInMinutes} minutes. If the button above does not work, copy and paste this URL into your browser:
        <br />
        <Link href={magicLinkUrl} className="text-[#0284c7] underline break-all">
          {magicLinkUrl}
        </Link>
      </Text>

      <Hr className="meta-border border-[#e5e7eb] my-5" />

      {/* Security Context Grid */}
      <Section className="bg-[#f9fafb] code-box rounded-md p-3 border border-solid border-[#f3f4f6]">
        <Text className="primary-text text-[11px] font-semibold uppercase tracking-wider text-[#4b5563] m-0 mb-2">
          Security Verification Metadata
        </Text>
        <table className="w-full text-left text-[11px] text-[#6b7280] secondary-text">
          <tbody>
            <tr>
              <td className="py-0.5 font-medium w-24">IP Address:</td>
              <td className="py-0.5 font-mono">{ipAddress}</td>
            </tr>
            <tr>
              <td className="py-0.5 font-medium">Device:</td>
              <td className="py-0.5">{userAgent}</td>
            </tr>
            <tr>
              <td className="py-0.5 font-medium">Approx. Origin:</td>
              <td className="py-0.5">{location}</td>
            </tr>
          </tbody>
        </table>
      </Section>
    </BaseLayout>
  );
};

export default MagicLinkEmail;
```

---

### Template 2: Multi-Seat Organization Invite

Features permission badge levels, inviter attribution, and clear decline/block mechanisms.

```tsx
import * as React from "react";
import {
  Button,
  Heading,
  Hr,
  Link,
  Section,
  Text,
} from "@react-email/components";
import { BaseLayout } from "./components/BaseLayout";

interface TeamInviteEmailProps {
  inviterName: string;
  inviterEmail: string;
  teamName: string;
  role: "Owner" | "Admin" | "Developer" | "Billing";
  acceptInviteUrl: string;
  declineInviteUrl: string;
}

export const TeamInviteEmail = ({
  inviterName = "Sarah Connor",
  inviterEmail = "s.connor@cyberdyne.io",
  teamName = "Cyberdyne Systems",
  role = "Developer",
  acceptInviteUrl = "https://app.acme.com/invites/accept?token=inv_99x8a7b6c5",
  declineInviteUrl = "https://app.acme.com/invites/decline?token=inv_99x8a7b6c5",
}: TeamInviteEmailProps) => {
  return (
    <BaseLayout previewText={`${inviterName} invited you to join ${teamName} on Acme`}>
      <Heading className="primary-text text-xl font-bold text-[#111827] mt-0 mb-3 tracking-tight">
        Join {teamName} on Acme
      </Heading>

      <Text className="primary-text text-sm leading-6 text-[#374151] mb-5">
        <strong>{inviterName}</strong> ({inviterEmail}) has invited you to collaborate on the <strong>{teamName}</strong> team account.
      </Text>

      {/* Role Assignment Card */}
      <Section className="code-box bg-[#f8fafc] border border-solid border-[#e2e8f0] rounded-lg p-4 mb-6">
        <table className="w-full text-sm">
          <tbody>
            <tr>
              <td className="text-[#64748b] secondary-text py-1">Assigned Role:</td>
              <td className="text-right py-1">
                <span className="bg-[#e0f2fe] text-[#0369a1] text-xs font-semibold px-2.5 py-1 rounded-full uppercase tracking-wider">
                  {role}
                </span>
              </td>
            </tr>
            <tr>
              <td className="text-[#64748b] secondary-text py-1">Team Workspace:</td>
              <td className="text-right font-medium primary-text text-[#0f172a] py-1">
                {teamName}
              </td>
            </tr>
          </tbody>
        </table>
      </Section>

      <Section className="text-center my-6">
        <Button
          className="bg-[#0f172a] hover:bg-[#1e293b] text-white font-medium text-sm px-6 py-3 rounded-lg no-underline inline-block w-full text-center box-border"
          href={acceptInviteUrl}
        >
          Accept Invitation
        </Button>
      </Section>

      <Text className="secondary-text text-xs text-[#6b7280] text-center mb-0">
        Prefer not to join? You can{" "}
        <Link href={declineInviteUrl} className="text-[#ef4444] underline">
          decline this invitation
        </Link>
        .
      </Text>

      <Hr className="meta-border border-[#e5e7eb] my-5" />

      <Text className="secondary-text text-[11px] text-[#9ca3af] leading-4 m-0">
        This invitation was intended for your email address. It will automatically expire in 7 calendar days. If you were not expecting this invitation, report it immediately to security@acme.com.
      </Text>
    </BaseLayout>
  );
};

export default TeamInviteEmail;
```

---

### Template 3: Stripe Itemized Invoice & Payment Receipt

Features a line-item billing table, sales tax breakdown, last 4 digits payment card attribution, and invoice PDF retrieval CTA.

```tsx
import * as React from "react";
import {
  Button,
  Heading,
  Hr,
  Link,
  Section,
  Text,
} from "@react-email/components";
import { BaseLayout } from "./components/BaseLayout";

interface LineItem {
  id: string;
  description: string;
  period: string;
  amount: number;
}

interface InvoiceEmailProps {
  invoiceId: string;
  billingDate: string;
  paymentMethod: string;
  subtotal: number;
  tax: number;
  total: number;
  currency: string;
  downloadPdfUrl: string;
  items: LineItem[];
}

export const StripeInvoiceEmail = ({
  invoiceId = "INV-2024-00891",
  billingDate = "October 31, 2024",
  paymentMethod = "Mastercard ending in 4242",
  subtotal = 149.0,
  tax = 12.67,
  total = 161.67,
  currency = "USD",
  downloadPdfUrl = "https://billing.stripe.com/p/session/live_12345/pdf",
  items = [
    {
      id: "li_1",
      description: "Acme Engine Pro Tier (Monthly Retainer)",
      period: "Nov 01, 2024 - Dec 01, 2024",
      amount: 149.0,
    },
  ],
}: InvoiceEmailProps) => {
  const formatCurrency = (val: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency }).format(val);

  return (
    <BaseLayout previewText={`Receipt for invoice ${invoiceId} - ${formatCurrency(total)}`}>
      <table className="w-full">
        <tbody>
          <tr>
            <td>
              <Heading className="primary-text text-xl font-bold text-[#111827] m-0 tracking-tight">
                Receipt #{invoiceId}
              </Heading>
              <Text className="secondary-text text-xs text-[#6b7280] mt-1 mb-0">
                Paid on {billingDate}
              </Text>
            </td>
            <td className="text-right">
              <span className="bg-[#dcfce7] text-[#15803d] text-xs font-bold px-2 py-1 rounded">
                PAID
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <Hr className="meta-border border-[#e5e7eb] my-5" />

      {/* Invoice Itemization Table */}
      <table className="w-full text-left border-collapse mb-4">
        <thead>
          <tr className="border-b border-solid border-[#e5e7eb]">
            <th className="secondary-text text-xs font-semibold text-[#6b7280] pb-2 uppercase tracking-wider">
              Description
            </th>
            <th className="secondary-text text-xs font-semibold text-[#6b7280] pb-2 text-right uppercase tracking-wider">
              Amount
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-b border-solid border-[#f3f4f6]">
              <td className="py-3">
                <Text className="primary-text text-sm font-medium text-[#111827] m-0">
                  {item.description}
                </Text>
                <Text className="secondary-text text-xs text-[#6b7280] m-0">
                  {item.period}
                </Text>
              </td>
              <td className="py-3 text-right primary-text text-sm font-medium text-[#111827] align-top">
                {formatCurrency(item.amount)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Totals Calculation */}
      <table className="w-full text-sm mb-6">
        <tbody>
          <tr>
            <td className="text-[#6b7280] secondary-text py-1">Subtotal</td>
            <td className="text-right primary-text py-1 text-[#111827]">
              {formatCurrency(subtotal)}
            </td>
          </tr>
          <tr>
            <td className="text-[#6b7280] secondary-text py-1">State & Sales Tax (8.5%)</td>
            <td className="text-right primary-text py-1 text-[#111827]">
              {formatCurrency(tax)}
            </td>
          </tr>
          <tr className="border-t border-solid border-[#e5e7eb]">
            <td className="font-bold text-base primary-text pt-2 text-[#111827]">Total Paid</td>
            <td className="font-bold text-base primary-text pt-2 text-right text-[#111827]">
              {formatCurrency(total)}
            </td>
          </tr>
        </tbody>
      </table>

      {/* Payment details metadata */}
      <Section className="code-box bg-[#f8fafc] border border-solid border-[#e2e8f0] rounded-lg p-3 mb-6">
        <Text className="secondary-text text-xs text-[#64748b] m-0">
          Charged to <strong>{paymentMethod}</strong>. Your card issuer has authorized this capture.
        </Text>
      </Section>

      <Section className="text-center">
        <Button
          className="bg-transparent border border-solid border-[#d1d5db] text-[#374151] primary-text font-medium text-xs px-4 py-2.5 rounded-lg no-underline inline-block hover:bg-[#f9fafb]"
          href={downloadPdfUrl}
        >
          Download Official PDF Invoice
        </Button>
      </Section>
    </BaseLayout>
  );
};

export default StripeInvoiceEmail;
```

---

### Template 4: Usage Limit Spike & Rate Limit Warning

Features HTML table progress bars, hard limit countdowns, and instant upgrade path links to prevent API outages.

```tsx
import * as React from "react";
import {
  Button,
  Heading,
  Hr,
  Section,
  Text,
} from "@react-email/components";
import { BaseLayout } from "./components/BaseLayout";

interface UsageLimitSpikeProps {
  metricName: string;
  currentUsage: number;
  thresholdLimit: number;
  percentageUsed: number;
  resetDate: string;
  upgradeUrl: string;
}

export const UsageLimitSpikeEmail = ({
  metricName = "Monthly Ingestion API Calls",
  currentUsage = 924500,
  thresholdLimit = 1000000,
  percentageUsed = 92.4,
  resetDate = "November 1, 2024",
  upgradeUrl = "https://app.acme.com/settings/billing/upgrade",
}: UsageLimitSpikeProps) => {
  const isSevere = percentageUsed >= 90;
  const barColor = isSevere ? "#ef4444" : "#f59e0b";

  return (
    <BaseLayout previewText={`ALERT: ${metricName} is at ${percentageUsed}% capacity`}>
      <Heading className="primary-text text-xl font-bold text-[#111827] mt-0 mb-2">
        Action Required: {metricName} at {percentageUsed}%
      </Heading>

      <Text className="primary-text text-sm leading-6 text-[#374151] mb-5">
        Your production environment has exceeded {percentageUsed}% of its allocated monthly quota. Once your organization hits 100%, API calls will return <code className="bg-[#f3f4f6] px-1 py-0.5 rounded text-xs">HTTP 429 Too Many Requests</code>.
      </Text>

      {/* Native HTML Progress Bar for Email Clients */}
      <Section className="code-box bg-[#f8fafc] border border-solid border-[#e2e8f0] rounded-lg p-5 mb-6">
        <table className="w-full text-xs font-semibold text-[#4b5563] mb-2">
          <tbody>
            <tr>
              <td>Current Consumption</td>
              <td className="text-right">
                {currentUsage.toLocaleString()} / {thresholdLimit.toLocaleString()} units
              </td>
            </tr>
          </tbody>
        </table>

        {/* Outer Bar */}
        <table
          className="w-full bg-[#e5e7eb] rounded-full overflow-hidden"
          style={{ height: "12px", borderCollapse: "collapse" }}
        >
          <tbody>
            <tr>
              {/* Active Fill */}
              <td
                style={{
                  width: `${percentageUsed}%`,
                  backgroundColor: barColor,
                  height: "12px",
                }}
              />
              {/* Remainder */}
              <td
                style={{
                  width: `${100 - percentageUsed}%`,
                  height: "12px",
                }}
              />
            </tr>
          </tbody>
        </table>

        <Text className="secondary-text text-[11px] text-[#6b7280] mt-3 mb-0">
          Quota resets on {resetDate}. You have {(thresholdLimit - currentUsage).toLocaleString()} calls remaining.
        </Text>
      </Section>

      <Section className="text-center my-6">
        <Button
          className="bg-[#ef4444] hover:bg-[#dc2626] text-white font-medium text-sm px-6 py-3 rounded-lg no-underline inline-block w-full text-center box-border shadow-sm"
          href={upgradeUrl}
        >
          Upgrade Quota Allocation
        </Button>
      </Section>

      <Hr className="meta-border border-[#e5e7eb] my-5" />

      <Text className="secondary-text text-xs text-[#6b7280] leading-5 m-0">
        Need custom high-throughput scaling? Contact our architecture team by replying directly to this email to request an emergency capacity override.
      </Text>
    </BaseLayout>
  );
};

export default UsageLimitSpikeEmail;
```

---

## 3. Production LLM Prompt Engine: React Email Spec

Use the prompt below with Claude 3.5 Sonnet or GPT-4o to build complete, client-compatible React Email components matching this design system without regression.

```markdown
You are a Staff Email Infrastructure Engineer specializing in building bulletproof React Email components that compile to cross-client HTML compatible with Gmail, Apple Mail, and Outlook 2016-365.

### TARGET ENVIRONMENT
- Framework: React Email (@react-email/components)
- Engine: Resend / Node.js
- Styling: Tailwind CSS classes via <Tailwind> + CSS variable dark-mode fallbacks
- Compatibility Matrix:
  * Outlook Desktop: Must utilize <table> based layout structures; avoid flexbox and grid completely.
  * Apple Mail / iOS: Enforce -webkit-text-size-adjust: none.
  * Dark Mode: Must declare color-scheme meta tags and use explicit dark-mode class overrides (.primary-text, .content-card, .email-bg).

### STRICT CODE CONSTRAINTS
1. NEVER output pseudo-code or comments like `// implement remaining fields here`. Provide the 100% complete file.
2. All components must import primitives from `@react-email/components`:
   `Html, Head, Preview, Body, Container, Section, Text, Heading, Button, Hr, Link, Tailwind`
3. Button elements must ALWAYS supply inline padding and display attributes (`display: inline-block`, `no-underline`) to avoid collapsed geometry in Outlook.
4. All images must specify concrete numerical `width` and `height` properties to prevent canvas blowouts prior to asset caching.
5. All layout containers must be constructed using `<table>` elements with explicit zeroed borders, padding, and margins if nested inside `<Section>`.
6. Define a comprehensive TypeScript Interface defining props with production fallback defaults in the function signature.
7. Wrap your entire component in the standard BaseLayout pattern.

### TEMPLATE REQUEST FORMAT
To generate a template, provide:
1. Template Name / Purpose
2. Props Schema (Data variables required)
3. Primary Action URL / Target
4. Key Information Hierarchy (e.g., Status badging, data grids, callouts)

BEGIN GENERATION BASED ON USER PARAMETERS.
```

---

## 4. Production Resend Dispatch Engine

This complete TypeScript pipeline features Zod payload validation, exponential backoff retries, metadata tracking, and idempotency key propagation.

### `lib/mailer.ts`

```typescript
import { Resend } from "resend";
import { z } from "zod";
import * as React from "react";

// Initialize Resend Client
const resend = new Resend(process.env.RESEND_API_KEY);

if (!process.env.RESEND_API_KEY) {
  throw new Error("FATAL: RESEND_API_KEY environment variable is missing.");
}

// Validation Schema for Generic Transactional Dispatch
export const SendTransactionalEmailSchema = z.object({
  to: z.union([z.string().email(), z.array(z.string().email())]),
  subject: z.string().min(1).max(256),
  react: z.custom<React.ReactElement>((data) => React.isValidElement(data), {
    message: "Must provide a valid React Element template",
  }),
  replyTo: z.string().email().optional().default("support@acme.com"),
  from: z.string().min(1).default("Acme Engine <notifications@updates.acme.com>"),
  idempotencyKey: z.string().uuid(),
  tags: z.array(
    z.object({
      name: z.string(),
      value: z.string(),
    })
  ).optional(),
});

export type SendTransactionalEmailInput = z.infer<typeof SendTransactionalEmailSchema>;

interface SendResult {
  success: boolean;
  messageId?: string;
  error?: string;
}

/**
 * Dispatches an email through Resend with Zod validation and retry mechanics.
 */
export async function sendTransactionalEmail(
  payload: SendTransactionalEmailInput,
  maxRetries: number = 3
): Promise<SendResult> {
  const validation = SendTransactionalEmailSchema.safeParse(payload);

  if (!validation.success) {
    return {
      success: false,
      error: `Validation Error: ${JSON.stringify(validation.error.flatten().fieldErrors)}`,
    };
  }

  const { to, subject, react, replyTo, from, idempotencyKey, tags } = validation.data;

  let attempt = 0;
  while (attempt < maxRetries) {
    try {
      attempt++;
      const { data, error } = await resend.emails.send(
        {
          from,
          to,
          subject,
          react,
          reply_to: replyTo,
          headers: {
            "X-Entity-Ref-ID": idempotencyKey,
            "Idempotency-Key": idempotencyKey,
          },
          tags: [
            ...(tags || []),
            { name: "environment", value: process.env.NODE_ENV || "development" },
          ],
        }
      );

      if (error) {
        // Evaluate rate limit or 5xx failures for retry eligibility
        if (attempt < maxRetries) {
          const backoffTime = Math.pow(2, attempt) * 250;
          await new Promise((res) => setTimeout(res, backoffTime));
          continue;
        }
        return { success: false, error: error.message };
      }

      return { success: true, messageId: data?.id };
    } catch (err: unknown) {
      if (attempt >= maxRetries) {
        return {
          success: false,
          error: err instanceof Error ? err.message : "Unknown dispatch network failure",
        };
      }
      const backoffTime = Math.pow(2, attempt) * 250;
      await new Promise((res) => setTimeout(res, backoffTime));
    }
  }

  return { success: false, error: "Exhausted maximum retry budget" };
}
```

---

## 5. Next.js App Router API Route Implementation

The edge-ready Next.js route below validates the user session, parses inbound JSON, and dispatches the `MagicLinkEmail` template with absolute typing.

### `app/api/auth/magic-link/route.ts`

```typescript
import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import crypto from "crypto";
import { sendTransactionalEmail } from "@/lib/mailer";
import MagicLinkEmail from "@/emails/MagicLinkEmail";

// Inbound Request Schema
const RequestSchema = z.object({
  email: z.string().email(),
  redirectUrl: z.string().url().optional(),
});

export async function POST(req: NextRequest) {
  try {
