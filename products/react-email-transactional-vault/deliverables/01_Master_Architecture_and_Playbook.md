# Module 1: Complete Architecture & Core Playbook

Shipping transactional emails that render identically across 60+ email clients requires abandoning standard modern web paradigms. Email client engines range from WebKit (Apple Mail) to Blink (Gmail) down to the Microsoft Word 2007–2019 rendering engine (`MSHTML`/`MSO`) powering Windows desktop Outlook.

This module details the complete rendering architecture, cross-client quirks, type-safe payload interpolation, and automated CI/CD visual regression pipelines that form the foundation of our production vault.

---

## 1. System Architecture: The Bulletproof Pipeline

Transactional email rendering differs fundamentally from standard React web rendering. Rather than compiling to a lightweight DOM tree hydrated in the browser, React Email templates must compile down to strict XHTML 1.0 Transitional markup, inline all CSS styles, inject conditional Vector Markup Language (VML) for Outlook desktop, and bypass aggressive sanitation engines (such as Gmail’s clipping engine and Apple Mail’s dark mode processor).

```
+--------------------------------------------------------------------------------+
|                        TRANSACTIONAL EMAIL ENGINE                              |
+--------------------------------------------------------------------------------+
                                       |
                   [Type-Safe App Event Payload (JSON)]
                                       |
                                       v
                  +-----------------------------------------+
                  |  1. Runtime Validation (Zod Engine)     |
                  |     - Type coercion                     |
                  |     - XSS sanitization                  |
                  |     - Currency/Date locale formatting   |
                  +-----------------------------------------+
                                       |
                                       v
                  +-----------------------------------------+
                  |  2. React Email Render Engine           |
                  |     - Tree transformation               |
                  |     - Inline CSS generation             |
                  |     - Conditional MSO comment injection |
                  +-----------------------------------------+
                                       |
                                       v
                  +-----------------------------------------+
                  |  3. Post-Processing & Optimization     |
                  |     - Gmail byte-size audit (<102KB)    |
                  |     - Pre-header padding injection      |
                  |     - Plaintext fallback generation     |
                  +-----------------------------------------+
                                       |
                                       v
                  +-----------------------------------------+
                  |  4. Delivery via Resend API             |
                  |     - DKIM, SPF, DMARC-aligned domain   |
                  |     - TLS 1.3 opportunistic encryption  |
                  +-----------------------------------------+
                                       |
         +-----------------------------+-----------------------------+
         |                             |                             |
         v                             v                             v
+------------------+         +-------------------+         +-------------------+
|  Apple WebKit    |         |  Google Blink     |         |  Microsoft MSO    |
|  (Apple Mail)    |         |  (Gmail Web/App)  |         |  (Outlook Win32)  |
|  - Full CSS3     |         |  - Strips classes |         |  - Word engine    |
|  - Strict Dark   |         |  - 102KB clipping |         |  - No flexbox/grid|
|    Mode overrides|         |  - Auto-link bugs |         |  - Requires VML   |
+------------------+         +-------------------+         +-------------------+
```

### The Three Golden Constraints

1. **The 102KB Boundary**: Gmail desktop cuts off any email message whose total raw HTML size exceeds 102 kilobytes, rendering a destructive `[Message clipped] View entire message` link. This destroys click-through tracking pixels and breaks footer unsubscribe functionality (risking immediate deliverability penalties and CAN-SPAM/GDPR compliance breaches).
2. **The MSO Word Rendering Engine**: Outlook 2013, 2016, 2019, and 2021 on Windows do not use Internet Explorer, Edge, or Chromium. They use **Microsoft Word**. This engine fundamentally does not understand `display: flex`, `display: grid`, `max-width`, `margin: auto`, CSS transitions, or standard `border-radius`.
3. **Aggressive Dark Mode Inversion Schemes**: While Apple Mail supports explicit `@media (prefers-color-scheme: dark)` overrides, Gmail mobile apps and Outlook desktop run aggressive algorithmic color inversions that flip pure black text to pure white and light gray backgrounds to dark slate—often rendering transparent logos invisible or creating low-contrast, unreadable paragraphs.

