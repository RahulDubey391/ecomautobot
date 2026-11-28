# Module 1: Realtime Systems Architecture & Conflict-Free Mental Models

To construct resilient, ultra-low latency collaborative systems, engineers must abandon the traditional client-server request-response paradigm. In a collaborative application—whether it is a Figma-style vector canvas, a multi-cursor code editor, or a live visual whiteboard—state exists simultaneously across distributed, volatile client runtimes and edge nodes. 

This module delivers the mathematical foundations, data-structure internals, network state machines, and edge topologies required to build fault-tolerant, conflict-free collaborative engines.

---

## 1. Foundations of Distributed State Convergence

Collaborative architectures fall into two primary paradigms: **Operational Transformation (OT)** and **Conflict-Free Replicated Data Types (CRDTs)**. While OT relies on a centralized coordinator to transform operation indices against concurrent operations, CRDTs achieve **Strong Eventual Consistency (SEC)** mathematically: if all nodes receive the same set of updates (regardless of order), they will compute identical local states without a central authority resolving conflicts.

### Mathematical Prerequisites for Convergence

A data structure qualifies as a join-semilattice (the core of state-based CRDTs) if it features a partial order ($\le$) and a merge operator ($\sqcup$) satisfying three algebraic invariants:

1. **Associativity**: $(a \sqcup b) \sqcup c = a \sqcup (b \sqcup c)$  
   *Network packets can be grouped and merged in arbitrary batches without altering the final state.*
2. **Commutativity**: $a \sqcup b = b \sqcup a$  
   *Packets can arrive out-of-order over asynchronous transport channels without divergence.*
3. **Idempotence**: $a \sqcup a = a$  
   *Duplicate packets resulting from network retries or overlapping syncing routines cause zero state corruption.*

### OT vs. CvRDT vs. CmRDT vs. Yjs Hybrid Model

| Dimension | Operational Transformation (OT) | State-based CRDT (CvRDT) | Operation-based CRDT (CmRDT) | Yjs Hybrid (YATA / StructStore) |
| :--- | :--- | :--- | :--- | :--- |
| **Primary Convergence Mechanism** | Centralized transformation functions rewrite array indices based on logical timestamps. | Monotonic join operation over full state or state deltas using semilattices. | Messaging middleware with Causal Delivery guarantees executes commutative operations. | Append-only doubly-linked items indexed in a contiguous linear memory array (`StructStore`). |
| **Network Wire Overhead** | **Extremely Low**: Payloads contain single-character operations and integer positions (e.g., `Retain(5), Insert("a")`). | **Extremely High**: Re-transmits the complete state or large delta payloads on every write. | **Low**: Broadcasts discrete operations; requires exact, causal delivery (often via vector clocks). | **Ultra-Low**: State vectors exchange missing sequence ranges; updates are packed via run-length binary encoding (`lib0`). |
| **Server Requirement** | Centralized, stateful single-threaded sequence authority required to define global execution order. | Completely decentralized, peer-to-peer or star topology; merges are naturally associative and commutative. | Decentralized or edge-brokered; requires causal messaging infrastructure (e.g., reliable broadcast). | Flexible: Decentralized P2P (WebRTC), Client-Server (WebSockets), or Distributed Serverless Edge (PartyKit / Cloudflare DO). |
| **Tombstone Overhead** | Zero tombstones; deleted elements are removed from array memory immediately. | High; deleted items remain as tombstones to prevent resurrecting deleted nodes during state merges. | Moderate; requires tracking deleted identifiers unless causal garbage collection is applied. | Optimized; adjacent deleted items are compacted into single tombstone structs containing sequence length ranges. |
| **Computational Complexity** | $\mathcal{O}(N \times M)$ where $N, M$ are concurrent operations requiring mutual transformation. | $\mathcal{O}(S)$ where $S$ is state size during full lattice merge. | $\mathcal{O}(1)$ local apply time, but requires buffer management for causally delayed updates. | $\mathcal{O}(\log M)$ lookup via binary search over client clock arrays, near $\mathcal{O}(1)$ amortized local insertion. |

---

## 2. Inside Yjs: The Mechanics of `lib0` and `StructStore`

