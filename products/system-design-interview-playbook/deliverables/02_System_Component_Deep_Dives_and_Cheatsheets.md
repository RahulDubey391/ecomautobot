# Module 2: Building Block Blueprints & Technology Selection Matrices

This module provides exhaustive, production-tested selection matrices, architectural trade-offs, and complete implementation blueprints for the core building blocks of distributed systems. Use these patterns to justify architectural decisions during FAANG-level system design rounds and implement them in high-throughput production environments.

---

## 1. Storage Engine Decision Matrix: SQL vs. NoSQL vs. NewSQL

Selecting the wrong persistence layer introduces operational overhead and scalability ceilings that are difficult to refactor later. Evaluate storage engines using the deterministic criteria below.

### 1.1 Technical Evaluation Matrix

| Dimension | Relational (RDBMS) | Key-Value | Document | Wide-Column | NewSQL |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Representative Systems** | PostgreSQL, MySQL 8.0+ | Redis, AWS DynamoDB, Aerospike | MongoDB, Couchbase | Apache Cassandra, ScyllaDB | CockroachDB, Google Cloud Spanner |
| **Primary Data Model** | Normalized Relations (Tables, Foreign Keys) | Unstructured Blobs / Primitive Key-Value | Semi-structured JSON / BSON Trees | Sparse multidimensional sorted map `(RowKey, ColumnKey, Timestamp)` | Relational with underlying distributed LSM/Raft engine |
| **ACID Guarantees** | Full ACID (Strict Serializability / Read Committed / Repeatable Read) | Eventual or Strong per single-key. Cross-key ACID rarely supported natively. | Single-document ACID default; Multi-document distributed ACID (high latency cost). | Tunable Consistency (AP bias). Eventual Consistency with Lightweight Transactions (LWT/Paxos). | Global ACID via Distributed Consensus (Raft/Paxos + TrueTime / Hybrid Logical Clocks). |
| **Scaling Mechanism** | Vertical write scaling (Read replicas with asynchronous replication lag; Sharding requires application-level routing like Vitess/Citus). | Horizontal partition hashing (Consistent Hashing rings with virtual nodes). | Horizontal auto-sharding via Range or Hash routing keys. | Masterless peer-to-peer ring topology. Linear horizontal scaling. | Distributed Raft consensus groups across distributed partitions (Ranges/Splits). |
| **Read Latency (p99)** | Sub-5ms (indexed single-row); Degrades with joins under concurrency. | Sub-1ms (In-Memory) to Sub-5ms (SSD-backed). | 2ms - 10ms (Index bounded). | Sub-5ms at high write/read concurrent loads. | 5ms - 25ms (Consensus overhead on cross-region reads). |
| **Write Latency (p99)** | 5ms - 15ms (Write-Ahead Log + B-Tree random disk mutations). | Sub-1ms (Redis) to Sub-5ms (DynamoDB append-only commit logs). | 5ms - 15ms (WiredTiger journal sync). | Sub-2ms (Pure sequential write to CommitLog + MemTable). | 10ms - 50ms (Multi-node consensus round-trips). |
| **Failure Domain** | Single Master failover (Promotion delay: 10s-60s via Patroni/Orchestrator). | Node failure auto-healed via hash-ring failover (<1s - 5s). | Primary-Replica Set failover window (typically 2s - 12s via Raft-like election). | Zero downtime. Quorum writes/reads mask dead nodes (`R + W > N`). | Range-level re-election (<3s). Zero operational downtime. |
| **Worst-Case Anti-Pattern** | High-velocity unbounded append-only logs (Table bloat, vacuum freeze). | Complex multi-attribute filtering or aggregate analytics. | Deep nested schema joins requiring `$lookup` across massive collections. | Ad-hoc analytics without partition keys; Frequent update mutations to column names. | Latency-critical sub-millisecond edge transactions. |

### 1.2 Decision Flow Framework

