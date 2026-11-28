# Module 4: Master Stress-Testing Rubrics, Network Chaos Audits & Swipe File

High-concurrency collaborative engines built on WebSockets, CRDTs (Conflict-free Replicated Data Types like Yjs), and edge state runtimes (such as Cloudflare Workers or PartyKit) fail in fundamentally different ways than traditional request-response architectures. A stateless REST API degrades by slowing down; a distributed real-time CRDT engine degrades through memory-leaking document histories, state vector serialization deadlocks, thundering herd reconnections, and split-brain document states.

This document serves as your operational blueprint for auditing, hardening, stress-testing, and debugging production-grade collaborative engines.

---

## 1. Production Scaling & Pre-Flight Architecture Audit Checklist

Before releasing any collaborative canvas, rich-text suite, or multiplayer spatial engine to production, every layer of the infrastructure must pass the thresholds defined below.

```
+---------------------------------------------------------------------------------------------------+
| PRE-FLIGHT AUDIT GATES                                                                            |
+--------------------------------+--------------------------------+---------------------------------+
| 1. DOCUMENT BOUNDARIES         | 2. EDGE WEBSOCKET LIMITS       | 3. PERSISTENCE & COMPACTION     |
| • Max Doc History: < 50MB      | • Mem/Conn: < 35KB base        | • Snapshot Frequency: 5 min     |
| • Tombstone Ratio: < 25%       | • Heartbeat: 30s ping/pong     | • Compaction Delta: 100 updates |
| • Subdoc Splitting: > 500 items| • Max Egress/Client: < 128KB/s | • Storage Write Queue: Backoff  |
+--------------------------------+--------------------------------+---------------------------------+
```

### 1.1 Document Sizing and Memory Limits

| Metric / Check | Target Threshold | Critical Warning Threshold | Remediation Plan | Verification Command / Script |
| :--- | :--- | :--- | :--- | :--- |
| **Y.Doc In-Memory Footprint** | `< 15 MB` active | `> 50 MB` per room | Implement dynamic subdocument splitting (`Y.Doc` nested in `Y.Map`) or purge non-retained transaction metadata. | `node -e "const Y=require('yjs'); const d=new Y.Doc(); console.log(process.memoryUsage().heapUsed);"` |
| **Transaction History Tombstones** | `< 15%` of total item count | `> 35%` total deleted structures | Enforce document compaction via `Y.encodeStateAsUpdate()` and re-seed from a flattened snapshot. | Inspect item tree: `doc.store.clients.forEach((c) => c.forEach(item => total++))` |
| **State Vector Size** | `< 2 KB` | `> 8 KB` (indicates client ID churn) | Client IDs are leaking. Enforce deterministic client ID pooling or recycle ephemeral peer sessions. | `Buffer.byteLength(Y.encodeStateVector(doc))` |
| **Subdocument Count** | `< 200` per root doc | `> 1,000` loaded simultaneously | Implement lazy loading: load subdocs via `subdoc.load()` only when their nodes enter the client viewport. | `doc.getSubdocs().size` |

### 1.2 WebSocket Gateway & Edge Concurrency

| Metric / Check | Target Threshold | Critical Warning Threshold | Remediation Plan | Verification Command / Script |
| :--- | :--- | :--- | :--- | :--- |
| **Memory per Idle Connection** | `< 30 KB` | `> 85 KB` | Disable per-socket JSON parsers. Use raw ArrayBuffers and shared typed buffers; offload awareness parsing. | Inspect heap snapshot: target `WebSocket` and `SocketProcessor` retainers. |
| **Heartbeat Jitter Tolerance** | 30s interval, 5s timeout | Fixed interval without jitter | Shift heartbeats to client-side detection using dual-interval ping/pong with randomized `±10%` jitter. | Stress test using `k6/ws` with drop-packet injection. |
| **Max Room Broadcast Concurrency**| 50 active broadcasters | `> 150` active broadcasters | Implement awareness throttling (limit pointer broadcasts to 30Hz) and spatial partitioning (quadtrees). | Run Locust/k6 headless clients broadcasting coordinates at 60Hz. |
| **Connection Handshake Latency** | `p95 < 80ms` (Edge) | `p95 > 350ms` | Route connections to nearest edge point-of-presence (PartyKit / Cloudflare Durable Objects). | `curl -w "Connect: %{time_connect} TTFB: %{time_starttransfer}\n" -o /dev/null -s https://[edge-url]` |