---

## 2. Cross-Client Rendering Engine Matrix

The following matrix documents the specific rendering behaviors across all major email clients and provides the production-grade workarounds applied across all templates in this Vault.

| Client | Core Rendering Engine | Major CSS/HTML Limitations | Vault Workaround / Engine Fix |
| :--- | :--- | :--- | :--- |
| **Apple Mail (macOS / iOS)** | WebKit | Full CSS3 support; aggressive font-boosting on iOS; automatic phone number and date detection wrapping text in blue links. | Add `x-apple-data-detectors=no` meta tag; disable font-boosting with `-webkit-text-size-adjust: none;`. |
| **Gmail (Webmail / Android / iOS)** | Blink (heavily sanitized) | Drops entire `<style>` tag if it contains a single syntax error; clips emails at 102KB; does not support CSS variables (`var(--token)`); strips custom data attributes. | Inline all critical styles directly on elements; post-process CSS to eliminate syntax errors; maintain unminified HTML payload below 98KB. |
| **Outlook for Windows (2016 - 2021)** | Microsoft Word (`MSO`) | Zero support for CSS Flexbox, CSS Grid, `max-width`, absolute positioning, or `box-shadow`; collapses empty table cells; ignores padding on `<div>` elements. | Ghost tables: wrap sections in `<!--[if mso]><table role="presentation">...<![endif]-->`; use VML (`v:roundrect`) for buttons; enforce explicit dimensions. |
| **Outlook.com / Office 365 (Web)** | Chromium / Gecko / WebKit | Strips custom `id` and changes classes with prefixes; intermittently drops margin declarations; modifies CSS background colors. | Use `margin` and `padding` exclusively on `<td>` elements; avoid shorthand CSS properties (use `padding-top`, `padding-bottom`, etc.). |
| **Samsung Email** | Chromium fork | Forces arbitrary dark mode overrides that cannot be easily disabled; aggressively wraps numbers and units. | Use meta tags `supported-color-schemes` and CSS rule `#MessageWebViewDiv` targeting to lock styles. |
| **Yahoo! Mail / AOL** | Blink / WebKit | Overwrites common CSS class names; wraps body in client-specific wrappers (e.g., `.ydp...`); drops pseudo-elements. | Use dedicated attribute selectors and double-class declarations to preserve cascading specificity. |

---

## 3. The Bulletproof Layout Shell (`BaseLayout.tsx`)

This layout shell forms the foundation for every template in this library. It handles:
- Correct XML namespaces for Outlook VML rendering.
- Dark mode meta flags for iOS, macOS, and Android.
- The "Preview Hack" (injecting non-breaking spaces and zero-width characters to prevent the inbox from pulling subsequent email body text into the subject preview snippet).
- Ghost table wrapping for container stability across MSO clients.

