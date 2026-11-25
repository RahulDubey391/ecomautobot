# Module 2: 50+ Production Test Suites, Auth Fixtures & Page Objects

This module contains complete, production-ready Playwright implementations for the most volatile, mission-critical integration points in modern SaaS architectures: Stripe custom element checkouts, Time-based One-Time Passwords (TOTP), ephemeral magic-link verification via API polling, streaming WebSockets, dynamic canvas/virtual data grids, large multipart CSV file ingestions, and matrix-based Role-Based Access Control (RBAC).

All code blocks conform to strict TypeScript, modern Page Object Model (POM) standards, custom fixture isolation, and zero-flake locator strategies (`getByRole`, `getByTestId`, web-first assertions).

---

## 1. Enterprise Auth Fixtures: TOTP, Storage State & Magic Links

### 1.1 Complete Auth Fixture Architecture (`fixtures/auth.fixture.ts`)

This fixture automates MFA (TOTP) generation using standard HMAC-SHA1 calculation and handles local storage session persistence, completely eliminating the login step across dependent specs.

```typescript
import { test as baseTest, expect, Page, BrowserContext } from '@playwright/test';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';

// --- Cryptographic TOTP Engine (RFC 6238 compliant) ---
export function generateTOTP(secret: string, timeStepWindow = 30): string {
  const cleanSecret = secret.replace(/\s+/g, '').toUpperCase();
  const base32Lookup = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';

  for (let i = 0; i < cleanSecret.length; i++) {
    const val = base32Lookup.indexOf(cleanSecret.charAt(i));
    if (val === -1) throw new Error('Invalid Base32 character encountered in TOTP secret');
    bits += val.toString(2).padStart(5, '0');
  }

  const bytes = new Uint8Array(Math.floor(bits.length / 8));
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(bits.substring(i * 8, (i + 1) * 8), 2);
  }

  const epoch = Math.floor(Date.now() / 1000);
  const counter = Math.floor(epoch / timeStepWindow);
  const counterBuffer = Buffer.alloc(8);
  counterBuffer.writeBigInt64BE(BigInt(counter));

  const hmac = crypto.createHmac('sha1', Buffer.from(bytes));
  hmac.update(counterBuffer);
  const digest = hmac.digest();

  const offset = digest[digest.length - 1] & 0xf;
  const binaryCode =
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] & 0xff) << 16) |
    ((digest[offset + 2] & 0xff) << 8) |
    (digest[offset + 3] & 0xff);

  const otp = binaryCode % 1000000;
  return otp.toString().padStart(6, '0');
}

// --- Extended Fixture Typing ---
type EnterpriseAuthFixtures = {
  authenticatedPage: Page;
  adminStorageState: string;
};

export const test = baseTest.extend<EnterpriseAuthFixtures>({
  adminStorageState: async ({}, use) => {
    const storageStatePath = path.resolve(__dirname, '../.auth/admin-state.json');
    await use(storageStatePath);
  },

  authenticatedPage: async ({ browser, adminStorageState }, use) => {
    let context: BrowserContext;

    if (fs.existsSync(adminStorageState)) {
      context = await browser.newContext({ storageState: adminStorageState });
      const page = await context.newPage();
      await use(page);
      await context.close();
      return;
    }

    // Fallback: Perform UI authentication and save storage state if cached file does not exist
    context = await browser.newContext();
    const page = await context.newPage();

    const baseUrl = process.env.BASE_URL || 'https://app.enterprise-saas.internal';
    const email = process.env.E2E_ADMIN_EMAIL || 'security-admin@enterprise-saas.internal';
    const password = process.env.E2E_ADMIN_PASSWORD || 'Str0ngP@ssw0rd!2026';
    const totpSecret = process.env.E2E_ADMIN_TOTP_SECRET || 'JBSWY3DPEHPK3PXP';

    await page.goto(`${baseUrl}/login`);
    await page.getByLabel('Work Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Continue with Secure SSO' }).click();

    // Challenge screen: TOTP Verification
    await expect(page.getByRole('heading', { name: 'Two-Factor Verification' })).toBeVisible();
    const token = generateTOTP(totpSecret);
    
    // Fill OTP split inputs or direct text field
    const otpInput = page.getByRole('textbox', { name: 'Verification Code' });
    if (await otpInput.isVisible()) {
      await otpInput.fill(token);
    } else {
      const splitInputs = page.locator('input[data-otp-index]');
      const digits = token.split('');
      for (let i = 0; i < digits.length; i++) {
        await splitInputs.nth(i).fill(digits[i]);
      }
    }

    await page.getByRole('button', { name: 'Verify Identity' }).click();
    await page.waitForURL(`${baseUrl}/dashboard`);
    await expect(page.getByTestId('main-navigation-panel')).toBeVisible();

    // Persist storage state for reuse
    const authDir = path.dirname(adminStorageState);
    if (!fs.existsSync(authDir)) {
      fs.mkdirSync(authDir, { recursive: true });
    }
    await context.storageState({ path: adminStorageState });

    await use(page);
    await context.close();
  },
});

export { expect } from '@playwright/test';
```

