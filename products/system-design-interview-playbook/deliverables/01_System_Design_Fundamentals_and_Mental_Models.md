# Module 1: Distributed Core Frameworks & The 45-Minute Interview Blueprint

---

## 1. The 45-Minute System Design Interview Operating System

Senior and Staff-level system design interviews do not evaluate whether you can name technologies. They evaluate your ability to lead technical ambiguity, manage precise trade-offs, and defend a deterministic path from business requirements to infrastructure topology.

```
+---------------------------------------------------------------------------------------------------+
|                                  THE 45-MINUTE TIME ALLOCATION                                    |
+-------------------+--------------------+------------------------------------+---------------------+
| 00:00 - 05:00     | 05:00 - 15:00      | 15:00 - 35:00                      | 35:00 - 45:00       |
| Phase 1: Scope    | Phase 2: High-Level| Phase 3: Deep Dive Core Components | Phase 4: Reliability|
| Requirements &    | Architecture &     | & Data Path Engineering            | Failure Modes, Edge |
| Scale Math        | Interface Contracts| (Partitioning, Consensus, Storage) | Cases & Evolution   |
+-------------------+--------------------+------------------------------------+---------------------+
```

### Phase 1: Scope & Quantitative Constraints (00:00 - 05:00)

Your goal is to transition from an ambiguous prompt (e.g., *"Design TikTok"*) to a mathematically bounded engineering specification.

#### 1. Clarification & Scoping Framework
Do not ask generic questions like *"Who is the user?"* Ask concrete architectural bounding questions:
*   **Access Patterns:** *"Is this system read-heavy or write-heavy? What is the expected read-to-write ratio (e.g., 100:1 for social feeds vs. 1:1 for messaging)?"*
*   **Latency Budgets:** *"What are the p95 and p99 latency SLAs at the edge API gateway (e.g., `< 50ms` for metadata, `< 200ms` for feed generation)?"*
*   **Consistency Requirements:** *"Can the system tolerate eventual consistency across regions (AP), or do financial/inventory invariants demand strict linearizability (CP)?"*
*   **Data Retention:** *"What is the time-to-live (TTL) on this data? Do we support cold historical archival (S3 Glacier) vs. hot real-time retrieval (NVMe SSD)?"*

#### 2. Functional & Non-Functional Requirements Ledger
Document requirements explicitly in your workspace using this exact schema:

```markdown
### Functional Requirements (Scope In-Bounds)
1. Core Action 1: Ingest video metadata and chunked video payloads.
2. Core Action 2: Generate personalized home feeds in real time.
3. Core Action 3: Stream video smoothly across variable bandwidth clients.

### Out of Scope (Explicitly Deferred)
- User authentication/OAuth (assumed handled by Identity Provider).
- Monetization, ad placement, and analytics pipeline.

### Non-Functional Requirements (Hard Operational SLAs)
- Daily Active Users (DAU): 100,000,000.
- Availability: 99.99% (no more than 52.6 minutes of downtime/year).
- Latency (p99): Read feed < 100ms; Write ingestion ACK < 250ms.
- Consistency: Eventual consistency on feed views; Strong consistency on user account states.
```

---

## 2. Back-of-the-Envelope Estimation Master Engine

Never guess numbers in an interview or capacity planning document. Anchor calculations to hardware primitives and power-of-two approximations.

### The Latency Numbers Every Systems Engineer Must Know

```
+---------------------------------------------+---------------+-----------------------+
| Hardware Operation                          | Exact Latency | Human-Scale Scaled Up |
+---------------------------------------------+---------------+-----------------------+
| L1 Cache Reference                          | 1 ns          | 1 second              |
| L2 Cache Reference                          | 4 ns          | 4 seconds             |
| Mutex Lock / Unlock                         | 17 ns         | 17 seconds            |
| Main Memory (RAM) Access                    | 100 ns        | 100 seconds           |
| Read 1 MB sequentially from RAM             | 3,000 ns (3µs)| 50 minutes            |
| Read 1 MB sequentially from NVMe SSD        | 12,000 ns(12µs| 3.3 hours             |
| Read 1 MB sequentially from 7.2k RPM HDD    | 20,000,000 ns | 7.6 months            |
| Round Trip Time (RTT) in same Data Center   | 500,000 ns    | 5.8 days              |
| Round Trip Time (RTT) Across US (SF to NYC) | 40,000,000 ns | 1.3 years             |
| Round Trip Time Across Continents           | 150,000,000 ns| 4.8 years             |
+---------------------------------------------+---------------+-----------------------+
```