Yjs implements the **YATA** (Yet Another Transformation Approach) algorithm, functioning not as a pure state-based or pure operation-based CRDT, but as a sequence-based structural CRDT optimized around contiguous memory blocks.

### The StructStore Memory Model

At the core of a `Y.Doc` is the `StructStore`. The `StructStore` maintains a dictionary mapping unique `client` identifiers (64-bit unsigned integers) to an array of items (`Item[]`), ordered strictly by their logical timestamp (`clock`).

```
Y.Doc
 └── StructStore
      ├── clients: Map<ClientID, Item[]>
      │    ├── Client 1024: [ Item(0..2), Item(3..7), Item(8..8) ]
      │    └── Client 2048: [ Item(0..0), Item(1..5) ]
      └── ds: DeleteSet (Garbage Collector tracking unmapped clocks)
```

#### Anatomical Breakdown of an `Item`

Every insert operation creates an `Item`. An `Item` contains:
- **`id` (`ID`)**: Composed of `client` (uint) and `clock` (uint). If an item represents the string `"world"`, it occupies 5 clock ticks: `id.clock` through `id.clock + 4`.
- **`left` / `right` (`Item | null`)**: Direct pointers forming a doubly linked list representing the intended display order at the moment of insertion.
- **`origin` / `rightOrigin` (`ID | null`)**: The immutable IDs of the neighbors flanking this item at creation. These fields break concurrent insert ties deterministically without reordering existing text.
- **`content` (`Content`)**: The payload (`ContentString`, `ContentEmbed`, `ContentFormat`, `ContentDeleted`, or `ContentJSON`).
- **`info` (bitfield byte)**: Stores metadata including whether the item is deleted, whether its left/right pointers are mapped, and whether it can merge with adjacent items.

```
+----------------------------------------------------------------------------------------+
|                                     Yjs Item                                           |
+--------------------+-------------------+-----------------------+-----------------------+
| id: {1024, 5}      | len: 4 ("data")   | origin: {1024, 4}     | rightOrigin: {2048, 1}|
+--------------------+-------------------+-----------------------+-----------------------+
| left: -> [Item]    | right: -> [Item]  | parent: -> [Y.Text]   | info: 0b00000100      |
+--------------------+-------------------+-----------------------+-----------------------+
```

When an item is deleted, Yjs does not delete the `Item` object from memory. Doing so would sever the doubly-linked list and corrupt causality proofs for future concurrent operations. Instead, Yjs sets the item's content to `ContentDeleted` (or sets a bit in `info`), increments the deletion counters, and registers the sequence range within the **DeleteSet (`ds`)**.

### State Vectors, Updates, and Diff Calculations

Yjs eliminates redundant network bandwidth via **State Vectors**. A State Vector represents the compact summary of all updates a given client has integrated.

$$\text{StateVector} = \{ \text{ClientID}_1: \text{Clock}_1, \ \text{ClientID}_2: \text{Clock}_2, \ \dots, \ \text{ClientID}_n: \text{Clock}_n \}$$

When two nodes sync:
1. **Node A** transmits its `StateVector` to **Node B** (Sync Step 1).
2. **Node B** reads Node A's `StateVector`, queries its own `StructStore`, and extracts all `Item` sequences with $\text{clock} > \text{StateVector}[\text{ClientID}]$.
3. **Node B** encodes these missing items along with its local `DeleteSet` into a binary blob using the `lib0` framework and transmits it to Node A (Sync Step 2).
4. **Node A** applies the binary blob directly into its `StructStore`. Convergence is reached in exactly $1$ round-trip ($1.5$ RTT for bidirectional sync).

### lib0 Variable-Length Encoding

Yjs writes to network sockets via the `lib0/encoding` library, which enforces aggressive binary compression:
- **VarUint / VarInt**: Unsigned integers are serialized 7 bits per byte. The 8th bit indicates if another byte follows. A client ID like `5` consumes 1 byte instead of 8 bytes.
- **Run-Length Encoding (RLE)**: Repeated client IDs, consecutive clocks, and sequential deletes are compressed into `[client, start_clock, length]` tuples.
- **String Table Compression**: Duplicate property keys in map structures are mapped to an integer dictionary within the payload header.

