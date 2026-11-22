# Module 3: Side Panel AI Workflows, Local LLM Ingestion & Stripe Licensing

---

## 1. Chrome Side Panel Streaming Architecture

Manifest V3 disallows persistent background pages, meaning long-running AI streaming pipelines cannot rely on a persistent `background.js` state. The Chrome Side Panel API (`chrome.sidePanel`) provides an isolated window environment with an active DOM that survives across tab navigation when pinned globally, or binds to specific tabs.

### 1.1 `manifest.json` Infrastructure

This production manifest configures the Side Panel, grants necessary permissions, establishes network security boundaries via a strict Content Security Policy, and wires background orchestration.

```json
{
  "manifest_version": 3,
  "name": "OmniPrompt Pro: Side Panel AI",
  "version": "1.0.0",
  "description": "Production-grade streaming AI assistant and zero-backend license engine.",
  "permissions": [
    "sidePanel",
    "storage",
    "tabs",
    "activeTab",
    "scripting"
  ],
  "host_permissions": [
    "https://api.openai.com/v1/*",
    "https://api.anthropic.com/v1/*",
    "https://*.workers.dev/*"
  ],
  "background": {
    "service_worker": "background.js",
    "type": "module"
  },
  "side_panel": {
    "default_path": "sidepanel.html"
  },
  "content_security_policy": {
    "extension_pages": "script-src 'self'; object-src 'self'; connect-src 'self' https://api.openai.com https://api.anthropic.com https://*.workers.dev;"
  },
  "action": {
    "default_title": "Open AI Workspace"
  }
}
```

---

### 1.2 Dual-Mode Side Panel Triggering (`background.js`)

The background service worker dynamically routes Side Panel behavior: clicking the extension icon opens the panel globally, while a keyboard shortcut or specific contextual event can bind it to a single dedicated tab.

```javascript
// background.js

chrome.runtime.onInstalled.addListener(() => {
  // Configures the panel to display across all open tabs by default
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
    .catch((error) => console.error("Error setting panel behavior:", error));
});

// Programmatic tab-specific override example
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "ENABLE_PAGE_CONTEXT" && sender.tab?.id) {
    const tabId = sender.tab.id;
    chrome.sidePanel.setOptions({
      tabId,
      path: "sidepanel.html",
      enabled: true
    }).then(() => {
      sendResponse({ status: "SUCCESS", tabId });
    }).catch((err) => {
      sendResponse({ status: "ERROR", error: err.message });
    });
    return true; // Keep message channel open for async response
  }
});
```

---

### 1.3 Bidirectional Streaming Pipeline (`chrome.runtime.Port`)

Running SSE (Server-Sent Events) or Chunked Transfer streams directly inside the Side Panel is preferred over running them in the background service worker, as the side panel's lifecycle remains active while open. However, when requests must interact with protected background APIs, a long-lived `chrome.runtime.Port` bridge ensures continuous backpressure-safe streaming.

#### Side Panel Implementation (`sidepanel.html` & `sidepanel.js`)

```html
<!-- sidepanel.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>OmniPrompt Side Panel</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --text: #f8fafc;
      --accent: #38bdf8;
      --border: #334155;
    }
    body {
      margin: 0;
      padding: 16px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      flex-direction: column;
      height: 100vh;
      box-sizing: border-box;
      overflow: hidden;
    }
    #chat-log {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 16px;
      padding-right: 4px;
    }
    .message {
      padding: 10px 14px;
      border-radius: 8px;
      line-height: 1.5;
      font-size: 14px;
      word-break: break-word;
      max-width: 85%;
    }
    .user {
      background: var(--accent);
      color: #000;
      align-self: flex-end;
    }
    .assistant {
      background: var(--card);
      border: 1px solid var(--border);
      align-self: flex-start;
    }
    #input-group {
      display: flex;
      gap: 8px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px;
    }
    textarea {
      flex: 1;
      background: transparent;
      border: none;
      color: var(--text);
      font-size: 14px;
      resize: none;
      outline: none;
      height: 48px;
    }
    button {
      background: var(--accent);
      color: #000;
      border: none;
      border-radius: 6px;
      padding: 0 16px;
      font-weight: 600;
      cursor: pointer;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  </style>
</head>
<body>
  <div id="chat-log"></div>
  <div id="input-group">
    <textarea id="prompt-input" placeholder="Ask AI about this page..."></textarea>
    <button id="submit-btn">Send</button>
  </div>
  <script type="module" src="sidepanel.js"></script>
</body>
</html>
```