```
Start Persistence Selection
│
├── Do you require ACID transactions across disparate business entities?
│   ├── YES ──> Do you require global distribution with > 10,000 write ops/sec?
│   │           ├── YES ──> Choose NewSQL (CockroachDB, Spanner)
│   │           └── NO  ──> Choose Relational (PostgreSQL, MySQL via Aurora/Patroni)
│   │
│   └── NO  ──> What is the dominant access pattern?
│               ├── Key-based lookups with sub-millisecond SLA? 
│               │   └── Choose Key-Value (Redis, DynamoDB)
│               │
│               ├── Highly flexible/polymorphic schema with nested hierarchies?
│               │   └── Choose Document (MongoDB)
│               │
│               └── Massive append rates (IoT, Time-Series, Audits) with predictable queries?
│                   └── Choose Wide-Column (ScyllaDB, Cassandra)
```

---

## 2. Distributed Caching Architecture & Invalidation Strategies

Caching is an optimization that introduces cache-coherency liabilities. A cache should never be introduced without defining eviction, synchronization patterns, and stampede mitigation strategies.

### 2.1 Caching Topologies & Write Strategies

```
Cache-Aside (Lazy Loading)     Write-Through                 Write-Back (Write-Behind)
App -> Cache (Miss)            App -> Cache                  App -> Cache (Immediate Ack)
App -> DB                      Cache -> DB (Synchronous)     Cache -> Queue/Worker -> DB (Async)
App -> Cache (Populate)
```

| Pattern | Write Latency | Read Latency | Consistency Window | Failure Recovery Risk | Implementation Complexity |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cache-Aside** | High (Writes directly to DB, invalidates Cache). | Medium (p99 spikes on cache misses). | Eventual (Dependent on TTL or cache invalidation events). | Zero data loss (DB is source of truth). Cache rebuilds on demand. | Low |
| **Write-Through** | High (Payload written to Cache AND Database before returning 200 OK). | Low (Data is guaranteed to exist in cache on subsequent read). | High (Cache and DB strictly identical). | Minimal data loss risk. Cache write failure aborts DB transaction. | Medium |
| **Write-Back (Write-Behind)** | Ultra-Low (Writes to memory buffer; DB written asynchronously via batch). | Ultra-Low (Served entirely from high-speed memory layer). | Low (Eventual consistency bounded by drain queue latency). | **Catastrophic data loss risk** if cache node crashes before flushing dirty pages. | High (Requires persistent queues, de-duplication, dirty-bit tracking). |
| **Refresh-Ahead** | Neutral (Standard write path). | Ultra-Low (Cache auto-reloads hot keys ahead of TTL expiration). | Eventual (Bounded by predictive algorithm accuracy). | Zero data loss. Consumes excess compute/database connections if misconfigured. | High |

### 2.2 Cache Invalidation & Stampede Mitigation: Probabilistic Early Expiration (XFetch)

The classic "Thundering Herd" or "Cache Stampede" occurs when a high-traffic key expires, causing hundreds of concurrent requests to hit the database simultaneously. 

The **XFetch Algorithm** (Vattani et al.) uses probabilistic early expiration to trigger a background refresh *before* the key expires, scaling dynamically with current read traffic.

$$\text{Read Condition:} \quad -\beta \cdot \delta \cdot \ln(\text{random}()) > \text{TTL} - \text{now}()$$

Where:
*   $\beta > 0$: Aggressiveness factor (higher values refresh earlier; default is $1.0$).
*   $\delta$: Delta compute time (milliseconds taken by the underlying database query).
*   $\text{random}()$: Uniform random variable $U(0, 1)$.

#### Production Implementation: Probabilistic Cache (Python 3.11+)

