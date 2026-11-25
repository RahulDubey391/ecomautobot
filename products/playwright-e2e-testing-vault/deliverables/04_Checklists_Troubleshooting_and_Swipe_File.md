# Module 4: Flaky Test Elimination Checklist & AI Test Prompts

Eliminating flakiness requires systematic debugging, strict selector governance, and deterministic execution environments. This module provides a 35-point enterprise audit checklist, a selector priority rubric with concrete code remedies, and 15 precision AI prompts designed to turn unstructured user stories into production-ready Playwright test suites.

---

## 1. The 35-Point Flaky Test Elimination Audit Checklist

Run your failing or intermittent specs against this 35-point checklist before merging into your mainline branch.

### Category A: Timing, Asynchrony & Auto-Waiting (Points 1–10)

- [ ] **1. Zero Arbitrary Timeouts**
  - *Symptom:* `await page.waitForTimeout(3000)` appears in tests.
  - *Root Cause:* Blind sleeps create race conditions on slow CI workers and waste execution time on fast ones.
  - *Remedy:* Replace with locator assertions: `await expect(locator).toBeVisible()`, or wait for specific network state: `await page.waitForResponse(resp => resp.url().includes('/api/v1/users') && resp.status() === 200)`.

- [ ] **2. Web-First Assertions Exclusively**
  - *Symptom:* Using non-retrying Jest/Vitest assertions: `expect(await locator.isVisible()).toBe(true)`.
  - *Root Cause:* Evaluates the DOM once synchronously. If an element is mid-transition, the test fails immediately.
  - *Remedy:* Use Playwright's retrying assertions: `await expect(locator).toBeVisible({ timeout: 7500 })`.

- [ ] **3. Actionability Gate Validation**
  - *Symptom:* `.click()` fails with "element intercepts pointer events" or "element is not stable".
  - *Root Cause:* Target element is animating, obscured by a sticky banner, or re-rendering.
  - *Remedy:* Await element stability explicitly or scroll into view:
    ```typescript
    await locator.scrollIntoViewIfNeeded();
    await expect(locator).toBeEnabled();
    await locator.click();
    ```

- [ ] **4. Hydration Desynchronization**
  - *Symptom:* Clicks succeed without throwing an error, but no state change occurs in React/Next.js/Vue apps.
  - *Root Cause:* The element is painted in the DOM (SSR) but client-side JavaScript has not attached event listeners.
  - *Remedy:* Assert client hydration via a known hydrated attribute, network idle, or state indicator before interacting:
    ```typescript
    await page.waitForFunction(() => window.__NEXT_DATA__?.page !== undefined);
    ```

- [ ] **5. Route Interception Registration Order**
  - *Symptom:* Intercepted routes (`page.route()`) fire inconsistently.
  - *Root Cause:* Route handlers are defined *after* the navigation or action that triggers the network request.
  - *Remedy:* Always register `page.route()` before triggering the action:
    ```typescript
    await page.route('**/api/v1/checkout', route => route.fulfill({ status: 200, body: '{}' }));
    await page.getByRole('button', { name: 'Submit Order' }).click();
    ```

- [ ] **6. Race Conditions Between Navigation and Click**
  - *Symptom:* Execution stalls after clicking a link, resulting in `TimeoutError: page.waitForURL`.
  - *Root Cause:* The page completes navigation before `page.waitForURL()` begins listening.
  - *Remedy:* Use `Promise.all` or direct locator actions that handle navigation automatically:
    ```typescript
    await Promise.all([
      page.waitForURL('**/dashboard'),
      page.getByRole('button', { name: 'Log In' }).click()
    ]);
    ```

- [ ] **7. Debounced Input Truncation**
  - *Symptom:* Forms submit partial input strings (e.g., "usr" instead of "user@example.com").
  - *Root Cause:* Instantaneous `locator.fill()` triggers form submission before debounced listeners process the full value.
  - *Remedy:* Explicitly assert input value before triggering submission:
    ```typescript
    const emailInput = page.getByLabel('Work Email');
    await emailInput.fill('user@example.com');
    await expect(emailInput).toHaveValue('user@example.com');
    ```

