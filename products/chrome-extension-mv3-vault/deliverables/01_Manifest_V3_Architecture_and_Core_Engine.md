# Module 1: Manifest V3 Lifecycle Architecture & Event-Driven Engine

Manifest V3 replaces background pages with ephemeral service workers. Unlike persistent background pages, an MV3 service worker can—and will—terminate at any moment. 

Chrome forcibly terminates service workers under three distinct conditions:
1. **Idle Timeout:** No events or API calls occur for 30 seconds.
2. **Task Execution Timeout:** A single synchronous event or ongoing asynchronous task takes longer than 5 minutes.
3. **Resource Reclamation:** Memory consumption crosses platform-defined thresholds under operating system pressure.

This module provides the architectural foundation to eliminate runtime disconnects, prevent dropped messages, and build reliable background sync pipelines.

---

## 1. The MV3 Lifecycle Reality & Failure Matrix

Relying on in-memory global variables (`let user = ...`) in a Manifest V3 background service worker is the single most common cause of production failures. State must be externalized or reconstituted immediately upon wake-up.

| Failure Symptom | Underlying Root Cause | Architectural Solution |
| :--- | :--- | :--- |
| `Error: Extension context invalidated` | The content script attempts to communicate with a reloaded or updated service worker. | Auto-reconnect content script wrapper with exponential backoff and tab reload prompt. |
| `The message port closed before a response was received` | Asynchronous handler returned without returning `true`, or worker died mid-execution. | Unified Typed RPC Bus with explicit port keep-alives and synchronous `return true` enforcement. |
| Background task silently stops at minute 5 | Chrome hard-kills service workers after 300 seconds, regardless of active network sockets or timers. | Chained chunking via the `chrome.alarms` API combined with Web Locks or Offscreen documents. |
| `MAX_WRITE_OPERATIONS_PER_MINUTE` exceeded | Excessive granular writes to `chrome.storage.sync`. | Memory-buffered write-coalescing cache with auto-flushing transaction queues. |

```
                       [ Incoming Event ]
                     (Alarm, Message, Action)
                                |
                                v
                   +--------------------------+
                   |  Worker Wakes / Spawns   |
                   +--------------------------+
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
+--------------------------+          +--------------------------+
|  Hydrate Cache/Session   |          | Register Event Handlers  |
| (from chrome.storage)    |          | (Synchronous Execution)  |
+--------------------------+          +--------------------------+
             |                                     |
             +------------------+------------------+
                                |
                                v
                   +--------------------------+
                   |  Process Work Payload    |
                   +--------------------------+
                                |
       +------------------------+------------------------+
       | <= 30s Idle                                     | Long Operation (>30s)
       v                                                 v
+--------------------------+               +-------------------------------+
|  Graceful Shutdown /     |               | Port Keep-Alive or Offscreen  |
|  Eviction from Memory    |               | Document Handoff Pattern      |
+--------------------------+               +-------------------------------+
```

---

## 2. Production `manifest.json` Master Template

This `manifest.json` includes the core permission configurations, background service worker declarations, side panel hooks, and secure content security policies required for production extensions.

```json
{
  "manifest_version": 3,
  "name": "Production MV3 Core Engine",
  "version": "1.0.0",
  "description": "High-performance, fault-tolerant Manifest V3 production core engine.",
  "minimum_chrome_version": "116",
  "background": {
    "service_worker": "background.bundle.js",
    "type": "module"
  },
  "permissions": [
    "storage",
    "alarms",
    "unlimitedStorage",
    "sidePanel",
    "offscreen"
  ],
  "host_permissions": [
    "https://api.yourdomain.com/*"
  ],
  "side_panel": {
    "default_path": "sidepanel.html"
  },
  "action": {
    "default_title": "Open Workspace",
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon-16.png",
      "32": "icons/icon-32.png",
      "48": "icons/icon-48.png",
      "128": "icons/icon-128.png"
    }
  },
  "content_scripts": [
    {
      "matches": ["https://*/*"],
      "js": ["content.bundle.js"],
      "run_at": "document_idle"
    }
  ],
  "content_security_policy": {
    "extension_pages": "script-src 'self'; object-src 'self'; worker-src 'self';"
  }
}
```