```python
import math
import random
import time
from typing import Any, Callable, Optional, Tuple
import redis

class ProbabilisticCache:
    def __init__(self, redis_client: redis.Redis, default_beta: float = 1.0):
        self.client = redis_client
        self.default_beta = default_beta

    def get_or_compute(
        self,
        key: str,
        ttl_seconds: int,
        compute_fn: Callable[[], Any],
        beta: Optional[float] = None
    ) -> Any:
        beta = beta or self.default_beta
        current_time = time.time()
        
        # Redis Hash Structure: 
        # HSET key:payload -> value
        # HSET key:metadata -> expiry:float, delta:float
        pipe = self.client.pipeline()
        pipe.hget(f"cache:{key}", "value")
        pipe.hget(f"cache:{key}", "expiry")
        pipe.hget(f"cache:{key}", "delta")
        value, expiry, delta = pipe.execute()

        should_recompute = False

        if value is None or expiry is None or delta is None:
            should_recompute = True
        else:
            expiry = float(expiry)
            delta = float(delta)
            time_to_expire = expiry - current_time
            
            # XFetch probabilistic test
            # If random() == 0, log is undefined, clamp min to 1e-10
            rand_val = max(random.random(), 1e-10)
            if -beta * delta * math.log(rand_val) > time_to_expire:
                should_recompute = True

        if should_recompute:
            # Acquire lightweight Redis lock to prevent concurrent re-computation
            lock_key = f"lock:{key}"
            acquired = self.client.set(lock_key, "1", nx=True, ex=10)
            
            if acquired or value is None:
                try:
                    start_time = time.time()
                    fresh_value = compute_fn()
                    delta = time.time() - start_time
                    expiry = time.time() + ttl_seconds
                    
                    # Store data atomically with underlying system TTL as a backstop
                    p = self.client.pipeline()
                    p.hset(f"cache:{key}", mapping={
                        "value": str(fresh_value),
                        "expiry": str(expiry),
                        "delta": str(delta)
                    })
                    # Set physical Redis TTL to 2x logical TTL to allow graceful recomputation
                    p.expire(f"cache:{key}", ttl_seconds * 2)
                    p.execute()
                    
                    return fresh_value
                finally:
                    if acquired:
                        self.client.delete(lock_key)
            else:
                # Another worker is refreshing; return stale data safely
                return value.decode("utf-8") if isinstance(value, bytes) else value

        return value.decode("utf-8") if isinstance(value, bytes) else value
```

### 2.3 Cache Eviction Strategy Profiles

*   **Least Recently Used (LRU):** Evicts items not accessed for the longest duration. Uses a Doubly Linked List + Hash Map ($O(1)$ read/write). Ideal for temporal locality (e.g., social feeds). Vulnerable to complete cache pollution under batch table scans.
*   **Least Frequently Used (LFU):** Evicts items with the lowest access frequency counter. Uses logarithmic count-min sketches or min-heaps ($O(1)$ amortized). Prevents scan pollution, but suffers from historic counter accumulation (stale items that were once hot remain in cache). Mitigation: Counter decay algorithms.
*   **Two-Queue (2Q) / Adaptive Replacement Cache (ARC):** Dynamically self-tunes between LRU (recency) and LFU (frequency). Tuning-free and immune to scan pollution. Use in systems with variable, unpredictable multi-tenant workloads.

---

## 3. Asynchronous Messaging & Streaming Selection Matrix

Message systems are divided into two fundamental architectures: **Log-Centric Streaming Engines** (dumb broker, smart consumer) and **JMS/AMQP Smart Brokers** (smart broker, dumb consumer).

### 3.1 Architectural Matrix: Kafka vs. RabbitMQ vs. Apache Pulsar vs. SQS