- [ ] **8. Toast and Transient Alert Dismissal Races**
  - *Symptom:* Test expects a toast message to appear, but it has already auto-dismissed.
  - *Root Cause:* Assertions occur too late in execution, after short auto-dismiss timers (e.g., 2000ms).
  - *Remedy:* Place the toast assertion immediately after the triggering action, or use locator listeners:
    ```typescript
    const toast = page.getByRole('alert');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(toast).toContainText('Changes saved successfully');
    ```

- [ ] **9. Dynamic Lists Re-indexing During Iteration**
  - *Symptom:* `IndexOutOfBounds` or "Element detached from DOM" when iterating with `locator.all()`.
  - *Root Cause:* The array of elements changes while the loop executes due to background polling or sorting.
  - *Remedy:* Filter lists dynamically or target by unique business key rather than indices:
    ```typescript
    await expect(page.getByTestId('order-row')).toHaveCount(5);
    const targetRow = page.getByTestId('order-row').filter({ hasText: 'ORD-9842' });
    await targetRow.getByRole('button', { name: 'View' }).click();
    ```

- [ ] **10. File Download Completion Gaps**
  - *Symptom:* Export tests intermittently fail with corrupted or partial files.
  - *Root Cause:* The file read executes before the browser finishes writing to disk.
  - *Remedy:* Wait for the `download` event and explicitly resolve the path:
    ```typescript
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export CSV' }).click();
    const download = await downloadPromise;
    const path = await download.path();
    expect(path).not.toBeNull();
    ```

---

### Category B: Network, State & Fixture Isolation (Points 11–18)

- [ ] **11. Shared Mutation State Across Parallel Workers**
  - *Symptom:* Tests pass when run sequentially (`--workers=1`) but fail with 409 Conflict when run concurrently.
  - *Root Cause:* Two tests mutate the same database record or use the same enterprise tenant.
  - *Remedy:* Enforce worker-level data partitioning using unique execution IDs:
    ```typescript
    const uniqueEmail = `test-user-${Date.now()}-${test.info().workerIndex}@example.com`;
    ```

- [ ] **12. Leaked Browser Context Storage**
  - *Symptom:* Test B fails because it inherits active session tokens or localStorage keys from Test A.
  - *Root Cause:* Tests reuse `browserContext` without clearing cookies/storage in teardown.
  - *Remedy:* Use built-in isolated fixtures (`page`, `context`) per test. If caching state with `storageState`, treat cached tokens as strictly read-only.

- [ ] **13. API Route Interception Collisions**
  - *Symptom:* Global mocks bleed across spec files, returning mocked payloads in unintended suites.
  - *Root Cause:* Mocking at the context level without unrouting in test hooks.
  - *Remedy:* Scope routes directly to the individual test `page`, or tear down routes on complete:
    ```typescript
    test.afterEach(async ({ page }) => {
      await page.unrouteAll({ behavior: 'ignoreErrors' });
    });
    ```

- [ ] **14. Unhandled 3rd-Party Telemetry & Analytics Traffic**
  - *Symptom:* Random timeouts caused by long-running HTTP calls to Datadog, Segment, or Google Analytics.
  - *Root Cause:* The network layer waits for 3rd-party trackers that stall on staging/sandbox environments.
  - *Remedy:* Block tracking domains entirely inside `playwright.config.ts`:
    ```typescript
    use: {
      launchOptions: {
        args: ['--host-rules=MAP *segment.io 127.0.0.1, MAP *google-analytics.com 127.0.0.1']
      }
    }
    ```

- [ ] **15. Clock Drift on Time-Sensitive Business Logic**
  - *Symptom:* Tests fail around midnight, during month-end transitions, or across daylight saving boundary dates.
  - *Root Cause:* Client and backend times are unsynchronized, breaking calendar selectors.
  - *Remedy:* Freeze system time deterministically in the context:
    ```typescript
    await page.clock.setFixedTime(new Date('2025-06-15T12:00:00Z'));
    ```