---

## 3. Resilient Service Worker Keep-Alive Engine

When your background worker needs to run tasks that take longer than 30 seconds (such as chunked file uploads, long database migrations, or waiting on slow AI inference streams), you must actively prevent idle termination.

The safest, compliant approach that avoids abusing runtime APIs is **Dual-Channel Lifecycle Management**:
1. Short-to-medium tasks use `chrome.runtime.Port` connections from an active UI surface (Side Panel, Popup, or Content Script).
2. Deep background processing uses sequential self-rescheduling `chrome.alarms` paired with `navigator.locks` to maintain state across restarts without breaking the 5-minute wall.

### `src/engine/KeepAliveManager.ts`

```typescript
export interface ITaskContext<T> {
  id: string;
  run: () => Promise<T>;
  timeoutMs?: number;
}

export class KeepAliveManager {
  private static instance: KeepAliveManager;
  private activePorts: Set<chrome.runtime.Port> = new Set();
  private keepAliveIntervalId: number | null = null;
  private readonly KEEPALIVE_PORT_NAME = "MV3_INTERNAL_KEEPALIVE";

  private constructor() {
    this.initPortListener();
  }

  public static getInstance(): KeepAliveManager {
    if (!KeepAliveManager.instance) {
      KeepAliveManager.instance = new KeepAliveManager();
    }
    return KeepAliveManager.instance;
  }

  /**
   * Initializes port listeners to monitor active UI connections.
   */
  private initPortListener(): void {
    chrome.runtime.onConnect.addListener((port) => {
      if (port.name === this.KEEPALIVE_PORT_NAME) {
        this.activePorts.add(port);
        port.onDisconnect.addListener(() => {
          this.activePorts.delete(port);
        });
      }
    });
  }

  /**
   * Wraps an asynchronous background job with explicit wake locks.
   * Prevents termination by cycling an internal port ping if a client is open.
   */
  public async executeLongRunningTask<T>(task: ITaskContext<T>): Promise<T> {
    const startTime = Date.now();
    const lockName = `task_lock_${task.id}`;

    // Request a Web Lock to prevent duplicate concurrent executions
    return await navigator.locks.request(lockName, { mode: "exclusive" }, async () => {
      this.startKeepAlivePings();
      try {
        const timeoutPromise = new Promise<never>((_, reject) => {
          if (task.timeoutMs) {
            setTimeout(() => {
              reject(new Error(`Task ${task.id} exceeded limit of ${task.timeoutMs}ms`));
            }, task.timeoutMs);
          }
        });

        return await Promise.race([task.run(), timeoutPromise]);
      } finally {
        this.stopKeepAlivePings();
        const duration = Date.now() - startTime;
        console.debug(`[KeepAliveManager] Task ${task.id} finalized in ${duration}ms`);
      }
    });
  }

  /**
   * Pings the internal keepalive port every 25 seconds.
   * Keeps Chrome from dropping the service worker during active IO operations.
   */
  private startKeepAlivePings(): void {
    if (this.keepAliveIntervalId !== null) return;

    this.keepAliveIntervalId = setInterval(() => {
      // Accessing a chrome API resets the 30-second idle timer
      chrome.runtime.getPlatformInfo(() => {
        // Heartbeat tick verified
      });
    }, 25000) as unknown as number;
  }

  private stopKeepAlivePings(): void {
    if (this.keepAliveIntervalId !== null) {
      clearInterval(this.keepAliveIntervalId);
      this.keepAliveIntervalId = null;
    }
  }

  /**
   * Factory method for Content Scripts, Popups, and Side Panels
   * to open a continuous lifecycle port to the Service Worker.
   */
  public static createClientKeepAlivePort(): () => void {
    let port: chrome.runtime.Port | null = chrome.runtime.connect({
      name: "MV3_INTERNAL_KEEPALIVE",
    });

    const pingTimer = setInterval(() => {
      try {
        port?.postMessage({ type: "PING" });
      } catch {
        clearInterval(pingTimer);
      }
    }, 20000);

    port.onDisconnect.addListener(() => {
      clearInterval(pingTimer);
      port = null;
    });

    return () => {
      clearInterval(pingTimer);
      port?.disconnect();
      port = null;
    };
  }
}
```