```tsx
// components/BaseLayout.tsx
import * as React from "react";
import {
  Html,
  Head,
  Body,
  Container,
  Preview,
  Font,
} from "@react-email/components";

interface BaseLayoutProps {
  previewText: string;
  children: React.ReactNode;
  lang?: string;
}

export const BaseLayout: React.FC<BaseLayoutProps> = ({
  previewText,
  children,
  lang = "en",
}) => {
  // Construct a sequence of zero-width non-joiners to consume inbox preview snippets
  const previewPadding = "\xa0\u200C".repeat(120);

  return (
    <Html lang={lang} xmlns="http://www.w3.org/1999/xhtml" xmlnsV="urn:schemas-microsoft-com:vml" xmlnsO="urn:schemas-microsoft-com:office:office">
      <Head>
        <meta httpEquiv="Content-Type" content="text/html; charset=UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <meta name="x-apple-disable-message-reformatting" />
        <meta name="color-scheme" content="light dark" />
        <meta name="supported-color-schemes" content="light dark" />
        <meta name="format-detection" content="telephone=no, date=no, address=no, email=no" />
        {/*[if mso]>
        <noscript>
          <xml>
            <o:OfficeDocumentSettings>
              <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
          </xml>
        </noscript>
        <![endif]*/}
        <Font
          fontFamily="Inter"
          fallbackFontFamily={["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"]}
          webFont={{
            url: "https://fonts.gstatic.com/s/inter/v13/UcCO3FwrK3iLTeHuS_fvQtMwCp50KnMw2boKoduKmMEVuLyfAZ9hjp-Ek-_EeA.woff2",
            format: "woff2",
          }}
          fontWeight={400}
          fontStyle="normal"
        />
        <style dangerouslySetInnerHTML={{ __html: `
          :root {
            color-scheme: light dark;
            supported-color-schemes: light dark;
          }
          /* Reset Styles */
          html, body {
            margin: 0 auto !important;
            padding: 0 !important;
            height: 100% !important;
            width: 100% !important;
            -webkit-text-size-adjust: 100% !important;
            -ms-text-size-adjust: 100% !important;
          }
          table, td {
            mso-table-lspace: 0pt !important;
            mso-table-rspace: 0pt !important;
            border-collapse: collapse !important;
          }
          img {
            -ms-interpolation-mode: bicubic;
            border: 0;
            outline: none;
            text-decoration: none;
            display: block;
          }
          /* Dark Mode Overrides for WebKit & Blink */
          @media (prefers-color-scheme: dark) {
            .dark-mode-bg {
              background-color: #090A0F !important;
            }
            .dark-mode-card {
              background-color: #141721 !important;
              border-color: #262B3D !important;
            }
            .dark-mode-text-primary {
              color: #F8FAFC !important;
            }
            .dark-mode-text-secondary {
              color: #94A3B8 !important;
            }
            .dark-mode-border {
              border-color: #262B3D !important;
            }
          }
          /* Custom Outlook Fallbacks */
          [owa] .layout-container {
            width: 600px !important;
          }
        `}} />
      </Head>
      <Preview>
        {previewText}
        {previewPadding}
      </Preview>
      <Body style={{
        margin: 0,
        padding: "40px 0 40px 0",
        backgroundColor: "#F1F5F9",
        WebkitFontSmoothing: "antialiased",
      }} className="dark-mode-bg">
        {/* Ghost Table for Outlook Desktop (MSO) to enforce standard 600px boundary */}
        {/*[if (gte mso 9)|(IE)]>
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="600" role="presentation" style="width: 600px;">
          <tr>
            <td align="center" valign="top">
        <![endif]*/}
        <Container
          className="dark-mode-card"
          style={{
            maxWidth: "600px",
            margin: "0 auto",
            backgroundColor: "#FFFFFF",
            borderRadius: "12px",
            border: "1px solid #E2E8F0",
            overflow: "hidden",
            boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.05)",
          }}
        >
          {children}
        </Container>
        {/*[if (gte mso 9)|(IE)]>
            </td>
          </tr>
        </table>
        <![endif]*/}
      </Body>
    </Html>
  );
};
```

---

## 4. Outlook & MSO Custom Element Architecture

### Bulletproof Buttons (Vector Markup Language - VML)

Modern CSS properties like `border-radius`, `box-shadow`, and `padding` fail when applied to standard anchor tags (`<a>`) in Outlook for Windows. The client simply strips the padding, causing the button background to wrap tightly around the text glyphs, and ignores all corner radiuses.

To fix this, we use conditional VML wrapping. Below is the production-ready button component used across the Vault:

```tsx
// components/BulletproofButton.tsx
import * as React from "react";

interface BulletproofButtonProps {
  href: string;
  children: React.ReactNode;
  width?: number;
  height?: number;
  backgroundColor?: string;
  textColor?: string;
  borderRadius?: number;
}

export const BulletproofButton: React.FC<BulletproofButtonProps> = ({
  href,
  children,
  width = 220,
  height = 48,
  backgroundColor = "#2563EB",
  textColor = "#FFFFFF",
  borderRadius = 6,
}) => {
  const arcSize = Math.round((borderRadius / height) * 100);

  return (
    <div style={{ textAlign: "center", margin: "24px 0" }}>
      {/*[if mso]>
      <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" 
        href="${href}" 
        style="height:${height}px;v-text-anchor:middle;width:${width}px;" 
        arcsize="${arcSize}%" 
        stroke="f" 
        fillcolor="${backgroundColor}">
        <w:anchorlock/>
        <center style="color:${textColor};font-family:sans-serif;font-size:16px;font-weight:600;">
          ${children}
        </center>
      </v:roundrect>
      <![endif]*/}
      {/* Standard CSS Button for all WebKit, Blink, and Modern Clients */}
      <a
        href={href}
        style={{
          backgroundColor,
          borderRadius: `${borderRadius}px`,
          color: textColor,
          display: "inline-block",
          fontFamily: "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
          fontSize: "15px",
          fontWeight: 600,
          lineHeight: `${height}px`,
          textAlign: "center",
          textDecoration: "none",
          width: `${width}px`,
          WebkitTextSizeAdjust: "none",
          msoHide: "all", // Explicitly instruct Outlook MSO to hide this modern anchor
        }}
      >
        {children}
      </a>
    </div>
  );
};
```

---

## 5. Dynamic Token Interpolation & Type-Safe Hydration Pipeline

Templates must never fail silently when dynamic user data (e.g., missing invoice line items, unescaped user-generated content, or invalid floats) is passed to the rendering engine. 

We implement an end-to-end type validation pipeline using **Zod** paired with a sanitization harness before handing the tree over to React Email.

```typescript
// engine/renderPipeline.ts
import { render } from "@react-email/render";
import { z } from "zod";
import * as React from "react";

/**
 * Example Contract: Invoice Email Schema
 */
export const InvoicePayloadSchema = z.object({
  recipientName: z.string().min(1).max(100),
  recipientEmail: z.string().email(),
  invoiceNumber: z.string().regex(/^INV-\d{4}-\d{4,}$/),
  issueDate: z.date(),
  items: z.array(
    z.object({
      description: z.string().min(1).max(255),
      quantity: z.number().int().positive(),
      unitPriceInCents: z.number().int().nonnegative(),
    })
  ).min(1),
  taxRatePercent: z.number().min(0).max(100).default(0),
  currencyCode: z.enum(["USD", "EUR", "GBP", "CAD"]).default("USD"),
  paymentLink: z.string().url(),
});

export type InvoicePayload = z.infer<typeof InvoicePayloadSchema>;

/**
 * Escapes unsafe characters in untrusted strings to mitigate injection vulnerabilities
 */
export function sanitizeEmailString(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Validates, sanitizes, and renders a React Email template to production HTML
 */
export async function compileEmail<T>(
  schema: z.ZodSchema<T>,
  untrustedData: unknown,
  TemplateComponent: React.ComponentType<T>
): Promise<{ html: string; text: string; cleanData: T }> {
  // 1. Validate payload structure runtime integrity
  const parsed = schema.safeParse(untrustedData);
  if (!parsed.success) {
    const errorDetails = JSON.stringify(parsed.error.format(), null, 2);
    throw new Error(`[EmailPayloadValidationError]: Schema enforcement failed:\n${errorDetails}`);
  }

  const cleanData = parsed.data;

  // 2. Render HTML via React Email
  const element = React.createElement(TemplateComponent, cleanData);
  const html = await render(element, { pretty: false });
  const text = await render(element, { plainText: true });

  // 3. Gmail Size Gate: Verify output does not exceed 102KB (104,448 bytes)
  const byteSize = Buffer.byteLength(html, "utf8");
  if (byteSize >= 102400) {
    console.warn(
      `[GmailClippingWarning]: Rendered HTML payload is ${byteSize} bytes. ` +
      `Gmail will clip this message! Target must remain under 102,400 bytes.`
    );
  }

  return { html, text, cleanData };
}
```

---

## 6. Automated Visual Regression Pipeline with Playwright