### Power-of-Two & Multiplier Conversion Matrix

```
2^10 = 1,024       ~= 1 Thousand (Kilo, 1 KB)
2^20 = 1,048,576   ~= 1 Million  (Mega, 1 MB)
2^30 = 1,073,741,824 ~= 1 Billion  (Giga, 1 GB)
2^40 = 1,099,511,627,776 ~= 1 Trillion (Tera, 1 TB)
2^50 ~= 1 Quadrillion (Peta, 1 PB)

1 Day = 86,400 seconds ~= 10^5 seconds (Conservative round: 86,400 -> 100,000 for mental math)
```

### The Capacity Planning Math Blueprint

```
                     Writes/Day
Write QPS = ----------------------------
                     86,400 sec

Read QPS  = Write QPS * Read-to-Write Ratio

Peak QPS  = Average QPS * 2 (or * 3 for spiky traffic like flash sales)

Ingress Bandwidth = Write QPS * Payload Size (in Bytes)

Egress Bandwidth  = Read QPS * Payload Size (in Bytes)

Cache RAM Required = (Daily Read Requests * Object Size) * 0.20 (80/20 Pareto Principle)
```

### Production Math Example: Photo/Media Service

*   **Inputs:**
    *   100 Million Daily Active Users (DAU).
    *   Each active user posts an average of 2 media items per day.
    *   Read-to-Write Ratio: 50:1 (Heavy consumption model).
    *   Average post metadata: 1 KB.
    *   Average post media item: 2 MB (compressed JPEG/WebP).
*   **Step 1: Write Operations & Throughput**
    *   Total Writes/Day: $100\text{M} \times 2 = 200\text{M writes/day}$.
    *   Average Write QPS: $\frac{200,000,000}{86,400} \approx \mathbf{2,315\text{ writes/sec}}$.
    *   Peak Write QPS (Factor of 2): $2,315 \times 2 \approx \mathbf{4,630\text{ writes/sec}}$.
*   **Step 2: Read Operations & Throughput**
    *   Average Read QPS: $2,315 \times 50 = \mathbf{115,750\text{ reads/sec}}$.
    *   Peak Read QPS (Factor of 2): $115,750 \times 2 = \mathbf{231,500\text{ reads/sec}}$.
*   **Step 3: Storage Requirements**
    *   Daily Metadata: $200\text{M writes} \times 1\text{ KB} = 200\text{ GB/day}$.
    *   Daily Media: $200\text{M writes} \times 2\text{ MB} = 400\text{ TB/day}$.
    *   3-Year Raw Storage Projection (Media): $400\text{ TB} \times 365 \times 3 = 438\text{ PB}$.
    *   With $3\times$ replication: $438\text{ PB} \times 3 = \mathbf{1.314\text{ Exabytes}}$.
*   **Step 4: Network Bandwidth Demands**
    *   Ingress (Media): $2,315 \text{ writes/sec} \times 2\text{ MB} = \mathbf{4.63\text{ GB/sec}}\; (37.04\text{ Gbps})$.
    *   Egress (Media): $115,750 \text{ reads/sec} \times 2\text{ MB} = \mathbf{231.5\text{ GB/sec}}\; (1.852\text{ Tbps})$.
    *   *Architectural Directive:* Direct client delivery via origin infrastructure will saturate uplinks; 100% of media retrieval must terminate on a globally distributed CDN with Origin Shielding.