| Dimension | Apache Kafka | RabbitMQ | Apache Pulsar | AWS SQS (Standard/FIFO) |
| :--- | :--- | :--- | :--- | :--- |
| **Core Architecture** | Distributed Append-Only Commit Log. Partitions mapped to disk segments. | Erlang AMQP Router. Exchange to Queue binding with in-memory buffers. | Tiered storage: Compute (Pulsar brokers) decoupled from Storage (BookKeeper). | Proprietary multi-tenant cloud message queue. Managed HTTP-based polling. |
| **Message Consumption** | **Pull-based:** Consumers track offset pointers against static log. | **Push-based:** Broker dispatches directly to connected consumer TCP sockets. | **Hybrid:** Pull for bulk batch streams; Push for real-time pub/sub consumers. | **Pull-based:** Explicit long-polling via `ReceiveMessage` API. |
| **Ordering Guarantees** | Strict per-partition ordering. No global ordering across partitions. | Total ordering within a single queue without priority/concurrency settings. | Strict per-partition ordering. Key_Shared mode provides strict per-key ordering. | FIFO: Strict per `MessageGroupId`. Standard: Best-effort (out-of-order possible). |
| **Message Deduplication** | Idempotent Producer (`PID` + sequence numbers); End-to-end transactional API. | No native deduplication. Application must manage message IDs via cache/store. | Native broker-level deduplication via producer sequence IDs. | FIFO: Native 5-minute deduplication window via SHA-256 hash or Deduplication ID. |
| **Retention & Playback** | Immutable retention (Time/Size bounded or Compacted). Full historical playback. | Ephemeral: Messages deleted immediately upon Consumer ACK. No native replay. | Infinite retention via tiered storage offload (S3/GCS). Full log playback. | Maximum 14-day retention. Deleted immediately upon `DeleteMessage` call. No replay. |
| **Throughput (Single Node)** | 100,000 to 1,000,000+ msgs/sec (zero-copy OS page cache to network). | 20,000 to 50,000 msgs/sec (CPU bound by Erlang context switching). | 100,000 to 500,000 msgs/sec (Decoupled write paths via BookKeeper). | Managed: Scaled automatically (Standard: Nearly unlimited; FIFO: 3,000/sec with batching). |
| **p99 Latency Profile** | 5ms - 25ms (Optimized for micro-batching throughput over raw latency). | <1ms - 3ms (Instant push mechanics; minimal buffering). | 5ms - 15ms (Pipelined write acknowledgments via Bookies). | 15ms - 50ms (Dominated by HTTP API transport overhead). |

### 3.2 Production Failure Modes & Operational Mitigations

#### 1. Split-Brain in Dynamic Clustered Brokers
*   **The Failure:** Network partition divides cluster. Both partitions accept writes, causing divergent state and data loss during reunification.
*   **Mitigation Strategy:** Set `min.insync.replicas` to $\lfloor N/2 \rfloor + 1$ (quorum). In Kafka: Set `acks=all`, configure Raft metadata quorum (KRaft) across 3 or 5 separate fault domains. Never run an even number of consensus voting nodes.

#### 2. Head-of-Line Blocking via Poison Pill Messages
*   **The Failure:** A malformed payload crashes consumer logic, consumer fails to ACK, broker re-delivers payload indefinitely, halting partition processing.
*   **Mitigation Blueprint:** Non-blocking Dead Letter Queue (DLQ) pattern with bounded retries.

```
Incoming Stream ──> Consumer Process ──(Success)──> Commit Offset
                         │
                      (Failure)
                         │
                         ▼
             Retry Topic (Backoff N <= 3)
                         │
                  (Exceeded Max)
                         │
                         ▼
              Dead Letter Queue (DLQ) ──> Alert & Human Remediation
```

#### 3. Idempotent Consumer Implementation (De-duplication Ledger)

Consumers will receive duplicate messages under network partitions, re-balancing events, or consumer restarts. Every distributed consumer must be idempotent.

```sql
-- PostgreSQL Transactional Outbox / Inbound Deduplication Schema
CREATE TABLE consumer_idempotency_ledger (
    message_id VARCHAR(255) PRIMARY KEY,
    consumer_group VARCHAR(100) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    response_payload JSONB
);

-- Atomically check and execute within the business database transaction:
BEGIN;

INSERT INTO consumer_idempotency_ledger (message_id, consumer_group)
VALUES ('msg_order_99824_phase2', 'order-fulfillment-service')
ON CONFLICT (message_id) DO NOTHING;

-- If rows affected == 0, abort immediately (message was already processed):
-- Otherwise, execute business logic safely:
UPDATE user_balances SET balance = balance - 150.00 WHERE user_id = 'usr_334';
INSERT INTO audit_logs (event, timestamp) VALUES ('CHARGE_PROCESSED', NOW());

COMMIT;
```

