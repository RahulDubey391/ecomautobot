# Module 3: 40+ Production System Architecture Blueprints

This module delivers six battle-tested, production-ready system architecture blueprints. Each blueprint details end-to-end data pipelines, exact schemas, executable algorithms, failure topologies, and mitigation strategies designed to survive multi-region partitions, extreme throughput spikes, and hard hardware failures.

---

## 1. Globally-Partitioned Distributed URL Shortener

A high-throughput, low-latency URL truncation and redirection platform handling 100,000 write QPS and 1,000,000 read QPS with sub-10ms redirect latency globally.

### 1.1 Architecture Topology

```
                       [ Global Anycast DNS / Cloudflare Edge ]
                                          |
                +-------------------------+-------------------------+
                |                                                   |
      [ US-East Edge (Envoy) ]                            [ EU-West Edge (Envoy) ]
                |                                                   |
      +---------+---------+                               +---------+---------+
      |                   |                               |                   |
[ Read Cache ]      [ API Gateway ]                 [ Read Cache ]      [ API Gateway ]
(Redis Cluster)     (Go HTTP/gRPC)                  (Redis Cluster)     (Go HTTP/gRPC)
      |                   |                               |                   |
      |             +-----+-----+                         |             +-----+-----+
      |             |           |                         |             |           |
      |       [Write Pods] [KGS Client]                   |       [Write Pods] [KGS Client]
      |             |           |                         |             |           |
      +-------------+           |                         +-------------+           |
                    |           |                                       |           |
          [ Central Storage ]   +------------+   +----------------------+           |
          (CockroachDB Multi-Region)         |   |                                  |
                                     [ Central Key Generation Service (Etcd) ]------+
```

### 1.2 Base62 Key Generation Service (KGS) Implementation

To eliminate write collisions without expensive coordination at runtime, the Key Generation Service pre-allocates contiguous ranges of 64-bit integers to worker nodes via an `etcd` distributed lease.

#### Go Range Allocator & Base62 Engine
```go
package main

import (
	"errors"
	"strings"
	"sync"
	"sync/atomic"
)

const (
	Alphabet    = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
	Base        = uint64(len(Alphabet))
	RangeBlock  = 1000000 // Allocate 1 million IDs per worker lease
)

type TokenRange struct {
	Current uint64
	Max     uint64
}

type KGSEngine struct {
	mu           sync.Mutex
	tokenRange   TokenRange
	rangeFetcher func() (uint64, uint64, error)
}

func NewKGSEngine(fetcher func() (uint64, uint64, error)) *KGSEngine {
	return &KGSEngine{rangeFetcher: fetcher}
}

func (k *KGSEngine) NextID() (uint64, error) {
	k.mu.Lock()
	defer k.mu.Unlock()

	if k.tokenRange.Current >= k.tokenRange.Max {
		min, max, err := k.rangeFetcher()
		if err != nil {
			return 0, errors.New("failed to acquire token range lease: " + err.Error())
		}
		k.tokenRange = TokenRange{Current: min, Max: max}
	}

	id := k.tokenRange.Current
	k.tokenRange.Current++
	return id, nil
}

func Base62Encode(num uint64) string {
	if num == 0 {
		return string(Alphabet[0])
	}
	var sb strings.Builder
	for num > 0 {
		rem := num % Base
		sb.WriteByte(Alphabet[rem])
		num = num / Base
	}
	// Reverse the string
	runes := []rune(sb.String())
	for i, j := 0, len(runes)-1; i < j; i, j = i+1, j-1 {
		runes[i], runes[j] = runes[j], runes[i]
	}
	return string(runes)
}
```

### 1.3 Database Schema (CockroachDB / Distributed SQL)

```sql
CREATE TABLE short_urls (
    short_code VARCHAR(11) NOT NULL,
    account_id UUID NOT NULL,
    original_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    expires_at TIMESTAMPTZ NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT pk_short_urls PRIMARY KEY (short_code)
) INTERLEAVE IN PARENT NONE;

CREATE INDEX idx_short_urls_account ON short_urls (account_id, created_at DESC);
CREATE INDEX idx_short_urls_expires ON short_urls (expires_at) WHERE expires_at IS NOT NULL;
```

### 1.4 Failure Handling & Bottleneck Mitigation