- [ ] **16. WebSockets and Server-Sent Events (SSE) Unhandled Drops**
  - *Symptom:* Real-time notifications or chat apps miss messages due to slow CI socket handshakes.
  - *Root Cause:* UI actions trigger before the WebSocket handshakes complete.
  - *Remedy:* Monitor the WebSocket frame explicitly before performing actions:
    ```typescript
    const wsPromise = page.waitForEvent('websocket', ws => ws.url().includes('/realtime'));
    await page.goto('/dashboard');
    const ws = await wsPromise;
    await ws.waitForEvent('framesent');
    ```

- [ ] **17. Non-Idempotent Database Seeds**
  - *Symptom:* "Duplicate key violation" or unexpected record counts when running retries.
  - *Root Cause:* Seed scripts run `INSERT` statements without upsert logic or clearing preceding records.
  - *Remedy:* Write seed factories using transactional rollbacks or `ON CONFLICT DO UPDATE` patterns.

- [ ] **18. Cold-Start API Delays**
  - *Symptom:* The very first test in a run times out; all subsequent tests pass cleanly.
  - *Root Cause:* Serverless backend infrastructure (AWS Lambda, Cloudflare Workers) cold-starting on staging.
  - *Remedy:* Add a global setup health check that pings the critical backend APIs before worker processes spawn.

---

### Category C: Selector Strategy & DOM Mutability (Points 19–25)

- [ ] **19. Over-Reliance on CSS Class Names Generated by Compilers**
  - *Symptom:* Selectors break on every production build (e.g., `.css-1x84a9`, `.sc-bdVaJa`).
  - *Root Cause:* Styled-components, Tailwind hashing, or CSS modules change class names when code is compiled.
  - *Remedy:* Switch to accessible roles: `page.getByRole('button', { name: 'Submit' })` or static test IDs.

- [ ] **20. Brittle Hierarchical Structural Selectors**
  - *Symptom:* `div > div:nth-child(3) > span` fails when an engineer wraps a component in a layout `<div>`.
  - *Root Cause:* Coupling locators directly to arbitrary DOM structure.
  - *Remedy:* Target elements using role semantics, labels, or locator chaining:
    ```typescript
    page.getByRole('dialog', { name: 'Edit Profile' }).getByRole('textbox', { name: 'Name' });
    ```

- [ ] **21. Exact String Matches on Case-Insensitive or Dynamic Labels**
  - *Symptom:* `page.getByText('Submit')` fails when CSS applies `text-transform: uppercase`.
  - *Root Cause:* Case mismatches or whitespace differences breaking string equality.
  - *Remedy:* Use regular expressions: `page.getByRole('button', { name: /submit/i })`.

- [ ] **22. Shadow DOM Component Boundary Failures**
  - *Symptom:* Locators fail to resolve inputs inside web components (e.g., Salesforce, Lit, Shoelace).
  - *Root Cause:* Incorrect selector engines unable to traverse through closed/open shadow roots.
  - *Remedy:* Rely on Playwright's native shadow DOM-piercing engine; avoid raw `document.querySelector` executions.

- [ ] **23. Hidden/Duplicate Modals in DOM**
  - *Symptom:* `locator.click()` throws "strict mode violation: resolved to 2 elements".
  - *Root Cause:* Previously closed modals are hidden with `display: none` or `visibility: hidden` but remain in the DOM.
  - *Remedy:* Scope queries to visible elements:
    ```typescript
    await page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: 'Confirm' }) }).locator(':visible').getByRole('button', { name: 'OK' }).click();
    ```

- [ ] **24. Missing Strict Mode Enforcement Handling**
  - *Symptom:* Tests fail unpredictably when a database returns multiple items with identical text.
  - *Root Cause:* A locator matches multiple elements when Playwright expects a unique target.
  - *Remedy:* Refine using `.first()`, `.filter()`, or precise accessible names.

- [ ] **25. SVG Icon Click Inaccuracies**
  - *Symptom:* Playwright fails to click an SVG icon or target drops to `0,0` coordinates.
  - *Root Cause:* SVGs often lack standard layout geometry for bounding box calculations.
  - *Remedy:* Target the enclosing accessible button:
    ```typescript
    // BAD: page.locator('svg.delete-icon').click();
    // GOOD:
    page.getByRole('button', { name: 'Delete Item' }).click();
    ```