---

## 4. Inter-Service & Client Communication Protocols

The choice of protocol defines networking overhead, CPU serialization cost, payload size, and schema evolvability.

### 4.1 Comparative Analysis

| Protocol | Transport | Serialization Format | Multiplexing | Streaming | Latency Overhead | Strict Schemas |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **gRPC** | HTTP/2 or HTTP/3 | Protocol Buffers (Binary) | Native (Single TCP connection handles concurrent streams) | Bidirectional (Unary, Client, Server, BiDi) | Ultra-Low (Compact binary payloads, minimal parsing overhead) | Enforced via `.proto` compiler definitions |
| **GraphQL** | HTTP/1.1 or HTTP/2 | JSON (Text) | Depends on underlying HTTP version | Subscriptions (via WebSockets or SSE) | Medium (Server-side AST parsing and field resolution overhead) | Enforced via SDL (Schema Definition Language) |
| **REST** | HTTP/1.1 or HTTP/2 | Typically JSON / XML (Text) | Depends on underlying HTTP version | Limited (Chunked Transfer Encoding) | Medium (Textual parsing, verbose headers, repeated connection handshakes) | Optional (OpenAPI/Swagger; decoupled from execution) |
| **WebSockets**| TCP (Framed) | Binary or Text | No (Single full-duplex byte channel per connection) | Full Duplex Continuous Streaming | Ultra-Low (Minimal 2 to 10-byte framing overhead post-handshake) | No native schema layer (Requires custom envelope) |
| **SSE (Server-Sent Events)** | HTTP/1.1 or HTTP/2 | Text (`text/event-stream`) | Native on HTTP/2 | Unidirectional (Server-to-Client only) | Low (Lightweight text framing, auto-reconnect supported) | No native schema layer |

### 4.2 Network Footprint & Payload Comparison

Identical entity serialized across protocols highlights the raw byte footprint efficiency:

```json
// JSON Payload (REST / GraphQL): 112 bytes (uncompressed)
{
  "user_id": 8941235,
  "user_name": "alex_architect",
  "account_status": "ACTIVE",
  "roles": ["read", "write", "admin"]
}
```

```protobuf
// Protocol Buffer Schema (gRPC)
syntax = "proto3";
package identity.v1;

enum AccountStatus {
  ACCOUNT_STATUS_UNSPECIFIED = 0;
  ACTIVE = 1;
  SUSPENDED = 2;
  DELETED = 3;
}

message UserProfileResponse {
  uint64 user_id = 1;
  string user_name = 2;
  AccountStatus account_status = 3;
  repeated string roles = 4;
}

// Wire serialization output: 38 bytes (66% bandwidth reduction vs raw JSON)
// Binary wire layout:
// 08 B3 D8 A1 04 12 0E 61 6C 65 78 5F 61 72 63 68 69 74 65 63 74 18 01 22 04 72 65 61 64 22 05 77 72 69 74 65 22 05 61 64 6D 69 6E
```

### 4.3 Protocol Selection Flowchart

*   **Internal Service-to-Service (East-West Traffic):** **gRPC**. Maximizes throughput, enforces strict compile-time types, minimizes CPU utilization on serialization/deserialization via Protobuf, and enables HTTP/2 streaming.
*   **External Public Developer APIs (North-South Traffic):** **REST over OpenAPI**. Maximizes compatibility with third-party tools, leverages ubiquitous browser caching, and handles corporate firewalls blocking HTTP/2 multiplexing.
*   **Complex Aggregation Frontends (BFF Pattern):** **GraphQL**. Eliminates over-fetching/under-fetching across composite frontends (Mobile/Web), consolidating dozens of backend microservice calls into a single query.
*   **Live Bi-Directional Streaming (Chat, Collaborative Canvas, Gaming):** **WebSockets**. Lowest bi-directional latency without HTTP overhead.
*   **Live Server-to-Client Unidirectional Updates (Market Tickers, Notification Feeds):** **SSE (Server-Sent Events)**. Runs cleanly over standard HTTP, bypasses proxy connection limits via HTTP/2, and provides built-in browser reconnection mechanics out-of-the-box.