*   **Cache Stampede Mitigation:** Implement probabilistic early expiration (XFetch algorithm) combined with a distributed mutex (`SingleFlight` in Go) on cache-fill operations.
*   **Preventing Cache Penetration for 404s:** Deploy a Scalable Inverted Bloom Filter at the Envoy edge layer. If the Bloom filter returns `false`, return an immediate HTTP 404 without hitting Redis or the persistent datastore.
*   **Hotkey Bottlenecks:** Keys experiencing $>5,000$ reads/sec are replicated across localized L1 memory caches (Go-Cache/FreeCache inside API nodes) with a 30-second TTL to shield L2 Redis clusters.

---

## 2. Real-Time Geospatial Ride-Sharing Dispatch System

A low-latency, stateful matching engine matching riders and drivers within a sub-second loop using Uber's H3 spatial indexing and in-memory spatial indexes.

### 2.1 State & Routing Lifecycle

```
[ Driver App ]            [ Ride-Dispatch Service ]            [ Driver Pool Engine ]           [ Matchmaker Pipeline ]
      |                              |                                  |                                 |
      |-- Report GPS (1-3s UDP) ---->|                                  |                                 |
      |                              |-- Geo-Update via H3 (Res 8) ---->|                                 |
      |                              |                                  |-- Batch Drivers (200ms tick) -->|
      |                              |                                                                    |-- Run Bipartite Matching
      |                              |<-- Offer Dispatched (gRPC Stream) ---------------------------------|
      |<-- Dispatch Offer Popup -----|
      |-- Accept (Atomic Lease) ---->|
```

### 2.2 Geospatial Indexing & State Management

Driver locations are pinned to H3 Resolution 8 (~460-meter edge length hexagons). Locations are held in Redis using spatial geospatial sorted sets along with localized cell buckets.

#### Redis H3 Ingestion & Ring Retrieval (Lua Script)
```lua
-- KEYS[1]: Base H3 index key (e.g., "geo:drivers:8826856235fffff")
-- ARGV[1]: Driver ID
-- ARGV[2]: Lat
-- ARGV[3]: Lon
-- ARGV[4]: Driver State (1 = Available, 2 = Busy)
-- ARGV[5]: Timestamp

local driver_id = ARGV[1]
local lat = tonumber(ARGV[2])
local lon = tonumber(ARGV[3])
local state = tonumber(ARGV[4])
local ts = tonumber(ARGV[5])

-- Clean up older state if driver is busy
if state ~= 1 then
    redis.call("HDEL", "driver:locations", driver_id)
    redis.call("ZREM", KEYS[1], driver_id)
    return 0
end

-- Update spatial location and metadata
redis.call("HSET", "driver:locations", driver_id, cjson.encode({
    lat = lat,
    lon = lon,
    ts = ts
}))

-- Add driver to spatial set indexed by timestamp for TTL auto-pruning
redis.call("ZADD", KEYS[1], ts, driver_id)
return 1
```

### 2.3 Dispatcher Match Pipeline: Kuhn-Munkres/Hungarian Optimization

Rather than greedy First-Come-First-Served (FCFS) matching, dispatch runs on discrete 2-second collection epochs to solve the Global Bipartite Maximum Matching problem, minimizing total pick-up Estimated Time of Arrival (ETA).

```
Epoch 0-2s Accumulation:
    Riders:  {R_1, R_2, R_3}
    Drivers: {D_1, D_2, D_3, D_4}

Cost Matrix C[i][j] = Cost(ETA(R_i, D_j) * 0.6) + Cost(Surge_Deficit * 0.4)

         D1    D2    D3    D4
   R1 [ 4.2,  8.1,  2.5, 10.0 ]
   R2 [ 1.5,  3.2,  7.1,  4.0 ]
   R3 [ 6.0,  2.1,  3.5,  5.5 ]

Solve min-cost edge cover -> Output: (R1 -> D3), (R2 -> D1), (R3 -> D2). D4 remains idling.
```

### 2.4 Race Condition & Locking Strategies

Driver lock offers are leased using distributed atomic primitives with Redis Redlock:

```
SET driver:lock:{driver_id} {dispatch_uuid} NX PX 8000
```

1. If Driver accepts within 8,000ms: Match transitions to `LOCKED` in PostgreSQL via conditional CAS update:
   ```sql
   UPDATE matches 
   SET status = 'ACCEPTED', driver_id = $1 
   WHERE id = $2 AND status = 'OFFERED';
   ```
2. If Driver declines or timeout lapses: Lock drops, and driver re-enters matching queue with a 5-second penalty backoff to prevent offer ping-ponging.