*   **Step 5: Hot Cache Layer Sizing (Redis/Memcached)**
    *   Read volume per day: $200\text{M writes} \times 50 = 10\text{ Billion reads/day}$.
    *   Total distinct items requested daily (assuming $20\%$ unique accessed): $2\text{ Billion items}$.
    *   Cache 20% of unique metadata requests: $2,000,000,000 \times 0.20 \times 1\text{ KB} = \mathbf{400\text{ GB RAM}}$.
    *   With an `m6i.16xlarge` AWS instance (256 GB RAM per node), a cluster of 3 nodes (primary-replica sets) accommodates the hot working set with failover headroom.

---

## 3. CAP Theorem, PACELC, and Real-World Trade-Offs

The textbook formulation of the CAP theorem states that a distributed system can guarantee at most two of Consistency, Availability, and Partition Tolerance simultaneously. In real-world networks, partitions (network drops, packet loss, fiber cuts) are non-negotiable. 

```
                       NETWORK PARTITION OCCURS (P)
                                  |
            +---------------------+---------------------+
            |                                           |
    CHOOSE CONSISTENCY (CP)                     CHOOSE AVAILABILITY (AP)
   Return Error / Time out                      Return Stale Local Data
   Halt processing until state is uniform.      Accept writes/reads locally.
   Example: Banking, Stock Ledgers              Example: DNS, Social Feeds
```

### The PACELC Theorem
Because the CAP theorem only models behavior *during an active partition*, Daniel Abadi formulated the **PACELC** theorem to model behavior during normal operations:

$$\text{If Partition (P) } \rightarrow \text{ Choose Availability (A) or Consistency (C);}$$
$$\text{Else (E) } \rightarrow \text{ Choose Latency (L) or Consistency (C).}$$

### Production System PACELC Classification

```
+-------------------+-----------------+-----------------------------------------------------------------+
| System            | PACELC Model    | Real-World Production Rationale                                 |
+-------------------+-----------------+-----------------------------------------------------------------+
| Apache Cassandra  | PA / EL         | During partitions, nodes accept local reads/writes (AP).       |
|                   |                 | Normally, yields eventual consistency to achieve single-digit   |
|                   |                 | millisecond write latency (EL).                                 |
+-------------------+-----------------+-----------------------------------------------------------------+
| Amazon DynamoDB   | PA / EL         | Default access provides high availability and lowest latency.   |
|                   | (Configurable)  | Can be toggled to PC/EC per-request using `ConsistentRead=true` |
|                   |                 | and TransactWriteItems.                                         |
+-------------------+-----------------+-----------------------------------------------------------------+
| Google Cloud      | PC / EC         | TrueTime API provides bounded clock error ($\epsilon \le 7$ms).|
| Spanner           |                 | Sacrifices write latency globally to guarantee external         |
|                   |                 | consistency (Strict Serializability) under all conditions.     |
+-------------------+-----------------+-----------------------------------------------------------------+
| CockroachDB       | PC / EC         | Uses Raft consensus per range. If a node loses quorum,         |
|                   |                 | it stops processing writes to prevent stale updates.           |
+-------------------+-----------------+-----------------------------------------------------------------+
| Apache Kafka      | PC / EC         | When `min.insync.replicas` is configured with `acks=all`, Kafka |
|                   | (Tunable)       | refuses writes if insufficient brokers acknowledge. Drops       |
|                   |                 | availability to ensure zero message loss.                       |
+-------------------+-----------------+-----------------------------------------------------------------+
| Redis Sentinel/   | PA / EL         | Asynchronous replication by default. If the master isolates,    |
| Cluster           |                 | writes committed to it can be lost during failover.             |
+-------------------+-----------------+-----------------------------------------------------------------+
| ZooKeeper / etcd  | PC / EC         | Built directly on Zab/Raft consensus algorithms. Requires       |
|                   |                 | quorum ($N/2 + 1$) for both reads and writes.                   |
+-------------------+-----------------+-----------------------------------------------------------------+
```

### Mathematical Quorum Tuning: Cassandra / DynamoDB

Quorum configurations govern whether a tunable system behaves as AP or CP:
*   $N$: Replication Factor (Total copies of data across independent nodes).
*   $W$: Write Quorum (Number of nodes that must ACK a write before returning success).
*   $R$: Read Quorum (Number of nodes that must respond to a read request).