---

## 4. End-to-End Strongly Typed RPC Message Bus

Untyped `chrome.runtime.sendMessage` calls quickly lead to runtime bugs in production. If a message handler does not return a literal `true`, Chrome drops the communication channel, producing the unhelpful error: *"The message port closed before a response was received."*

Here is an end-to-end, type-safe RPC messaging layer across Background, Popup, Side Panel, and Content Script contexts.

### `src/engine/rpc/contracts.ts`

```typescript
export type ExtensionContext = "BACKGROUND" | "CONTENT_SCRIPT" | "POPUP" | "SIDEPANEL";

export interface UserSessionPayload {
  userId: string;
  token: string;
  expiresAt: number;
}

export interface RPCProtocol {
  GET_SESSION: {
    request: void;
    response: UserSessionPayload | null;
  };
  MUTATE_SETTING: {
    request: { key: string; value: unknown };
    response: { success: boolean; updatedAt: number };
  };
  STREAM_AI_COMPLETION: {
    request: { prompt: string; maxTokens: number };
    response: { jobId: string; status: "QUEUED" | "PROCESSING" };
  };
}

export type RPCAction = keyof RPCProtocol;

export interface RPCEnvelope<T extends RPCAction> {
  id: string;
  action: T;
  payload: RPCProtocol[T]["request"];
  source: ExtensionContext;
  timestamp: number;
}

export interface RPCResponseEnvelope<T extends RPCAction> {
  id: string;
  action: T;
  data?: RPCProtocol[T]["response"];
  error?: {
    code: string;
    message: string;
    stack?: string;
  };
  success: boolean;
}
```

### `src/engine/rpc/RPCServer.ts`

```typescript
import { RPCProtocol, RPCAction, RPCEnvelope, RPCResponseEnvelope, ExtensionContext } from "./contracts";

type HandlerMap = {
  [K in RPCAction]?: (
    payload: RPCProtocol[K]["request"],
    sender: chrome.runtime.MessageSender
  ) => Promise<RPCProtocol[K]["response"]>;
};

export class RPCServer {
  private handlers: HandlerMap = {};
  private currentContext: ExtensionContext;

  constructor(context: ExtensionContext) {
    this.currentContext = context;
    this.bindListener();
  }

  public register<K extends RPCAction>(
    action: K,
    handler: (
      payload: RPCProtocol[K]["request"],
      sender: chrome.runtime.MessageSender
    ) => Promise<RPCProtocol[K]["response"]>
  ): void {
    if (this.handlers[action]) {
      throw new Error(`Handler already registered for action: ${action}`);
    }
    this.handlers[action] = handler as any;
  }

  private bindListener(): void {
    chrome.runtime.onMessage.addListener(
      (rawMessage: unknown, sender: chrome.runtime.MessageSender, sendResponse: (response: any) => void) => {
        if (!this.isValidEnvelope(rawMessage)) {
          return false; // Ignore messages not matching our protocol
        }

        const envelope = rawMessage as RPCEnvelope<any>;
        const handler = this.handlers[envelope.action];

        if (!handler) {
          // Silently pass or return error if addressed specifically
          return false;
        }

        // Execute async handler and explicitly return true to hold channel open
        (async () => {
          try {
            const result = await handler(envelope.payload, sender);
            const response: RPCResponseEnvelope<any> = {
              id: envelope.id,
              action: envelope.action,
              data: result,
              success: true,
            };
            sendResponse(response);
          } catch (err: any) {
            const errorResponse: RPCResponseEnvelope<any> = {
              id: envelope.id,
              action: envelope.action,
              success: false,
              error: {
                code: err.code || "INTERNAL_EXECUTION_ERROR",
                message: err.message || "An unhandled error occurred during RPC execution",
                stack: process.env.NODE_ENV === "development" ? err.stack : undefined,
              },
            };
            sendResponse(errorResponse);
          }
        })();

        return true; // Crucial: Keeps the sendResponse port alive asynchronously
      }
    );
  }

  private isValidEnvelope(msg: unknown): msg is RPCEnvelope<any> {
    return (
      typeof msg === "object" &&
      msg !== null &&
      "id" in msg &&
      "action" in msg &&
      "timestamp" in msg &&
      "source" in msg
    );
  }
}
```