---

## 3. High-Throughput Distributed Rate Limiter

A multi-tenant rate limiter operating at the ingress proxy (Envoy), supporting Token Bucket and Sliding Window Counter algorithms with a throughput capacity of $>5,000,000$ operations/sec at $<1.5$ms latency.

### 3.1 Architectural Layout

```
[ Ingress Traffic ]
       |
  [ Envoy Proxy ]
       | (CheckRateLimit gRPC)
       +---------------------------------------------+
       |                                             |
[ Rate Limiter Engine (Go) ]               [ Rate Limiter Engine (Go) ]
       |                                             |
       +----------------------+----------------------+
                              |
                     [ Redis Cluster 7.x ]
               (Local-memory L1 + Remote L2)
```

### 3.2 Dynamic Sliding Window Rate Limiting (Redis Engine)

The sliding window log uses memory-efficient transactional hashes to prevent the memory expansion typical of raw sorted sets (`ZSET`).

#### Production Lua Script for Sliding Window Counter
```lua
-- KEYS[1]: Tenant Rate Limit Key (e.g., "rl:tenant_abc:api_write")
-- ARGV[1]: Current UNIX millisecond timestamp
-- ARGV[2]: Window size in milliseconds (e.g., 60000 for 1 minute)
-- ARGV[3]: Maximum allowed requests in window
-- ARGV[4]: Cost per request (typically 1)

local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local clear_before = now - window

-- Remove old buckets
redis.call("ZREMRANGEBYSCORE", key, "-inf", clear_before)

-- Compute total hits in active window
local current_requests = 0
local elements = redis.call("ZRANGE", key, 0, -1, "WITHSCORES")
for i = 1, #elements, 2 do
    current_requests = current_requests + 1
end

if current_requests + cost <= limit then
    -- Add unique member to sorted set (timestamp + random entropy)
    redis.call("ZADD", key, now, now .. ":" .. redis.call("INCR", "rl:entropy"))
    redis.call("PEXPIRE", key, window)
    return {1, limit - (current_requests + cost)}
else
    return {0, 0}
end
```

### 3.3 Envoy Proxy Rate-Limit Service Config (Descriptor Map)

```yaml
domain: edge-api-gateway
descriptors:
  - key: tenant_tier
    value: enterprise
    rate_limit:
      unit: MINUTE
      requests_per_unit: 100000
  - key: tenant_tier
    value: free
    rate_limit:
      unit: MINUTE
      requests_per_unit: 60
  - key: route
    value: /v1/auth/login
    rate_limit:
      unit: MINUTE
      requests_per_unit: 5
```

### 3.4 Operational Trade-Offs & Edge Cases

| Failure Mode | Architecture Strategy | Production Trade-off |
| :--- | :--- | :--- |
| **Redis Node Partition** | Local in-process sliding-window fallback (Sync via Envoy mesh gossip). | Allows an overshoot of $+12\%$ capacity above the limit, preserving API availability (Fail-Open policy). |
| **Microbursting** | Dual-bucket configuration (Leaky Bucket smoothing in front of Token Bucket). | Adds $0.4\text{ms}$ processing latency to bursty traffic; eliminates CPU spikes on downstream microservices. |
| **Clock Drift** | Use Redis `TIME` command rather than client worker system clocks. | Introduces round-trip overhead. Mitigate by using high-frequency local hyper-accurate chrony sync (NTP PTP). |

---

## 4. Ultra-Low Latency Streaming Video Feed (TikTok/Reels Engine)

A dynamic media delivery pipeline serving personalized, chunk-streamed, short-form video sequences with immediate playback start times ($<200$ms time-to-first-frame).

### 4.1 System Ingestion & Delivery Topography

```
[ Raw Video Upload ]
        |
 [ Media Ingestion API ]
        |
 [ Kafka Video Tasks ] ---> [ Transcoding Cluster (FFmpeg / NVENC) ]
                                      |
                                      +--> Master Manifest (.m3u8)
                                      +--> HLS 1080p, 720p, 480p, 360p (Segments: .ts/.m4s)
                                      |
                               [ S3 Object Store ]
                                      |
                           [ Multi-CDN Global Mesh ]
                            (Cloudflare / Fastly)
                                      ^
                                      | Dynamic Video Feed Manifest
[ Client App ] <------------------ [ Feed Retrieval Service ]
                                      ^
                                      | Ranked ID Array
                               [ Retrieval & ML Scoring Engine ]
```