#### The Strong Consistency Invariant
$$W + R > N$$

If $W + R > N$, the read set and write set must overlap by at least one node containing the most recent write timestamp, guaranteeing **Strong Consistency**.

```
Scenario: N = 3, W = 2, R = 2  (2 + 2 = 4 > 3 -> Strong Consistency)
Nodes: [Node A, Node B, Node C]
1. Write succeeds on Node A and Node B. (Node C misses write due to latency).
2. Read requests data from Node B and Node C.
3. Node B has Version 2; Node C has Version 1.
4. Client resolves conflict via highest timestamp (V2) and triggers Read Repair to Node C.
```

If $W + R \le N$, the read set can query nodes that missed the latest write, resulting in **Eventual Consistency** with lower latency and higher availability.

---

## 4. Distributed Consistency Spectrum & Isolation Levels

### The Consistency Continuum

```
STRONGEST                                                                WEAKEST
Linearizability -> Sequential -> Causal -> Read-After-Write -> Eventual
   (Global Clock)     (Program Order) (Dependency)  (Session Stickiness)   (Convergence)
```

1.  **Linearizability (External Consistency):** Every operation appears to execute atomically at an exact point in time between its invocation and its response on a global wall-clock timeline. Requires hardware-synchronized clocks (Google TrueTime) or single-leader consensus sequencing (Raft/Paxos).
2.  **Sequential Consistency:** Operations do not need to be ordered by global real-time, but every client observes writes in the identical order, and individual process program order is respected.
3.  **Causal Consistency:** Operations that are causally related (question $\rightarrow$ answer) must be seen by every node in the same order. Concurrent operations that are independent may be seen in differing order.
4.  **Read-After-Write (Monotonic Read) Consistency:** A user updates a record, then immediately reads it. They are guaranteed to see their own update, even if other concurrent observers cannot see it yet.
5.  **Eventual Consistency:** Given no new updates, all replicas eventually converge to the same value. High performance, zero coordinator overhead, complex conflict resolution (Last-Write-Wins, CRDTs).

### Transaction Isolation Levels vs. Anomalies

Distributed transactions must guard against isolation phenomena defined by ANSI SQL and the extended Berenson et al. taxonomy:

```
+--------------------+------------+----------------------+--------------+------------+
| Isolation Level    | Dirty Read | Non-Repeatable Read  | Phantom Read | Write Skew |
+--------------------+------------+----------------------+--------------+------------+
| Read Uncommitted   | YES        | YES                  | YES          | YES        |
| Read Committed     | NO         | YES                  | YES          | YES        |
| Repeatable Read    | NO         | NO                   | YES          | YES        |
| Snapshot Isolation | NO         | NO                   | NO           | YES        |
| Serializable       | NO         | NO                   | NO           | NO         |
+--------------------+------------+----------------------+--------------+------------+
```

*   **Write Skew Failure Case (Snapshot Isolation):** Two doctors are on call. Policy requires at least one doctor on call at all times. Both doctors issue concurrent transactions to take leave:
    *   Tx 1 checks active doctors: Count = 2. Safe to leave.
    *   Tx 2 checks active doctors: Count = 2. Safe to leave.
    *   Both Tx 1 and Tx 2 commit concurrently under Snapshot Isolation because they modified different records (Doctor A's status vs Doctor B's status).
    *   *Result:* 0 doctors on call. System invariant violated. Requires **Serializable** isolation via two-phase locking or Serializable Snapshot Isolation (SSI).

---

## 5. Horizontal Scaling & Data Partitioning Patterns

Scaling systems horizontally requires deterministic strategies for mapping dynamic keys to discrete storage instances.

```
1. Range Partitioning:
[A - E] -> Node 1     [F - M] -> Node 2     [N - Z] -> Node 3
Risk: Severe write hotspotting on current temporal keys (e.g., today's date "2023-10-27").

2. Hash Partitioning (Mod N):
Node = Hash(Key) % N
Risk: Changing N from 3 to 4 invalidates ~75% of cache keys, triggering an outage.

3. Consistent Hashing:
Keys and Nodes mapped onto a 2^32 - 1 integer ring.
Node additions/removals only remap K/N keys where K = total keys, N = total nodes.
```