### `src/engine/rpc/RPCClient.ts`

```typescript
import { RPCProtocol, RPCAction, RPCEnvelope, RPCResponseEnvelope, ExtensionContext } from "./contracts";

export class RPCClient {
  private currentContext: ExtensionContext;
  private defaultTimeoutMs: number;

  constructor(context: ExtensionContext, defaultTimeoutMs = 15000) {
    this.currentContext = context;
    this.defaultTimeoutMs = defaultTimeoutMs;
  }

  public async call<K extends RPCAction>(
    action: K,
    payload: RPCProtocol[K]["request"],
    targetTabId?: number
  ): Promise<RPCProtocol[K]["response"]> {
    const envelope: RPCEnvelope<K> = {
      id: crypto.randomUUID(),
      action,
      payload,
      source: this.currentContext,
      timestamp: Date.now(),
    };

    return new Promise<RPCProtocol[K]["response"]>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(
          new Error(
            `[RPCClient] Call to ${action} timed out after ${this.defaultTimeoutMs}ms`
          )
        );
      }, this.defaultTimeoutMs);

      const responseCallback = (response: RPCResponseEnvelope<K>) => {
        clearTimeout(timeout);

        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }

        if (!response) {
          return reject(new Error("Empty response received from RPC endpoint."));
        }

        if (!response.success) {
          const err = new Error(response.error?.message || "Unknown RPC Error");
          (err as any).code = response.error?.code;
          return reject(err);
        }

        resolve(response.data!);
      };

      if (targetTabId !== undefined) {
        chrome.tabs.sendMessage(targetTabId, envelope, responseCallback);
      } else {
        chrome.runtime.sendMessage(envelope, responseCallback);
      }
    });
  }
}
```

---

## 5. Resilient Persistent Cache Layer with Debounced Writes

Frequent calls to `chrome.storage.sync` will trigger the `MAX_WRITE_OPERATIONS_PER_MINUTE` quota (120 writes/minute). Additionally, the service worker must hydrate an in-memory cache on startup to serve reads instantly without waiting on storage disk I/O.

### `src/engine/storage/PersistentStorageEngine.ts`