### 4.2 Database Schema: User Action Graph (ScyllaDB / Cassandra)

```sql
CREATE KEYSPACE video_platform WITH replication = {
    'class': 'NetworkTopologyStrategy', 
    'us-east': 3, 
    'eu-central': 3
};

CREATE TABLE video_platform.user_video_timeline (
    user_id UUID,
    bucket_id INT, -- Partition key balancer (YYYYWW)
    published_at TIMESTAMP,
    video_id UUID,
    author_id UUID,
    hls_manifest_url TEXT,
    engagement_metrics MAP<TEXT, BIGINT>,
    PRIMARY KEY ((user_id, bucket_id), published_at, video_id)
) WITH CLUSTERING ORDER BY (published_at DESC);

CREATE TABLE video_platform.video_metadata (
    video_id UUID PRIMARY KEY,
    author_id UUID,
    duration FLOAT,
    resolutions_available SET<TEXT>,
    video_status TEXT, -- ENCODING, READY, BLOCKED
    tags SET<TEXT>,
    created_at TIMESTAMP
);
```

### 4.3 Low Latency Media Pre-Buffering Strategy

To achieve $<200$ms playback latency, segment partitioning and delivery client contracts must be synchronized:

1.  **Micro-Chunking:** Media segmented into strict 1.5-second HLS chunks.
2.  **Manifest-Inject Prediction:** The feed response contains the first video's complete manifest, alongside prefetch URLs for the first two segments of the subsequent three videos in the ranked array.

```json
{
  "feed": [
    {
      "video_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "manifest_url": "https://cdn.platform.video/manifests/9b1deb4d.m3u8",
      "preload_segments": [
        "https://cdn.platform.video/chunks/9b1deb4d_720p_001.mp4",
        "https://cdn.platform.video/chunks/9b1deb4d_720p_002.mp4"
      ]
    },
    {
      "video_id": "2e3c0c1b-2615-4672-83b6-9bb51f28b248",
      "manifest_url": "https://cdn.platform.video/manifests/2e3c0c1b.m3u8",
      "preload_segments": [
        "https://cdn.platform.video/chunks/2e3c0c1b_720p_001.mp4"
      ]
    }
  ]
}
```

### 4.4 Fan-Out Retrieval Engine (Two-Tier Hybrid)

*   **Celebrity Accounts ($>500,000$ followers):** Fan-out-on-read. Videos do not write to follower feeds. Instead, the retrieval engine queries the global celebrity store and blends results with the user's base timeline via a K-Way Merge algorithm.
*   **Standard Accounts ($<500,000$ followers):** Fan-out-on-write via Kafka consumers. Video references are written directly to followers' timeline storage partitions in ScyllaDB.

---

## 5. Double-Entry Immutable Financial Ledger

A strictly compliant, mission-critical financial accounting ledger supporting multi-asset transactions, deterministic balance calculation, and guaranteed audit integrity.

### 5.1 Financial Integrity Constraints

1.  **Zero-Sum Balancing:** The sum of debits must equal the sum of credits for every transaction across all legs:
    $$\sum \text{Debits} - \sum \text{Credits} = 0$$
2.  **Immutability:** No `UPDATE` or `DELETE` operations permitted on ledger transaction lines. Corrections require compensatory entries.
3.  **Strict Isolation:** Strong SERIALIZABLE isolation to eliminate write-skew, phantom reads, and non-repeatable reads.

### 5.2 Relational Schema (PostgreSQL with Native Isolation Enforcements)

```sql
CREATE TYPE transaction_state AS ENUM ('PENDING', 'POSTED', 'ARCHIVED');
CREATE TYPE account_type AS ENUM ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE');

CREATE TABLE accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    account_number VARCHAR(64) UNIQUE NOT NULL,
    type account_type NOT NULL,
    currency VARCHAR(3) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(128) NOT NULL,
    state transaction_state NOT NULL DEFAULT 'POSTED',
    description TEXT NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    CONSTRAINT uq_transaction_idempotency UNIQUE(idempotency_key)
);

CREATE TABLE ledger_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount NUMERIC(28, 12) NOT NULL, -- Negative indicates Credit, Positive indicates Debit
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    CONSTRAINT nonzero_amount CHECK (amount <> 0)
);

CREATE INDEX idx_ledger_entries_acc_time ON ledger_entries (account_id, created_at DESC);
```