---

## 3. Edge Persistence Topologies & Room Lifecycles

In modern edge environments (PartyKit, Cloudflare Durable Objects, Fastly Compute), state must transition cleanly between ultra-fast volatile memory and durable long-term storage.

### The Three-Tier Storage Topology

```
+-------------------------------------------------------------------------------+
| Tier 1: Volatile Memory (Edge Worker / PartyKit Core)                         |
| - Y.Doc resides fully in-memory as native V8 objects.                         |
| - Microsecond reads/writes; mutations handled via pure pointer modifications.|
+---------------------------------------+---------------------------------------+
                                        |
                   Debounced WAL Flush  | Flush on 100 updates OR 2000ms
                                        v
+-------------------------------------------------------------------------------+
| Tier 2: Transactional Write-Ahead Log (WAL) (Edge KV / SQLite / DO Storage)    |
| - High-throughput append-only table: `room_updates(id, room, update_blob)`    |
| - Un-compacted, monotonic log of lib0-encoded byte arrays.                    |
+---------------------------------------+---------------------------------------+
                                        |
                 Compaction Worker Hook | Every 500 updates OR Room Idle
                                        v
+-------------------------------------------------------------------------------+
| Tier 3: Cold Durable Snapshot Store (S3 / R2 / GCS)                          |
| - Monolithic compacted Yjs snapshot (`Y.encodeStateAsUpdate(ydoc)`).          |
| - Truncates Tier 2 WAL completely; serves as cold boot payload.               |
+-------------------------------------------------------------------------------+
```

### Snapshot Compaction Lifecycle

```
[ Room Wakeup ] 
       │
       ▼
Read Tier 3 Snapshot from S3/R2 ──► Y.applyUpdate(doc, s3Snapshot)
       │
       ▼
Query Tier 2 WAL (WHERE id > snapshot_seq) ──► Loop: Y.applyUpdate(doc, row.blob)
       │
       ▼
[ Room Ready: Accept WebSocket Connections ]
       │
       ├─► Client Update ──► Apply to Memory ──► Write to Tier 2 WAL (Batch)
       │
       ▼
[ Compaction Threshold Met (e.g., 500 Updates) ]
       │
       ├─► 1. Acquire Distributed Mutex (prevent concurrent compaction)
       ├─► 2. snapshotBytes = Y.encodeStateAsUpdate(doc)
       ├─► 3. Atomic PUT to Tier 3 (S3/R2)
       ├─► 4. DELETE FROM Tier 2 WAL WHERE seq <= compacted_seq
       └─► 5. Release Mutex
```

---

## 4. Production Engine: Resilient Client WebSocket State Machine

This client-side connection manager uses an explicit Finite State Machine (FSM). It handles exponential backoff with full jitter, binary frame serialization, and an offline mutation queue that flushes upon reconnection.

```
       ┌────────────────────────┐
       │      DISCONNECTED      │◄─────────────────────────────┐
       └───────────┬────────────┘                              │
                   │ connect()                                 │
                   ▼                                           │
       ┌────────────────────────┐                              │
       │       CONNECTING       │                              │
       └───────────┬────────────┘                              │
                   │ onopen                                    │
                   ▼                                           │
       ┌────────────────────────┐      Heartbeat Timeout       │
       │       CONNECTED        ├──────────────────────────────┤
       └───────────┬────────────┘      (or unrecoverable err)  │
                   │ sync_complete                             │
                   ▼                                           │
       ┌────────────────────────┐                              │
       │         SYNCED         ├──────────────────────────────┘
       └────────────────────────┘
```

Save this implementation as `ConnectionStateMachine.ts`:

```typescript
import * as Y from "yjs";
import * as syncProtocol from "y-protocols/sync";
import * as awarenessProtocol from "y-protocols/awareness";
import * as encoding from "lib0/encoding";
import * as decoding from "lib0/decoding";

export type ConnectionState = "DISCONNECTED" | "CONNECTING" | "CONNECTED" | "SYNCED";

export interface EngineConfig {
  url: string;
  room: string;
  doc: Y.Doc;
  awareness: awarenessProtocol.Awareness;
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  heartbeatIntervalMs?: number;
  heartbeatTimeoutMs?: number;
}

const MESSAGE_SYNC = 0;
const MESSAGE_AWARENESS = 1;
const MESSAGE_HEARTBEAT = 2;

export class ResilientConnectionEngine {
  private ws: WebSocket | null = null;
  private state: ConnectionState = "DISCONNECTED";
  private backoffAttempts = 0;
  private readonly baseBackoffMs: number;
  private readonly maxBackoffMs: number;
  private readonly heartbeatIntervalMs: number;
  private readonly heartbeatTimeoutMs: number;
  private heartbeatIntervalTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
  private offlineBuffer: Uint8Array[] = [];
  private isExplicitlyClosed = false;

  constructor(private readonly config: EngineConfig) {
    this.baseBackoffMs = config.baseBackoffMs ?? 1000;
    this.maxBackoffMs = config.maxBackoffMs ?? 30000;
    this.heartbeatIntervalMs = config.heartbeatIntervalMs ?? 15000;
    this.heartbeatTimeoutMs = config.heartbeatTimeoutMs ?? 5000;

    // Hook local doc updates
    this.config.doc.on("update", this.handleLocalDocUpdate);
    this.config.awareness.on("update", this.handleLocalAwarenessUpdate);
  }

  public connect(): void {
    if (this.state === "CONNECTED" || this.state === "SYNCED" || this.state === "CONNECTING") {
      return;
    }

    this.isExplicitlyClosed = false;
    this.transitionTo("CONNECTING");

    const endpoint = `${this.config.url}/${encodeURIComponent(this.config.room)}`;
    this.ws = new WebSocket(endpoint);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = this.handleOpen;
    this.ws.onmessage = this.handleMessage;
    this.ws.onerror = this.handleError;
    this.ws.onclose = this.handleClose;
  }

  public disconnect(): void {
    this.isExplicitlyClosed = true;
    this.cleanupTimers();
    if (this.ws) {
      this.ws.close(1000, "Normal Closure");
      this.ws = null;
    }
    this.transitionTo("DISCONNECTED");
  }

  public getState(): ConnectionState {
    return this.state;
  }

  private handleOpen = (): void => {
    this.backoffAttempts = 0;
    this.transitionTo("CONNECTED");
    this.startHeartbeat();

    // 1. Send Sync Step 1: advertise what we know via our State Vector
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, MESSAGE_SYNC);
    syncProtocol.writeSyncStep1(encoder, this.config.doc);
    this.sendRaw(encoding.toUint8Array(encoder));

    // 2. Broadcast local Awareness
    const awarenessStates = this.config.awareness.getStates();
    if (awarenessStates.size > 0) {
      const awarenessEncoder = encoding.createEncoder();
      encoding.writeVarUint(awarenessEncoder, MESSAGE_AWARENESS);
      encoding.writeVarUint8Array(
        awarenessEncoder,
        awarenessProtocol.encodeAwarenessUpdate(
          this.config.awareness,
          Array.from(awarenessStates.keys())
        )
      );
      this.sendRaw(encoding.toUint8Array(awarenessEncoder));
    }

    // 3. Flush updates that accumulated while offline
    while (this.offlineBuffer.length > 0) {
      const pending = this.offlineBuffer.shift();
      if (pending) {
        this.sendRaw(pending);
      }
    }
  };

  private handleMessage = (event: MessageEvent): void => {
    if (!(event.data instanceof ArrayBuffer)) {
      return;
    }

    const payload = new Uint8Array(event.data);
    const decoder = decoding.createDecoder(payload);
    const messageType = decoding.readVarUint(decoder);

    switch (messageType) {
      case MESSAGE_SYNC: {
        const syncEncoder = encoding.createEncoder();
        encoding.writeVarUint(syncEncoder, MESSAGE_SYNC);
        
        // syncProtocol handles Step 1, Step 2, and update parsing
        const syncMessageType = syncProtocol.readSyncMessage(
          decoder,
          syncEncoder,
          this.config.doc,
          this
        );

        // If the reply contains bytes, send it back immediately
        if (encoding.length(syncEncoder) > 1) {
          this.sendRaw(encoding.toUint8Array(syncEncoder));
        }

        // If we completed Step 2 (received our missing data), we are fully synced
        if (syncMessageType === syncProtocol.messageYjsSyncStep2 && this.state !== "SYNCED") {
          this.transitionTo("SYNCED");
        }
        break;
      }

      case MESSAGE_AWARENESS: {
        const update = decoding.readVarUint8Array(decoder);
        awarenessProtocol.applyAwarenessUpdate(this.config.awareness, update, this);
        break;
      }

      case MESSAGE_HEARTBEAT: {
        // Pong received; cancel timeout disconnect
        if (this.heartbeatTimeoutTimer) {
          clearTimeout(this.heartbeatTimeoutTimer);
          this.heartbeatTimeoutTimer = null;
        }
        break;
      }

      default:
        console.warn(`[YjsEngine] Unknown protocol message type: ${messageType}`);
    }
  };

  private handleError = (err: Event): void => {
    console.error("[YjsEngine] WebSocket emitted an error:", err);
    // Let onclose handle reconnect logic
  };

  private handleClose = (event: CloseEvent): void => {
    this.cleanupTimers();
    this.ws = null;
    this.transitionTo("DISCONNECTED");

    if (!this.isExplicitlyClosed) {
      this.scheduleReconnect();
    }
  };

  private scheduleReconnect(): void {
    this.backoffAttempts++;
    
    // Exponential Backoff with Decorrelated Jitter:
    // sleep = min(maxBackoff, baseBackoff * 2 ^ attempt) * random(0.8, 1.2)
    const exponential = Math.min(
      this.maxBackoffMs,
      this.baseBackoffMs * Math.pow(2, this.backoffAttempts)
    );
    const jitter = 0.8 + Math.random() * 0.4;
    const delay = Math.floor(exponential * jitter);

    console.info(`[YjsEngine] Reconnecting in ${delay}ms (attempt ${this.backoffAttempts})`);
    setTimeout(() => this.connect(), delay);
  }

  private startHeartbeat(): void {
    this.cleanupTimers();
    this.heartbeatIntervalTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        const encoder = encoding.createEncoder();
        encoding.writeVarUint(encoder, MESSAGE_HEARTBEAT);
        this.sendRaw(encoding.toUint8Array(encoder));

        // Start dead-man switch timer: fail if pong not returned within heartbeatTimeoutMs
        this.heartbeatTimeoutTimer = setTimeout(() => {
          console.warn("[YjsEngine] Heartbeat timeout. Severing stalled socket.");
          if (this.ws) {
            this.ws.close(4000, "Heartbeat Timeout");
          }
        }, this.heartbeatTimeoutMs);
      }
    }, this.heartbeatIntervalMs);
  }

  private cleanupTimers(): void {
    if (this.heartbeatIntervalTimer) {
      clearInterval(this.heartbeatIntervalTimer);
      this.heartbeatIntervalTimer = null;
    }
    if (this.heartbeatTimeoutTimer) {
      clearTimeout(this.heartbeatTimeoutTimer);
      this.heartbeatTimeoutTimer = null;
    }
  }

  private handleLocalDocUpdate = (update: Uint8Array, origin: unknown): void => {
    // Suppress loops: do not broadcast back updates originating from this engine instance
    if (origin === this) {
      return;
    }

    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, MESSAGE_SYNC);
    syncProtocol.writeUpdate(encoder, update);
    const serialized = encoding.toUint8Array(encoder);

    if (this.state === "SYNCED" || this.state === "CONNECTED") {
      this.sendRaw(serialized);
    } else {
      this.offlineBuffer.push(serialized);
    }
  };

  private handleLocalAwarenessUpdate = (
    { added, updated, removed }: { added: number[]; updated: number[]; removed: number[] },
    origin: unknown
  ): void => {
    if (origin === this) {
      return;
    }

    const changedClients = added.concat(updated, removed);
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, MESSAGE_AWARENESS);
    encoding.writeVarUint8Array(
      encoder,
      awarenessProtocol.encodeAwarenessUpdate(this.config.awareness, changedClients)
    );
    this.sendRaw(encoding.toUint8Array(encoder));
  };

  private sendRaw(data: Uint8Array): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    }
  }

  private transitionTo(newState: ConnectionState): void {
    const oldState = this.state;
    this.state = newState;
    if (oldState !== newState) {
      console.info(`[YjsEngine] State: ${oldState} -> ${newState}`);
    }
  }

  public destroy(): void {
    this.config.doc.off("update", this.handleLocalDocUpdate);
    this.config.awareness.off("update", this.handleLocalAwarenessUpdate);
    this.disconnect();
    this.offlineBuffer = [];
  }
}
```