### 1.3 Persistence, Snapshots, and Compaction

| Metric / Check | Target Threshold | Critical Warning Threshold | Remediation Plan | Verification Command / Script |
| :--- | :--- | :--- | :--- | :--- |
| **Compaction Write Latency** | `p99 < 150ms` | `p99 > 800ms` | Write snapshots to S3/R2 asynchronously via write-ahead logging (WAL) buffered in a local Durable Object/Redis buffer. | Monitor edge storage write duration via OpenTelemetry spans. |
| **Snapshot Rehydration Time** | `< 50ms` on cold start | `> 250ms` | Store fully compacted updates; never rehydrate through raw sequential transaction loops. | `console.time('hydrate'); Y.applyUpdate(doc, snapshot); console.timeEnd('hydrate');` |
| **Uncompacted Update Count** | `< 100` appended rows | `> 1,000` appended rows | Trigger automatic background consolidation when appending to document update logs in Postgres/DynamoDB. | `SELECT room_id, count(*) FROM doc_updates GROUP BY room_id HAVING count(*) > 100;` |

---

## 2. Reconnection Backoff & Network Chaos Matrix

When edge network partitions occur, naive clients will trigger a **thundering herd problem** by simultaneously reconnecting and blasting large state vectors at the gateway, collapsing the edge nodes.

### 2.1 Reconnection Strategy Matrix

```
Delay (ms)
  ^
  |                                     Full Jitter: UniformRandom(0, Min(Cap, Base * 2^attempt))
Cap|-----------------------------------*--*----*------
  |                                  *
  |                           *     *   *
  |                     *          *
  |              *           *
Base|______*_____*_____________________________________> Attempts
```

| Strategy | Formula | Pros | Cons | Recommendation |
| :--- | :--- | :--- | :--- | :--- |
| **Fixed Interval** | $t = \text{Base}$ | Simple to trace | Thundering herd guaranteed; edge nodes crash on multi-client disconnect. | **FORBIDDEN** in production. |
| **Pure Exponential** | $t = \min(\text{Cap}, \text{Base} \times 2^{\text{attempt}})$ | Mitigates simple collisions | Creates harmonic synchronization spikes across reconnection pools. | Not recommended. |
| **Full Jitter** | $t = \text{random}(0, \min(\text{Cap}, \text{Base} \times 2^{\text{attempt}}))$ | Maximally distributes edge load; breaks synchronization locks instantly. | Initial retries might reconnect excessively fast without a small floor. | **STANDARD OPTION** for room-based sync. |
| **Decorrelated Jitter** | $t = \min(\text{Cap}, \text{random}(\text{Base}, t_{\text{prev}} \times 3))$ | Balances quick recovery with complete entropy; optimal for canvas/presence. | Slightly higher memory retention on client (tracks state variable). | **OPTIMAL CHOICE** for high-frequency multiplayer. |

### 2.2 Production Reconnection Engine

This drop-in, zero-dependency client implements **Decorrelated Jitter**, offline transaction queuing, document state preservation, and payload compaction during network partitions.