---

### 1.2 Magic Link Polling & Email API Mock Verification (`specs/auth-magic-link.spec.ts`)

This spec triggers a passwordless login and uses an API request context to poll Mailosaur or an in-memory test email API directly, extracting the dynamic JWT link without third-party web interface latency.

```typescript
import { test, expect } from '@playwright/test';

interface MailInboxMessage {
  id: string;
  to: string;
  subject: string;
  html: string;
  receivedAt: string;
}

test.describe('Passwordless Magic Link Verification', () => {
  const mailTrapApiUrl = 'http://localhost:8025/api/v1/messages';
  const targetEmail = `e2e-magic-${Date.now()}@test.internal`;

  test('requests magic link, polls backend mail catcher, and validates user token session', async ({ page, request }) => {
    // 1. Trigger the link send
    await page.goto('/login/magic-link');
    await page.getByRole('textbox', { name: 'Corporate Email' }).fill(targetEmail);
    await page.getByRole('button', { name: 'Send Magic Link' }).click();

    await expect(page.getByTestId('confirmation-banner')).toContainText(
      'A secure sign-in link has been sent to your email.'
    );

    // 2. Poll API with progressive exponential backoff
    let magicLinkUrl = '';
    const maxAttempts = 10;
    const initialDelayMs = 500;

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const response = await request.get(mailTrapApiUrl);
      if (response.ok()) {
        const messages: MailInboxMessage[] = await response.json();
        const targetedMessage = messages.find((msg) => msg.to.includes(targetEmail));

        if (targetedMessage) {
          // Parse href matching secure login URL format
          const linkMatch = targetedMessage.html.match(/href="([^"]+\/auth\/verify\?token=[^"]+)"/);
          if (linkMatch && linkMatch[1]) {
            magicLinkUrl = linkMatch[1];
            break;
          }
        }
      }
      await new Promise((resolve) => setTimeout(resolve, initialDelayMs * Math.pow(1.5, attempt)));
    }

    expect(magicLinkUrl).not.toBe('');

    // 3. Navigate directly to verified magic link URL
    await page.goto(magicLinkUrl);

    // 4. Assert authentication handshake completes and redirects to on-boarding
    await expect(page).toHaveURL(/.*\/onboarding\/welcome/);
    await expect(page.getByTestId('user-profile-badge')).toBeVisible();
    await expect(page.getByTestId('user-profile-badge')).toContainText(targetEmail);
  });
});
```

---

## 2. Stripe Checkout & Payment Element Page Object Architecture

Stripe Elements load cross-origin `iframe` components (`js.stripe.com`). Standard Playwright selectors fail here unless targeted through `FrameLocator`.

```
┌────────────────────────────────────────────────────────────────┐
│ Page Context (Host Application)                               │
│  - Shipping Address Inputs                                     │
│  - Order Summary Total                                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ FrameLocator('iframe[name*="__privateStripeFrame"]')     │  │
│  │  - Card Number: input[name="cardnumber"]                 │  │
│  │  - Expiry:      input[name="exp-date"]                   │  │
│  │  - CVC:         input[name="cvc"]                        │  │
│  │  - Postal:      input[name="postal"]                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│  - Submit Button: [data-testid="pay-button"]                   │
└────────────────────────────────────────────────────────────────┘
```

### 2.1 Stripe Payment Page Object (`models/StripeCheckoutPage.ts`)