```typescript
type StorageArea = "local" | "sync" | "session";

interface StorageSchema {
  sessionToken: string | null;
  userSettings: {
    theme: "light" | "dark" | "system";
    telemetryEnabled: boolean;
  };
  lastSyncTimestamp: number;
}

export class PersistentStorageEngine {
  private static instance: PersistentStorageEngine;
  private memoryCache: Map<string, unknown> = new Map();
  private writeQueue: Map<string, unknown> = new Map();
  private debounceTimer: number | null = null;
  private readonly DEBOUNCE_DELAY_MS = 150;
  private isInitialized = false;

  private constructor(private preferredArea: StorageArea = "local") {}

  public static getInstance(area: StorageArea = "local"): PersistentStorageEngine {
    if (!PersistentStorageEngine.instance) {
      PersistentStorageEngine.instance = new PersistentStorageEngine(area);
    }
    return PersistentStorageEngine.instance;
  }

  /**
   * Initializes the in-memory cache directly from persistent storage.
   * Must be called during worker initialization.
   */
  public async initialize(): Promise<void> {
    if (this.isInitialized) return;

    const allData = await this.readAllFromStorage();
    for (const [key, val] of Object.entries(allData)) {
      this.memoryCache.set(key, val);
    }

    // Bind cross-context storage changes to update local memory cache instantly
    chrome.storage.onChanged.addListener((changes, areaName) => {
      if (areaName === this.preferredArea) {
        for (const [key, change] of Object.entries(changes)) {
          if (change.newValue === undefined) {
            this.memoryCache.delete(key);
          } else {
            this.memoryCache.set(key, change.newValue);
          }
        }
      }
    });

    this.isInitialized = true;
  }

  public get<K extends keyof StorageSchema>(key: K): StorageSchema[K] | undefined {
    return this.memoryCache.get(key as string) as StorageSchema[K] | undefined;
  }

  public async set<K extends keyof StorageSchema>(
    key: K,
    value: StorageSchema[K]
  ): Promise<void> {
    // Write-through update on the memory cache for instant local reads
    this.memoryCache.set(key as string, value);
    this.writeQueue.set(key as string, value);

    return new Promise((resolve, reject) => {
      if (this.debounceTimer !== null) {
        clearTimeout(this.debounceTimer);
      }

      this.debounceTimer = setTimeout(async () => {
        try {
          await this.flushQueue();
          resolve();
        } catch (err) {
          reject(err);
        }
      }, this.DEBOUNCE_DELAY_MS) as unknown as number;
    });
  }

  public async delete<K extends keyof StorageSchema>(key: K): Promise<void> {
    this.memoryCache.delete(key as string);
    this.writeQueue.delete(key as string);
    await chrome.storage[this.preferredArea].remove(key as string);
  }

  private async flushQueue(): Promise<void> {
    if (this.writeQueue.size === 0) return;

    const payload: Record<string, unknown> = {};
    for (const [key, val] of this.writeQueue.entries()) {
      payload[key] = val;
    }

    this.writeQueue.clear();
    this.debounceTimer = null;

    return new Promise<void>((resolve, reject) => {
      chrome.storage[this.preferredArea].set(payload, () => {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        resolve();
      });
    });
  }

  private readAllFromStorage(): Promise<Record<string, unknown>> {
    return new Promise((resolve, reject) => {
      chrome.storage[this.preferredArea].get(null, (items) => {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        resolve(items || {});
      });
    });
  }
}
```

---

## 6. End-to-End Background Service Worker Harness

Now we wire the components together in `background.ts`. This entry point handles lifecycle hydration, initializes the RPC server, mounts keep-alives, and schedules periodic work via `chrome.alarms`.

### `src/background.ts`

```typescript
import { KeepAliveManager } from "./engine/KeepAliveManager";
import { RPCServer } from "./engine/rpc/RPCServer";
import { PersistentStorageEngine } from "./engine/storage/PersistentStorageEngine";

// 1. Instantiate Core Singletons
const storage = PersistentStorageEngine.getInstance("local");
const keepAlive = KeepAliveManager.getInstance();
const rpcServer = new RPCServer("BACKGROUND");

/**
 * Service Worker Top-Level Bootstrap.
 * Must run synchronously on initial evaluation.
 */
(async function bootstrap() {
  console.debug("[Background Engine] Initializing Service Worker Context...");

  // Synchronously initialize the persistent cache before handling messages
  await storage.initialize();

  // 2. Register Typed RPC Endpoints
  rpcServer.register("GET_SESSION", async (_, sender) => {
    console.debug(`[Background Engine] Session requested by caller: ${sender.id}`);
    const token = storage.get("sessionToken");

    if (!token) return null;

    return {
      userId: "usr_prod_9921",
      token,
      expiresAt: Date.now() + 3600000,
    };
  });

  rpcServer.register("MUTATE_SETTING", async ({ key, value }) => {
    console.debug(`[Background Engine] Mutating setting: ${key} ->`, value);
    const currentSettings = storage.get("userSettings") || {
      theme: "system",
      telemetryEnabled: true,
    };

    const updated = {
      ...currentSettings,
      [key]: value,
    };

    await storage.set("userSettings", updated);
    return { success: true, updatedAt: Date.now() };
  });

  rpcServer.register("STREAM_AI_COMPLETION", async (payload) => {
    // Offload long tasks through the KeepAliveManager
    return await keepAlive.executeLongRunningTask({
      id: `ai_job_${Date.now()}`,
      timeoutMs: 60000,
      run: async () => {
        // Simulating heavy background processing / API coordination
        await new Promise((res) => setTimeout(res, 2000));
        return { jobId: crypto.randomUUID(), status: "QUEUED" };
      },
    });
  });

  // 3. Configure Safe Recurring Tasks via chrome.alarms (never setInterval)
  chrome.alarms.create("MAINTENANCE_HEARTBEAT", {
    periodInMinutes: 4.5, // Fires just before the 5-minute timeout window
  });

  console.debug("[Background Engine] Service Worker successfully mounted.");
})();

// Listen for lifecycle alarms
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "MAINTENANCE_HEARTBEAT") {
    console.debug("[Background Engine] Running maintenance sync...");
    // Update a timestamp to record the wake event
    storage.set("lastSyncTimestamp", Date.now());
  }
});

// Clean up resources on extension installation/updates
chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === chrome.runtime.OnInstalledReason.INSTALL) {
    console.info("[Background Engine] First run detected. Initializing defaults.");
    await storage.set("userSettings", { theme: "system", telemetryEnabled: true });
    await storage.set("sessionToken", null);
  }
});
```

