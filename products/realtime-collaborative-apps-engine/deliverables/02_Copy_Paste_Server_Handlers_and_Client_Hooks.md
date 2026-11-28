# Module 2: Ready-to-Use PartyKit, Liveblocks & Custom WebSocket Servers

## 1. Architectural Wire Protocols & Frame Serialization

Collaborative applications operate on two distinct data paths: **ephemeral presence** (transient data such as cursors, selections, and typing indicators) and **persistent state** (CRDT documents, canvas graphs, and revision logs). Mixing these without clear protocol definitions causes serialization bottlenecks, frame drops, and head-of-line blocking.

### 1.1 Wire Protocol Frame Specification

To maximize throughput and minimize garbage collection pauses in edge runtimes (Cloudflare Workers, Fastly) and Node.js environments, we define a hybrid protocol:
* **Binary Frames (`ArrayBuffer` / `Uint8Array`):** CRDT mutations (Yjs updates, Automerge sync steps) and bulk document snapshots.
* **Text Frames (Strict UTF-8 JSON):** Control messages, room authentication, lease renewals, and structured metadata.

```
+-----------------------------------------------------------------------+
|                         Binary Protocol Frame                         |
+--------+------------------+------------------+------------------------+
| Byte 0 | Bytes 1-16       | Bytes 17-20      | Bytes 21+              |
| Magic  | UUID (Room ID    | Payload Length   | CRDT Raw Delta Payload |
| 0xAA   | 128-bit Binary)  | (UInt32BE)       | (Yjs / Automerge)      |
+--------+------------------+------------------+------------------------+

+-----------------------------------------------------------------------+
|                          JSON Control Frame                           |
+-----------------------------------------------------------------------+
| { "type": "AUTH" | "HEARTBEAT" | "AWARENESS" | "ERROR", ...data }     |
+-----------------------------------------------------------------------+
```

### 1.2 Protocol Message Types & Enums

Save this file as `shared/protocol.ts`. It provides strict typing across both the server engines and client consumers.

```typescript
// shared/protocol.ts

export const PROTOCOL_VERSION = 1;

export enum MessageType {
  // Connection Lifecycle
  CLIENT_HANDSHAKE = 100,
  SERVER_ACK = 101,
  HEARTBEAT_PING = 102,
  HEARTBEAT_PONG = 103,
  ROOM_TERMINATED = 104,

  // Authentication & RBAC
  AUTH_REQUEST = 200,
  AUTH_SUCCESS = 201,
  AUTH_FAILURE = 202,
  TOKEN_REFRESH = 203,

  // Ephemeral State (Awareness)
  AWARENESS_UPDATE = 300,
  AWARENESS_QUERY = 301,
  CURSOR_BROADCAST = 302,

  // Document Engine Control
  DOCUMENT_SAVE_SIGNAL = 400,
  DOCUMENT_RESET = 401,
}

export type ClientHandshakeMessage = {
  type: MessageType.CLIENT_HANDSHAKE;
  protocolVersion: number;
  clientSessionId: string;
  authToken: string;
};

export type ServerAckMessage = {
  type: MessageType.SERVER_ACK;
  protocolVersion: number;
  assignedClientId: number;
  connectionLeaseExpiresAt: number;
};

export type AwarenessPayload = {
  clientId: number;
  user: {
    id: string;
    name: string;
    color: string;
    avatar?: string;
  };
  cursor: { x: number; y: number; targetNodeId?: string } | null;
  selection: string[] | null;
  lastUpdated: number;
};

export type AwarenessUpdateMessage = {
  type: MessageType.AWARENESS_UPDATE;
  states: AwarenessPayload[];
};

export type HeartbeatMessage = {
  type: MessageType.HEARTBEAT_PING | MessageType.HEARTBEAT_PONG;
  timestamp: number;
};

export type ProtocolMessage =
  | ClientHandshakeMessage
  | ServerAckMessage
  | AwarenessUpdateMessage
  | HeartbeatMessage;
```

---

## 2. Production Edge-Ready PartyKit Handlers

PartyKit provides an edge-native, Cloudflare Durable Objects-based architecture. State resides in memory directly on the edge node nearest the user. Below is the battle-tested PartyKit server managing Yjs documents, authentication, vector-clock-driven snapshots, and alarm-based auto-persisting.

Save this file as `partykit-server/src/server.ts`.