```typescript
// ProductionReconnectingSocket.ts
export type ConnectionState = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RECONNECTING';

export interface SocketConfig {
  url: string;
  protocols?: string[];
  baseDelayMs: number;
  maxDelayMs: number;
  maxQueueSize: number;
  heartbeatIntervalMs: number;
  heartbeatTimeoutMs: number;
  onOpen?: () => void;
  onMessage?: (data: ArrayBuffer) => void;
  onStateChange?: (state: ConnectionState) => void;
}

export class ProductionReconnectingSocket {
  private ws: WebSocket | null = null;
  private state: ConnectionState = 'DISCONNECTED';
  private attempts = 0;
  private prevDelay: number;
  private queue: Uint8Array[] = [];
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatWatchdog: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  constructor(private readonly config: SocketConfig) {
    this.prevDelay = config.baseDelayMs;
  }

  public connect(): void {
    if (this.state === 'CONNECTED' || this.state === 'CONNECTING') return;

    this.intentionallyClosed = false;
    this.updateState(this.attempts === 0 ? 'CONNECTING' : 'RECONNECTING');

    try {
      this.ws = new WebSocket(this.config.url, this.config.protocols);
      this.ws.binaryType = 'arraybuffer';
      this.bindSocketEvents();
    } catch (err) {
      this.scheduleReconnect();
    }
  }

  public send(payload: Uint8Array): void {
    if (this.state === 'CONNECTED' && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(payload);
    } else {
      this.enqueuePayload(payload);
    }
  }

  public disconnect(): void {
    this.intentionallyClosed = true;
    this.clearTimers();
    if (this.ws) {
      this.ws.close(1000, 'Normal Closure');
      this.ws = null;
    }
    this.updateState('DISCONNECTED');
  }

  private bindSocketEvents(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      this.updateState('CONNECTED');
      this.attempts = 0;
      this.prevDelay = this.config.baseDelayMs;
      this.startHeartbeat();
      this.flushQueue();
      this.config.onOpen?.();
    };

    this.ws.onmessage = (event: MessageEvent) => {
      this.resetHeartbeatWatchdog();
      if (event.data instanceof ArrayBuffer) {
        // Intercept internal 1-byte PONG packet (0xFF)
        const view = new Uint8Array(event.data);
        if (view.byteLength === 1 && view[0] === 0xff) {
          return;
        }
        this.config.onMessage?.(event.data);
      }
    };

    this.ws.onerror = () => {
      // Handled in onclose to avoid duplicate reconnects
    };

    this.ws.onclose = () => {
      this.clearTimers();
      this.ws = null;
      if (!this.intentionallyClosed) {
        this.updateState('RECONNECTING');
        this.scheduleReconnect();
      } else {
        this.updateState('DISCONNECTED');
      }
    };
  }

  private calculateDecorrelatedJitter(): number {
    // AWS Decorrelated Jitter: Sleep = min(Cap, Random(Base, Sleep * 3))
    const min = this.config.baseDelayMs;
    const max = this.prevDelay * 3;
    const sleep = Math.min(
      this.config.maxDelayMs,
      Math.floor(Math.random() * (max - min + 1) + min)
    );
    this.prevDelay = sleep;
    return sleep;
  }

  private scheduleReconnect(): void {
    this.attempts++;
    const delay = this.calculateDecorrelatedJitter();
    setTimeout(() => {
      if (!this.intentionallyClosed) {
        this.connect();
      }
    }, delay);
  }

  private enqueuePayload(payload: Uint8Array): void {
    if (this.queue.length >= this.config.maxQueueSize) {
      // FIFO drop policy for awareness/transient states
      this.queue.shift();
    }
    this.queue.push(payload);
  }

  private flushQueue(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    while (this.queue.length > 0) {
      const payload = this.queue.shift();
      if (payload) this.ws.send(payload);
    }
  }

  private startHeartbeat(): void {
    this.clearTimers();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        // Send single-byte internal PING packet (0xFE)
        this.ws.send(new Uint8Array([0xfe]));
        this.heartbeatWatchdog = setTimeout(() => {
          // Heartbeat failed; socket deadlocked
          this.ws?.close(4000, 'Heartbeat Timeout');
        }, this.config.heartbeatTimeoutMs);
      }
    }, this.config.heartbeatIntervalMs);
  }

  private resetHeartbeatWatchdog(): void {
    if (this.heartbeatWatchdog) {
      clearTimeout(this.heartbeatWatchdog);
      this.heartbeatWatchdog = null;
    }
  }

  private clearTimers(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.heartbeatWatchdog) clearTimeout(this.heartbeatWatchdog);
    this.heartbeatTimer = null;
    this.heartbeatWatchdog = null;
  }

  private updateState(newState: ConnectionState): void {
    this.state = newState;
    this.config.onStateChange?.(newState);
  }

  public get currentState(): ConnectionState {
    return this.state;
  }
}
```