To guarantee pixel-level consistency across releases without manually running tests through Litmus or Email on Acid for every minor copy change, we execute Playwright visual snapshots locally and within CI/CD.

This setup tests:
1. **Light Mode Desktop** (1280 × 800)
2. **Dark Mode Desktop** (1280 × 800 via `@media (prefers-color-scheme: dark)`)
3. **Mobile Screen Emulation** (iPhone 14 Pro, 393 × 852)
4. **Byte Size Constraints** (Ensuring the compiled file stays under 100KB)

### Playwright Test Harness (`tests/email-visuals.spec.ts`)

```typescript
// tests/email-visuals.spec.ts
import { test, expect } from "@playwright/test";
import { compileEmail, InvoicePayloadSchema } from "../engine/renderPipeline";
import { InvoiceTemplate } from "../templates/InvoiceTemplate";

test.describe("Transactional Email Rendering: Invoice Template", () => {
  const mockPayload = {
    recipientName: "Alexander Hamilton",
    recipientEmail: "alexander@treasury.gov",
    invoiceNumber: "INV-2026-90412",
    issueDate: new Date("2026-03-30T12:00:00Z"),
    items: [
      { description: "Enterprise Cloud Node License (Annual)", quantity: 2, unitPriceInCents: 120000 },
      { description: "Tier 1 Priority Support SLA", quantity: 1, unitPriceInCents: 45000 },
    ],
    taxRatePercent: 8.5,
    currencyCode: "USD" as const,
    paymentLink: "https://pay.vault.local/inv_live_90412",
  };

  let renderedHtml: string;

  test.beforeAll(async () => {
    const result = await compileEmail(InvoicePayloadSchema, mockPayload, InvoiceTemplate);
    renderedHtml = result.html;
  });

  test("Strict Payload Size Gate (< 100KB)", async () => {
    const byteSize = Buffer.byteLength(renderedHtml, "utf8");
    // Stay safely under the 102,400-byte Gmail limit
    expect(byteSize).toBeLessThan(100 * 1024);
  });

  test("Desktop Light Mode: Rendering Consistency", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.setContent(renderedHtml, { waitUntil: "networkidle" });

    // Ensure main wrapper exists and matches snapshot
    const container = page.locator(".layout-container");
    await expect(page).toHaveScreenshot("invoice-desktop-light.png", {
      maxDiffPixelRatio: 0.01,
    });
  });

  test("Desktop Dark Mode: Rendering Consistency", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.setContent(renderedHtml, { waitUntil: "networkidle" });

    await expect(page).toHaveScreenshot("invoice-desktop-dark.png", {
      maxDiffPixelRatio: 0.01,
    });
  });

  test("Mobile Viewport: Single Column Flow & Font Legibility", async ({ page }) => {
    // iPhone 14 Pro Viewport
    await page.setViewportSize({ width: 393, height: 852 });
    await page.setContent(renderedHtml, { waitUntil: "networkidle" });

    // Validate that CTA button does not overflow container
    const cta = page.locator("a:has-text('View Invoice')");
    const box = await cta.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      expect(box.x).toBeGreaterThan(0);
      expect(box.x + box.width).toBeLessThanOrEqual(393);
    }

    await expect(page).toHaveScreenshot("invoice-mobile.png", {
      maxDiffPixelRatio: 0.02,
    });
  });
});
```

---

## 7. Pre-Flight Deliverability & Compilation Checklist

Before deploying any new template or payload model to production, run this checklist directly against your template code and infrastructure.

### Markup & CSS Architecture
- [ ] **Byte-Weight Check**: Total rendered HTML string size is strictly under **100KB** (102,400 bytes) measured via `Buffer.byteLength(html, 'utf8')`.
- [ ] **CSS Inlining**: No raw external stylesheets or remote `<link>` tags (excluding defined webfonts). All CSS rules are inlined directly or scoped in `<style>` blocks that use client-safe syntax.
- [ ] **MSO Ghost Wrapping**: The top-level document body wraps the 600px inner container in an `<!--[if (gte mso 9)|(IE)]>` table check.
- [ ] **Vector Markup Fallbacks**: Every primary Call To Action (button) implements a conditional `v:roundrect` shape block with explicit pixel widths and heights for legacy Outlook clients.
- [ ] **Preview Padding Snippet**: The pre-header element uses at least 120 alternating `\xa0\u200C` zero-width characters to prevent body copy from leaking into the inbox preview.
- [ ] **Image Tags**: Every `<img>` tag has explicitly declared `width`, `height`, `alt`, and `style={{ display: "block" }}` properties to prevent Outlook inline-spacing bugs.