```typescript
// partykit-server/src/server.ts
import type * as Party from "partykit/server";
import * as Y from "yjs";
import { jwtVerify, createRemoteJWKSet } from "jose";

const JWKS = createRemoteJWKSet(
  new URL(process.env.AUTH_JWKS_URL || "https://auth.example.com/.well-known/jwks.json")
);

interface UserContext {
  userId: string;
  role: "admin" | "editor" | "viewer";
  organizationId: string;
}

export default class CollaborativeRoomServer implements Party.Server {
  private doc: Y.Doc;
  private connections: Map<Party.Connection, UserContext> = new Map();
  private isPersisting: boolean = false;
  private lastSnapshotVector: Uint8Array | null = null;

  constructor(readonly room: Party.Room) {
    this.doc = new Y.Doc();
  }

  /**
   * Room Lifecycle: Called when the server initializes or wakes from hibernation.
   */
  async onStart(): Promise<void> {
    const rawDocumentSnapshot = await this.room.storage.get<Uint8Array>("document_state");
    if (rawDocumentSnapshot) {
      Y.applyUpdate(this.doc, rawDocumentSnapshot);
      this.lastSnapshotVector = Y.encodeStateVector(this.doc);
    }

    // Schedule incremental flush every 30 seconds
    const currentAlarm = await this.room.storage.getAlarm();
    if (currentAlarm === null) {
      await this.room.storage.setAlarm(Date.now() + 30_000);
    }
  }

  /**
   * HTTP upgrade hook: Authenticate connection before promoting to WebSocket.
   */
  async onConnect(connection: Party.Connection, ctx: Party.ConnectionContext): Promise<void> {
    const url = new URL(ctx.request.url);
    const token = url.searchParams.get("token");

    if (!token) {
      connection.close(4001, "Authentication required: Missing token");
      return;
    }

    try {
      const { payload } = await jwtVerify(token, JWKS, {
        issuer: process.env.AUTH_ISSUER || "https://auth.example.com",
        audience: process.env.AUTH_AUDIENCE || "multiplayer-engine",
      });

      const userCtx: UserContext = {
        userId: payload.sub as string,
        role: (payload.role as "admin" | "editor" | "viewer") || "viewer",
        organizationId: payload.org_id as string,
      };

      // Check room tenant authorization
      const expectedOrg = this.room.id.split(":")[0];
      if (userCtx.organizationId !== expectedOrg && userCtx.role !== "admin") {
        connection.close(4003, "Forbidden: Multi-tenant violation");
        return;
      }

      this.connections.set(connection, userCtx);

      // 1. Send SyncStep 1 to client (Document State Vector)
      const stateVector = Y.encodeStateVector(this.doc);
      const syncStep1Message = this.constructSyncMessage(0, stateVector);
      connection.send(syncStep1Message);

    } catch (err) {
      connection.close(4002, `Authentication failed: ${(err as Error).message}`);
    }
  }

  /**
   * Handle incoming binary updates and awareness frames.
   */
  async onMessage(message: string | ArrayBuffer, sender: Party.Connection): Promise<void> {
    const senderCtx = this.connections.get(sender);
    if (!senderCtx) {
      sender.close(4001, "Unauthorized");
      return;
    }

    // Handle binary frames (Yjs Updates)
    if (message instanceof ArrayBuffer) {
      if (senderCtx.role === "viewer") {
        // Drop mutations silently or send violation back
        return;
      }

      const uint8 = new Uint8Array(message);
      const messageType = uint8[0];
      const payload = uint8.subarray(1);

      if (messageType === 0) {
        // SyncStep 1 received: reply with SyncStep 2
        const replyUpdate = Y.encodeStateAsUpdate(this.doc, payload);
        const syncStep2 = this.constructSyncMessage(1, replyUpdate);
        sender.send(syncStep2);
      } else if (messageType === 1 || messageType === 2) {
        // SyncStep 2 or incremental mutation update
        Y.applyUpdate(this.doc, payload, sender);
        
        // Broadcast update to all other connected clients
        this.room.broadcast(message, [sender.id]);
      }
      return;
    }

    // Handle JSON Frames (Awareness & Heartbeats)
    try {
      const parsed = JSON.parse(message);
      if (parsed.type === "AWARENESS_UPDATE") {
        // Broadcast cursor/selection immediately to peers
        this.room.broadcast(message, [sender.id]);
      }
    } catch (err) {
      // Invalid frame drop
    }
  }

  /**
   * Cleanup client state on disconnect.
   */
  async onClose(connection: Party.Connection): Promise<void> {
    this.connections.delete(connection);
  }

  /**
   * Scheduled Alarms: Flush state to persistent storage.
   */
  async onAlarm(): Promise<void> {
    if (this.isPersisting) return;

    try {
      this.isPersisting = true;
      const currentDocState = Y.encodeStateAsUpdate(this.doc);
      
      // Persist raw state vector to Durable Object storage
      await this.room.storage.put("document_state", currentDocState);

      // External webhook flush to cold storage (e.g. S3 / Postgres)
      if (process.env.COLD_STORAGE_WEBHOOK_URL) {
        await fetch(process.env.COLD_STORAGE_WEBHOOK_URL, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream", "X-Room-Id": this.room.id },
          body: currentDocState,
        });
      }
    } catch (error) {
      console.error(`[Persist Failure] Room: ${this.room.id}`, error);
    } finally {
      this.isPersisting = false;
      // Reschedule for next 30-second window
      await this.room.storage.setAlarm(Date.now() + 30_000);
    }
  }

  private constructSyncMessage(type: number, payload: Uint8Array): Uint8Array {
    const combined = new Uint8Array(payload.length + 1);
    combined[0] = type;
    combined.set(payload, 1);
    return combined;
  }
}
```