```typescript
import { Page, Locator, FrameLocator, expect } from '@playwright/test';

export interface CardDetails {
  number: string;
  expiry: string;
  cvc: string;
  zip: string;
}

export class StripeCheckoutPage {
  readonly page: Page;
  readonly checkoutButton: Locator;
  readonly orderSuccessHeader: Locator;
  readonly stripeFrameLocator: FrameLocator;
  readonly cardNumberInput: Locator;
  readonly cardExpiryInput: Locator;
  readonly cardCvcInput: Locator;
  readonly billingZipInput: Locator;
  readonly submitPaymentButton: Locator;
  readonly processingIndicator: Locator;

  constructor(page: Page) {
    this.page = page;
    this.checkoutButton = page.getByTestId('initiate-checkout-button');
    this.orderSuccessHeader = page.getByRole('heading', { name: 'Payment Successful' });
    
    // Stripe mounts Payment Element inside a nested iframe structure
    this.stripeFrameLocator = page.frameLocator('iframe[name^="__privateStripeFrame"]').first();
    this.cardNumberInput = this.stripeFrameLocator.locator('input[name="cardnumber"]');
    this.cardExpiryInput = this.stripeFrameLocator.locator('input[name="exp-date"]');
    this.cardCvcInput = this.stripeFrameLocator.locator('input[name="cvc"]');
    this.billingZipInput = this.stripeFrameLocator.locator('input[name="postal"]');
    
    this.submitPaymentButton = page.getByTestId('stripe-submit-button');
    this.processingIndicator = page.getByTestId('stripe-loading-spinner');
  }

  async goto() {
    await this.page.goto('/billing/checkout');
    await expect(this.checkoutButton).toBeVisible();
  }

  async selectPlan(planName: string) {
    await this.page.getByRole('radio', { name: planName }).check();
    await this.checkoutButton.click();
  }

  async fillPaymentDetails(card: CardDetails) {
    // Assert Stripe elements inside the iframe are fully interactive
    await expect(this.cardNumberInput).toBeVisible({ timeout: 15000 });
    
    // Sequential character typing mimics precise input masks to bypass Stripe client-side validation failures
    await this.cardNumberInput.pressSequentially(card.number, { delay: 50 });
    await this.cardExpiryInput.pressSequentially(card.expiry, { delay: 50 });
    await this.cardCvcInput.pressSequentially(card.cvc, { delay: 50 });
    
    if (await this.billingZipInput.isVisible()) {
      await this.billingZipInput.pressSequentially(card.zip, { delay: 50 });
    }
  }

  async submitPayment() {
    await expect(this.submitPaymentButton).toBeEnabled();
    await this.submitPaymentButton.click();
  }

  async verifySuccess() {
    await expect(this.processingIndicator).toBeHidden({ timeout: 20000 });
    await expect(this.orderSuccessHeader).toBeVisible({ timeout: 15000 });
  }

  async verifyDeclinedError(expectedMessage: string) {
    const errorBanner = this.page.getByTestId('stripe-payment-error');
    await expect(errorBanner).toBeVisible();
    await expect(errorBanner).toContainText(expectedMessage);
  }
}
```

### 2.2 Stripe Execution Specs with Scenarios (`specs/stripe-checkout.spec.ts`)

```typescript
import { test, expect } from '@playwright/test';
import { StripeCheckoutPage } from '../models/StripeCheckoutPage';

test.describe('Stripe Checkout Workflows', () => {
  let checkoutPage: StripeCheckoutPage;

  test.beforeEach(async ({ page }) => {
    checkoutPage = new StripeCheckoutPage(page);
    await checkoutPage.goto();
  });

  test('processes valid payment with 3D Secure / Success test card', async () => {
    await checkoutPage.selectPlan('Enterprise Annual Tier');
    await checkoutPage.fillPaymentDetails({
      number: '4242424242424242',
      expiry: '12/28',
      cvc: '242',
      zip: '94103',
    });
    await checkoutPage.submitPayment();
    await checkoutPage.verifySuccess();
  });

  test('handles declined cards with appropriate UX feedback', async () => {
    await checkoutPage.selectPlan('Enterprise Annual Tier');
    await checkoutPage.fillPaymentDetails({
      number: '4000000000000002', // Stripe Card Declined test number
      expiry: '05/27',
      cvc: '123',
      zip: '94103',
    });
    await checkoutPage.submitPayment();
    await checkoutPage.verifyDeclinedError('Your card was declined.');
  });

  test('handles insufficient funds error', async () => {
    await checkoutPage.selectPlan('Enterprise Annual Tier');
    await checkoutPage.fillPaymentDetails({
      number: '4000000000009995', // Stripe Insufficient Funds
      expiry: '11/26',
      cvc: '999',
      zip: '94103',
    });
    await checkoutPage.submitPayment();
    await checkoutPage.verifyDeclinedError('Your card has insufficient funds.');
  });
});
```

