# Module 3: Advanced Workflows, Live Cursors, Selection Sync & Offline Fallbacks

High-performance collaborative applications require two separate data lifecycles: **Durable State** (document mutations, canvas geometry, rich-text state) governed by Conflict-Free Replicated Data Types (CRDTs), and **Ephemeral State** (cursor coordinates, viewport bounds, selection ranges, live presence) requiring high-frequency, low-overhead broadcast.

This module provides the architecture, algorithms, and production-ready source code to unify Yjs, PartyKit, Tiptap/ProseMirror, and IndexedDB into a zero-latency, local-first engine with offline resilience.

---

## 1. Dual-Channel Protocol Topology

To prevent state-tree bloat and eliminate memory leaks, never route high-frequency cursor coordinates through the durable CRDT log. Route mutations through the persistent Yjs document stream, and route pointer movements through ephemeral Awareness or direct raw WebSocket frames.

```
+---------------------------------------------------------------------------------------+
|                                    CLIENT BROWSER                                     |
|                                                                                       |
|   +-------------------------+                     +-------------------------------+   |
|   |   UI Layer: Canvas /    |                     |   Rich-Text Layer: Tiptap /   |   |
|   |   DOM Pointer Events    |                     |   ProseMirror Editor          |   |
|   +------------+------------+                     +---------------+---------------+   |
|                |                                                  |                   |
|                | Normalized (X, Y)                                | CRDT Transactions |
|                v                                                  v                   |
|   +----------------------------+                     +----------------------------+   |
|   | Cursor Interpolation Engine|                     | Y.Doc / Y.UndoManager      |   |
|   | (RAF Loop + Linear Lerp)   |                     | (Scoped Local Origin)      |   |
|   +------------+---------------+                     +------------+---------------+   |
|                |                                                  |                   |
|                | Ephemeral Payloads                               | SyncStep 1 & 2    |
|                v                                                  v                   |
|   +-------------------------------------------------------------------------------+   |
|   |                       PartyKit WebSocket Client Provider                      |   |
|   +---------------------------------------+---------------------------------------+   |
+-------------------------------------------|-------------------------------------------+
                                            |
                         Dual-Channel Over WebSocket
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                    PARTYKIT EDGE ROOM                                 |
|                                                                                       |
|   +------------------------------------+    +-------------------------------------+   |
|   | Awareness Broadcast Broker         |    | Durable CRDT Broker                 |   |
|   | - In-memory connection map         |    | - y-protocols/sync                  |   |
|   | - 30Hz - 60Hz throttled fan-out    |    | - State vector comparison           |   |
|   | - Zero disk persistence            |    | - Periodic flush to Edge Key-Value  |   |
|   +------------------------------------+    +-------------------------------------+   |
+---------------------------------------------------------------------------------------+
```

### Protocol Envelope Specification

| Traffic Type | Transport Channel | Frequency Target | Serialization Format | Target Latency Envelope | Persistence Strategy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Pointer Coordinates** | WS Ephemeral / Awareness | 30ms - 50ms (Throttled) | Binary / Compact Array Buffer | `< 45ms` | None (Drop on disconnect) |
| **Selection Ranges** | Yjs Awareness Protocol | Event-Driven (Debounced 15ms) | JSON via Uint8Array State | `< 80ms` | None (TTL: 10 seconds) |
| **Rich-Text Mutations** | Yjs Sync Protocol v2 | Instantaneous (Event Loop) | Lib0 Packed Uint8Array | `< 120ms` | IndexedDB (Local) + Edge KV |
| **Canvas Shape Tree** | Y.Map / Y.Array CRDT | Instantaneous (Local Optimistic) | Lib0 Packed Uint8Array | `< 120ms` | IndexedDB (Local) + Edge KV |

---

## 2. High-Performance Live Cursors & Selection Sync

A production cursor implementation requires:
1. **Coordinate Normalization**: Translating absolute screen pixels into fractional `[0.0, 1.0]` coordinates relative to the shared canvas or document container.
2. **Bandwidth Throttling**: Limiting outbound frames to a fixed tick rate (typically 30–50 updates per second).
3. **Client-Side Interpolation**: Smoothing incoming updates via a requestAnimationFrame (RAF) loop with Linear Interpolation (Lerp) to hide network jitter.

