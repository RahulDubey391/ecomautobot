# Module 2: 25+ Production MV3 Code Templates & Boilerplates

This module provides ready-to-deploy, copy-paste MV3 boilerplates and production patterns. Every template is hardened for cross-browser runtime quirks, Manifest V3 service worker lifecycle constraints, and strict Shadow DOM CSS isolation.

---

## 1. Cross-Browser MV3 Capability Matrix

Before deploying code across WebKit, Gecko, and Chromium, use this runtime capability matrix to configure your build targets and feature fallbacks.

| Runtime Feature | Chromium (Chrome, Edge, Brave) | Gecko (Firefox 115+ ESR / 120+) | WebKit (Safari 16.4+) | Production Workaround / Polyfill Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Background Runtime** | Service Worker (`background.service_worker`) | Event Page / Background Worker (MV3) | Background Service Worker / Persistent Fallback | Use Webpack/Vite dual-compile target or Mozilla `webextension-polyfill`. |
| **`chrome.sidePanel`** | Native support (Chrome 114+) | Not supported (uses `sidebar_action`) | Not supported (uses App Extension container) | Feature-detect `chrome.sidePanel`; fallback to injected iframe or Gecko `browser.sidebarAction`. |
| **`chrome.offscreen`** | Native support (Chrome 109+) | Not supported (Service workers have full DOM via Event Pages) | Not supported | Detect `chrome.offscreen`; fallback to background page DOM parsing on Firefox/Safari. |
| **Declarative Net Request**| Full static & dynamic ruleset support | Restricted rule counts; full support in 113+ | Static rulesets supported; dynamic modifications restricted | Normalize rules via standard JSON; strip non-Chromium regex properties during build. |
| **Script Injection** | `chrome.scripting.executeScript` | `browser.scripting.executeScript` | `browser.scripting.executeScript` (partial) | Normalize through Promise-based wrapper returning raw execution results. |

---

## 2. Enterprise Vite + React 18 + Tailwind CSS Build System

This production build configuration handles multi-entry Manifest V3 targets without relying on brittle third-party Vite plugins. It splits compilation into deterministic bundles for the Background Service Worker, the Side Panel, the Options UI, and an isolated Content Script.

### `package.json`
```json
{
  "name": "mv3-production-suite",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite build --watch --mode development",
    "build": "tsc && vite build --mode production",
    "lint": "eslint src --ext .ts,.tsx --max-warnings 0"
  },
  "dependencies": {
    "clsx": "^2.1.0",
    "lucide-react": "^0.344.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "tailwind-merge": "^2.2.1",
    "webextension-polyfill": "^0.10.0"
  },
  "devDependencies": {
    "@types/node": "^20.11.24",
    "@types/react": "^18.2.61",
    "@types/react-dom": "^18.2.19",
    "@types/webextension-polyfill": "^0.10.7",
    "@vitejs/plugin-react": "^4.2.1",
    "autoprefixer": "^10.4.18",
    "postcss": "^8.4.35",
    "tailwindcss": "^3.4.1",
    "typescript": "^5.3.3",
    "vite": "^5.1.4"
  }
}
```

### `vite.config.ts`
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";
import { writeFileSync, copyFileSync, mkdirSync, existsSync } from "fs";