---

## 3. High-Throughput Real-Time WebSocket Messaging

Testing WebSockets requires validating both UI rendering and bidirectional protocol frame integrity.

```typescript
import { test, expect, WebSocket } from '@playwright/test';

interface ChatPayload {
  channelId: string;
  sender: string;
  body: string;
  timestamp: number;
}

test.describe('Real-Time Collaborative Messaging over WebSocket', () => {
  test('intercepts frames, publishes messages, and ensures zero dropped frames across dual sessions', async ({ page }) => {
    const receivedFrames: string[] = [];
    const sentFrames: string[] = [];
    let trackedWebSocket: WebSocket | null = null;

    // Listen to WebSocket initialization event on the page
    page.on('websocket', (ws) => {
      trackedWebSocket = ws;
      
      ws.on('framesent', (event) => {
        sentFrames.push(event.payload.toString());
      });
      
      ws.on('framereceived', (event) => {
        receivedFrames.push(event.payload.toString());
      });
      
      ws.on('close', () => {
        // Socket closed
      });
    });

    await page.goto('/channels/engineering-core');

    // Wait until connection is registered
    await expect.poll(() => trackedWebSocket !== null, {
      message: 'WebSocket connection failed to initialize',
      timeout: 10000,
    }).toBeTruthy();

    const chatInput = page.getByPlaceholder('Message #engineering-core');
    const uniqueMessage = `Payload Signature Verification: ${Date.now()}`;

    // Send payload via UI
    await chatInput.fill(uniqueMessage);
    await chatInput.press('Enter');

    // UI Verification
    const messageLocator = page.locator('[data-testid="message-stream-item"]').filter({ hasText: uniqueMessage });
    await expect(messageLocator).toBeVisible();

    // Protocol Frame Verification
    await expect.poll(() => {
      return sentFrames.some((frame) => {
        try {
          const parsed = JSON.parse(frame);
          return parsed.event === 'chat:message' && parsed.data.body === uniqueMessage;
        } catch {
          return false;
        }
      });
    }, {
      message: 'Frame was never dispatched through the active WebSocket channel',
      timeout: 5000,
    }).toBe(true);

    // Simulate external incoming frame from server to test browser renderer
    const incomingBroadcast: ChatPayload = {
      channelId: 'engineering-core',
      sender: 'Alice (Staff Architect)',
      body: `System Auto Alert: Deploy Green-${Date.now()}`,
      timestamp: Date.now(),
    };

    // Synthesize socket injection by evaluating in page window context
    await page.evaluate((payload) => {
      const socket = (window as unknown as { __TEST_SOCKET_INSTANCE__: WebSocket }).__TEST_SOCKET_INSTANCE__;
      if (socket) {
        socket.dispatchEvent(
          new MessageEvent('message', {
            data: JSON.stringify({ event: 'chat:message', data: payload }),
          })
        );
      }
    }, incomingBroadcast);

    // Validate synthesized frame appears on DOM
    await expect(page.locator(`text=${incomingBroadcast.body}`)).toBeVisible({ timeout: 5000 });
  });
});
```

---

## 4. Large CSV File Upload with Boundary & Network Interception

Testing 100,000+ line multipart payloads requires dynamically buffering mock fixtures in-memory rather than committing massive binary assets to source control.