---

## 3. Custom Node.js + `ws` + Redis Pub/Sub Backbone

When hosting outside of serverless or edge primitives, you need a high-concurrency Node.js server backed by Redis Pub/Sub to scale WebSockets horizontally across an auto-scaling Kubernetes or container cluster.

### 3.1 Horizontal Scaling Topography

```
                                      +------------------------+
                                      | AWS ALB / Cloudflare   |
                                      +------------------------+
                                         /                  \
                                        /                    \
              +-------------------------------+       +-------------------------------+
              | Pod 1: Node.js ws Server      |       | Pod 2: Node.js ws Server      |
              | Local Room Connections: 4,000 |       | Local Room Connections: 4,000 |
              +-------------------------------+       +-------------------------------+
                              ^                                       ^
                              |                                       |
                              v                                       v
              +---------------------------------------------------------------+
              |              Redis 7.x Cluster / DragonflyDB                 |
              |   Channel: "room:{roomId}:sync"  (Binary Mutations)           |
              |   Channel: "room:{roomId}:aware" (Ephemeral Awareness)        |
              +---------------------------------------------------------------+
```

### 3.2 Production Cluster Server Implementation

Save this file as `server/src/multiplayer-node-cluster.ts`.

```typescript
// server/src/multiplayer-node-cluster.ts
import { createServer, IncomingMessage } from "http";
import { WebSocketServer, WebSocket } from "ws";
import Redis from "ioredis";
import * as Y from "yjs";
import { parse } from "url";
import { jwtVerify, createRemoteJWKSet } from "jose";

interface AuthenticatedSocket extends WebSocket {
  isAlive: boolean;
  userId: string;
  roomId: string;
  role: "admin" | "editor" | "viewer";
}

interface RoomInstance {
  doc: Y.Doc;
  clients: Set<AuthenticatedSocket>;
}

const PORT = parseInt(process.env.PORT || "8080", 10);
const REDIS_URL = process.env.REDIS_URL || "redis://localhost:6379";

const redisPub = new Redis(REDIS_URL, { maxRetriesPerRequest: 3 });
const redisSub = new Redis(REDIS_URL, { maxRetriesPerRequest: 3 });

const JWKS = createRemoteJWKSet(new URL(process.env.AUTH_JWKS_URL!));
const server = createServer();
const wss = new WebSocketServer({ noServer: true });

// Active in-memory rooms local to this container
const localRooms = new Map<string, RoomInstance>();

/**
 * Global Redis Subscription Routing Engine
 */
redisSub.psubscribe("room:*:sync", "room:*:aware", (err) => {
  if (err) throw err;
});

redisSub.on("pmessage", (_pattern, channel, messageBuffer) => {
  const parts = channel.split(":");
  const roomId = parts[1];
  const channelType = parts[2];
  
  const room = localRooms.get(roomId);
  if (!room) return;

  if (channelType === "sync") {
    const rawUpdate = Buffer.from(messageBuffer, "base64");
    Y.applyUpdate(room.doc, rawUpdate, "REDIS_SOURCE");

    // Distribute to all local sockets connected to this room
    for (const client of room.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(rawUpdate);
      }
    }
  } else if (channelType === "aware") {
    for (const client of room.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(messageBuffer);
      }
    }
  }
});

/**
 * HTTP Handshake Interception & Upgrade Verification
 */
server.on("upgrade", async (request: IncomingMessage, socket, head) => {
  const { pathname, query } = parse(request.url || "", true);

  if (!pathname?.startsWith("/v1/rooms/")) {
    socket.write("HTTP/1.1 404 Not Found\r\n\r\n");
    socket.destroy();
    return;
  }

  const roomId = pathname.replace("/v1/rooms/", "");
  const token = query.token as string;

  if (!token) {
    socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
    socket.destroy();
    return;
  }

  try {
    const { payload } = await jwtVerify(token, JWKS);
    
    wss.handleUpgrade(request, socket, head, (ws) => {
      const authWs = ws as AuthenticatedSocket;
      authWs.isAlive = true;
      authWs.userId = payload.sub as string;
      authWs.roomId = roomId;
      authWs.role = (payload.role as "admin" | "editor" | "viewer") || "viewer";

      wss.emit("connection", authWs, request);
    });
  } catch (error) {
    socket.write("HTTP/1.1 403 Forbidden\r\n\r\n");
    socket.destroy();
  }
});

/**
 * WebSocket Connection Handler
 */
wss.on("connection", async (ws: AuthenticatedSocket) => {
  const { roomId, role } = ws;

  // Initialize or fetch in-memory room
  let room = localRooms.get(roomId);
  if (!room) {
    room = {
      doc: new Y.Doc(),
      clients: new Set(),
    };
    localRooms.set(roomId, room);

    // Load initial snapshot from Redis / Persistent store
    const snapshot = await redisPub.getBuffer(`snapshot:${roomId}`);
    if (snapshot) {
      Y.applyUpdate(room.doc, snapshot);
    }
  }
  room.clients.add(ws);

  // Send current state vector to initiate handshake
  const stateVector = Y.encodeStateVector(room.doc);
  ws.send(Buffer.from(stateVector));

  ws.on("pong", () => {
    ws.isAlive = true;
  });

  ws.on("message", async (data: Buffer, isBinary: boolean) => {
    if (isBinary) {
      if (role === "viewer") return; // Enforce RBAC

      const update = new Uint8Array(data);
      Y.applyUpdate(room!.doc, update, ws);

      // Publish to Redis for horizontal scale (Cluster Propagation)
      await redisPub.publish(
        `room:${roomId}:sync`,
        Buffer.from(update).toString("base64")
      );
    } else {
      // JSON Frame (Awareness data)
      await redisPub.publish(`room:${roomId}:aware`, data.toString("utf-8"));
    }
  });

  ws.on("close", () => {
    const r = localRooms.get(roomId);
    if (!r) return;
    r.clients.delete(ws);

    if (r.clients.size === 0) {
      // Flush back to Redis before unmounting from memory
      const currentDocBytes = Y.encodeStateAsUpdate(r.doc);
      redisPub.set(`snapshot:${roomId}`, Buffer.from(currentDocBytes));
      localRooms.delete(roomId);
    }
  });
});

/**
 * Heartbeat Verification (Detect and tear down zombie connections)
 */
const heartbeatInterval = setInterval(() => {
  wss.clients.forEach((client) => {
    const authWs = client as AuthenticatedSocket;
    if (!authWs.isAlive) {
      authWs.terminate();
      return;
    }
    authWs.isAlive = false;
    authWs.ping();
  });
}, 30000);

wss.on("close", () => clearInterval(heartbeatInterval));

server.listen(PORT, () => {
  console.log(`[WebSocket Server] Running on port ${PORT}`);
});
```