export default defineConfig(({ mode }) => {
  const isDev = mode === "development";

  return {
    plugins: [
      react(),
      {
        name: "postbuild-manifest-copy",
        closeBundle() {
          if (!existsSync("dist")) {
            mkdirSync("dist", { recursive: true });
          }
          copyFileSync("src/manifest.json", "dist/manifest.json");
          if (existsSync("src/assets/icons")) {
            mkdirSync("dist/icons", { recursive: true });
            ["icon-16.png", "icon-48.png", "icon-128.png"].forEach((icon) => {
              const srcIcon = resolve(`src/assets/icons/${icon}`);
              if (existsSync(srcIcon)) {
                copyFileSync(srcIcon, resolve(`dist/icons/${icon}`));
              }
            });
          }
        },
      },
    ],
    build: {
      outDir: "dist",
      emptyOutDir: !isDev,
      sourcemap: isDev ? "inline" : false,
      minify: !isDev,
      rollupOptions: {
        input: {
          sidepanel: resolve(__dirname, "src/sidepanel/index.html"),
          options: resolve(__dirname, "src/options/index.html"),
          background: resolve(__dirname, "src/background/index.ts"),
          content: resolve(__dirname, "src/content/index.ts"),
          offscreen: resolve(__dirname, "src/offscreen/index.html"),
        },
        output: {
          entryFileNames: (chunkInfo) => {
            if (chunkInfo.name === "background") return "background.js";
            if (chunkInfo.name === "content") return "content.js";
            return "assets/[name]-[hash].js";
          },
          chunkFileNames: "assets/[name]-[hash].js",
          assetFileNames: "assets/[name]-[hash].[ext]",
        },
      },
    },
    resolve: {
      alias: {
        "@": resolve(__dirname, "src"),
      },
    },
  };
});
```

### `src/manifest.json`
```json
{
  "manifest_version": 3,
  "name": "MV3 Production Core",
  "version": "1.0.0",
  "description": "Hardened, multi-surface Manifest V3 enterprise client engine.",
  "permissions": [
    "storage",
    "tabs",
    "activeTab",
    "scripting",
    "sidePanel",
    "offscreen"
  ],
  "host_permissions": [
    "https://*/*"
  ],
  "background": {
    "service_worker": "background.js",
    "type": "module"
  },
  "side_panel": {
    "default_path": "src/sidepanel/index.html"
  },
  "options_ui": {
    "page": "src/options/index.html",
    "open_in_tab": true
  },
  "content_scripts": [
    {
      "matches": ["https://*/*"],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ],
  "web_accessible_resources": [
    {
      "resources": ["assets/*", "icons/*"],
      "matches": ["https://*/*"]
    }
  ]
}
```

### `tailwind.config.js`
```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./src/**/*.{html,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        vault: {
          50: "#f0fdf4",
          500: "#22c55e",
          900: "#14532d",
          950: "#052e16",
        },
      },
    },
  },
  plugins: [],
};
```

---

## 3. Isolated Shadow DOM UI Content Script Injector

This template creates an impenetrable Closed Shadow Root for injecting custom React/Tailwind interfaces into client web pages. It injects CSS directly into the shadow tree to guarantee zero style leakage from or to the parent application.

### `src/content/index.ts`
```typescript
import React from "react";
import ReactDOM from "react-dom/client";
import { ContentOverlay } from "./ContentOverlay";

const CONTAINER_ID = "vault-extension-mount-root";

function injectIsolatedApp(): void {
  // Prevent duplicate mounts on SPAs with repeated dynamic navigation
  if (document.getElementById(CONTAINER_ID)) {
    return;
  }

  const hostElement = document.createElement("div");
  hostElement.id = CONTAINER_ID;
  hostElement.style.cssText = `
    all: initial !important;
    position: fixed !important;
    top: 0 !important;
    right: 0 !important;
    width: 0 !important;
    height: 0 !important;
    overflow: visible !important;
    z-index: 2147483647 !important;
  `;

  // Attach shadow root defensively
  const shadowRoot = hostElement.attachShadow({ mode: "closed" });
  const mountPoint = document.createElement("div");
  mountPoint.id = "shadow-app-root";

  // Construct inline isolated CSS
  const styleSheet = document.createElement("style");
  styleSheet.textContent = `
    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    }
    .panel-wrapper {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 380px;
      max-height: 80vh;
      background: #0f172a;
      color: #f8fafc;
      border: 1px solid #334155;
      border-radius: 12px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      animation: vault-slide-in 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes vault-slide-in {
      from { transform: translateY(16px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
    .panel-header {
      padding: 14px 16px;
      border-bottom: 1px solid #1e293b;
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: #1e293b;
    }
    .panel-title {
      font-size: 14px;
      font-weight: 600;
      color: #38bdf8;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .panel-body {
      padding: 16px;
      font-size: 13px;
      line-height: 1.5;
      overflow-y: auto;
    }
    .action-button {
      background: #0284c7;
      color: white;
      border: none;
      padding: 8px 12px;
      border-radius: 6px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      margin-top: 12px;
      width: 100%;
    }
    .action-button:hover { background: #0369a1; }
    .close-btn {
      background: transparent;
      border: none;
      color: #94a3b8;
      cursor: pointer;
      font-size: 16px;
      line-height: 1;
      padding: 4px;
    }
    .close-btn:hover { color: #f8fafc; }
  `;

  shadowRoot.appendChild(styleSheet);
  shadowRoot.appendChild(mountPoint);
  document.documentElement.appendChild(hostElement);

  const root = ReactDOM.createRoot(mountPoint);
  root.render(
    React.createElement(ContentOverlay, {
      onClose: () => {
        root.unmount();
        hostElement.remove();
      },
    })
  );
}