---

## 7. Connecting Content Scripts & UI Contexts

Here is how you use the RPC engine inside a Content Script or Side Panel. It handles establishing the lifecycle keep-alive port, sends strongly typed RPC requests, and listens for changes on dynamic stores.

### `src/content.ts` (or `src/sidepanel.ts`)

```typescript
import { KeepAliveManager } from "./engine/KeepAliveManager";
import { RPCClient } from "./engine/rpc/RPCClient";

// 1. Bind UI Keep-Alive Port to keep the Service Worker awake during operations
const disconnectKeepAlive = KeepAliveManager.createClientKeepAlivePort();

// 2. Initialize the Typed RPC Client
const client = new RPCClient("CONTENT_SCRIPT", 10000);

async function runApplication() {
  try {
    // 3. Perform a type-safe RPC call
    const session = await client.call("GET_SESSION", undefined);
    console.log("[Content App] Active User Session:", session);

    // 4. Trigger an update
    const mutationResult = await client.call("MUTATE_SETTING", {
      key: "theme",
      value: "dark",
    });

    console.log("[Content App] Mutation Complete:", mutationResult.success);
  } catch (err: any) {
    console.error("[Content App] RPC Error encountered:", err.message, err.code);
  }
}

// Execute application logic
runApplication();

// Clean up the port connection when navigating away or unmounting
window.addEventListener("beforeunload", () => {
  disconnectKeepAlive();
});
```

---

## 8. Verification & Debugging Runbook

To confirm your service worker lifecycle handles wake/sleep cycles properly without dropping messages, run these tests before deploying to the Chrome Web Store.

### Step 1: Force Worker Eviction
1. Open Chrome and navigate to `chrome://serviceworkers`.
2. Locate your extension by ID.
3. Observe its operational status: `RUNNING`.
4. Click **Stop**. The worker state will transition to `STOPPED`.
5. Trigger an RPC call from the UI (Popup, Side Panel, or Content Script).
6. **Expected Result:** The worker should instantly spawn, handle the request via `RPCServer`, update state, and return the response without dropping the message.

### Step 2: Validate Inactivity Shutdown
1. Open the background console via `chrome://extensions` (Inspect views: Service Worker).
2. Leave the browser idle for 31 seconds. Do not click the console window (doing so keeps the worker alive via Chrome DevTools).
3. Check `chrome://extensions`.
4. **Expected Result:** The worker should transition to an *Inactive* state without uncaught errors or leaks.

### Step 3: Quota Boundary Audit
1. Run the storage benchmark in your extension's console:
```javascript
for (let i = 0; i < 200; i++) {
  chrome.storage.sync.set({ [`key_${i}`]: `value_${i}` });
}
```
2. **Expected Result:** Native execution will trigger `MAX_WRITE_OPERATIONS_PER_MINUTE`.
3. Next, test the batching engine:
```javascript
const storage = PersistentStorageEngine.getInstance("sync");
for (let i = 0; i < 200; i++) {
  storage.set(`key_${i}`, `value_${i}`);
}
```
4. **Expected Result:** Updates are debounced and coalesced into a single consolidated write, running well within your quota.