---

## 5. Distributed Rate Limiting & Traffic Shaping Engines

Rate limiters protect down-stream distributed services from Cascading Failure, resource exhaustion, and Denial of Service.

### 5.1 Algorithmic Trade-off Analysis

| Algorithm | Memory Consumption | Processing Complexity | Burst Handling Capability | Boundary Traffic Spikes |
| :--- | :--- | :--- | :--- | :--- |
| **Token Bucket** | Minimal ($O(1)$ state per user: Counter + Timestamp). | Low (Simple math on evaluation). | **High**: Allows bursts up to bucket capacity while enforcing replenishment rate. | Smooths egress traffic smoothly. |
| **Leaky Bucket** | Low ($O(1)$ state if counter; $O(N)$ if queue-based). | Low-Medium (Requires queue or time-leak calculation). | **Zero**: Enforces perfectly smooth, constant egress rate; buffers or drops excess. | Eliminates bursts entirely. Ideal for data egress to rate-limited third-party APIs. |
| **Fixed Window Counter** | Absolute Minimal ($O(1)$ integer counter per time window). | Minimal ($O(1)$ atomic increment). | **Uncontrolled**: Susceptible to $2\times$ traffic burst at window boundaries. | **Critical Flaw**: $2\times$ rate limit can cross boundary (e.g., end of min 1, start of min 2). |
| **Sliding Window Log** | Extreme ($O(N)$ entries per user, where $N$ is count of requests in window). | High (Memory cleanups require range deletions: `ZREMRANGEBYSCORE`). | **High**: Perfectly accurate rate limiting. Zero boundary anomalies. | Flawless accuracy, but will crash Redis under massive traffic surges. |
| **Sliding Window Counter** | Minimal ($O(1)$ memory: stores current and previous window counts). | Low (Interpolates weighted count based on percentage of current window). | **Medium**: Balances boundary smoothing with fixed memory footprints. | Approximates sliding window with $<0.05\%$ variance. Ideal balance for production. |

### 5.2 Production Redis Sliding Window Counter (Atomic Lua Script)

This production-grade script implements an atomic **Sliding Window Counter** inside Redis. It interpolates between the previous window and the current window to prevent boundary spikes while maintaining an $O(1)$ memory footprint.

```lua
-- KEYS[1]: Base rate limiter key (e.g., 'ratelimit:user_81273')
-- ARGV[1]: Max requests allowed in window
-- ARGV[2]: Window size in seconds (e.g., 60)
-- ARGV[3]: Current UNIX timestamp in seconds (passed by caller to ensure sync)

local rate_limit_key = KEYS[1]
local max_requests = tonumber(ARGV[1])
local window_size = tonumber(ARGV[2])
local current_timestamp = tonumber(ARGV[3])

-- Determine the current and previous sub-window keys based on integer division
local current_window_bucket = math.floor(current_timestamp / window_size)
local prev_window_bucket = current_window_bucket - 1

local cur_key = rate_limit_key .. ":" .. current_window_bucket
local prev_key = rate_limit_key .. ":" .. prev_window_bucket

-- Fetch counts from Redis
local current_count = tonumber(redis.call("GET", cur_key) or "0")
local prev_count = tonumber(redis.call("GET", prev_key) or "0")

-- Calculate weight of previous window:
-- Example: If window is 60s, and we are 15s into current window:
-- weight = (60 - 15) / 60 = 0.75
local time_into_current_window = current_timestamp % window_size
local prev_weight = (window_size - time_into_current_window) / window_size
local estimated_count = math.floor(prev_count * prev_weight + current_count)

if estimated_count >= max_requests then
    -- Rate limit exceeded
    local retry_after = window_size - time_into_current_window
    return {0, tostring(max_requests), tostring(max_requests - estimated_count), tostring(retry_after)}
else
    -- Under limit: Increment current window counter atomically
    local new_count = redis.call("INCRBY", cur_key, 1)
    if new_count == 1 then
        -- Set TTL to 2x window size to allow accurate interpolation for next cycle
        redis.call("EXPIRE", cur_key, window_size * 2)
    end
    
    local remaining = max_requests - (estimated_count + 1)
    local reset_in = window_size - time_into_current_window
    return {1, tostring(max_requests), tostring(math.max(0, remaining)), tostring(reset_in)}
end
```