---

## 4. Multi-Tenant Room Authorization & Middleware

Authentication must be handled during the HTTP GET upgrade handshake, but dynamic token expiration, revoking authorization, and room-level permission mutations must be enforced over the live socket session.

### 4.1 Token Invalidation and Dynamic Demotion

Below is an authorization middleware class usable within any Node.js custom WebSocket loop. Save this file as `server/src/auth-guard.ts`.

```typescript
// server/src/auth-guard.ts
import { jwtVerify, JWTVerifyGetKey } from "jose";

export interface SessionMetadata {
  userId: string;
  orgId: string;
  role: "admin" | "editor" | "viewer";
  exp: number;
}

export class WebSocketAuthGuard {
  private keySet: JWTVerifyGetKey;

  constructor(jwksUri: string) {
    const { createRemoteJWKSet } = require("jose");
    this.keySet = createRemoteJWKSet(new URL(jwksUri));
  }

  /**
   * Evaluates upgrade request and unpacks payload.
   */
  async authenticateRequest(token: string): Promise<SessionMetadata> {
    try {
      const { payload } = await jwtVerify(token, this.keySet, {
        algorithms: ["RS256", "EdDSA"],
      });

      return {
        userId: payload.sub as string,
        orgId: (payload.org_id as string) || "global",
        role: (payload.role as "admin" | "editor" | "viewer") || "viewer",
        exp: (payload.exp as number) * 1000,
      };
    } catch (err) {
      throw new Error(`Token validation failed: ${(err as Error).message}`);
    }
  }

  /**
   * Validates if a user session is authorized to touch a given Room namespace.
   * Namespace Pattern: {tenantId}:{workspaceId}:{resourceId}
   */
  validateNamespaceAccess(roomId: string, session: SessionMetadata): boolean {
    const parts = roomId.split(":");
    if (parts.length < 3) {
      // Legacy or single-tenant room format fallback
      return true;
    }

    const [tenantId] = parts;
    if (session.role === "admin") return true;
    return session.orgId === tenantId;
  }

  /**
   * Setup dynamic demotion timer. Automatically downgrades connection if token expires
   * without renegotiation.
   */
  scheduleTokenExpiryCheck(
    session: SessionMetadata,
    onExpire: () => void
  ): NodeJS.Timeout {
    const timeUntilExpiry = session.exp - Date.now();
    const safetyBuffer = 5000; // 5s early trigger

    return setTimeout(() => {
      onExpire();
    }, Math.max(timeUntilExpiry - safetyBuffer, 0));
  }
}
```