```javascript
// sidepanel.js
const chatLog = document.getElementById("chat-log");
const promptInput = document.getElementById("prompt-input");
const submitBtn = document.getElementById("submit-btn");

let activeController = null;

function appendMessage(role, text = "") {
  const msgEl = document.createElement("div");
  msgEl.className = `message ${role}`;
  msgEl.textContent = text;
  chatLog.appendChild(msgEl);
  chatLog.scrollTop = chatLog.scrollHeight;
  return msgEl;
}

submitBtn.addEventListener("click", async () => {
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  promptInput.value = "";
  submitBtn.disabled = true;

  appendMessage("user", prompt);
  const assistantBubble = appendMessage("assistant", "...");

  try {
    // 1. Fetch license token from chrome.storage
    const { license_token } = await chrome.storage.sync.get("license_token");
    if (!license_token) {
      throw new Error("No active license. Please link your Stripe key.");
    }

    // 2. Query the current active tab context
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    let pageContext = "";

    if (tab?.id && !tab.url.startsWith("chrome://")) {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => document.body.innerText.slice(0, 4000)
      }).catch(() => [{ result: "" }]);
      pageContext = result;
    }

    // 3. Directly stream from Anthropic/OpenAI using Fetch + SSE
    activeController = new AbortController();
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Using ephemeral token or proxy token validated against Cloudflare
        "Authorization": `Bearer ${license_token}` 
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        stream: true,
        messages: [
          { 
            role: "system", 
            content: `You are an AI assistant analyzing a webpage. Content:\n\n${pageContext}` 
          },
          { role: "user", content: prompt }
        ]
      }),
      signal: activeController.signal
    });

    if (!response.ok) {
      const errJson = await response.json().catch(() => ({}));
      throw new Error(errJson.error?.message || `Server returned ${response.status}`);
    }

    // 4. Stream consumption via ReadableStream and TextDecoder
    assistantBubble.textContent = "";
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // Retain partial chunks in buffer

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith("data: ")) continue;
        if (trimmed === "data: [DONE]") break;

        try {
          const parsed = JSON.parse(trimmed.replace(/^data: /, ""));
          const delta = parsed.choices[0]?.delta?.content || "";
          assistantBubble.textContent += delta;
          chatLog.scrollTop = chatLog.scrollHeight;
        } catch (e) {
          // Skip corrupt or unparseable frame chunks
        }
      }
    }
  } catch (error) {
    assistantBubble.textContent = `Error: ${error.message}`;
    assistantBubble.style.borderColor = "#ef4444";
  } finally {
    submitBtn.disabled = false;
    activeController = null;
  }
});
```

---

## 2. Chrome Built-in Gemini Nano (Prompt API) Integration

Chrome 127+ ships with an on-device Large Language Model (Gemini Nano) directly integrated into the browser through the `window.ai` / `ai.languageModel` API. It enables zero-latency, free, fully offline inferencing.

### 2.1 Complete Production Wrapper (`GeminiNanoEngine.js`)

This engine monitors engine capabilities, tracks model download states, handles session recreation across context limits, and implements a fallback to cloud execution when hardware limits fail.