### Production-Grade Consistent Hash Ring with Virtual Nodes

The primary failure mode of naive consistent hashing is non-uniform data distribution (hotspotting). We solve this by allocating $V$ **virtual nodes** per physical node distributed pseudorandomly across the integer ring.

```python
"""
production_hash_ring.py
Fully functional, deterministic consistent hash ring with virtual nodes.
"""

from typing import List, Optional
import bisect
import hashlib


class ConsistentHashRing:
    def __init__(self, replicas: int = 150):
        """
        :param replicas: Number of virtual nodes per physical node.
                         Higher value increases uniform distribution across the keyspace.
        """
        self.replicas: int = replicas
        self.ring: List[int] = []  # Sorted list of virtual node hashes
        self.ring_map: dict[int, str] = {}  # Hash -> Physical Node Identifier
        self.nodes: set[str] = set()

    def _hash(self, key: str) -> int:
        """Computes 32-bit integer MD5 digest."""
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def add_node(self, node: str) -> None:
        """Registers a physical node and creates virtual replicas on the ring."""
        if node in self.nodes:
            return
        self.nodes.add(node)
        for i in range(self.replicas):
            virtual_key = f"{node}#VN{i}"
            val = self._hash(virtual_key)
            bisect.insort(self.ring, val)
            self.ring_map[val] = node

    def remove_node(self, node: str) -> None:
        """Removes a physical node and purges all associated virtual nodes."""
        if node not in self.nodes:
            return
        self.nodes.remove(node)
        new_ring: List[int] = []
        for val in self.ring:
            if self.ring_map[val] == node:
                del self.ring_map[val]
            else:
                new_ring.append(val)
        self.ring = new_ring

    def get_node(self, key: str) -> Optional[str]:
        """Maps a given key to the first available node along the ring clockwise."""
        if not self.ring:
            return None

        val = self._hash(key)
        idx = bisect.bisect_right(self.ring, val)

        # Wrap around the ring to index 0 if the key hash is greater than all nodes
        if idx == len(self.ring):
            idx = 0

        return self.ring_map[self.ring[idx]]


# Self-test block demonstrating migration behavior
if __name__ == "__main__":
    ring = ConsistentHashRing(replicas=100)
    for storage_node in ["node-alpha", "node-beta", "node-gamma"]:
        ring.add_node(storage_node)

    test_keys = [f"user_session_token_{i}" for i in range(10000)]
    initial_distribution = {}

    for k in test_keys:
        target = ring.get_node(k)
        initial_distribution[target] = initial_distribution.get(target, 0) + 1

    print("Initial distribution across nodes:")
    for node, count in initial_distribution.items():
        print(f"  {node}: {count} keys ({count / 100:.1f}%)")

    # Add 4th node to prove minimal key relocation
    ring.add_node("node-delta")
    relocated = 0
    for k in test_keys:
        if ring.get_node(k) == "node-delta":
            relocated += 1

    print(f"\nKeys gracefully migrated to newly added node-delta: {relocated}")
    print(f"Expected theoretical delta (1/N = 1/4): ~2500 keys. Actual: {relocated} keys.")
```

---

## 6. Production Resilience & Fault Tolerance Checklist

Distributed systems degrade in unpredictably non-linear ways. Use this checklist during Phase 4 of any system design interview or production architectural review.

```
                              CASCADING OUTAGE PREVENTION
                                           |
            +------------------------------+------------------------------+
            |                              |                              |
   1. Circuit Breakers            2. Token Bucket Limiting       3. Idempotency Keys
   (Isolate slow failures)        (Hard boundary on traffic)     (Deduplicate retries)
```

### The System Resilience Defense Matrix