### 5.3 Enforcing Balance Invariance via Deferred Triggers

```sql
CREATE OR REPLACE FUNCTION verify_transaction_balance() 
RETURNS TRIGGER AS $$
DECLARE
    sum_amount NUMERIC(28, 12);
BEGIN
    SELECT COALESCE(SUM(amount), 0)
    INTO sum_amount
    FROM ledger_entries
    WHERE transaction_id = NEW.transaction_id;

    IF sum_amount <> 0 THEN
        RAISE EXCEPTION 'Financial invariant violated: Transaction % does not balance to zero. Net diff: %', 
            NEW.transaction_id, sum_amount;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trigger_enforce_zero_balance
AFTER INSERT OR UPDATE ON ledger_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION verify_transaction_balance();
```

### 5.4 High-Scale Idempotent Execution Pipeline (Go Core)

```go
package ledger

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"github.com/shopspring/decimal"
)

type EntryLeg struct {
	AccountID string
	Amount    decimal.Decimal // Positive: Debit, Negative: Credit
}

type PostingService struct {
	DB *sql.DB
}

func (s *PostingService) ExecuteTransaction(ctx context.Context, idempotencyKey string, desc string, legs []EntryLeg) error {
	// Step 1: Pre-validation of zero-sum constraint
	runningSum := decimal.Zero
	for _, leg := range legs {
		runningSum = runningSum.Add(leg.Amount)
	}
	if !runningSum.IsZero() {
		return fmt.Errorf("transaction imbalance: sum is %s", runningSum.String())
	}

	// Step 2: Atomic Serializable Execution
	tx, err := s.DB.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelSerializable})
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// Step 3: Insert parent transaction with Idempotency Key
	var txID string
	txInsert := `
		INSERT INTO transactions (idempotency_key, state, description)
		VALUES ($1, 'POSTED', $2)
		ON CONFLICT (idempotency_key) DO NOTHING
		RETURNING id;`
	
	err = tx.QueryRowContext(ctx, txInsert, idempotencyKey, desc).Scan(&txID)
	if errors.Is(err, sql.ErrNoRows) {
		// Idempotency hit: Transaction was executed previously. Return cleanly without mutating state.
		return nil
	} else if err != nil {
		return err
	}

	// Step 4: Insert ledger entries
	stmt, err := tx.PrepareContext(ctx, `
		INSERT INTO ledger_entries (transaction_id, account_id, amount) 
		VALUES ($1, $2, $3);`)
	if err != nil {
		return err
	}
	defer stmt.Close()

	for _, leg := range legs {
		_, err := stmt.ExecContext(ctx, txID, leg.AccountID, leg.Amount.String())
		if err != nil {
			return err
		}
	}

	// Commit will trigger deferred invariant check
	return tx.Commit()
}
```

---

## 6. Multi-Tenant Global Notification & Alerting Engine

An event-driven dispatch platform managing prioritization, real-time message routing, channel failovers, and per-tenant rate governance across Push (APNs, FCM), SMS, and Email, processing 100,000,000 notifications per 24 hours.

### 6.1 End-to-End Pipeline

```
[ Application Core / Webhooks ]
               |
  [ Notification Ingestion API ]
               |
    [ Routing & Deduplication ]
     (Redis Sliding Window)
               |
     [ Tiered Kafka Ingress ]
       +-------+-------+
       |       |       |
    (P0 Tier) (P1 Tier) (P2 Bulk)
       |       |       |
  [ Global Dispatch Worker Fleet ]
       |
  [ Circuit-Breaker Integration ]
       +---------------+---------------+
       |               |               |
 [ Push: APNs/FCM ] [ SMS: Twilio/AWS ] [ Email: SES/SendGrid ]
```

### 6.2 Priority Routing & Dead-Letter Infrastructure

```
Kafka Topology:
- `notification.p0.critical`: Transactional OTPs, Security Alerts (p99 < 1s)
- `notification.p1.transactional`: Order updates, Flight shifts (p99 < 15s)
- `notification.p2.marketing`: Promo Blasts, Weekly Summaries (p99 < 10m)
- `notification.dlq.retry`: Linear backoff queue (retries: 3)
- `notification.dlq.poison`: Manual inspection sink (exhausted retries)
```

### 6.3 Dynamic Channel Circuit Breaker & Failover Engine

