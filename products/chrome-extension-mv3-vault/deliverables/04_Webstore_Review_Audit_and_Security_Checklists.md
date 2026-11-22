# Module 4: Chrome Web Store Approval Checklist & Security Hardening Rubric

The Chrome Web Store (CWS) review process is largely automated at the first gate, followed by high-scrutiny manual reviews whenever high-impact permissions or ambiguous extension behaviors are detected. Failing a review can delay releases by weeks or lead to outright extension suspension. 

This guide provides the exact configuration recipes, manifest justification copy, Content Security Policy (CSP) patterns, GitHub Actions CI/CD deployment pipelines, and a policy-compliant review prompt engine to pass reviews on day one.

---

## 1. Single-Purpose Policy & Permissions Audit Rubric

Chrome Web Store policy dictates that an extension must have a single, clear purpose. Review rejections occur when permissions do not tightly map to that declared purpose, or when the declared metadata (name, description, promotional tiles) fails to articulate why those permissions are vital.

### 1.1 Permission-by-Permission Review Justification Matrix

When submitting to the Developer Dashboard, any broad permission requires a human-readable justification. Use these pre-cleared explanation templates in the CWS submission console:

| Permission | Review Risk Level | Common Rejection Reason | Pre-Approved Justification Template |
| :--- | :--- | :--- | :--- |
| `activeTab` | Low | Applying full-host patterns instead of tab context. | *"Used strictly to access the current active page URL and DOM structure upon explicit user invocation via action click or keyboard shortcut. No background capture or persistence occurs."* |
| `storage` | Low | Unencrypted secrets or excessive quota usage. | *"Used to persist user interface state, local configuration options, and local cache of synchronization timestamps across browser sessions using `chrome.storage.local`."* |
| `tabs` | Medium | Requesting `tabs` when `activeTab` was sufficient. | *"Required to query existing tabs within the current window to prevent opening duplicate workflow instances and to route synchronized status badges across open editor sessions."* |
| `scripting` | Medium | Injecting arbitrary external code or non-local scripts. | *"Required to inject pre-packaged, statically compiled CSS and isolated content extraction scripts into host pages when the user triggers the transformation workflow."* |
| `declarativeNetRequest` | High | Blocking ads/content without explicit purpose statement. | *"Required to attach client-side authentication headers and strip cross-origin cache blockers for direct API integration to the user's provisioned workspace backend."* |
| `cookies` | High | Broad domain queries or tracking. | *"Required to detect session presence on `https://*.yourdomain.com` to maintain unified user authentication between our web platform and this companion extension."* |
| `<all_urls>` / `*://*/*` | Critical | Fails least-privilege review; could use explicit hosts. | *"The core function is a document extraction tool that operates across arbitrary user-specified websites. The extension analyzes text selected by the user on whatever page they are actively browsing."* |

### 1.2 Pre-Submission Verification Checklist

Run through this mechanical audit prior to generating the production zip:

- [ ] **Manifest Single-Purpose Test**: Remove any legacy permissions left over from development (`management`, `webNavigation`, `downloads`). If a feature is not live, remove the permission.
- [ ] **No Remote Code**: Inspect your final build for `importScripts()` targeting remote endpoints, dynamic `eval()`, `new Function()`, or dynamic `<script>` tag injections. Every byte must be bundled in the `.zip`.
- [ ] **Data Minimization in `manifest.json`**: Limit `host_permissions` strictly to the domains your API contacts and user-specified content targets.
- [ ] **Privacy Policy Live Endpoint**: The policy URL in the dashboard must be public, mention the extension by name, detail how data is processed, and explicitly confirm that user data is never sold or used for creditworthiness/lending purposes.
- [ ] **Working Demo Credentials**: If your extension requires an account, provide pre-seeded test credentials (username and password or API token) in the review instructions field.

---

## 2. Manifest V3 CSP Hardening Recipes

Manifest V3 strictly disallows remote executable code. The default CSP for extension pages is:

```http
script-src 'self'; object-src 'self';
```