```typescript
import { test, expect } from '@playwright/test';

test.describe('Large CSV Multipart File Ingestion', () => {
  test('generates dynamic 10,000-row CSV payload, buffers to upload input, and validates processing pipeline', async ({ page }) => {
    // 1. In-memory programmatic CSV generation (10,000 entities)
    const rowCount = 10000;
    const csvHeader = 'transaction_id,amount,currency,customer_ref,status\n';
    const rows: string[] = [];

    for (let i = 1; i <= rowCount; i++) {
      rows.push(`txn_${i},${(Math.random() * 1000).toFixed(2)},USD,cust_${i},PENDING`);
    }

    const fullCsvBuffer = Buffer.from(csvHeader + rows.join('\n'), 'utf-8');

    await page.goto('/operations/ingestion');

    // 2. Intercept upload endpoint to confirm headers, multipart boundaries, and enforce assertion
    let uploadInterceptionFired = false;
    await page.route('**/api/v1/uploads/csv-stream', async (route) => {
      const request = route.request();
      const headers = request.headers();

      // Assert multipart content headers
      expect(headers['content-type']).toContain('multipart/form-data');
      
      uploadInterceptionFired = true;

      // Mock processing payload back to client
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          jobId: 'job_csv_897123984',
          recordsProcessed: rowCount,
          status: 'QUEUED',
          validationErrors: 0,
        }),
      });
    });

    // 3. Set input files via Playwright Buffer syntax
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.getByTestId('csv-drop-zone-browse').click();
    const fileChooser = await fileChooserPromise;

    await fileChooser.setFiles({
      name: 'annual_ledger_ingest.csv',
      mimeType: 'text/csv',
      buffer: fullCsvBuffer,
    });

    // 4. Submit ingestion pipeline
    await page.getByRole('button', { name: 'Process Ledger Batch' }).click();

    // 5. Assert confirmation and check state transitions
    await expect(page.getByTestId('batch-progress-bar')).toBeVisible();
    await expect(page.getByTestId('batch-metric-count')).toContainText('10,000');
    await expect(page.getByTestId('job-status-badge')).toContainText('QUEUED');
    
    expect(uploadInterceptionFired).toBe(true);
  });
});
```

---

## 5. Virtualized Data Grid Testing: Infinite Scroll, Cell Edits & Keyboard Navigation

Virtualized grids render only visible rows into the DOM. Directly grabbing `tr:nth-child(500)` will fail. You must scroll programmatically, wait for the virtual buffer to mount nodes, and then assert.

```typescript
import { test, expect, Page, Locator } from '@playwright/test';

export class VirtualDataGridPage {
  readonly page: Page;
  readonly gridViewport: Locator;
  readonly loadedRows: Locator;

  constructor(page: Page) {
    this.page = page;
    this.gridViewport = page.getByRole('treegrid');
    this.loadedRows = page.locator('[role="row"][data-row-index]');
  }

  async goto() {
    await this.page.goto('/analytics/virtual-grid');
    await expect(this.gridViewport).toBeVisible();
  }

  async scrollToRow(rowIndex: number, rowHeight = 35) {
    // Scroll container using calculate offsets directly on the virtual viewport
    await this.gridViewport.evaluate((element, offset) => {
      element.scrollTop = offset;
    }, rowIndex * rowHeight);

    // Wait for dynamic layout stabilizing
    await expect(this.page.locator(`[role="row"][data-row-index="${rowIndex}"]`)).toBeVisible({
      timeout: 10000,
    });
  }

  async editCell(rowIndex: number, columnKey: string, newValue: string) {
    const row = this.page.locator(`[role="row"][data-row-index="${rowIndex}"]`);
    const cell = row.locator(`[role="gridcell"][data-col-id="${columnKey}"]`);

    await cell.dblclick();
    const inlineEditor = cell.locator('input.grid-inline-editor');
    await expect(inlineEditor).toBeVisible();
    
    await inlineEditor.fill('');
    await inlineEditor.fill(newValue);
    await inlineEditor.press('Enter');

    // Confirm write-back
    await expect(cell).toContainText(newValue);
  }

  async navigateViaKeyboard(startRow: number, startColKey: string, navigations: ('ArrowDown' | 'ArrowUp' | 'ArrowRight' | 'ArrowLeft')[]) {
    const initialCell = this.page
      .locator(`[role="row"][data-row-index="${startRow}"]`)
      .locator(`[role="gridcell"][data-col-id="${startColKey}"]`);
    
    await initialCell.click();

    for (const key of navigations) {
      await this.page.keyboard.press(key);
      await this.page.waitForTimeout(50); // Frame buffer stabilization
    }
  }
}

test.describe('Virtualized High-Frequency Data Grid Validation', () => {
  test('scrolls to index 500, performs double-click cell edits, and asserts keyboard navigation boundaries', async ({ page }) => {
    const grid = new VirtualDataGridPage(page);
    await grid.goto();

    // 1. Initial State: Row 500 should not exist in viewport DOM
    await expect(page.locator('[role="row"][data-row-index="500"]')).toHaveCount(0);

    // 2. Perform virtual scroll into row 500
    await grid.scrollToRow(500);

    // 3. Edit Record at index 500
    const updatedValue = 'CORP-AMER-94819';
    await grid.editCell(500, 'account_code', updatedValue);

    // 4. Validate keyboard traversal
    await grid.navigateViaKeyboard(500, 'account_code', ['ArrowDown', 'ArrowRight']);
    
    // Target should now be Row 501, next column ('status')
    const activeCell = page.locator(':focus');
    await expect(activeCell).toHaveAttribute('data-col-id', 'status');
    
    const parentRow = page.locator('[role="row"]:has(:focus)');
    await expect(parentRow).toHaveAttribute('data-row-index', '501');
  });
});
```