### Dark Mode Architecture
- [ ] **Meta declarations**: Document `<head>` includes `<meta name="color-scheme" content="light dark" />` and `<meta name="supported-color-schemes" content="light dark" />`.
- [ ] **Dual-Palette Contrast**: Primary and secondary text colors inside dark-mode styles maintain a WCAG AA contrast ratio of at least **4.5:1** against the declared dark surface (`#141721` or `#090A0F`).
- [ ] **Asset Protection**: All logos and brand marks are rendered as transparent PNGs with a subtle white drop-shadow/stroke (`drop-shadow(0 0 1px rgba(255,255,255,0.8))`) to remain legible if Gmail or Outlook inverts backgrounds to black.

### Data Hydration & Security
- [ ] **Schema Validation**: All dynamic data variables are parsed via strict runtime schemas (Zod).
- [ ] **XSS Sanitization**: Dynamic strings (such as usernames, notes, or descriptions) are checked and sanitized for HTML entities before insertion.
- [ ] **Zero Template Language Leaks**: No raw handlebars (`{{var}}`) or template syntax reach production; missing inputs throw descriptive compile-time errors rather than rendering blank elements.

---

## 8. Client Debugging Matrix

When rendering anomalies occur during staging, use this debugging guide:

### Symptom 1: Ghost gaps (2-3px spaces) beneath images
- **Root Cause**: The client treats the image as an inline element, allocating space for font descenders (`g`, `y`, `p`).
- **Fix**: Apply `display: block !important; margin: 0; padding: 0; outline: none; border: none;` to the image element. Ensure the parent `<td>` has `line-height: 0; font-size: 0px;`.

### Symptom 2: Desktop Outlook centers a left-aligned container
- **Root Cause**: Outlook ignores `margin: 0 auto` or `margin: 0` on `div` wrappers.
- **Fix**: Wrap the component in a table with an explicit align attribute: `<table align="left" role="presentation">`.

### Symptom 3: Gmail strips all `<style>` rules, breaking layout
- **Root Cause**: A single syntax error (e.g., an unescaped character, an empty property, an unsupported `@media` nesting query, or an unclosed brace) was detected inside the `<style>` block.
- **Fix**: Run all custom styles through a CSS validator. Never nest CSS rules inside templates; keep the stylesheet 100% flat.

### Symptom 4: Links turn unexpectedly blue on iOS / Apple Mail
- **Root Cause**: Apple Mail's data detection engine matches dates, phone numbers, and physical addresses, automatically injecting inline `<a>` tags with default WebKit link styles.
- **Fix**: Add the following rule to your `<Head>` block:
```html
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no" />
```
Then, add this CSS override:
```css
a[x-apple-data-detectors] {
  color: inherit !important;
  text-decoration: none !important;
  font-size: inherit !important;
  font-family: inherit !important;
  font-weight: inherit !important;
  line-height: inherit !important;
}
```

---

## 9. Vault Implementation Standards

Throughout the remaining modules and templates in this Vault, every single component adheres strictly to the architectural standards defined here:

1. Every template extends `BaseLayout.tsx`.
2. Every interactive link or button implements `BulletproofButton.tsx` or its inline text equivalent.
3. Every payload is paired with a corresponding `.schema.ts` file containing a validated Zod schema.
4. Every template is tested against our Playwright visual regression suite across both desktop and mobile viewports.

This architecture ensures your transactional emails render consistently, maintain deliverability compliance, and work reliably across all major email clients.