You cannot loosen `script-src` to include external URLs or `'unsafe-eval'`. The recipes below ensure production compatibility without violating this baseline.

### Recipe 2.1: Loading Third-Party SDKs (Analytics, Auth, Error Tracking)

Never attempt to inject remote `<script src="https://cdn.example.com/sdk.js">` tags. Bundle all third-party dependencies locally at build time.

#### Packaging PostHog Analytics Without Dynamic Scripts

Most analytics SDKs inject remote scripts by default. Configure them to run locally:

```typescript
// src/shared/analytics.ts
import posthog from 'posthog-js';

export function initAnalytics(): typeof posthog {
  posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'https://app.posthog.com',
    autocapture: false, // Turn off dynamic DOM capture if injecting into arbitrary pages
    capture_pageview: false, // Manage pageviews explicitly
    disable_session_recording: true, // Session recording often violates CWS data minimization
    advanced_disable_decide: true, // Prevents loading remote feature flag scripts
    persistence: 'localStorage',
    bootstrap: {
      distinctID: 'anonymous_user',
    },
  });

  return posthog;
}

export function trackEvent(eventName: string, properties: Record<string, unknown> = {}): void {
  // Ensure we do not track PII or site-specific sensitive content
  posthog.capture(eventName, {
    ...properties,
    extension_version: chrome.runtime.getManifest().version,
  });
}
```

### Recipe 2.2: WebAssembly in MV3

If you are using WASM for local processing (e.g., SQLite, AI models, cryptography), you must explicitly allow `'wasm-unsafe-eval'` inside `manifest.json`. This does *not* violate CWS policy, provided you do not execute remote code.

#### `manifest.json` CSP Configuration:

```json
{
  "manifest_version": 3,
  "name": "Local Processing Engine",
  "version": "1.0.0",
  "content_security_policy": {
    "extension_pages": "script-src 'self' 'wasm-unsafe-eval'; object-src 'self';"
  }
}
```

#### Safe Local WASM Initialization:

```typescript
// src/engine/wasm-loader.ts
export async function loadLocalWasmModule(modulePath: string): Promise<WebAssembly.Instance> {
  const url = chrome.runtime.getURL(modulePath);
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Failed to load WASM binary at ${modulePath}: ${response.statusText}`);
  }

  const bytes = await response.arrayBuffer();
  const compiled = await WebAssembly.compile(bytes);
  
  // Instantiation is fully offline and local
  const instance = await WebAssembly.instantiate(compiled, {
    env: {
      memory: new WebAssembly.Memory({ initial: 256, maximum: 512 }),
      abort: () => console.error("WASM execution aborted"),
    },
  });

  return instance;
}
```

### Recipe 2.3: Safe Dynamic Template Rendering Without `innerHTML` or `eval`

Using `element.innerHTML` with untrusted data is the primary cause of security-based rejections and XSS vulnerabilities. Use this zero-dependency, safe DOM factory:

```typescript
// src/shared/safe-dom.ts
type Attributes = Record<string, string | ((e: Event) => void)>;
type Child = HTMLElement | string | number | null | undefined;

export function createElement<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attributes = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);

  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on') && typeof value === 'function') {
      const eventName = key.slice(2).toLowerCase();
      element.addEventListener(eventName, value);
    } else if (typeof value === 'string') {
      element.setAttribute(key, value);
    }
  }

  for (const child of children) {
    if (child === null || child === undefined) continue;
    if (child instanceof Node) {
      element.appendChild(child);
    } else {
      element.appendChild(document.createTextNode(String(child)));
    }
  }

  return element;
}