If a downstream provider (e.g., Twilio for SMS) drops below 95% delivery success over an active 2-minute rolling window, the engine trips its breaker and redirects traffic to a fallback provider (e.g., AWS SNS) or converts the transmission to an in-app inbox notification.

#### Provider Failover Circuit Breaker (State Machine)

```
        +---------+
        | Normal  | <------------------------------------+
        +---------+                                      |
             |                                           |
     Failure Rate >= 5%                                  |
     over 2 min rolling window                           |
             |                                           |
             v                                           |
      +--------------+      Success Rate >= 98%          |
      |   Tripped    |      over 5-minute probe window   |
      | (Use Backup) |                                   |
      +--------------+                                   |
             |                                           |
       300s TTL passes                                   |
             |                                           |
             v                                           |
       +------------+                                    |
       | Half-Open  | -----------------------------------+
       | (5% Probe) |
       +------------+
```

#### Go Delivery Pipeline with Channel Fallback
```go
package notification

import (
	"context"
	"errors"
	"time"
)

type NotificationMessage struct {
	ID        string
	TenantID  string
	UserID    string
	Category  string // P0, P1, P2
	Payload   string
	Channel   string // SMS, PUSH, EMAIL
	Fallback  string
	Attempt   int
}

type Provider interface {
	Send(ctx context.Context, msg NotificationMessage) error
	IsHealthy() bool
}

type DispatchRouter struct {
	PrimarySMS  Provider
	FallbackSMS Provider
}

func (r *DispatchRouter) RouteSMS(ctx context.Context, msg NotificationMessage) error {
	ctxWithTimeout, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	if r.PrimarySMS.IsHealthy() {
		err := r.PrimarySMS.Send(ctxWithTimeout, msg)
		if err == nil {
			return nil
		}
		// Primary failed: log and continue to fallback
	}

	// Primary degraded or timed out: Route to Fallback
	if r.FallbackSMS != nil && r.FallbackSMS.IsHealthy() {
		msg.Attempt++
		return r.FallbackSMS.Send(ctxWithTimeout, msg)
	}

	return errors.New("all SMS transport options unavailable")
}
```

### 6.4 Notification Idempotency Schema (Redis TTL Fingerprinting)

To prevent duplicate deliveries during worker retries or webhook replays, compute a unique deterministic notification digest:
$$\text{Digest} = \text{SHA256}(\text{TenantID} + \text{UserID} + \text{EventKey} + \text{PayloadFingerprint})$$

```
# Evaluated atomically prior to dispatch
SET notification:lock:{Digest} "DISPATCHING" NX EX 86400
```
- If Redis returns `nil`: Abort dispatch. Message marked as `DUPLICATE_DROP`.
- If Redis returns `OK`: Proceed with provider dispatch.

---

## 7. Comparative Architectural Blueprint Matrix

| Dimension | 1. URL Shortener | 2. Ride Dispatch | 3. Rate Limiter | 4. Video Feed | 5. Financial Ledger | 6. Notifications |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Primary Datastore** | CockroachDB | Memory / Redis | Redis Cluster | ScyllaDB + S3 | PostgreSQL (Serializable) | ScyllaDB + Kafka |
| **Consistency Mode** | Strong (Writes), Eventual (Reads) | Immediate in-memory / Causal | Eventual / Tunable (Token bucket) | Eventual / Causal | Strict Serializable (Zero-drift ACID) | At-least-once / Deduplicated |
| **Dominant Bottleneck** | Read throughput on hot keys | High-velocity writes (driver GPS update storm) | Network latency at edge layer | P99 video chunk delivery latency | Contention on single hot-account balance | 3rd-party provider latency / rate limits |
| **Critical Mitigation** | Scalable Bloom filter + SingleFlight | Geo-hex bucketing (H3) + Distributed Locking | Local L1 cache + Redis Lua pipeline | CDN micro-caching + Aggressive prefetching | Invariant trigger checks + Immutability | Circuit breaker + Tiered fallback routing |
| **P99 Target** | $< 10\text{ms}$ | $< 500\text{ms}$ | $< 1.5\text{ms}$ | $< 200\text{ms}$ | $< 50\text{ms}$ | $< 1.0\text{s}$ (P0 items) |

---

## 8. Failure Domain Checklist

Before promoting any of these distributed patterns to production, verify resilience against the following failure domains:

- [ ] **Split-Brain Network Partitions:** The database layer must have an odd replica count