---

### Category D: CI/CD Environment & Worker Hardware (Points 26–30)

- [ ] **26. CPU Throttling and Worker Over-Allocation**
  - *Symptom:* Tests run reliably locally on an M-series Mac (8–16 cores) but fail intermittently on GitHub Actions / GitLab runners.
  - *Root Cause:* Running default auto-worker configurations on standard 2-vCPU CI machines over-subscribes the CPU, leading to slow rendering.
  - *Remedy:* Restrict CI workers inside `playwright.config.ts`:
    ```typescript
    workers: process.env.CI ? 2 : undefined,
    ```

- [ ] **27. Out-of-Memory (OOM) Browser Crashes**
  - *Symptom:* CI jobs fail with `Target closed` or `Crash error code: 137`.
  - *Root Cause:* Memory leaks across large test suites running in a single browser process instance.
  - *Remedy:* Set reasonable suite chunking in CI matrices, or force context recycling after a set number of runs.

- [ ] **28. Missing System Dependencies in Custom Docker Containers**
  - *Symptom:* Headless browsers fail to render fonts, producing garbled text or missing glyphs.
  - *Root Cause:* Container environments lack essential system font libraries (e.g., `fonts-liberation`, `libasound2`).
  - *Remedy:* Standardize CI execution on official Playwright containers: `mcr.microsoft.com/playwright:v1.49.0-jammy`.

- [ ] **29. Video and Trace Artifact Disk Saturation**
  - *Symptom:* CI runs fail at the end of execution during artifact upload or crash mid-suite due to zero remaining disk space.
  - *Root Cause:* Unconditional recording of videos and full traces across thousands of passed tests.
  - *Remedy:* Configure traces and videos to record only on the first retry:
    ```typescript
    trace: 'on-first-retry',
    video: 'on-first-retry',
    ```

- [ ] **30. Stale CI Caches Polluting Build Steps**
  - *Symptom:* Test code reflects new changes, but node dependencies or browser binaries run old versions.
  - *Root Cause:* Bad cache keys matching across invalid `package-lock.json` hashes.
  - *Remedy:* Bind Playwright cache keys directly to the current Playwright package version:
    ```yaml
    key: ${{ runner.os }}-playwright-${{ hashFiles('**/package-lock.json') }}
    ```

---

### Category E: Animation, Layout Shifts & Visual Rendering (Points 31–35)

- [ ] **31. Layout Shifts (CLS) Interrupting Clicks**
  - *Symptom:* "Element clicked at (x, y) intercepted by other element."
  - *Root Cause:* Hero images, ads, or web fonts loading dynamically move elements right as the click event registers.
  - *Remedy:* Explicitly wait for dimensions to stabilize or set explicit `width` and `height` CSS attributes:
    ```typescript
    const button = page.getByRole('button', { name: 'Checkout' });
    await expect(button).toBeVisible();
    await button.click();
    ```

- [ ] **32. Continuous CSS Transitions Blocking Screenshot Tests**
  - *Symptom:* Visual regression tests throw 0.5% - 2% pixel differences on buttons or progress bars.
  - *Root Cause:* CSS animations, spinning loaders, or breathing pulses continue running during capture.
  - *Remedy:* Disable CSS animations inside visual regression configuration:
    ```typescript
    await expect(page).toHaveScreenshot({ animations: 'disabled' });
    ```

- [ ] **33. Non-Standard Font Rendering Across Operating Systems**
  - *Symptom:* Visual tests recorded on macOS fail on Linux CI runners due to anti-aliasing variations.
  - *Root Cause:* OS-level differences in font engines (CoreText vs. FreeType).
  - *Remedy:* Run visual tests inside Docker containers locally, or configure a slight pixel threshold:
    ```typescript
    expect(await page.screenshot()).toMatchSnapshot('landing.png', {
      maxDiffPixelRatio: 0.02
    });
    ```