### 2.3 Network Chaos Scenarios & Injection Recipes

Use this matrix during pre-production verification to simulate degraded mobile and enterprise networks.

```
+---------------------------------------------------------------------------------------------------+
| NETWORK CHAOS SIMULATION SUITE                                                                    |
+--------------------------+------------------------------+-----------------------------------------+
| SCENARIO                 | NETWORK PROFILE              | TARGET VALIDATION METRIC                |
| High-Speed Degradation   | 250ms Latency, 8% Loss       | Zero state divergence after 30 seconds  |
| Flappy Subway Transition | Drop every 12s, reconnect 3s | No split-brain; queue drops stale pos   |
| Asymmetric Splice        | Client TX 100%, RX 0%        | Watchdog timeout forces hard disconnect |
+--------------------------+------------------------------+-----------------------------------------+
```

#### Chaos Injection Commands

##### Scenario A: Flappy Edge Network (Linux `tc` / `iproute2`)
Inject 150ms of network latency with 25ms of jitter and a 12% random packet drop on interface `eth0`:
```bash
sudo tc qdisc add dev eth0 root netem delay 150ms 25ms distribution normal loss 12%
# Teardown command:
# sudo tc qdisc del dev eth0 root
```

##### Scenario B: The Zombie Half-Open Socket (Packet Blackhole)
Silently discard outgoing server responses without issuing TCP resets (`RST`), triggering client ping/pong watchdogs:
```bash
# Block incoming WebSocket acknowledgments/traffic from server port 4444
sudo iptables -A INPUT -p tcp --sport 4444 -j DROP
# Teardown command:
# sudo iptables -D INPUT -p tcp --sport 4444 -j DROP
```

##### Scenario C: Split-Brain State Vector Recovery Test
Run two discrete headless clients making concurrent mutations while disconnected, reconnect them to an active coordinator, and assert deterministic document convergence:

```typescript
// verifyConvergence.ts
import * as Y from 'yjs';

export function testConvergence() {
  const docA = new Y.Doc();
  const docB = new Y.Doc();

  // Emulate cross-client synchronization setup
  const mapA = docA.getMap('canvas');
  const mapB = docB.getMap('canvas');

  // Partition phase: Client A and Client B diverge concurrently
  mapA.set('shape_1', { x: 100, y: 200, color: 'blue' });
  mapB.set('shape_1', { x: 150, y: 250, color: 'red' });
  mapB.set('shape_2', { x: 0, y: 0, color: 'green' });

  // Sync step 1: Send B's changes to A
  const stateVectorA = Y.encodeStateVector(docA);
  const diffForA = Y.encodeStateAsUpdate(docB, stateVectorA);

  // Sync step 2: Send A's changes to B
  const stateVectorB = Y.encodeStateVector(docB);
  const diffForB = Y.encodeStateAsUpdate(docA, stateVectorB);

  // Merge phase
  Y.applyUpdate(docA, diffForA);
  Y.applyUpdate(docB, diffForB);

  // Determinism Verification
  const jsonA = JSON.stringify(mapA.toJSON());
  const jsonB = JSON.stringify(mapB.toJSON());

  if (jsonA !== jsonB) {
    throw new Error(`CRDT Divergence Failure!\nDocA: ${jsonA}\nDocB: ${jsonB}`);
  }

  console.log('CONVERGENCE_VERIFIED: State hashes match identically across isolated nodes.');
}
testConvergence();
```