```javascript
// GeminiNanoEngine.js

export class GeminiNanoEngine {
  constructor(options = {}) {
    this.systemPrompt = options.systemPrompt || "You are a concise, helpful assistant.";
    this.temperature = options.temperature ?? 0.7;
    this.topK = options.topK ?? 40;
    this.session = null;
  }

  /**
   * Evaluates if Gemini Nano is supported, downloaded, or pending user approval.
   * Returns: 'readily' | 'after-download' | 'no'
   */
  async getAvailability() {
    if (!("ai" in globalThis) || !("languageModel" in globalThis.ai)) {
      return "no";
    }

    try {
      const capabilities = await globalThis.ai.languageModel.capabilities();
      return capabilities.available; // 'readily' | 'after-download' | 'no'
    } catch (err) {
      console.warn("Gemini Nano capabilities check failed:", err);
      return "no";
    }
  }

  /**
   * Initializes the session, monitoring progress if the browser must fetch model weights.
   */
  async initSession(onDownloadProgress = null) {
    const availability = await this.getAvailability();

    if (availability === "no") {
      throw new Error("DEVICE_NOT_SUPPORTED: Gemini Nano is unavailable on this hardware/browser.");
    }

    const options = {
      systemPrompt: this.systemPrompt,
      temperature: this.temperature,
      topK: this.topK
    };

    if (availability === "after-download") {
      if (typeof onDownloadProgress === "function") {
        options.monitor = (m) => {
          m.addEventListener("downloadprogress", (e) => {
            const percentage = Math.round((e.loaded / e.total) * 100);
            onDownloadProgress(percentage, e.loaded, e.total);
          });
        };
      }
    }

    this.session = await globalThis.ai.languageModel.create(options);
    return this.session;
  }

  /**
   * Streams completion tokens with an abort signal.
   * Emits tokens via an async generator.
   */
  async *promptStream(text, signal = null) {
    if (!this.session) {
      await this.initSession();
    }

    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }

    let previousLength = 0;
    const stream = this.session.promptStreaming(text, { signal });

    for await (const cumulativeChunk of stream) {
      if (signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
      }
      
      // promptStreaming returns the entire accumulated text; slice to yield only delta tokens
      const delta = cumulativeChunk.slice(previousLength);
      previousLength = cumulativeChunk.length;
      yield delta;
    }
  }

  /**
   * Inspects context window constraints and remaining token balance.
   */
  async getContextInfo() {
    if (!this.session) {
      await this.initSession();
    }
    return {
      maxTokens: this.session.maxTokens,
      tokensSoFar: this.session.tokensSoFar,
      tokensLeft: this.session.tokensLeft
    };
  }

  /**
   * Clones the current operational context to preserve pre-loaded prompts.
   */
  async clone() {
    if (!this.session) throw new Error("No active session to clone.");
    return await this.session.clone();
  }

  /**
   * Destroys the model context and frees VRAM/RAM allocations.
   */
  destroy() {
    if (this.session) {
      this.session.destroy();
      this.session = null;
    }
  }
}
```

---

### 2.2 Dual-Engine Hybrid Strategy (Local First, Cloud Fallback)

To ensure zero downtime for users without modern GPUs or supported Chrome flags, use this hybrid pipeline pattern:

```javascript
// HybridAIManager.js
import { GeminiNanoEngine } from "./GeminiNanoEngine.js";

export class HybridAIManager {
  constructor(cloudFallbackFn) {
    this.localEngine = new GeminiNanoEngine();
    this.cloudFallback = cloudFallbackFn; // Callable to OpenAI/Anthropic stream
  }

  async *executePrompt(prompt, onToken, signal) {
    const availability = await this.localEngine.getAvailability();

    if (availability === "readily" || availability === "after-download") {
      try {
        console.info("[Execution Engine]: Local Gemini Nano selected.");
        const stream = this.localEngine.promptStream(prompt, signal);
        for await (const token of stream) {
          yield { token, source: "gemini-nano" };
        }
        return;
      } catch (localError) {
        console.warn("[Local AI Failed, falling back to Cloud]:", localError);
        this.localEngine.destroy();
      }
    } else {
      console.info("[Execution Engine]: Cloud LLM fallback selected (Incompatible local environment).");
    }

    // Cloud Fallback Implementation
    const cloudStream = await this.cloudFallback(prompt, signal);
    for await (const token of cloudStream) {
      yield { token, source: "cloud" };
    }
  }
}
```

---

## 3. Serverless Stripe Licensing Without a Custom Auth Database

Eliminate standard user registration databases (Postgres, Supabase, Firebase) by employing **Asymmetrically Signed Extension Entitlement Tokens**. 

### 3.1 Cryptographic Architecture Overview

```
                      STRIPE CHECKOUT FLOW
  +------------------+         +------------------+         +-----------------------+
  |  Extension UI    |         | Stripe Hosted    |         | Cloudflare Worker     |
  |  "Upgrade Plan"  |-------->| Checkout Session |-------->| Webhook Listener      |
  +------------------+         +------------------+         +-----------------------+
                                                                       |
                                                                       | Signs JWT via
                                                                       | Private Key (RS256)
                                                                       v
                                                            +-----------------------+
                                                            | Issues Encrypted /    |
                                                            | Signed License Token  |
                                                            +-----------------------+
                                                                       |
                                    +----------------------------------+
                                    v
                         VERIFICATION IN EXTENSION
  +---------------------------------------------------------------------------------+
  | Service Worker imports public key -> Verifies signature locally via WebCrypto   |
  | Decodes claims: { email, plan: 'PRO', exp: 1775000000, sub_id: 'sub_xyz' }     |
  +---------------------------------------------------------------------------------+
```