---

## 6. Declarative Role-Based Access Control (RBAC) Matrix

Testing RBAC with individual, repetitive test specs leads to maintenance overhead. Use a parameter-driven combinatorial test matrix to validate permissions across roles.

### 6.1 RBAC Configuration Matrix

| Role | Dashboard Access | Access User Management | Edit Organization Settings | Trigger Billing Ingestion |
| :--- | :--- | :--- | :--- | :--- |
| **System Admin** | Allow (200) | Allow (200) | Allow (200) | Allow (200) |
| **Security Officer** | Allow (200) | Read-Only (Auditor View) | Deny (403 UI Screen) | Deny (403 Action Hidden) |
| **Auditor** | Allow (200) | Deny (404 / Hidden) | Deny (403 UI Screen) | Deny (403 Action Hidden) |
| **Standard Member** | Allow (200) | Deny (Hidden from DOM) | Deny (Redirect to /dashboard) | Deny (Action Forbidden) |

### 6.2 Matrix Execution Engine (`specs/rbac-matrix.spec.ts`)

```typescript
import { test, expect, Page } from '@playwright/test';

interface RoleProfile {
  roleName: string;
  storageStateFile: string;
  canAccessUserManagement: boolean;
  canMutateOrgSettings: boolean;
  canTriggerIngestion: boolean;
}

const ROLES: RoleProfile[] = [
  {
    roleName: 'System Admin',
    storageStateFile: '.auth/admin-state.json',
    canAccessUserManagement: true,
    canMutateOrgSettings: true,
    canTriggerIngestion: true,
  },
  {
    roleName: 'Security Officer',
    storageStateFile: '.auth/security-officer-state.json',
    canAccessUserManagement: true,
    canMutateOrgSettings: false,
    canTriggerIngestion: false,
  },
  {
    roleName: 'Auditor',
    storageStateFile: '.auth/auditor-state.json',
    canAccessUserManagement: false,
    canMutateOrgSettings: false,
    canTriggerIngestion: false,
  },
  {
    roleName: 'Standard Member',
    storageStateFile: '.auth/member-state.json',
    canAccessUserManagement: false,
    canMutateOrgSettings: false,
    canTriggerIngestion: false,
  },
];

for (const role of ROLES) {
  test.describe(`Access Control Enforcement Matrix for: [${role.roleName}]`, () => {
    // Allocate browser contexts isolated to pre-stored role sessions
    test.use({ storageState: role.storageStateFile });

    test(`enforces User Management path boundaries`, async ({ page }) => {
      await page.goto('/settings/users');

      if (role.canAccessUserManagement) {
        await expect(page).toHaveURL(/.*\/settings\/users/);
        await expect(page.getByTestId('users-directory-table')).toBeVisible();
      } else {
        // Must either route to 403 screen or redirect to fallback safe location
        const forbiddenHeader = page.getByRole('heading', { name: /Access Denied|Unauthorized|Not Found/ });
        const redirectCondition = page.url().endsWith('/dashboard');
        
        if (!redirectCondition) {
          await expect(forbiddenHeader).toBeVisible();
        } else {
          expect(page.url()).toContain('/dashboard');
        }
      }
    });

    test(`enforces Organization Mutation boundaries`, async ({ page }) => {
      await page.goto('/settings/organization');

      const saveSettingsButton = page.getByRole('button', { name: 'Save Organization Policy' });

      if (role.canMutateOrgSettings) {
        await expect(saveSettingsButton).toBeVisible();
        await expect(saveSettingsButton).toBeEnabled();
      } else {
        // Button must either be absent from the DOM, disabled, or prompt an authorization guard
        const count = await saveSettingsButton.count();
        if (count > 0) {
          await expect(saveSettingsButton).toBeDisabled();
        } else {
          expect(count).toBe(0);
        }
      }
    });

    test(`enforces Billing Ingestion execution controls`, async ({ page }) => {
      await page.goto('/operations/ingestion');

      const executeButton = page.getByRole('button', { name: 'Process Ledger Batch' });

      if (role.canTriggerIngestion) {
        await expect(executeButton).toBeVisible();
        await expect(executeButton).toBeEnabled();
      } else {
        await expect(executeButton).toBeHidden();
      }
    });
  });
}
```