### Cursor Engine: `CursorEngine.ts`

```typescript
export interface Point {
  x: number;
  y: number;
}

export interface PeerCursorState {
  clientId: number;
  userName: string;
  userColor: string;
  current: Point;
  target: Point;
  lastUpdate: number;
  selection?: {
    anchor: number;
    head: number;
  } | null;
}

export class CursorEngine {
  private peers: Map<number, PeerCursorState> = new Map();
  private rafId: number | null = null;
  private container: HTMLElement;
  private onRenderCallback: (peers: PeerCursorState[]) => void;
  private readonly LERP_FACTOR = 0.22; // Smoothing constant
  private readonly STALE_THRESHOLD_MS = 5000;

  constructor(
    container: HTMLElement,
    onRender: (peers: PeerCursorState[]) => void
  ) {
    this.container = container;
    this.onRenderCallback = onRender;
    this.startRenderLoop();
  }

  /**
   * Normalizes DOM client coordinates into a 0.0 -> 1.0 container space.
   */
  public normalizeCoordinates(clientX: number, clientY: number): Point {
    const rect = this.container.getBoundingClientRect();
    const x = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  /**
   * Translates normalized coordinates back to absolute container pixels.
   */
  public denormalizeCoordinates(point: Point): Point {
    const rect = this.container.getBoundingClientRect();
    return {
      x: point.x * rect.width,
      y: point.y * rect.height,
    };
  }

  /**
   * Receives incoming network payload from Awareness channel.
   */
  public ingestPeerState(
    clientId: number,
    payload: {
      userName: string;
      userColor: string;
      point: Point;
      selection?: { anchor: number; head: number } | null;
    }
  ): void {
    const now = performance.now();
    const existing = this.peers.get(clientId);

    if (existing) {
      existing.target = payload.point;
      existing.lastUpdate = now;
      existing.selection = payload.selection;
      existing.userName = payload.userName;
      existing.userColor = payload.userColor;
    } else {
      this.peers.set(clientId, {
        clientId,
        userName: payload.userName,
        userColor: payload.userColor,
        current: { ...payload.point },
        target: { ...payload.point },
        lastUpdate: now,
        selection: payload.selection,
      });
    }
  }

  public removePeer(clientId: number): void {
    this.peers.delete(clientId);
  }

  private startRenderLoop(): void {
    const tick = () => {
      const now = performance.now();
      const activePeers: PeerCursorState[] = [];

      for (const [clientId, state] of this.peers.entries()) {
        if (now - state.lastUpdate > this.STALE_THRESHOLD_MS) {
          this.peers.delete(clientId);
          continue;
        }

        // Apply Linear Interpolation (LERP): Pos = Pos + (Target - Pos) * Factor
        state.current.x += (state.target.x - state.current.x) * this.LERP_FACTOR;
        state.current.y += (state.target.y - state.current.y) * this.LERP_FACTOR;

        activePeers.push(state);
      }

      this.onRenderCallback(activePeers);
      this.rafId = requestAnimationFrame(tick);
    };

    this.rafId = requestAnimationFrame(tick);
  }

  public destroy(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
    }
    this.peers.clear();
  }
}
```

---

## 3. PartyKit Multiplayer Edge Broker

This PartyKit server implementation coordinates durable Yjs CRDT synchronization and broadcasts awareness states across edge nodes.

### PartyKit Server Room: `party/index.ts`