1. **Purchaser** completes Stripe Checkout.
2. Stripe sends `checkout.session.completed` event to a Cloudflare Worker webhook.
3. The Worker assembles an entitlement payload and signs it using an **Ed25519** private key.
4. The client provides their license key string (the signature + payload base64) directly into the extension.
5. The extension independently verifies this signature using an embedded **Ed25519 public key** via the native `crypto.subtle` API. **No remote database lookups are required to validate the subscription state.**

---

### 3.2 Cloudflare Worker Webhook & Key Generator (`worker.js`)

This complete, zero-dependency Cloudflare Worker signs license payloads using the standard Web Crypto API.

```javascript
// worker.js - Cloudflare Worker Environment

// Convert a base64url string to Uint8Array
function base64UrlToUint8Array(base64Url) {
  let base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4) {
    base64 += "=";
  }
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
}

// Convert ArrayBuffer / Uint8Array to base64url string
function bufferToBase64Url(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Sign an arbitrary string via Ed25519 PKCS#8 Raw Private Key
async function signEd25519(payloadString, privateKeyJwk) {
  const key = await crypto.subtle.importKey(
    "jwk",
    privateKeyJwk,
    { name: "Ed25519", namedCurve: "Ed25519" },
    false,
    ["sign"]
  );

  const encoder = new TextEncoder();
  const data = encoder.encode(payloadString);
  const signature = await crypto.subtle.sign({ name: "Ed25519" }, key, data);
  return bufferToBase64Url(signature);
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const signature = request.headers.get("Stripe-Signature");
    const rawBody = await request.text();

    // 1. Verify Webhook Authenticity (HMAC SHA-256)
    const validWebhook = await verifyStripeSignature(rawBody, signature, env.STRIPE_WEBHOOK_SECRET);
    if (!validWebhook) {
      return new Response("Invalid Stripe signature", { status: 400 });
    }

    const event = JSON.parse(rawBody);

    if (event.type === "checkout.session.completed") {
      const session = event.data.object;
      const customerEmail = session.customer_details?.email || session.customer_email;
      const subscriptionId = session.subscription || "one-time-order";
      
      // Entitlement payload: valid for 1 year if yearly, 30 days if monthly
      const expiresAt = Math.floor(Date.now() / 1000) + (30 * 24 * 60 * 60);

      const claims = {
        iss: "omniprompt-licensing",
        sub: customerEmail,
        plan: "PRO_MONTHLY",
        subscription_id: subscriptionId,
        exp: expiresAt,
        iat: Math.floor(Date.now() / 1000)
      };

      const header = { alg: "EdDSA", typ: "JWT" };
      const encodedHeader = bufferToBase64Url(new TextEncoder().encode(JSON.stringify(header)));
      const encodedPayload = bufferToBase64Url(new TextEncoder().encode(JSON.stringify(claims)));
      const signingInput = `${encodedHeader}.${encodedPayload}`;

      // 2. Sign using private key stored securely in Cloudflare Environment Secret
      const privateKeyJwk = JSON.parse(env.ED25519_PRIVATE_KEY_JWK);
      const signaturePart = await signEd25519(signingInput, privateKeyJwk);

      const fullLicenseToken = `${signingInput}.${signaturePart}`;

      // In production, emit email to user via Postmark, Resend, or SendGrid containing fullLicenseToken
      console.log(`[LICENSE CREATED]: ${customerEmail} -> ${fullLicenseToken}`);

      return new Response(JSON.stringify({ received: true, license: fullLicenseToken }), {
        headers: { "Content-Type": "application/json" },
        status: 200
      });
    }

    return new Response(JSON.stringify({ received: true }), { status: 200 });
  }
};

// Stripe Signature Verifier (SubtleCrypto)
async function verifyStripeSignature(body, sigHeader, secret) {
  if (!sigHeader || !secret) return false;
  
  const parts = sigHeader.split(",").reduce((acc, part) => {
    const [key, val] = part.split("=");
    if (key && val) acc[key.trim()] = val.trim();
    return acc;
  }, {});

  if (!parts.t || !parts.v1) return false;

  const timestamp = parts.t;
  const signature = parts.v1;
  const payloadToSign = `${timestamp}.${body}`;

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const signatureBytes = base64UrlToUint8Array(signature);
  const expectedSignature = await crypto.subtle.sign("HMAC", key, encoder.encode(payloadToSign));

  // Constant-time array comparison
  const expectedBytes = new Uint8Array(expectedSignature);
  if (expectedBytes.length !== signatureBytes.length) return false;
  let matches = 0;
  for (let i = 0; i < expectedBytes.length; i++) {
    matches |= expectedBytes[i] ^ signatureBytes[i];
  }
  return matches === 0;
}
```