---

## 3. Yjs & WebSocket Packet Optimization Cheatsheet

Naive implementations stream high-frequency events (mouse moves, canvas drags, selection bounds) as full JSON objects over text frames. Doing this at 60Hz across 30 users will choke the edge gateway's bandwidth and cause client thread contention.

### 3.1 Serialization Payload Comparisons

```
JSON vs. VarUint Wire Overhead (Cursor Frame)
+-------------------------------------------------------+
| JSON: 142 bytes                                       |
| {"type":"cursor","userId":"usr_89f3","x":1042.8421,...|
+-------------------------------------------------------+
| Lib0 VarUint / Float32 Encoded: 14 bytes              |
| [0x01, 0x05, 0x89, 0xF3, 0x44, 0x82, 0x5A, ...]      |
+-------------------------------------------------------+
```

| Message Type | Raw JSON Payload Size | Optimized Binary Size | Savings | Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Cursor Coordinates** | 138 bytes | 12 bytes | **91.3%** | Pack `x`, `y` into `Int16Array` (scaled to canvas view bounds); skip string user IDs in favor of 32-bit mapped client IDs. |
| **Yjs Incremental Transaction** | 412 bytes (JSON base64) | 38 bytes | **90.7%** | Direct `Uint8Array` passthrough using standard Yjs structural run-length encoding. |
| **Heartbeat / Watchdog** | 22 bytes (`{"type":"ping"}`) | 1 byte | **95.4%** | Magic single-byte control frames: `0xFE` (Ping), `0xFF` (Pong). |
| **Awareness Multi-Presence** | 2,450 bytes (30 peers) | 380 bytes | **84.5%** | Delta-encode awareness updates; omit stale/unchanged client states. |

### 3.2 High-Frequency Awareness Throttling & Variable-Precision Packing

```typescript
// awarenessPacking.ts
import * as encoding from 'lib0/encoding';
import * as decoding from 'lib0/decoding';

export interface CursorState {
  clientId: number; // 32-bit local client index
  x: number;        // Canvas relative coordinates (0.0 to 65535.0)
  y: number;
  tool: number;     // Bitfield (0-255)
}

/**
 * Packs cursor state into exactly 9 bytes:
 * [0x01: MessageType.Cursor] (1 byte)
 * [Uint32 ClientId]          (4 bytes)
 * [Uint16 X Coord]           (2 bytes)
 * [Uint16 Y Coord]           (2 bytes)
 */
export function packCursor(cursor: CursorState): Uint8Array {
  const encoder = encoding.createEncoder();
  
  // Magic opcode for cursor frame: 0x01
  encoding.writeUint8(encoder, 0x01);
  encoding.writeUint32(encoder, cursor.clientId);
  
  // Clamp floats to Uint16 space (0 - 65535) for canvas sub-pixel accuracy
  const clampedX = Math.max(0, Math.min(65535, Math.round(cursor.x)));
  const clampedY = Math.max(0, Math.min(65535, Math.round(cursor.y)));
  
  encoding.writeUint16(encoder, clampedX);
  encoding.writeUint16(encoder, clampedY);

  return encoding.toUint8Array(encoder);
}

export function unpackCursor(buffer: Uint8Array): CursorState {
  const decoder = decoding.createDecoder(buffer);
  const messageType = decoding.readUint8(decoder);
  
  if (messageType !== 0x01) {
    throw new Error(`Unexpected message opcode: ${messageType}`);
  }

  return {
    clientId: decoding.readUint32(decoder),
    x: decoding.readUint16(decoder),
    y: decoding.readUint16(decoder),
    tool: 0
  };
}
```