---

## 5. Production React Multiplayer Hooks

This client integration layer features full connection lifecycle state machines, automatic reconnection with exponential backoff and jitter, non-blocking awareness tracking, and direct binding to dynamic CRDT state.

### 5.1 Realtime Multiplayer Room Hook

Save this file as `client/src/hooks/useMultiplayerRoom.ts`.

```typescript
// client/src/hooks/useMultiplayerRoom.ts
import { useEffect, useRef, useState, useCallback } from "react";

export type ConnectionStatus = "CONNECTING" | "CONNECTED" | "DISCONNECTED" | "ERROR" | "RECONNECTING";

interface MultiplayerConfig {
  endpoint: string;
  roomId: string;
  getAuthToken: () => Promise<string>;
  onBinaryMessage?: (data: Uint8Array) => void;
  onJsonMessage?: (data: any) => void;
  maxReconnectAttempts?: number;
}

export function useMultiplayerRoom({
  endpoint,
  roomId,
  getAuthToken,
  onBinaryMessage,
  onJsonMessage,
  maxReconnectAttempts = 10,
}: MultiplayerConfig) {
  const [status, setStatus] = useState<ConnectionStatus>("DISCONNECTED");
  const [error, setError] = useState<Error | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const backoffTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const unmountedRef = useRef<boolean>(false);

  const connect = useCallback(async () => {
    if (unmountedRef.current) return;
    setStatus((prev) => (prev === "DISCONNECTED" ? "CONNECTING" : "RECONNECTING"));

    try {
      const token = await getAuthToken();
      const wsUrl = `${endpoint}/v1/rooms/${roomId}?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        if (unmountedRef.current) {
          ws.close();
          return;
        }
        reconnectAttemptsRef.current = 0;
        setStatus("CONNECTED");
        setError(null);
      };

      ws.onmessage = (event: MessageEvent) => {
        if (event.data instanceof ArrayBuffer) {
          onBinaryMessage?.(new Uint8Array(event.data));
        } else if (typeof event.data === "string") {
          try {
            const parsed = JSON.parse(event.data);
            onJsonMessage?.(parsed);
          } catch (e) {
            console.error("[useMultiplayerRoom] JSON Parse Error", e);
          }
        }
      };

      ws.onerror = () => {
        setError(new Error("WebSocket network failure"));
      };

      ws.onclose = (event) => {
        if (unmountedRef.current) return;

        // Terminal auth errors (4000-4003) -> Do not reconnect
        if (event.code >= 4001 && event.code <= 4003) {
          setStatus("ERROR");
          setError(new Error(`Disconnected: ${event.reason} (Code: ${event.code})`));
          return;
        }

        setStatus("DISCONNECTED");
        
        // Exponential backoff with Full Jitter
        if (reconnectAttemptsRef.current < maxReconnectAttempts) {
          const attempt = reconnectAttemptsRef.current++;
          const baseDelay = Math.min(1000 * Math.pow(2, attempt), 30000);
          const jitter = Math.random() * baseDelay;
          const delay = jitter;

          backoffTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          setStatus("ERROR");
          setError(new Error("Max reconnection budget exhausted."));
        }
      };

      socketRef.current = ws;
    } catch (err) {
      setStatus("ERROR");
      setError(err as Error);
    }
  }, [endpoint, roomId, getAuthToken, onBinaryMessage, onJsonMessage, maxReconnectAttempts]);

  const sendBinary = useCallback((data: Uint8Array) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(data);
    }
  }, []);

  const sendJson = useCallback((data: any) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(data));
    }
  }, []);

  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;
      if (backoffTimeoutRef.current) clearTimeout(backoffTimeoutRef.current);
      if (socketRef.current) {
        socketRef.current.close(1000, "Component unmounted");
      }
    };
  }, [connect]);

  return { status, error, sendBinary, sendJson };
}
```

### 5.2 Ephemeral Awareness & Multi-Cursor Sync Hook

Save this file as `client/src/hooks/useAwarenessPresence.ts`.

```typescript
// client/src/hooks/useAwarenessPresence.ts
import { useEffect, useState, useCallback, useRef } from "react";
import { AwarenessPayload } from "../../shared/protocol";