// Resilient execution against dynamic single page apps
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", injectIsolatedApp);
} else {
  injectIsolatedApp();
}
```

### `src/content/ContentOverlay.tsx`
```typescript
import React, { useState, useEffect } from "react";

interface ContentOverlayProps {
  onClose: () => void;
}

interface PageAnalysisPayload {
  h1Count: number;
  wordCount: number;
  canonicalUrl: string;
}

export const ContentOverlay: React.FC<ContentOverlayProps> = ({ onClose }) => {
  const [analyzing, setAnalyzing] = useState<boolean>(false);
  const [data, setData] = useState<PageAnalysisPayload | null>(null);

  const executeAnalysis = () => {
    setAnalyzing(true);
    // Runs against the host DOM directly outside the shadow boundary
    const h1Nodes = document.querySelectorAll("h1");
    const bodyText = document.body.innerText || "";
    const canonicalLink = document.querySelector("link[rel='canonical']")?.getAttribute("href") || window.location.href;

    setTimeout(() => {
      setData({
        h1Count: h1Nodes.length,
        wordCount: bodyText.split(/\s+/).filter(Boolean).length,
        canonicalUrl: canonicalLink,
      });
      setAnalyzing(false);
    }, 250);
  };

  useEffect(() => {
    executeAnalysis();
  }, []);

  return (
    <div className="panel-wrapper">
      <div className="panel-header">
        <span className="panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect width="18" height="18" x="3" y="3" rx="2" />
            <path d="m9 12 2 2 4-4" />
          </svg>
          Vault Isolated Runtime
        </span>
        <button onClick={onClose} className="close-btn" aria-label="Close UI">
          ×
        </button>
      </div>

      <div className="panel-body">
        {analyzing && <p style={{ color: "#94a3b8" }}>Extracting host page telemetry...</p>}
        
        {!analyzing && data && (
          <div>
            <div style={{ marginBottom: 12 }}>
              <div style={{ color: "#94a3b8", fontSize: 11, textTransform: "uppercase" }}>Target Scope</div>
              <div style={{ wordBreak: "break-all", fontWeight: 500, marginTop: 2 }}>{data.canonicalUrl}</div>
            </div>
            
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
              <div style={{ background: "#1e293b", padding: 8, borderRadius: 6 }}>
                <span style={{ fontSize: 11, color: "#94a3b8" }}>H1 Elements</span>
                <p style={{ fontSize: 18, fontWeight: 700, color: "#38bdf8" }}>{data.h1Count}</p>
              </div>
              <div style={{ background: "#1e293b", padding: 8, borderRadius: 6 }}>
                <span style={{ fontSize: 11, color: "#94a3b8" }}>Total Words</span>
                <p style={{ fontSize: 18, fontWeight: 700, color: "#38bdf8" }}>{data.wordCount.toLocaleString()}</p>
              </div>
            </div>

            <button 
              className="action-button" 
              onClick={() => {
                chrome.runtime.sendMessage({
                  type: "STORE_AUDIT_LOG",
                  payload: { ...data, timestamp: Date.now() },
                });
              }}
            >
              Sync to Extension Core
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
```

---

## 4. Production Offscreen Document Engine (DOM Parsing & Audio Capture)

Manifest V3 background service workers lack access to both the `DOMParser` and the `navigator.mediaDevices.getUserMedia` APIs. This module provides a thread-safe coordinator that controls offscreen documents, automatically spawning and tearing them down to preserve memory.

```
+--------------------------------------------------------------------+
|                     BACKGROUND SERVICE WORKER                      |
|                                                                    |
|  +---------------------------+       +--------------------------+  |
|  | OffscreenDocumentManager  | ----> | chrome.offscreen API     |  |
|  | (Singleton State Manager) |       | (Spawns / Despawns Host) |  |
|  +---------------------------+       +--------------------------+  |
|                |                                                   |
+----------------|---------------------------------------------------+
                 | Runtime Message Bus (PARSING / AUDIO_RECORDING)
                 v
+--------------------------------------------------------------------+
|                         OFFSCREEN DOCUMENT                         |
|                       (offscreen.html / .ts)                       |
|                                                                    |
|  +---------------------------+       +--------------------------+  |
|  |   DOMParser Scrape Engine |       |   Web Audio API Bridge   |  |
|  |   - Full HTML Parsing     |       |   - Tab Capture Stream   |  |
|  |   - Metadata Extraction   |       |   - MediaStreamRecorder  |  |
|  +---------------------------+       +--------------------------+  |
+--------------------------------------------------------------------+
```

### `src/background/offscreen-manager.ts`
```typescript
interface OffscreenMessageRequest {
  target: "OFFSCREEN";
  action: "PARSE_DOM" | "START_AUDIO_CAPTURE" | "STOP_AUDIO_CAPTURE";
  data?: any;
}

interface OffscreenMessageResponse {
  success: boolean;
  result?: any;
  error?: string;
}

const OFFSCREEN_PATH = "src/offscreen/index.html";

export class OffscreenDocumentManager {
  private static instance: OffscreenDocumentManager;
  private isCreating: boolean = false;

  private constructor() {}

  public static getInstance(): OffscreenDocumentManager {
    if (!OffscreenDocumentManager.instance) {
      OffscreenDocumentManager.instance = new OffscreenDocumentManager();
    }
    return OffscreenDocumentManager.instance;
  }

  public async setupDocument(reason: chrome.offscreen.Reason): Promise<void> {
    if (await this.hasDocument()) {
      return;
    }

    if (this.isCreating) {
      await new Promise<void>((resolve) => {
        const interval = setInterval(async () => {
          if (!this.isCreating) {
            clearInterval(interval);
            resolve();
          }
        }, 50);
      });
      return;
    }

    this.isCreating = true;
    try {
      await chrome.offscreen.createDocument({
        url: OFFSCREEN_PATH,
        reasons: [reason],
        justification: "DOM execution and Web Audio decoding inaccessible inside MV3 Background Workers.",
      });
    } catch (error: any) {
      if (!error.message.includes("Only a single offscreen document may be created")) {
        throw error;
      }
    } finally {
      this.isCreating = false;
    }
  }

  public async closeDocument(): Promise<void> {
    if (await this.hasDocument()) {
      await chrome.offscreen.closeDocument();
    }
  }

  private async hasDocument(): Promise<boolean> {
    const clients = await (clients as any).matchAll({ includeUncontrolled: true, type: "window" });
    return clients.some((c: any) => c.url.includes(chrome.runtime.id) && c.url.includes("offscreen"));
  }

  public async executeTask<T = any>(
    action: OffscreenMessageRequest["action"],
    data: any,
    reason: chrome.offscreen.Reason
  ): Promise<T> {
    await this.setupDocument(reason);

    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        {
          target: "OFFSCREEN",
          action,
          data,
        } as OffscreenMessageRequest,
        (response: OffscreenMessageResponse) => {
          if (chrome.runtime.lastError) {
            return reject(new Error(chrome.runtime.lastError.message));
          }
          if (!response || !response.success) {
            return reject(new Error(response?.error || "Unknown offscreen evaluation failure"));
          }
          resolve(response.result as T);
        }
      );
    });
  }
}

export const offscreenManager = OffscreenDocumentManager.getInstance();
```

### `src/offscreen/index.html`
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Offscreen Processing Pipeline</title>
</head>
<body>
  <div id="audio-anchor"></div>
  <script type="module" src="./index.ts"></script>
</body>
</html>
```

### `src/offscreen/index.ts`
```typescript
interface OffscreenMessageRequest {
  target: "OFFSCREEN";
  action: "PARSE_DOM" | "START_AUDIO_CAPTURE" | "STOP_AUDIO_CAPTURE";
  data?: any;
}

interface ScrapedMetadata {
  title: string;
  metaTags: Record<string, string>;
  openGraph: Record<string, string>;
}

let mediaRecorder: MediaRecorder | null = null;
let audioChunks: Blob[] = [];

chrome.runtime.onMessage.addListener((message: OffscreenMessageRequest, _sender, sendResponse) => {
  if (message.target !== "OFFSCREEN") {
    return false;
  }

  switch (message.action) {
    case "PARSE_DOM":
      try {
        const rawHtml = message.data?.html as string;
        if (!rawHtml) {
          throw new Error("No raw HTML string supplied to parser");
        }
        const parsed = parseHeadlessDOM(rawHtml);
        sendResponse({ success: true, result: parsed });
      } catch (err: any) {
        sendResponse({ success: false, error: err.message });
      }
      return true;

    case "START_AUDIO_CAPTURE":
      startMediaRecording(message.data?.streamId)
        .then(() => sendResponse({ success: true }))
        .catch((err) => sendResponse({ success: false, error: err.message }));
      return true;

    case "STOP_AUDIO_CAPTURE":
      stopMediaRecording()
        .then((base64Audio) => sendResponse({ success: true, result: base64Audio }))
        .catch((err) => sendResponse({ success: false, error: err.message }));
      return true;

    default:
      sendResponse({ success: false, error: "Unsupported offscreen action" });
      return false;
  }
});

function parseHeadlessDOM(html: string): ScrapedMetadata {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");

  const title = doc.querySelector("title")?.textContent || "";
  const metaElements = doc.querySelectorAll("meta");
  const metaTags: Record<string, string> = {};
  const openGraph: Record<string, string> = {};

  metaElements.forEach((el) => {
    const name = el.getAttribute("name");
    const property = el.getAttribute("property");
    const content = el.getAttribute("content") || "";

    if (name) {
      metaTags[name.toLowerCase()] = content;
    }
    if (property && property.startsWith("og:")) {
      openGraph[property.toLowerCase()] = content;
    }
  });

  return { title, metaTags, openGraph };
}

async function startMediaRecording(streamId: string): Promise<void> {
  audioChunks = [];
  const mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    } as any,
    video: false,
  });

  mediaRecorder = new MediaRecorder(mediaStream, { mimeType: "audio/webm" });
  mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) {
      audioChunks.push(event.data);
    }
  };

  mediaRecorder.start();
}

async function stopMediaRecording(): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!mediaRecorder) {
      return reject(new Error("Active media recorder not found"));
    }

    mediaRecorder.onstop = async () => {
      const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
      const reader = new FileReader();
      reader.onloadend = () => {
        resolve(reader.result as string);
      };
      reader.onerror = () => reject(new Error("Failed converting audio buffer to Data URL"));
      reader.readAsDataURL(audioBlob);
    };

    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach((track) => track.stop());
    mediaRecorder = null;
  });
}
```

---

## 5. Cross-Browser Unified Runtime Wrapper

This wrapper standardizes API differences across Chrome (Chromium), Firefox (Gecko), and Safari (WebKit), providing a uniform Promise-based interface for storage, messaging, side panels, and window injection.

### `src/utils/browser-runtime.ts`
```typescript
import browser from "webextension-polyfill";

export type BrowserVendor = "chrome" | "firefox" | "safari" | "edge" | "unknown";

export class UnifiedBrowser {
  private static cachedVendor: BrowserVendor | null = null;

  public static getVendor(): BrowserVendor {
    if (this.cachedVendor) return this.cachedVendor;

    const userAgent = navigator.userAgent.toLowerCase();
    if (userAgent.includes("edg/")) {
      this.cachedVendor = "edge";
    } else if (userAgent.includes("firefox")) {
      this.cachedVendor = "firefox";
    } else if (userAgent.includes("safari") && !userAgent.includes("chrome")) {
      this.cachedVendor = "safari";
    } else if (userAgent.includes("chrome")) {
      this.cachedVendor = "chrome";
    } else {
      this.cachedVendor = "unknown";
    }

    return this.cachedVendor;
  }

  // Cross-browser persistent key-value storage
  public static async getStorage<T = any>(key: string, area: "local" | "sync" = "local"): Promise<T | null> {
    try {
      const result = await browser.storage[area].get(key);
      return result && result[key] !== undefined ? (result[key] as T) : null;
    } catch {
      return null;
    }
  }

  public static async setStorage(key: string, value: any, area: "local" | "sync" = "local"): Promise<void> {
    await browser.storage[area].set({ [key]: value });
  }

  // Unified Side Panel / Sidebar Router
  public static async openSideInterface(windowId?: number): Promise<void> {
    const vendor = this.getVendor();

    if (vendor === "chrome" || vendor === "edge") {
      if ("sidePanel" in chrome && typeof (chrome as any).sidePanel.open === "function") {
        if (windowId !== undefined) {
          await (chrome as any).sidePanel.open({ windowId });
        } else {
          const currentWindow = await browser.windows.getCurrent();
          if (currentWindow.id) {
            await (chrome as any).sidePanel.open({ windowId: currentWindow.id });
          }
        }
        return;
      }
    }

    if (vendor === "firefox") {
      if ("sidebarAction" in browser && typeof (browser as any).sidebarAction.open === "function") {
        await (browser as any).sidebarAction.open();
        return;
      }
    }

    // Fallback: Open options UI in responsive sidebar tab
    await browser.runtime.openOptionsPage();
  }

  // Typed runtime message bus with timeout protection
  public static async sendMessageWithTimeout<T = any>(
    message: any,
    timeoutMs: number = 8000
  ): Promise<T> {
    const timeoutPromise = new Promise<never>((_, reject) => {
      setTimeout(() => reject(new Error(`Message timeout after ${timeoutMs}ms`)), timeoutMs);
    });