---

## 5. Production Engine: Edge Room Coordinator

Below is the complete server-side PartyKit / Edge Worker class. It coordinates the room lifecycle: hydrating state from snapshot and transactional logs on cold boot, processing binary updates, broadcasting awareness, debouncing disk writes, and running garbage collection during teardown.

Save this implementation as `RoomCoordinator.ts`:

```typescript
import type * as Party from "partykit/server";
import * as Y from "yjs";
import * as syncProtocol from "y-protocols/sync";
import * as awarenessProtocol from "y-protocols/awareness";
import * as encoding from "lib0/encoding";
import * as decoding from "lib0/decoding";

const MESSAGE_SYNC = 0;
const MESSAGE_AWARENESS = 1;
const MESSAGE_HEARTBEAT = 2;

export interface StorageDriver {
  fetchLatestSnapshot(roomId: string): Promise<Uint8Array | null>;
  saveSnapshot(roomId: string, data: Uint8Array): Promise<void>;
  appendLogEntry(roomId: string, update: Uint8Array): Promise<void>;
  drainLogEntries(roomId: string): Promise<Uint8Array[]>;
}

export default class RoomCoordinator implements Party.Server {
  private doc: Y.Doc = new Y.Doc();
  private awareness: awarenessProtocol.Awareness = new awarenessProtocol.Awareness(this.doc);
  private isHydrated = false;
  private pendingUpdatesCount = 0;
  private flushDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(readonly room: Party.Room) {}

  /**
   * Cold-boot initialization: runs once per worker instance lifecycle.
   */
  async onStart(): Promise<void> {
    await this.hydrateRoom();

    // Hook internal doc events to manage local mutations and persistence accounting
    this.doc.on("update", (update: Uint8Array, origin: unknown) => {
      // Avoid tracking updates sourced directly from storage hydration
      if (origin === "storage-hydration") return;

      this.pendingUpdatesCount++;
      this.scheduleStorageFlush();
    });

    this.awareness.on("update", ({ added, updated, removed }, origin) => {
      if (origin === "local") return;
      const changed = added.concat(updated, removed);
      const encoder = encoding.createEncoder();
      encoding.writeVarUint(encoder, MESSAGE_AWARENESS);
      encoding.writeVarUint8Array(
        encoder,
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, changed)
      );
      this.room.broadcast(encoding.toUint8Array(encoder));
    });
  }

  /**
   * Handles incoming WebSocket connection upgrades.
   */
  async onConnect(conn: Party.Connection, ctx: Party.ConnectionContext): Promise<void> {
    // Block connections until state hydration completes
    if (!this.isHydrated) {
      await this.hydrateRoom();
    }

    // Handshake: Send Step 1 to new client to query what it needs
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, MESSAGE_SYNC);
    syncProtocol.writeSyncStep1(encoder, this.doc);
    conn.send(encoding.toUint8Array(encoder));

    // Send the current room awareness state
    const awarenessStates = this.awareness.getStates();
    if (awarenessStates.size > 0) {
      const awarenessEncoder = encoding.createEncoder();
      encoding.writeVarUint(awarenessEncoder, MESSAGE_AWARENESS);
      encoding.writeVarUint8Array(
        awarenessEncoder,
        awarenessProtocol.encodeAwarenessUpdate(
          this.awareness,
          Array.from(awarenessStates.keys())
        )
      );
      conn.send(encoding.toUint8Array(awarenessEncoder));
    }
  }

  /**
   * Demuxes binary protocol messages received from clients.
   */
  onMessage(message: string | ArrayBuffer, sender: Party.Connection): void {
    if (typeof message === "string") {
      // In strict binary protocols, ignore plain text payloads
      return;
    }

    const payload = new Uint8Array(message);
    const decoder = decoding.createDecoder(payload);
    const messageType = decoding.readVarUint(decoder);

    switch (messageType) {
      case MESSAGE_SYNC: {
        const replyEncoder = encoding.createEncoder();
        encoding.writeVarUint(replyEncoder, MESSAGE_SYNC);

        // Apply client update / process Step 1 or Step 2
        syncProtocol.readSyncMessage(decoder, replyEncoder, this.doc, sender);

        // If the syncProtocol output contains payload bytes, reply directly to sender
        if (encoding.length(replyEncoder) > 1) {
          sender.send(encoding.toUint8Array(replyEncoder));
        }

        // Broadcast raw updates to all other peers in the room
        this.room.broadcast(payload, [sender.id]);
        break;
      }

      case MESSAGE_AWARENESS: {
        const update = decoding.readVarUint8Array(decoder);
        awarenessProtocol.applyAwarenessUpdate(this.awareness, update, sender);
        // Echo to all connections except sender
        this.room.broadcast(payload, [sender.id]);
        break;
      }

      case MESSAGE_HEARTBEAT: {
        // Echo heartbeat ping directly back to client as heartbeat pong
        const echoEncoder = encoding.createEncoder();
        encoding.writeVarUint(echoEncoder, MESSAGE_HEARTBEAT);
        sender.send(encoding.toUint8Array(echoEncoder));
        break;
      }

      default:
        console.warn(`[RoomCoordinator] Unknown message type: ${messageType}`);
    }
  }

  /**
   * Cleanup awareness when clients disconnect.
   */
  onClose(connection: Party.Connection): void {
    awarenessProtocol.removeAwarenessStates(
      this.awareness,
      [parseInt(connection.id, 10)],
      "connection-closed"
    );
  }

  /**
   * Cold Hydration pipeline: Snapshots + Write-Ahead Log playback.
   */
  private async hydrateRoom(): Promise<void> {
    if (this.isHydrated) return;

    try {
      // Read binary snapshot from Edge Key-Value Durable Storage
      const snapshot = await this.room.storage.get<Uint8Array>("base_snapshot");
      if (snapshot) {
        Y.applyUpdate(this.doc, snapshot, "storage-hydration");
      }

      // Replay all un-compacted WAL entries
      const walEntries = (await this.room.storage.get<Uint8Array[]>("wal_log")) ?? [];
      for (const entry of walEntries) {
        Y.applyUpdate(this.doc, entry, "storage-hydration");
      }

      this.isHydrated = true;
      console.info(`[RoomCoordinator] Room ${this.room.id} hydrated successfully.`);
    } catch (err) {
      console.error(`[RoomCoordinator] Critical failure hydrating room ${this.room.id}:`, err);
      throw err;
    }
  }

  /**
   * Batched/Debounced Flush to Durable Storage.
   */
  private scheduleStorageFlush(): void {
    if (this.flushDebounceTimer) return;

    this.flushDebounceTimer = setTimeout(async () => {
      this.flushDebounceTimer = null;
      await this.persistState();
    }, 2000); // Debounce interval: 2 seconds
  }

  /**
   * Performs Snapshot Compaction or WAL appends.
   */
  private async persistState(): Promise<void> {
    // If pending updates exceed the compaction threshold, compress to a monolithic snapshot
    if (this.pendingUpdatesCount >= 200) {
      const compactedBytes = Y.encodeStateAsUpdate(this.doc);
      await this.room.storage.put("base_snapshot", compactedBytes);
      await this.room.storage.delete("wal_log");
      this.pendingUpdatesCount = 0;
      console.info(`[RoomCoordinator] Compacted room ${this.room.id} into monolithic snapshot.`);
    } else {
      // Otherwise, save the full document state to storage
      const snapshotBytes = Y.encodeStateAsUpdate(this.doc);
      await this.room.storage.put("base_snapshot", snapshotBytes);
      this.pendingUpdatesCount = 0;