- [ ] **34. Unpinned Device Emulation Scale Factors**
  - *Symptom:* Tests fail on mobile viewports due to differences between physical resolution and CSS pixels.
  - *Root Cause:* Omitting explicit `deviceScaleFactor` when configuring custom viewports.
  - *Remedy:* Use built-in device presets from Playwright's device registry:
    ```typescript
    import { devices } from '@playwright/test';
    const config = {
      use: { ...devices['iPhone 14 Pro'] }
    };
    ```

- [ ] **35. Intermittent Sticky Headers Obstructing Viewport Focus**
  - *Symptom:* Playwright scrolls an element into view, but a `position: fixed` header blocks the upper 80px of the screen.
  - *Root Cause:* Auto-scroll places the element at the top edge of the window, beneath the persistent header.
  - *Remedy:* Dispatch clicks through programmatic offsets or scroll with margins:
    ```typescript
    await locator.evaluate((el) => {
      el.scrollIntoView({ block: 'center', inline: 'nearest' });
    });
    await locator.click();
    ```

---

## 2. Enterprise Selector Priority Rubric & Locator Cheat Sheet

To keep test suites maintainable across large teams, enforce this selector hierarchy. Every step away from user-facing attributes increases future maintenance costs.

### Selector Priority Matrix

| Priority | Locator Type | Playwright Method | Resilience Score (1–10) | Primary Use Case | Critical Anti-Patterns |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **P1** | Accessible Role | `page.getByRole()` | **10** | Buttons, links, dialogs, checkboxes, headings. Reflects real user assistive access. | `getByRole('button')` without `{ name: 'Save' }` (strict mode error). |
| **P2** | Label Associated | `page.getByLabel()` | **9** | Form inputs, text areas, dropdown fields with standard accessible labels. | Matching dynamic values: `getByLabel('Welcome back, John')`. |
| **P3** | User-Facing Text | `page.getByText()` | **8** | Static content verification, paragraphs, non-interactive badges, status labels. | Matching fluctuating values without regular expressions. |
| **P4** | Form Placeholder | `page.getByPlaceholder()`| **7** | Inputs lacking explicit HTML `<label>` tags (use temporarily while patching accessible code). | Using placeholder as a long-term substitute for proper labels. |
| **P5** | Accessible Alt/Title | `page.getByAltText()`, `page.getByTitle()` | **7** | Images, diagrams, interactive icons with explicit tooltips. | Relying on image filenames (`avatar_v2_final.png`). |
| **P6** | Dedicated Test ID | `page.getByTestId()` | **6** | Dynamic canvas elements, highly custom SVG charts, complex virtualized data grids. | Attaching test IDs to every element; this bypasses accessibility checks. |
| **P7** | Scoped CSS / Chaining| `locator.filter({ hasText })` | **5** | Isolating a single row in a table or item in a list based on an internal value. | Deep nesting: `div.panel > div > ul > li`. |
| **P8 (BANNED)** | Raw Structural XPath / Dynamic CSS | `page.locator('//div[3]/span')` | **1** | None. Immediate rejection in code review. | Relying on generated CSS classes or arbitrary layout positions. |

---

### Production Refactoring Examples: Anti-Patterns vs. Modern Solutions

#### 1. Targeting Table Rows Based on Internal Content
```typescript
// ❌ ANTI-PATTERN: Brittle structural locator (breaks if column order changes)
await page.locator('table > tbody > tr:nth-child(4) > td:nth-child(2) > button').click();

//  PRODUCTION FIX: Functional locator chaining with accessible roles
await page.getByRole('row')
  .filter({ has: page.getByRole('cell', { name: 'INV-2026-001' }) })
  .getByRole('button', { name: 'Download Invoice' })
  .click();
```

#### 2. Interacting with Form Controls
```typescript
// ❌ ANTI-PATTERN: Leaking internal CSS implementation details
await page.locator('input.form-control-lg[name="user_email"]').fill('director@enterprise.com');

//  PRODUCTION FIX: Accessible label matching
await page.getByLabel('Work Email Address').fill('director@enterprise.com');
```