---

### 3.3 Client-Side Offline Verification Engine (`LicenseValidator.js`)

This module requires **no server calls** to check licenses. It parses the custom EdDSA JWT using Chrome's native `crypto.subtle` APIs, validating signature fidelity and expiration timestamps entirely offline.

```javascript
// LicenseValidator.js

// Public Key deployed with the extension client (JWK format)
const PUBLIC_KEY_JWK = {
  kty: "OKP",
  crv: "Ed25519",
  x: "mDqwb0bX47W97d8bMhB_d6aV53gE192f1F8z_7XoYVw", // REPLACE WITH YOUR GENERATED PUBLIC KEY
  ext: true,
  key_ops: ["verify"]
};

export class LicenseValidator {
  /**
   * Helper decoding a base64url component to a standard decoded String
   */
  static decodeSegment(base64Url) {
    let base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    while (base64.length % 4) {
      base64 += "=";
    }
    return atob(base64);
  }

  /**
   * Helper parsing Base64Url into Uint8Array for SubtleCrypto verification
   */
  static base64UrlToUint8Array(base64Url) {
    let base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    while (base64.length % 4) {
      base64 += "=";
    }
    const raw = atob(base64);
    const output = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) {
      output[i] = raw.charCodeAt(i);
    }
    return output;
  }

  /**
   * Cryptographically verifies the license string and asserts expiration time.
   */
  static async verifyLicense(licenseString) {
    if (!licenseString || typeof licenseString !== "string") {
      return { valid: false, error: "MISSING_LICENSE" };
    }

    const segments = licenseString.trim().split(".");
    if (segments.length !== 3) {
      return { valid: false, error: "MALFORMED_JWT" };
    }

    const [headerB64, payloadB64, signatureB64] = segments;

    try {
      // 1. Parse payloads
      const payload = JSON.parse(this.decodeSegment(payloadB64));
      const signedData = new TextEncoder().encode(`${headerB64}.${payloadB64}`);
      const signatureBytes = this.base64UrlToUint8Array(signatureB64);

      // 2. Import Public Key into SubtleCrypto
      const cryptoKey = await crypto.subtle.importKey(
        "jwk",
        PUBLIC_KEY_JWK,
        { name: "Ed25519", namedCurve: "Ed25519" },
        false,
        ["verify"]
      );

      // 3. Mathematical validation of EdDSA signature
      const isSignatureValid = await crypto.subtle.verify(
        { name: "Ed25519" },
        cryptoKey,
        signatureBytes,
        signedData
      );

      if (!isSignatureValid) {
        return { valid: false, error: "TAMPERED_OR_INVALID_SIGNATURE" };
      }

      // 4. Temporal assertions
      const now = Math.floor(Date.now() / 1000);
      if (payload.exp && payload.exp < now) {
        return { valid: false, error: "LICENSE_EXPIRED", expiredAt: new Date(payload.exp * 1000) };
      }

      return {
        valid: true,
        claims: payload
      };
    } catch (err) {
      return { valid: false, error: `VERIFICATION_FAILED: ${err.message}` };
    }
  }

  /**
   * Persists the token into encrypted or standard chrome storage
   */
  static async activate(licenseString) {
    const check = await this.verifyLicense(licenseString);
    if (!check.valid) {
      throw new Error(`Activation Refused: ${check.error}`);
    }

    await chrome.storage.sync.set({
      license_token: licenseString.trim(),
      license_cached_email: check.claims.sub,
      license_plan: check.claims.plan
    });

    return check.claims;
  }
}
```

---

## 4. Key Pair Generation Utility

Use Node.js (v18+) and the built-in `crypto` module to output your production JWKs for both the Cloudflare Worker and Extension frontend:

```javascript
// generate_keys.js
import crypto from "node:crypto";

const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");

const publicKeyJwk = publicKey.export({ format: "jwk" });
const privateKeyJwk = privateKey.export({ format: "jwk" });

console.log("=== CLOUDFLARE WORKER PRIVATE SECRET (ED25519_PRIVATE_KEY_JWK) ===");
console.log(JSON.stringify