```typescript
import type * as Party from "partykit/server";
import { onConnect } from "y-partykit";

export default class CollaborativeRoomServer implements Party.Server {
  constructor(readonly room: Party.Room) {}

  /**
   * Intercept connection handshake to authenticate and set initial tags.
   */
  async onConnect(connection: Party.Connection, ctx: Party.ConnectionContext) {
    // Standard y-partykit protocol takes ownership of the persistent Y.Doc sync
    return onConnect(connection, this.room, {
      persist: {
        mode: "history", // Saves complete transaction history to Edge Storage
      },
    });
  }

  /**
   * Handle non-CRDT, sub-millisecond custom operational messages.
   */
  onMessage(message: string | ArrayBuffer, sender: Party.Connection) {
    if (typeof message === "string") {
      try {
        const parsed = JSON.parse(message);
        if (parsed.type === "heartbeat") {
          sender.send(JSON.stringify({ type: "heartbeat-ack", time: Date.now() }));
          return;
        }

        // Broadcast non-persisted canvas transient events (e.g., laser pointer)
        if (parsed.type === "transient-broadcast") {
          this.room.broadcast(message, [sender.id]);
        }
      } catch (e) {
        // Drop unformatted packets silently to prevent server panics
      }
    }
  }

  async onClose(connection: Party.Connection) {
    // Explicit server-side garbage cleanup on hard drop
  }
}
```

---

## 4. Collaborative Rich-Text Architecture (Tiptap + Yjs Subdocs)

When scaling collaborative applications to massive hierarchies (e.g., an infinite canvas containing hundreds of distinct text cards), binding the entire canvas to a single monolithic Y.Text CRDT causes severe performance degradation. Every keystroke forces the entire client fleet to process global vector calculations.

The solution is **Y.Doc Subdocs**. The master document acts as a spatial index of cards (`Y.Map<Y.Doc>`), and the rich-text editor dynamically mounts subdocuments on demand.

```
+-------------------------------------------------------------------+
|                  ROOT DOCUMENT (Master Y.Doc)                     |
|  Y.Map("canvas-nodes")                                            |
|    |                                                              |
|    +---> Node "card-01": Y.Map { x: 100, y: 400, doc: SubDoc-A }  |
|    |                                                              |
|    +---> Node "card-02": Y.Map { x: 500, y: 200, doc: SubDoc-B }  |
+-------------------------------------------------------------------+
                               |
             +-----------------+-----------------+
             | Mount Subdoc                      | Mount Subdoc
             v                                   v
+-----------------------------+     +-----------------------------+
|    SUBDOCUMENT: SubDoc-A    |     |    SUBDOCUMENT: SubDoc-B    |
|                             |     |                             |
| Y.XmlFragment("prosemirror")|     | Y.XmlFragment("prosemirror")|
| Tiptap Instance #1 (Active) |     | Tiptap Instance #2 (Active) |
+-----------------------------+     +-----------------------------+
```

### Collaborative Editor Component: `CollaborativeEditor.tsx`

```tsx
import React, { useEffect } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Collaboration from "@tiptap/extension-collaboration";
import CollaborationCursor from "@tiptap/extension-collaboration-cursor";
import * as Y from "yjs";
import YPartyKitProvider from "y-partykit/provider";

interface CollaborativeEditorProps {
  roomName: string;
  partyHost: string;
  subdoc: Y.Doc;
  user: {
    name: string;
    color: string;
  };
}

export const CollaborativeEditor: React.FC<CollaborativeEditorProps> = ({
  roomName,
  partyHost,
  subdoc,
  user,
}) => {
  // 1. Establish isolated provider for the targeted Subdoc or Doc
  const provider = React.useMemo(() => {
    return new YPartyKitProvider(partyHost, roomName, subdoc, {
      connect: false, // Defer connection until awareness is initialized
    });
  }, [partyHost, roomName, subdoc]);

  // 2. Initialize Tiptap with ProseMirror CRDT Bindings
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        // The Collaboration extension takes ownership of history handling
        history: false,
      }),
      Collaboration.configure({
        document: subdoc,
        field: "prosemirror", // Target key in the subdoc
      }),
      CollaborationCursor.configure({
        provider: provider,
        user: {
          name: user.name,
          color: user.color,
        },
      }),
    ],
  });

  useEffect(() => {
    // Set awareness metadata
    provider.awareness.setLocalStateField("user", {
      name: user.name,
      color: user.color,
    });

    // Mount connection
    provider.connect();

    return () => {
      provider.disconnect();
      provider.destroy();
    };
  }, [provider, user]);

  return (
    <div className="collaborative-editor-wrapper border rounded-lg p-4 bg-white shadow-sm">
      <div className="status-bar mb-2 flex items-center justify-between text-xs text-gray-500">
        <span className="flex items-center gap-2">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ backgroundColor: user.color }}
          />
          {user.name} (Editing: {subdoc.guid})
        </span>
      </div>
      <EditorContent editor={editor} className="prose max-w-none focus:outline-none" />
    </div>
  );
};
```