#### 3. Modal Confirmations
```typescript
// ❌ ANTI-PATTERN: Blind test-id usage bypassing modal structure
await page.locator('[data-testid="confirm-btn"]').click();

//  PRODUCTION FIX: Scope to accessible dialog role to guarantee context
const dialog = page.getByRole('dialog', { name: 'Delete Customer Account' });
await expect(dialog).toBeVisible();
await dialog.getByRole('button', { name: 'Confirm Deletion' }).click();
```

---

## 3. AI Precision Prompt Swipe File

Use these system prompts and template pairs with advanced LLMs (Claude 3.5 Sonnet, GPT-4o, etc.) to generate robust, production-ready Playwright tests from user stories, functional specs, or Jira tickets.

### The Enterprise Playwright System Prompt

```markdown
You are a Staff Quality Engineer and Playwright Core Specialist. Write clean, robust, and maintainable Playwright (TypeScript) end-to-end test suites.

Strict Constraints:
1. Playwright Test Framework: Use modern `@playwright/test` APIs (Playwright v1.40+).
2. Locator Rules:
   - Prioritize user-facing, accessible locators: `page.getByRole()`, `page.getByLabel()`, `page.getByText()`.
   - Never generate raw, brittle CSS or XPath selectors (e.g., NO `.btn-primary`, NO `div > div > span`).
   - Use `page.getByTestId()` ONLY for dynamic/canvas elements lacking accessible representations.
3. Asynchrony & Waiting:
   - NEVER use `page.waitForTimeout()`.
   - Use web-first assertions: `await expect(locator).toBeVisible()`, `await expect(locator).toHaveText()`.
   - Ensure proper use of `Promise.all` when waiting for navigations triggered by actions.
4. Clean Architecture:
   - Encapsulate interactive workflows into clean Page Object Models (POMs) or domain fixtures when requested.
   - Tests must run independently with isolated state. Do not share mutable state across tests.
   - Include realistic test data, utilizing TypeScript types throughout.
```

---

### Prompt 1: Standard User Story to Feature Spec

```markdown
### SYSTEM: Use the Enterprise Playwright System Prompt.

### TASK:
Convert the following User Story and Acceptance Criteria into a fully realized Playwright test suite written in TypeScript.

### USER STORY:
As an Organization Admin
I want to invite new team members via their email addresses and assign them roles (Admin, Editor, Viewer)
So that they can collaborate on projects within our workspace.

### ACCEPTANCE CRITERIA:
1. Clicking "Invite Member" inside Workspace Settings opens a modal dialog.
2. The modal contains an Email input field and a Role selection dropdown.
3. Submitting an invalid email format displays an inline validation error: "Please enter a valid work email".
4. Selecting "Admin" shows a warning badge: "Admins have full billing permissions".
5. Submitting a valid payload fires a POST request to `/api/v1/invitations` and renders a success toast: "Invitation sent successfully".
6. The invited user immediately appears in the "Pending Invitations" table.

### TECHNICAL REQUIREMENTS:
- Use Web-First assertions exclusively.
- Mock the network call to `/api/v1/invitations` using `page.route()`.
- Ensure proper scoping of the modal dialog using `page.getByRole('dialog')`.
```

---

### Prompt 2: High-Complexity CRUD with Optimistic UI Validation

```markdown
### SYSTEM: Use the Enterprise Playwright System Prompt.

### TASK:
Generate a Playwright test spec that validates an Optimistic UI update pattern for a Project Management Board.

### INPUT REQUIREMENTS:
- Target Action: Renaming a board column from "To Do" to "Backlog".
- Optimistic Behavior: The UI must update immediately without displaying a loading spinner.
- Network Emulation: Introduce an artificial 1500ms network delay on the update endpoint: `PATCH /api/v2/columns/col-123`.
- Failure Case: If the API responds with an HTTP 500 status code, verify that the UI rolls back to the original title ("To Do") and displays an error toast: "Failed to update column name. Changes reverted."

### CODE CONSTRAINTS:
- Use `page.route()` to delay and conditionally fail the API request.
- Assert that the optimistic text change occurs *before* the network request completes.
- Assert that the rollback occurs cleanly after the 500 error returns.
```