interface AwarenessUser {
  id: string;
  name: string;
  color: string;
  avatar?: string;
}

interface UseAwarenessOptions {
  sendJson: (data: any) => void;
  currentUser: AwarenessUser;
  idleTimeoutMs?: number;
}

export function useAwarenessPresence({
  sendJson,
  currentUser,
  idleTimeoutMs = 15000,
}: UseAwarenessOptions) {
  const [peers, setPeers] = useState<Map<number, AwarenessPayload>>(new Map());
  const localClientId = useRef<number>(Math.floor(Math.random() * 100000000));
  const idleTimer = useRef<NodeJS.Timeout | null>(null);

  // Broadcast local changes to peers
  const broadcastPresence = useCallback(
    (cursor: { x: number; y: number; targetNodeId?: string } | null, selection: string[] | null) => {
      const payload: AwarenessPayload = {
        clientId: localClientId.current,
        user: currentUser,
        cursor,
        selection,
        lastUpdated: Date.now(),
      };

      sendJson({
        type: "AWARENESS_UPDATE",
        states: [payload],
      });
    },
    [currentUser, sendJson]
  );

  // Update Peer State with stale garbage collection
  const handleIncomingAwareness = useCallback((states: AwarenessPayload[]) => {
    setPeers((prevPeers) => {
      const next = new Map(prevPeers);
      for (const st of states) {
        if (st.clientId === localClientId.current) continue;
        
        if (st.cursor === null && st.selection === null) {
          next.delete(st.clientId);
        } else {
          next.set(st.clientId, st);
        }
      }
      return next;
    });
  }, []);

  // Track global window pointer movements
  useEffect(() => {
    const handlePointerMove = (e: PointerEvent) => {
      broadcastPresence({ x: e.clientX, y: e.clientY }, null);

      if (idleTimer.current) clearTimeout(idleTimer.current);
      idleTimer.current = setTimeout(() => {
        // Go Idle: clear pointer
        broadcastPresence(null, null);
      }, idleTimeoutMs);
    };

    const handlePointerLeave = () => {
      broadcastPresence(null, null);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerleave", handlePointerLeave);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerleave", handlePointerLeave);
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, [broadcastPresence, idleTimeoutMs]);

  // Periodic pruning of dead awareness states (dropped sockets without clean close)
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      setPeers((prevPeers) => {
        let changed = false;
        const next = new Map(prevPeers);
        for (const [id, value] of next.entries()) {
          if (now - value.lastUpdated > idleTimeoutMs) {