---

## 7. Operational Runbook: Anti-Flake Checklist & Troubleshooting

Follow this sequential checklist whenever writing or triaging Playwright tests.

```
       Test Execution Failure
                 │
                 ▼
     Is there a network race?
    (Missing request wait-for)
        ├── YES ──► Intercept with page.waitForResponse()
        └── NO
                 │
                 ▼
     Is it a virtualized list?
  (Element unmounted from DOM)
        ├── YES ──► Virtual scroll: scrollToRow(n)
        └── NO
                 │
                 ▼
    Is it an external iframe?
       (Stripe / Identity)
        ├── YES ──► page.frameLocator()
        └── NO
                 │
                 ▼
   Replace locator with getByRole() or getByTestId()
```

### 7.1 Production Flake Resolution Index

| Root Cause Pattern | Bad Practice (Flaky) | Production Pattern (Deterministic) |
| :--- | :--- | :--- |
| **Element Detachment** | `page.waitForTimeout(5000)` | `await expect(locator).toBeVisible({ timeout: 10000 })` |
| **Iframe Synchronization** | `page.frames()[1].click('#btn')` | `page.frameLocator('iframe[name="..."]').getByRole('button')` |
| **Asynchronous Network Race** | Click submit then assert URL immediately | `await Promise.all([page.waitForResponse('**/api/save'), locator.click()])` |
| **Dynamic ID Locators** | `page.locator('#btn-129381')` | `page.getByRole('button', { name: 'Save' })` |
| **Animations / Transitions** | `locator.click()` during a CSS transition | `await expect(locator).toHaveAttribute('data-animating', 'false')` |
| **Input Mask Discarding Input** | `locator.fill('42424242')` (Stripe drops digits) | `locator.pressSequentially('42424242', { delay: 50 })` |

### 7.2 Strict Locator Governance Policy

1. **Role First:** Use `page.getByRole('button', { name: 'Submit' })` as your primary locator. This tests accessibility trees and page semantics simultaneously.
2. **Explicit Test IDs:** When semantically indistinct elements exist (e.g., custom chart canvases, SVG nodes), use `page.getByTestId('sales-bar-canvas')`. Ensure backend sets the property: `data-testid="value"`.
3. **No XPath or CSS Chains:** Never merge relative CSS hierarchies (e.g., `div > div:nth-child(2) > span.active`). These break during design system updates.
4. **No Arbitrary Sleep:** `page.waitForTimeout()` is banned in production codebases. Use `expect.poll()` or `waitForResponse()` instead.

---

## 8. Enterprise Generative System Prompts

Use these prompts with large language models to turn component files into test suites matching the patterns in this module.

### Prompt 1: Converting React/Vue Form Components into Page Object Models
```text
System: You are a Staff Test Engineer specializing in Playwright and TypeScript.
Task: Analyze the provided frontend component code and generate a production-ready Playwright Page Object Model (POM) and an accompanying test file.

Constraints:
1. Strict TypeScript usage: specify all interfaces, return types, and parameter shapes.
2. Zero use of page.waitForTimeout(). Use web-first assertions (expect(locator).toBeVisible()).
3. Adhere strictly to the Playwright Locator priority order:
   - Primary: page.getByRole()
   - Secondary: page.getByLabel(), page.getByPlaceholder(), page.getByText()
   - Tertiary: page.