// Example Production Usage:
export function renderUserProfile(container: HTMLElement, username: string, onClick: () => void): void {
  container.replaceChildren(); // Safely wipe old DOM nodes

  const card = createElement(
    'div',
    { class: 'profile-card' },
    createElement('span', { class: 'text-bold' }, username),
    createElement('button', { class: 'btn-primary', onclick: onClick }, 'Inspect Workspace')
  );

  container.appendChild(card);
}
```

---

## 3. Automated CI/CD Release Pipeline

Avoid manual zip uploads. Manual uploads risk human error, such as forgetting to build assets, including development keys, or omitting nested files. Use this complete GitHub Actions pipeline with Google's API to publish updates automatically on every tagged release.

### 3.1 Obtaining Chrome Web Store API Credentials

Before configuring the pipeline, acquire the following four secrets from the [Google Cloud Console](https://console.cloud.google.com/) and [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole/):

1. **`CHROME_CLIENT_ID`**: OAuth Client ID from Google Cloud Console (APIs & Services > Credentials).
2. **`CHROME_CLIENT_SECRET`**: OAuth Client Secret associated with the Client ID.
3. **`CHROME_REFRESH_TOKEN`**: Long-lived refresh token obtained through the OAuth Playground for the scope `https://www.googleapis.com/auth/chromewebstore`.
4. **`CHROME_EXTENSION_ID`**: The 32-character extension ID found in the dashboard URL.

### 3.2 Production Deployment Script

Create `scripts/cws-publish.ts` to manage upload, error parsing, and submission.

```typescript
// scripts/cws-publish.ts
import fs from 'fs';
import path from 'path';

interface TokenResponse {
  access_token: string;
  expires_in: number;
  token_type: string;
}

interface UploadResponse {
  uploadState: 'SUCCESS' | 'FAILURE' | 'IN_PROGRESS';
  itemError?: Array<{ error_code: string; error_detail: string }>;
}

async function getAccessToken(clientId: string, clientSecret: string, refreshToken: string): Promise<string> {
  const params = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    refresh_token: refreshToken,
    grant_type: 'refresh_token',
  });

  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  });

  if (!response.ok) {
    throw new Error(`Failed to refresh token: ${await response.text()}`);
  }

  const data = (await response.json()) as TokenResponse;
  return data.access_token;
}

async function uploadZip(extensionId: string, token: string, zipPath: string): Promise<void> {
  const url = `https://www.googleapis.com/upload/chromewebstore/v1.1/items/${extensionId}`;
  const fileBuffer = fs.readFileSync(zipPath);

  console.log(`Uploading ${zipPath} (${fileBuffer.length} bytes) to CWS ID: ${extensionId}...`);

  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'x-goog-api-version': '2',
    },
    body: fileBuffer,
  });

  const result = (await response.json()) as UploadResponse;

  if (result.uploadState !== 'SUCCESS') {
    console.error('Upload failed details:', JSON.stringify(result.itemError, null, 2));
    throw new Error(`Upload failed with status: ${result.uploadState}`);
  }

  console.log('Package upload succeeded.');
}

async function publishItem(extensionId: string, token: string, target: 'default' | 'trustedTesters'): Promise<void> {
  const url = `https://www.googleapis.com/chromewebstore/v1.1/items/${extensionId}/publish?publishTarget=${target}`;

  console.log(`Submitting extension for review (Target: ${target})...`);

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'x-goog-api-version': '2',
      'Content-Length': '0',
    },
  });

  if (!response.ok) {
    throw new Error(`Publish failed: ${await response.text()}`);
  }

  console.log('Submission accepted. The extension is currently pending review.');
}