---

### Prompt 3: Multi-Role RBAC Permission Matrix Suite

```markdown
### SYSTEM: Use the Enterprise Playwright System Prompt.

### TASK:
Generate a parameter-driven Playwright test file testing role-based access control (RBAC) across three distinct roles: Admin, Billing Manager, and Member.

### DATA MATRIX:
| Role | Can Access Invoices (/billing) | Can Delete Workspace | Can View Workspace Analytics |
| :--- | :--- | :--- | :--- |
| Admin | YES | YES | YES |
| Billing Manager | YES | NO (Button Hidden) | NO (Redirect to 403) |
| Member | NO (Redirect to 403) | NO (Button Hidden) | YES |

### IMPLEMENTATION DETAILS:
- Implement a data-driven test using `test.describe.each()`.
- Use pre-configured auth states: `storageState: 'auth/admin.json'`, etc.
- Verify both UI affordances (button visibility) and route protections (redirects to `/403`).
```

---

### Prompt 4: Resilient Visual Regression Spec with Dynamic Masking

```markdown
### SYSTEM: Use the Enterprise Playwright System Prompt.

### TASK:
Generate a visual regression test for a Financial Dashboard containing dynamic, fluctuating data elements.

### VISUAL REQUIREMENTS:
- Component URL: `/analytics/revenue-dashboard`
- Elements requiring dynamic masking:
  - User avatars (loaded via random URLs).
  - Real-time stock ticker values (`[data-testid="stock-ticker"]`).
  - Current timestamp display: "Last updated: HH:mm:ss".
- Target Viewports: Desktop (1280x800) and Tablet (768x1024).

### PLAYWRIGHT CONSTRAINTS:
- Use `await expect(page).toHaveScreenshot()`.
- Use the `mask` option to hide the dynamic elements listed above.
- Disable CSS animations: `animations: 'disabled'`.
- Define an acceptable visual difference threshold: `maxDiffPixelRatio: 0.01`.
```

---

### Prompt 5: Payment Processing & Stripe Elements Iframe Flow

```markdown
### SYSTEM: Use the Enterprise Playwright System Prompt.

### TASK:
Generate a Playwright test covering a checkout flow that integrates Stripe Elements (embedded iframes).

### WORKFLOW:
1. User navigates to `/checkout?plan=pro_annual`.
2. Verifies the order summary: "$240.00 / year".
3. Enters cardholder name in the standard DOM input.
4. Locates the Stripe iframe for card details.
5. Fills in the card number, expiration date, and CVC inside the Stripe iframe.
6. Submits the form and verifies the redirect to `/checkout/success?session_id=...`.

### IMPLEMENTATION RULES:
- Use `page.frameLocator()` to interact with the Stripe iframe securely.
- Avoid hardcoding card numbers as raw strings; declare them in a clear test-data constant.
- Wait for the confirmation redirect with `page.waitForURL()`.
```

---

### Prompt 6: File Upload & Drag-and-Drop Processing

```markdown
### SYSTEM: Use the Enterprise Playwright System Prompt.

### TASK:
Generate a complete Playwright test suite for a document parser that supports both traditional file selection and drag-and-drop operations.

### ACCEPTANCE CRITERIA:
1. Handle hidden `<input type="file">` elements using `locator.setInputFiles()`.
2. Emulate an HTML5 Drag and Drop event dispatching a sample PDF document onto the drop-zone element: `getByTestId('dropzone')`.
3. Validate client-side file size restrictions: uploading a file larger than 10MB must trigger the error: "File exceeds 10MB limit."
4. Upon successful upload, assert the appearance of the processing status bar, followed by the text: "Parsing Complete".

### IMPLEMENTATION DETAILS:
- Create mock file payloads dynamically using `Buffer.from()` inside the test.
- Do not rely on external physical files on disk.
```

---

### Prompt 7: Data Table Sorting, Filtering, and Pagination

```markdown
### SYSTEM: Use the Enterprise Play