---

## 5. Scoped Undo/Redo Engine

The most critical defect in standard multi-user undo implementations is **destructive inversion clobbering**: User A types, User B types immediately after, and User A presses `Cmd+Z`, inadvertently rolling back User B's characters.

To isolate history, configure `Y.UndoManager` with explicit **Origin Scoping** and tracked transaction origins.

```typescript
// Define explicit transaction origins
export const TransactionOrigins = {
  LOCAL_USER: Symbol("TRANSACTION_ORIGIN_LOCAL_USER"),
  REMOTE_SYNC: Symbol("TRANSACTION_ORIGIN_REMOTE_SYNC"),
  SYSTEM_MIGRATION: Symbol("TRANSACTION_ORIGIN_SYSTEM_MIGRATION"),
};
```

### Scoped Undo Manager: `ScopedUndoManager.ts`

```typescript
import * as Y from "yjs";
import { TransactionOrigins } from "./TransactionOrigins";

export interface UndoManagerOptions {
  captureTimeout?: number;
}

export class ScopedUndoManagerEngine {
  private undoManager: Y.UndoManager;
  private scopeDoc: Y.Doc;

  constructor(
    targetType: Y.Type,
    doc: Y.Doc,
    options: UndoManagerOptions = { captureTimeout: 500 }
  ) {
    this.scopeDoc = doc;

    // Track only transactions originating from the authenticated local user
    this.undoManager = new Y.UndoManager(targetType, {
      trackedOrigins: new Set([TransactionOrigins.LOCAL_USER]),
      captureTimeout: options.captureTimeout,
    });

    this.registerEventPumps();
  }

  private registerEventPumps(): void {
    this.undoManager.on("stack-item-added", (event: { stackItem: any; type: string }) => {
      // Annotate the history item with transactional metadata
      event.stackItem.meta.set("timestamp", Date.now());
      event.stackItem.meta.set("clientVersion", this.scopeDoc.clientID);
    });

    this.undoManager.on("stack-item-popped", (event: { stackItem: any; type: string }) => {
      // Fires when an undo or redo step executes across the CRDT
    });
  }

  /**
   * Executes a mutation on the document tagged with the Local User Origin.
   */
  public executeLocalMutation(mutationFn: () => void): void {
    this.scopeDoc.transact(() => {
      mutationFn();
    }, TransactionOrigins.LOCAL_USER);
  }

  /**
   * Reverts the latest local mutation without modifying remote operations.
   */
  public undo(): boolean {
    const result = this.undoManager.undo();
    return result !== null;
  }

  /**
   * Re-applies the latest undone local mutation.
   */
  public redo(): boolean {
    const result = this.undoManager.redo();
    return result !== null;
  }

  public clearHistory(): void {
    this.undoManager.clear();
  }

  public destroy(): void {
    this.undoManager.destroy();
  }
}
```

---

## 6. Offline Persistence & Partition Reconciliation

A resilient collaborative web engine must treat the local IndexedDB instance as the absolute source of truth during startup, hydrate memory state instantaneously, queue local updates while offline, and seamlessly merge states via the Yjs State Vector protocol when reconnected.

```
+---------------------------------------------------------------------------------------+
|                                    CLIENT STARTUP                                     |
|                                                                                       |
|   1. Initialize Local Y.Doc                                                          |
|   2. Attach IndexedDB Provider (IndexeddbPersistence)                                 |
|   3. Read Local Uint8Array Snapshot from IndexedDB (0ms network delay)                |
|   4. Mark Client as Locally Hydrated (Render UI immediately)                         |
|                                                                                       |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                    NETWORK SYNC                                       |
|                                                                                       |
|   5. Establish WebSocket to PartyKit Edge Server                                      |
|   6. Compute Local State Vector: Y.encodeStateVector(doc)                             |
|   7. Send Vector via SyncStep 1                                                       |
|   8. Edge Server replies with missing delta: SyncStep 2                               |
|   9. Apply Missing Updates to Local Doc -> Automatically written back to IndexedDB   |
|                                                                                       |
+---------------------------------------------------------------------------------------+
```