### 3.3 Dynamic Awareness Engine with Adaptive Rate Throttling

```typescript
// AdaptiveAwarenessThrottler.ts
export class AdaptiveAwarenessThrottler {
  private lastBroadcast = 0;
  private pendingFrame: CursorState | null = null;
  private throttleTimer: ReturnType<typeof setTimeout> | null = null;
  
  // Rate limits based on velocity: Static = 10Hz, Moving = 30Hz, Ultra-Fast = 60Hz
  private currentInterval = 33; // Default ~30Hz (ms)

  constructor(private readonly broadcastFn: (packed: Uint8Array) => void) {}

  public pushLocalPosition(cursor: CursorState): void {
    this.pendingFrame = cursor;
    const now = performance.now();
    const elapsed = now - this.lastBroadcast;

    if (elapsed >= this.currentInterval) {
      this.flush();
    } else if (!this.throttleTimer) {
      this.throttleTimer = setTimeout(() => {
        this.flush();
      }, this.currentInterval - elapsed);
    }
  }

  public setHighVelocityMode(isHighVelocity: boolean): void {
    // Dynamic throttling: dial back down during regular movements to protect network edge
    this.currentInterval = isHighVelocity ? 16 : 33; // 60Hz vs 30Hz
  }

  private flush(): void {
    if (this.throttleTimer) {
      clearTimeout(this.throttleTimer);
      this.throttleTimer = null;
    }

    if (this.pendingFrame) {
      const payload = packCursor(this.pendingFrame);
      this.broadcastFn(payload);
      this.lastBroadcast = performance.now();
      this.pendingFrame = null;
    }
  }
}
```

---

## 4. Production Runbooks & Triage Playbooks (Swipe File)

---

### Playbook 1: CRDT State Vector Divergence & Phantom Updates

#### Severity: P1 (Data Corruption / Collaborative Desync)

#### 1. Symptoms & Alert Triggers
* Clients report seeing different canvas node locations or missing paragraph characters while both sockets report connected (`READY_STATE = 1`).
* Disconnect/refresh temporarily resolves the issue for one user while breaking it for another.
* Edge logs throw `Y.Update decoder error: Unexpected end of array` or `State vector missing dependency`.

#### 2. Immediate Mitigation (5-Minute Fix)
Force an ephemeral full-state re-synchronization across all active connected peers in the degraded room without dropping their physical WebSocket connections.

```typescript
// Admin Emergency Broadcast via Edge Controller / CLI
export function emergencyForceRoomResync(room: RoomDurableObject) {
  // 1. Generate baseline compacted snapshot from canonical storage
  const canonicalBytes = room.getStorageSnapshot(); 
  
  // 2. Broadcast hard reset instruction with magic opcode (0xAA)
  const encoder = encoding.createEncoder();
  encoding.writeUint8(encoder, 0xaa);
  encoding.writeVarUint8Array(encoder, canonicalBytes);
  const resetPacket = encoding.toUint8Array(encoder);

  room.broadcast(resetPacket);
}
```
Client handler hook:
```typescript
if (opcode === 0xAA) {
  const cleanUpdate = decoding.readVarUint8Array(decoder);
  // Re-instantiate internal Y.Doc completely
  doc.destroy();
  doc = new Y.Doc();
  Y.applyUpdate(doc, cleanUpdate);
  renderCanvas(doc);
}
```

#### 3. Root Cause Diagnosis & Forensic Steps
1. Capture raw binary updates from the active room using the extraction command:
   ```bash
   npx partykit export-room --room canvas-live-prod-402 --output /tmp/corrupt-room.bin
   ```