async function run(): Promise<void> {
  const {
    CHROME_CLIENT_ID,
    CHROME_CLIENT_SECRET,
    CHROME_REFRESH_TOKEN,
    CHROME_EXTENSION_ID,
  } = process.env;

  if (!CHROME_CLIENT_ID || !CHROME_CLIENT_SECRET || !CHROME_REFRESH_TOKEN || !CHROME_EXTENSION_ID) {
    throw new Error('Missing one or more required environment variables for CWS publishing.');
  }

  const zipPath = path.resolve(process.cwd(), 'dist/extension.zip');
  if (!fs.existsSync(zipPath)) {
    throw new Error(`Zip artifact not found at ${zipPath}`);
  }

  const token = await getAccessToken(CHROME_CLIENT_ID, CHROME_CLIENT_SECRET, CHROME_REFRESH_TOKEN);
  await uploadZip(CHROME_EXTENSION_ID, token, zipPath);
  await publishItem(CHROME_EXTENSION_ID, token, 'default');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

### 3.3 GitHub Actions Workflow Definition

Create `.github/workflows/deploy.yml`. This workflow triggers whenever a semver tag (e.g., `v1.2.0`) is pushed to the repository.

```yaml
name: Release Extension to Chrome Web Store

on:
  push:
    tags:
      - 'v*.*.*'

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Check out source
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Typecheck and Unit Tests
        run: |
          npm run typecheck
          npm run test:unit

      - name: Build Extension Bundle
        run: npm run build

      - name: Package Extension Artifact
        run: |
          mkdir -p dist
          cd dist/build && zip -r ../extension.zip ./*
          cd ../..

      - name: Publish to Chrome Web Store
        env:
          CHROME_CLIENT_ID: ${{ secrets.CHROME_CLIENT_ID }}
          CHROME_CLIENT_SECRET: ${{ secrets.CHROME_CLIENT_SECRET }}
          CHROME_REFRESH_TOKEN: ${{ secrets.CHROME_REFRESH_TOKEN }}
          CHROME_EXTENSION_ID: ${{ secrets.CHROME_EXTENSION_ID }}
        run: npx tsx scripts/cws-publish.ts

      - name: Upload Build Artifact to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: dist/extension.zip
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## 4. Policy-Compliant Review Booster Engine

Chrome Web Store guidelines prohibit:
- Incentivizing users to leave reviews (e.g., "Review for free premium").
- Gating or filtering bad reviews (e.g., "Rate us: If 5 stars, go to Web Store; if 1 star, send email"). You must give the user direct access without deceptive mechanics.
- Spamming prompts repeatedly.

To collect positive reviews ethically, prompt users **only after they experience a successful outcome (the "Aha!" moment)**, and back off completely if they dismiss the prompt.

### 4.1 The Review Prompt State Machine

```
[ User Completes Core Action ]
              │
              ▼
  Has user completed ≥ 5 actions?
              │
      ┌───────┴───────┐
     YES              NO ───► [ Do Nothing ]
      │
      ▼
  Days since install ≥ 3?
      │
      ┌───────┴───────┐
     YES              NO ───► [ Do Nothing ]
      │
      ▼
  Prompt dismissed previously?
      │
      ┌───────┴───────┐
      NO             YES ───► [ Do Nothing ]
      │
      ▼
  [ Display Feedback Prompt ]
      │
      ├───────────────────────────────┐
      ▼                               ▼
[ "Leave a Review" ]          [ "Not Now / Dismiss" ]
      │                               │
      ▼                               ▼
Open Web Store Review Tab       Record Permanent Dismissal
```

### 4.2 Complete Review Trigger Implementation

Create `src/shared/review-prompter.ts` to manage storage operations, state transitions, and UI presentation:

```typescript
// src/shared/review-prompter.ts

interface ReviewPromptState {
  installTimestamp: number;
  coreActionCount: number;
  promptDismissed: boolean;
  reviewCompleted: boolean;
}

const STORAGE_KEY = 'cws_review_state';
const MIN_ACTIONS_REQUIRED = 5;
const MIN_DAYS_SINCE_INSTALL = 3;

export class ReviewPrompter {
  private static async getState(): Promise<ReviewPromptState> {
    const result = await chrome.storage.local.get(STORAGE_KEY);
    const existing = result[STORAGE_KEY] as Partial<ReviewPromptState> | undefined;

    return {
      installTimestamp: existing?.installTimestamp ?? Date.now(),
      coreActionCount: existing?.coreActionCount ?? 0,
      promptDismissed: existing?.promptDismissed ?? false,
      reviewCompleted: existing?.reviewCompleted ?? false,
    };
  }

  private static async saveState(state: ReviewPromptState): Promise<void> {
    await chrome.storage.local.set({ [STORAGE_KEY]: state });
  }

  /**
   * Call this function whenever the user successfully completes an important workflow
   * (e.g., generated an asset, exported a file, completed an automation).
   */
  public static async recordCoreAction(parentContainer: HTMLElement): Promise<void> {
    const state = await this.getState();

    if (state.promptDismissed || state.reviewCompleted) {
      return;
    }

    state.coreActionCount += 1;
    await this.saveState(state);

    if (this.isEligibleForPrompt(state)) {
      this.renderPrompt(parentContainer, state);
    }
  }

  private static isEligibleForPrompt(state: ReviewPromptState): boolean {
    const elapsedDays = (Date.now() - state.installTimestamp) / (1000 * 60 * 60 * 24);
    return state.coreActionCount >= MIN_ACTIONS_REQUIRED && elapsedDays >= MIN_DAYS_SINCE_INSTALL;
  }

  private static renderPrompt(container: HTMLElement, state: ReviewPromptState): void {
    // Avoid double rendering
    if (container.querySelector('#cws-review-banner')) {
      return;
    }

    const banner = document.createElement('div');
    banner.id = 'cws-review-banner';
    banner.style.cssText = `
      box-sizing: border-box;
      padding: 12px 16px;
      margin: 12px 0;
      background-color: #f8fafc;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-family: system-ui, -apple-system, sans-serif;
    `;

    const text = document.createElement('p');
    text.style.cssText = 'margin: 0; font-size: 13px; color: #334155; line-height: 1.4;';
    text.textContent = `You've completed ${state.coreActionCount} tasks with our extension! Has it been helpful to your workflow?`;

    const buttonRow = document.createElement('div');
    buttonRow.style.cssText = 'display: flex; gap: 8px; justify-content: flex-end;';

    const dismissBtn = document.createElement('button');
    dismissBtn.textContent = 'Don’t show again';
    dismissBtn.style.cssText = `
      background: transparent;
      border: none;
      color: #64748b;
      font-size: 12px;
      cursor: pointer;
      padding: 4px 8px;
    `;
    dismissBtn.onclick = async () => {
      state.promptDismissed = true;
      await this.saveState(state);
      banner.remove();
    };

    const reviewBtn = document.createElement('button');
    reviewBtn.textContent = 'Leave a review on Web Store';
    reviewBtn.style.cssText = `
      background-color: #2563eb;
      color: #ffffff;
      border: none;
      border-radius: 4px;
      font-size: 12px;
      padding: 6px 12px;
      font-weight: 500;
      cursor: pointer;
    `;
    reviewBtn.onclick = async () => {
      state.reviewCompleted = true;
      await this.saveState(state);
      banner.remove();
      
      const extensionId = chrome.runtime.id;
      chrome.tabs.create({
        url: `https://chromewebstore.google.com/detail/${extensionId}/reviews`,
      });
    };

    buttonRow.appendChild(dismissBtn);
    buttonRow.appendChild(reviewBtn);
    banner.appendChild(text);
    banner.appendChild(buttonRow);

    container.prepend(banner);
  }
}
```

---

## 5. Pre-Submission Verification Manifest

To prevent pipeline failures, run your compiled `manifest.json` against this production baseline before publishing:

```json
{
  "manifest_version": 3,
  "name": "Production Vault Extension",
  "version": "1.0.0",
  "description": "Streamline browser workflows with isolated local-first processing tools.",
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  },
  "action": {
    "default_popup": "src/popup/index.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png"
    }
  },
  "background": {
    "service_worker": "dist/service-worker.js",
    "type": "module"
  },
  "permissions": [
    "storage",
    "activeTab"
  ],
  "host_permissions": [
    "https://api.yourdomain.com/v1/*"
  ],
  "content_security_policy": {
    "extension_pages": "script-src 'self'; object-src 'self';"
  },
  "minimum_chrome_version": "114"
}
```

### Final Release Checks
1. Ensure `icons/icon128.png` is crisp and exactly 128x128 pixels (used by the Web Store UI).
2. Confirm the version number in `package.json`, `manifest.json`, and the Git tag are identical.
3. Validate that your `.zip` archive contains only the production assets (`manifest.json`, bundled runtime scripts, compiled HTML/CSS, and icons). It must **not** contain `.git`, `src` (if bundling via Vite), `.env` files, or TypeScript sources.