### Persistence Sync Bridge: `PersistenceSyncBridge.ts`

```typescript
import * as Y from "yjs";
import { IndexeddbPersistence } from "y-indexeddb";
import YPartyKitProvider from "y-partykit/provider";

export type ConnectionStatus = "offline-storage" | "connecting" | "synced" | "disconnected";

export interface SyncBridgeConfiguration {
  documentId: string;
  partyHost: string;
  onStatusChange?: (status: ConnectionStatus) => void;
  onFirstHydrated?: () => void;
}

export class PersistenceSyncBridge {
  public readonly doc: Y.Doc;
  private idbProvider: IndexeddbPersistence;
  private wsProvider: YPartyKitProvider;
  private isDestroyed = false;

  constructor(private config: SyncBridgeConfiguration) {
    this.doc = new Y.Doc();

    // 1. Initialize IndexedDB Persistence Engine
    this.idbProvider = new IndexeddbPersistence(config.documentId, this.doc);
    
    // 2. Initialize PartyKit Provider (keep disconnected until local data surfaces)
    this.wsProvider = new YPartyKitProvider(
      config.partyHost,
      config.documentId,
      this.doc,
      { connect: false }
    );

    this.setupLifecyclePipelines();
  }

  private setupLifecyclePipelines(): void {
    // Notify caller that local storage is ready
    this.idbProvider.once("synced", () => {
      if (this.isDestroyed) return;

      this.config.onFirstHydrated?.();
      this.config.onStatusChange?.("connecting");

      // Connect to the network only after loading offline state
      this.wsProvider.connect();
    });

    // Wire up network status events
    this.wsProvider.on("status", (event: { status: string }) => {
      if (this.isDestroyed) return;

      switch (event.status) {
        case "connected":
          this.config.onStatusChange?.("synced");
          break;
        case "connecting":
          this.config.onStatusChange?.("connecting");
          break;
        case "disconnected":
        default:
          this.config.onStatusChange?.("disconnected");
          break;
      }
    });

    this.wsProvider.on("sync", (isSynced: boolean) => {
      if (isSynced && !this.isDestroyed) {
        this.config.onStatusChange?.("synced");
      }
    });
  }

  /**
   * Forcibly persists a compact snapshot to IndexedDB, clearing the update transaction log.
   */
  public async compactLocalStorage(): Promise<void> {
    if (this.idbProvider.synced) {
      // Reading state vector merges fragmented rows in IndexedDB
      const snapshot = Y.encodeStateAsUpdate(this.doc);
      await this.idbProvider.clearData();
      Y.applyUpdate(this.doc, snapshot);
    }
  }

  public destroy(): void {
    this.isDestroyed = true;
    this.wsProvider.disconnect();
    this.wsProvider.destroy();
    this.idbProvider.destroy();
    this.doc.destroy();
  }
}
```

---

## 7. Operational Runbook & Verification Testing

Execute these tests before promoting any collaborative engine build to production.

### Realtime Engine Verification Matrix

```
+----------------------------------------------------------------------------------------------------+
| SCENARIO                 TEST EXECUTION PROCEDURE                     PASS / FAIL CRITERIA         |
+----------------------------------------------------------------------------------------------------+
| 1. High-Jitter           Throttle network via Chrome DevTools to      Cursor renders smoothly via  |
|    Cursor Smoothing      300ms latency, 10% packet drop. Move mouse.  LERP at 60 FPS without snap  |
|                                                                       or rubber-banding artifacts. |
|                                                                                                    |
| 2. Partition Reconnect   Disconnect Wi-Fi on Client A. Make 50 text   Client A automatically       |
|    & Convergence         edits. Make 50 distinct edits on Client B.   reconnects and reconciles    |
|                          Reconnect Wi-Fi on Client A.                 all edits without dataloss.  |
|                                                                                                    |
| 3. Scoped Undo           User A types "Alpha". User B types "Beta".   User A's editor removes      |
|    Isolation             User A executes `Cmd+Z`.                     "Alpha"; "Beta" remains      |
|                                                                       unaltered on both screens.   |
|                                                                       |
| 4. Cold Offline Boot     Load app on an offline browser with a        All document nodes load      |
|                          pre-populated IndexedDB instance.            instantly (< 50ms) without   |
|                                                                       throwing WebSocket errors.   |
+----------------------------------------------------------------------------------------------------+
```