### 5.3 Standard HTTP Response Headers (IETF Draft Compliant)

When building an enterprise rate-limiting reverse proxy (e.g., in Envoy, Kong, or custom API Gateways), you must return standard RFC-compliant headers:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json; charset=utf-8
Retry-After: 45
RateLimit-Limit: 1000
RateLimit-Remaining: 0
RateLimit-Reset: 45

{
  "error": {
    "code": "TOO_MANY_REQUESTS",
    "message": "API rate limit exceeded. Retry in 45 seconds.",
    "retry_after_seconds": 45
  }
}
```

When under the limit, mirror the state back on every successful response:

```http
HTTP/1.1 200 OK
RateLimit-Limit: 1000
RateLimit-Remaining: 742
RateLimit-Reset: 18
```

---

## 6. Component Selection Synthesis Blueprint

Use this architectural cheatsheet to justify cross-component system designs in distributed scale scenarios:

```
                  ┌──────────────────────────────────────────────┐
                  │              Incoming Client                 │
                  │        (Mobile / Web / Third-Party)          │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         │ [TLS 1.3 / HTTP/2 or 3]
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │             Global API Gateway               │
                  │  - Envoy Proxy / Kong                        │
                  │  - Distributed Rate Limiting (Redis Sliding) │
                  │  - Auth Validation / JWT Decryption          │
                  └───────┬──────────────────────────────┬───────┘
                          │                              │
             gRPC (Intra-Cluster)              GraphQL / REST (BFF)
                          │                              │
                          ▼                              ▼
      ┌─────────────────────────────────────┐  ┌───────────────────────────────────┐
      │       Core Domain Services          │  │       Aggregator Services         │
      │  (Go / Java / Rust Microservices)   │  │       (Node.js / Go BFF)          │
      └───────────┬─────────────────────────┘  └─────────────────┬─────────────────┘
                  │                                              │
         Write    │         Read                                 │
         Path     ├──────────────────────┐                       │
                  ▼                      ▼                       │
      ┌──────────────────────┐  ┌─────────────────┐              │
      │   Database Primary   │  │ Cache Cluster   │◄─────────────┘
      │  - PostgreSQL/NewSQL │  │ - Redis Cluster │ (Cache-Aside + XFetch)
      │  - Strict ACID       │  │ - 2Q/ARC Evict  │
      └───────────┬──────────┘  └─────────────────┘
                  │
                  │ CDC (Debezium / DynamoDB Streams)
                  ▼
      ┌──────────────────────┐
      │   Streaming Engine   │
      │  - Apache Kafka      │
      │  - Strict Ordering   │
      └───────────┬──────────┘
                  │
                  ├──────────────────────────────┐
                  ▼                              ▼
      ┌──────────────────────┐        ┌──────────────────────┐
      │ Real-time Analytics  │        │   Async Processing   │
      │ - ClickHouse / Druid │        │ - Workers / DLQ      │
      └──────────────────────┘        │ - RabbitMQ / SQS     │
                                      └──────────────────────┘
```

### Component Rules of Thumb
1. **Never use distributed transactions (2PC)** across disparate domains; implement the Saga pattern with compensating actions driven by an immutable event log (Kafka).
2. **Never expose internal storage details or gRPC endpoints directly to external browsers**; front them with an API Gateway converting to REST/JSON or GraphQL with decoupled public contracts.
3. **Always set physical Redis TTLs higher than logical application