```
+-------------------+-----------------------------------+-----------------------------------------------+
| Defense Pattern   | Primary Failure Prevented         | Implementation Standard                       |
+-------------------+-----------------------------------+-----------------------------------------------+
| Circuit Breaker   | Cascading thread pool exhaustion  | Trip state: Open after 50% failure rate over  |
|                   | caused by slow external upstream. | 10s sliding window. Half-open test every 5s.  |
+-------------------+-----------------------------------+-----------------------------------------------+
| Exponential       | Thundering herd / retry storms    | Formula:                                      |
| Backoff + Jitter  | against recovering databases.     | $T_{sleep} = \min(M, B \cdot 2^i) \pm \text{jitter}$ |
+-------------------+-----------------------------------+-----------------------------------------------+
| Token Bucket      | Resource starvation and buffer    | Enforce at Reverse Proxy / API Gateway        |
| Rate Limiter      | bloat at the transport layer.     | per Tenant ID or Client IP.                   |
+-------------------+-----------------------------------+-----------------------------------------------+
| Idempotency Key   | Double charges, duplicate records | Client supplies `Idempotency-Key` UUID. Store |
| Engine            | caused by network retries.        | result in Redis with 120-second TTL lock.     |
+-------------------+-----------------------------------+-----------------------------------------------+
| Load Shedding     | System tail-latency collapse via  | Monitor CPU / P99 queue wait times. Return    |
|                   | unbounded queueing.               | `HTTP 503` immediately when queue depth > max.|
+-------------------+-----------------------------------+-----------------------------------------------+
```

### Production Envoy Circuit Breaking & Outlier Detection Configuration

This production Envoy filter configuration prevents thread-pool starvation by shedding traffic when an upstream dependency begins failing:

```yaml
static_resources:
  clusters:
    - name: payment_processing_service
      connect_timeout: 0.25s
      type: STRICT_DNS
      dns_lookup_family: V4_ONLY
      lb_policy: ROUND_ROBIN
      load_assignment:
        cluster_name: payment_processing_service
        endpoints:
          - lb_endpoints:
              - endpoint:
                  address:
                    socket_address:
                      address: payment-service.internal
                      port_value: 8443
      circuit_breakers:
        thresholds:
          - priority: DEFAULT
            max_connections: 1024          # Max concurrent TCP connections
            max_pending_requests: 100       # Max pending requests in queue
            max_requests: 2048              # Max active concurrent requests
            max_retries: 3                  # Max concurrent retries
            track_remaining: true
      outlier_detection:
        consecutive_5xx: 5                  # Trip if 5 consecutive 5xx errors occur
        interval: 10s                       # Scan interval
        base_ejection_time: 30s             # Remove dead host from cluster for 30s
        max_ejection_percent: 50            # Evict at most 50% of instances
```

---

## 7. The 45-Minute Interview Defense Template

Keep this template visible during interviews. It ensures your presentation follows the trajectory expected of senior candidates:

```markdown
### 1. Requirements Formalization (5 mins)
- [ ] Document Functional Boundaries (Must-haves vs Out-of-Scope)
- [ ] Document Non-Functional Requirements (Latency, Throughput, Consistency, SLA)
- [ ] Compute QPS, Bandwidth Ingress/Egress, and Storage footprints

### 2. High-Level Blueprint & Data Contracts (10 mins)
- [ ] Draw Client -> CDN / Load Balancer -> API Gateway topology
- [ ] Define precise REST / gRPC endpoint definitions
- [ ] Draft entity relational/document schema with primary/partition keys

### 3. Core Engine Deep Dive (20 mins)
- [ ] Apply Sharding / Partitioning Strategy (Consistent Hashing / Shard Key)
- [ ] Define the exact Consistency Strategy (Raft, Strong vs Eventual, Quorums)
- [ ] Detail the Hot Storage / Caching Layer (Write-through vs Write-back, TTL)
- [ ] Trace the Read Path end-to-end (Client to DB to Client)
- [ ] Trace the Write Path end-to-end (Client to WAL to ACK)

### 4. Resiliency & Scale Hardening (10 mins)
- [ ] Identify Single Points of Failure (SPOFs) at every tier
- [ ] Apply Circuit Breakers, Retries with Jitter, and Rate Limiters
- [ ] Defend Data Loss Scenarios (Replication lag, Failover, Brain-Split handling)