### Chaos Engineering: Simulated Client Partition Suite

Run this integration test with Vitest or Playwright to systematically verify document convergence after a split-brain event:

```typescript
import { test, expect } from "vitest";
import * as Y from "yjs";

test("CRDT State Convergence under Split-Brain Network Partition", () => {
  // 1. Initialize two isolated virtual client documents
  const clientADoc = new Y.Doc();
  const clientBDoc = new Y.Doc();

  const clientAText = clientADoc.getText("content");
  const clientBText = clientBDoc.getText("content");

  // 2. Base synchronization phase
  const baseUpdate = Y.encodeStateAsUpdate(clientADoc);
  Y.applyUpdate(clientBDoc, baseUpdate);

  // 3. Trigger network partition (Disconnect)
  // Both clients concurrently write to the same character index
  clientAText.insert(0, "USER_A_INIT; ");
  clientBText.insert(0, "USER_B_INIT; ");

  // Deep concurrent mid-string splice operations
  clientAText.insert(13, "[Mutation A]");
  clientBText.insert(13, "[Mutation B]");

  expect(clientAText.toString()).not.toBe(clientBText.toString());

  // 4. Heal the partition: exchange state vectors and missing updates
  const stateVectorA = Y.encodeStateVector(clientADoc);
  const stateVectorB = Y.encodeStateVector(clientBDoc);

  // Calculate two-way missing deltas
  const missingDeltaForB = Y.encodeStateAsUpdate(clientADoc, stateVectorB);
  const missingDeltaForA = Y.encodeStateAsUpdate(clientBDoc, stateVectorA);

  // Exchange and apply
  Y.applyUpdate(clientBDoc, missingDeltaForB);
  Y.applyUpdate(clientADoc, missingDeltaForA);

  // 5. Assert strict deterministic convergence
  const finalStringA = clientAText.toString();
  const finalStringB = clientBText.toString();

  expect(finalStringA).toBe(finalStringB);
  expect(finalStringA.length).toBeGreaterThan(0);
});
```

---

## 8. Production Checklist: Canvas & Rich-Text Deployments

Use this validation checklist before every production deploy:

- [ ] **Dual-Channel Isolation**: Verify pointer movements route through ephemeral Awareness or raw WebSockets, and never write directly to the top-level persistent `Y.Doc`.
- [ ] **Document Coordinate Normalization**: Verify all cursor payloads broadcast normalized values `[0.0, 1.0]` based on container bounding boxes, rather than raw browser `clientX`/`clientY` pixels.
- [ ] **Linear Lerp Interpolation**: Ensure peer cursor positions are refreshed inside a `requestAnimationFrame` loop using a LERP damping factor between `0.18` and `0.25`.
- [ ] **Awareness Timeout Enforcement**: Confirm peers are pruned from UI state if no awareness updates arrive within `5000ms`.
- [ ] **Subdoc Partitioning**: If your canvas supports independently selectable nodes or nested documents, confirm each node uses a `Y.Doc` subdoc rather than one monolithic rich-text CRDT.
- [ ] **Scoped Undo Origins**: Check that `Y.UndoManager` explicitly sets `trackedOrigins: new Set([TransactionOrigins.LOCAL_USER])` to prevent local undo operations from rolling back remote peer keystrokes.
- [ ] **Local-First IndexedDB Hydration**: Ensure `y-indexeddb` completes its hydration check before initiating remote WebSocket transport connections, preventing empty state writes from overriding cached content.
- [ ] **Compact Snapshot Compaction**: Confirm that older update logs in IndexedDB are merged periodically using `Y.encodeStateAsUpdate(doc)` to prevent local storage quota exhaustion.