2. Analyze structural integrity via the Yjs inspection script:
   ```javascript
   // inspectCorruptDoc.js
   const Y = require('yjs');
   const fs = require('fs');
   
   const file = fs.readFileSync('/tmp/corrupt-room.bin');
   const doc = new Y.Doc();
   
   try {
     Y.applyUpdate(doc, file);
     console.log('Doc successfully parsed. Client IDs in store:');
     for (const [clientId, items] of doc.store.clients.entries()) {
       console.log(`Client ${clientId}: ${items.length} operations. Deleted items: ${items.filter(i => i.deleted).length}`);
     }
   } catch (err) {
     console.error('CRITICAL: Binary stream corrupted at byte position:', err);
   }
   ```
3. Common cause: A client framework updated document state within an unhandled microtask, mutating state before applying external remote updates, which violates strict linear clock progression.

#### 4. Verification & Clean Resolution
* Ensure transaction listeners are synchronous:
  ```typescript
  // PREVENTS DIVERGENCE: Always wrap client edits in transactions
  doc.transact(() => {
    sharedMap.set('property', value);
  }, 'local-ui-mutation');
  ```
* Post-incident verify: Run `testConvergence()` from Section 2.3 against the snapshot taken from storage.

---

### Playbook 2: WebSocket Edge Memory Leak & Event Loop Starvation

#### Severity: P1 (Service Degradation / Cascading Edge Eviction)

#### 1. Symptoms & Alert Triggers
* Edge worker memory metrics climb linearly until hitting runtime limits (e.g., 128MB per Durable Object, 512MB on node instances), followed by process restarts.
* Edge heartbeat responses jump from $12\text{ms}$ to $>2,500\text{ms}$.
* WebSocket error metrics report sudden jumps in status codes `1006` (Abnormal Closure).

#### 2. Immediate Mitigation
Trigger isolated node eviction or force active rooms to shed their memory caches and offload state to cold storage.

```bash
# Force worker recycling on Cloudflare / PartyKit
npx partykit rollback --tag active-safe-point
# Or trigger manual DO re-allocation:
curl -X POST https://api.partykit.io/v1/rooms/canvas-room-12/evict \
  -H "Authorization: Bearer $PARTYKIT_ADMIN_TOKEN"
```

#### 3. Root Cause Diagnosis & Forensic Steps
Capture node profiles under active traffic using dynamic inspector hooks:

```bash
# Attach node-inspect inside live container
node --inspect=0.0.0.0:9229 dist/server.js
# Trigger an immediate on-demand heap profile:
curl -X POST http://localhost:8080/debug/pprof/heap
```

Look for the three primary memory leak culprits in collaborative systems:
1. **Unregistered Transaction Listeners:** Adding `doc.on('update', ...)` inside a UI component without running `.off('update')` upon unmount.
2. **Awareness State Accumulation:** Inactive clients never emitting `destroy()` transactions, leaving zombie peer records inside the `awareness.states` map.
3. **Transaction Origin Objects Retaining Closures:** Storing DOM nodes or context handles inside the `origin` field of `doc.transact(..., origin)`.

```typescript
// AUDIT TEST: Find retained awareness objects
console.log('Active awareness size:', awareness.getStates().size);
// If active connections (e.g. 5) does not match awareness states (e.g. 542),
// run awareness cleanup:
awareness.cleanUnusedStates();
```

#### 4. Verification & Post-Mortem Hardening
Patch the core server runtime to evict awareness state after an explicit idle timeout:

```typescript
// Auto-eviction patch for awareness instances
const AWARENESS_TIMEOUT_MS = 60_000;

export function monitorZombieAwareness(awareness: any) {
  setInterval(() => {
    const now = Date.now();
    awareness.getStates().forEach((state: any, clientId: number) => {
      if (now - state.lastUpdated > AWARENESS_TIMEOUT_MS) {
        // Enforce cleanup to avoid unbounded leaks
        awareness.removeAwarenessStates([clientId], 'timeout-purge');
      }
    });
  }, 15_000);
}
```

---

### Playbook 3: Cold-Start Thundering Herd & Distributed Lock Contention

#### Severity: P2 (Degraded User Experience / Connection Queue Spikes)

#### 1. Symptoms &
