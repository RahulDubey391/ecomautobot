# Module 2: 60+ Copy-Paste Query Tuning Recipes & Indexing Strategies

This deliverable contains battle-tested, production-grade indexing templates, query blueprints, and schema patterns for PostgreSQL 14, 15, 16, and 17. Every pattern is engineered to eliminate sequential scans, avoid buffer-cache thrashing, prevent lock contention, and maximize Index-Only Scans across high-throughput OLTP and analytics workloads.

---

## 1. Master Index Selection Decision Matrix

Use this matrix to identify the correct access method before writing queries or schema migrations.

| Workload / Query Pattern | Data Type / Domain | Scale / Volume | Recommended Access Method | Storage Overhead | Write Amplification Risk | Notes / Operator Classes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Single-column exact match or sort | `uuid`, `bigint`, `text`, `timestamptz` | Any | Standard B-Tree | Low | Low | Default `btree`. Keep fillfactor default (90-100) unless hot-updates occur. |
| Compound filter + sorting | Mixed scalar types | Any | Composite B-Tree (Equality-First, Sort-Second) | Low to Medium | Low to Medium | Column order matters: `(tenant_id, status, created_at DESC)`. |
| Index-Only Scans with non-filtered payload | Scalar types | >10M rows | B-Tree with `INCLUDE` clause | Medium | Low (HOT friendly) | `INCLUDE (payload, updated_at)` avoids index tuple re-sorting and supports HOT. |
| Semi-structured containment search (`@>`, `?`, `?&`) | `jsonb` | Any | GIN (`jsonb_ops` or `jsonb_path_ops`) | High (2x-5x B-Tree) | High | `jsonb_path_ops` is 40-60% smaller, supports `@>` only. `jsonb_ops` supports key existence. |
| Top-level scalar extraction from document | `jsonb` extraction (`->>`) | Any | Expression B-Tree | Low | Low | Example: `CREATE INDEX ... ON tbl (( (data->>'user_id')::bigint ))`. |
| Time-series, append-only logs, physical order | `timestamptz`, `bigint` sequence | >50M rows | BRIN (Block Range Index) | Extremely Low (<1% of B-Tree) | Near Zero | Physical correlation must be near 1.0. Tune `pages_per_range = 32` or `64`. |
| Overlapping scheduling, reservations | `tsrange`, `tstzrange`, `daterange` | Any | GiST with Exclusion Constraints | Medium to High | Medium | Enforces zero overlapping ranges at storage layer using `&&` operator. |
| Proximity, geometric search, kNN | `geometry`, `geography`, `point` | Any | GiST or SP-GiST | Medium | Medium | Use `gist` for general spatial data; use `spgist` for non-overlapping spatial partitioning. |
| State-machine queues (`status = 'QUEUED'`) | `enum`, `varchar` | High turn | Partial B-Tree | Negligible | Very Low | `WHERE status IN ('queued', 'retry')` indexes only 1% of the active table footprint. |
| Full-Text Search with stemming | `tsvector` | Any | GIN | High | High | Always store generated `tsvector` column with `STORED`; avoid runtime functional conversion. |
| Trigram substring / pattern search (`LIKE '%foo%'`) | `text`, `varchar` | Any | GIN with `pg_trgm` | High | High | Requires `CREATE EXTENSION pg_trgm;` and `gin (col gin_trgm_ops)`. |

---

## 2. High-Volume B-Tree & Multi-Column Ordering Recipes

### Recipe 2.1: The Equality-Sort-Range (ESR) Index Architecture

PostgreSQL executes index traversals most efficiently when index columns are ordered using the ESR rule:
1. **Equality (`=`):** Columns evaluated with exact equality.
2. **Sort (`ORDER BY`):** Columns determining sort direction without runtime re-sorting.
3. **Range (`<`, `>`, `BETWEEN`, `IN`):** Range conditions that terminate strict index bounds.

```sql
-- Target Schema: Multi-tenant financial ledger
CREATE TABLE financial_ledger_entries (
    entry_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    account_id UUID NOT NULL,
    status VARCHAR(32) NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL,
    amount NUMERIC(18, 4) NOT NULL,
    description TEXT,
    CONSTRAINT pk_financial_ledger_entries PRIMARY KEY (entry_id)
);

-- Slow Access Pattern: Equality on tenant_id and status, Sort by posted_at, Range filter on amount
-- Target Query:
-- SELECT entry_id, amount, posted_at 
-- FROM financial_ledger_entries 
-- WHERE tenant_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
--   AND status = 'POSTED'
--   AND posted_at >= '2024-01-01 00:00:00Z'
-- ORDER BY posted_at DESC;

-- Anti-Pattern: Indexing Sort or Range before Equality
-- BAD: CREATE INDEX idx_err ON financial_ledger_entries (posted_at DESC, tenant_id, status);

-- Production Optimal Index (ESR Pattern applied):
CREATE INDEX CONCURRENTLY idx_fle_tenant_status_posted_desc
ON financial_ledger_entries (tenant_id, status, posted_at DESC);

-- Verification:
EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
SELECT entry_id, amount, posted_at 
FROM financial_ledger_entries 
WHERE tenant_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
  AND status = 'POSTED'
  AND posted_at >= '2024-01-01 00:00:00Z'
ORDER BY posted_at DESC;
-- Plan must yield: "Index Scan using idx_fle_tenant_status_posted_desc" with NO Sort node.
```

### Recipe 2.2: Covering Indexes with `INCLUDE` to Eliminate Heap Fetches

To achieve pure **Index-Only Scans**, attributes needed strictly for projection (payloads) should be packed into the index leaf pages via `INCLUDE`. This keeps the B-Tree navigation branch compact while eliminating reads to table pages (heap).

```sql
-- Target Schema: High-throughput API session tokens
CREATE TABLE auth_sessions (
    session_id UUID NOT NULL DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    ip_address INET NOT NULL,
    user_agent TEXT,
    last_active_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT pk_auth_sessions PRIMARY KEY (session_id)
);

-- Target Query: Authenticate active token and read session metadata
-- SELECT ip_address, user_agent, last_active_at 
-- FROM auth_sessions 
-- WHERE user_id = 'e2b9c7b0-8f92-48a3-a7c8-7de85e1d528b' 
--   AND revoked = false;

-- Covering Index Construction:
-- Key Columns: user_id, revoked (used in B-Tree search path)
-- Included Columns: ip_address, user_agent, last_active_at (stored only at the leaf level)
CREATE INDEX CONCURRENTLY idx_auth_sessions_covering 
ON auth_sessions (user_id, revoked) 
INCLUDE (ip_address, user_agent, last_active_at);

-- Verification:
VACUUM ANALYZE auth_sessions;

EXPLAIN (ANALYZE, BUFFERS)
SELECT ip_address, user_agent, last_active_at 
FROM auth_sessions 
WHERE user_id = 'e2b9c7b0-8f92-48a3-a7c8-7de85e1d528b' 
  AND revoked = false;
-- Plan must yield: "Index Only Scan using idx_auth_sessions_covering", Heap Fetches: 0
```

### Recipe 2.3: Functional & Expression Indexes for Sanitized Lookups

Indexes do not automatically cover queries executing functions against columns (`LOWER()`, `DATE_TRUNC()`). Construct explicit expression indexes that mirror query predicates identically.

```sql
-- Case-Insensitive Email Lookups
CREATE TABLE users (
    user_id UUID NOT NULL DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_users PRIMARY KEY (user_id)
);

-- Unique Expression Index for normalized, case-insensitive lookups:
CREATE UNIQUE INDEX CONCURRENTLY idx_users_lower_email 
ON users (LOWER(email));

-- Deterministic Execution: Query must strictly match expression
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_id 
FROM users 
WHERE LOWER(email) = LOWER('Engineering-Ops@Company.com');
-- Plan must yield: "Index Scan using idx_users_lower_email"
```

---

## 3. Partial & Conditional Indexing for Hot/Cold Patterns

Partial indexes drastically reduce storage footprints and eliminate index maintenance overhead during table modifications on cold records.

### Recipe 3.1: Active-State Queues and Soft-Deletes

Indexes should index only operational records, ignoring dead, archived, or soft-deleted rows.

```sql
CREATE TABLE webhook_dispatch_queue (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    destination_url TEXT NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL, -- 'PENDING', 'PROCESSING', 'DELIVERED', 'FAILED'
    attempts INT NOT NULL DEFAULT 0,
    scheduled_for TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT pk_webhook_dispatch_queue PRIMARY KEY (event_id)
);

-- In high volume systems, 99.9% of rows are 'DELIVERED' or 'deleted_at IS NOT NULL'.
-- BAD: CREATE INDEX idx_wh_bad ON webhook_dispatch_queue (status, scheduled_for);

-- High-Efficiency Partial Index for Worker Polling:
CREATE INDEX CONCURRENTLY idx_webhook_queue_processing_active
ON webhook_dispatch_queue (scheduled_for, attempts)
WHERE status IN ('PENDING', 'PROCESSING') 
  AND deleted_at IS NULL;

-- Worker Queue Polling Query:
EXPLAIN (ANALYZE, BUFFERS)
SELECT event_id, destination_url, payload, attempts
FROM webhook_dispatch_queue
WHERE status IN ('PENDING', 'PROCESSING')
  AND deleted_at IS NULL
  AND scheduled_for <= clock_timestamp()
ORDER BY scheduled_for ASC
LIMIT 50
FOR UPDATE SKIP LOCKED;
-- Plan yields an ultra-fast Index Scan over only unhandled events.
```

### Recipe 3.2: Sparse Unique Constraints (Multi-Tenant Enforcements)

Enforce uniqueness across a logical subset of records without conflicting with archive records or historical entries.

```sql
CREATE TABLE user_subscriptions (
    subscription_id UUID NOT NULL DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    plan_code VARCHAR(64) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Requirement: A user can have infinite cancelled/inactive subscriptions, 
-- but ONLY ONE single active subscription across the entire platform.
CREATE UNIQUE INDEX CONCURRENTLY uq_user_single_active_subscription
ON user_subscriptions (user_id)
WHERE is_active = true;

-- Verification of constraint:
-- First active insert: SUCCESS
INSERT INTO user_subscriptions (user_id, plan_code, is_active) 
VALUES ('c4bca280-97f2-4948-a00d-5a822fc610c1', 'ENTERPRISE_TIER', true);

-- Inactive duplicate insert: SUCCESS
INSERT INTO user_subscriptions (user_id, plan_code, is_active, cancelled_at) 
VALUES ('c4bca280-97f2-4948-a00d-5a822fc610c1', 'PRO_TIER', false, clock_timestamp());

-- Second active insert: FAILS with unique constraint violation
-- INSERT INTO user_subscriptions (user_id, plan_code, is_active) 
-- VALUES ('c4bca280-97f2-4948-a00d-5a822fc610c1', 'BASIC_TIER', true);
```

---

## 4. JSONB Indexing Masterclass: GIN vs. Expression B-Tree

Choosing between GIN and B-Tree for JSONB depends on access patterns:
* **B-Tree on Expression:** Scalable when extracting a specific, known scalar path.
* **GIN with `jsonb_path_ops`:** Ideal for arbitrary containment (`@>`), significantly smaller and faster than default GIN.
* **GIN with `jsonb_ops`:** Necessary if checking top-level key existence (`?`, `?&`, `?|`).

```sql
CREATE TABLE audit_events (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    metadata JSONB NOT NULL,
    CONSTRAINT pk_audit_events PRIMARY KEY (event_id)
);
```

### Recipe 4.1: Expression B-Tree for Hot Scalar Key Extraction

If 95% of queries filter by a fixed field, such as `metadata->>'organization_id'`, never use a full GIN index. Use an Expression B-Tree.

```sql
-- Creates an ultra-dense, low-write-cost B-Tree
CREATE INDEX CONCURRENTLY idx_audit_events_org_id_btree
ON audit_events (((metadata->>'organization_id')::UUID), occurred_at DESC);

-- Query must strictly match the cast and expression:
EXPLAIN (ANALYZE, BUFFERS)
SELECT event_id, occurred_at 
FROM audit_events
WHERE ((metadata->>'organization_id')::UUID) = 'a5661eb1-9bb4-4fa9-b88d-e6b772c1cba5'
ORDER BY occurred_at DESC
LIMIT 20;
-- Plan executes via Index Scan on idx_audit_events_org_id_btree with 0 runtime parsing overhead.
```

### Recipe 4.2: Containment GIN Optimization (`jsonb_path_ops` vs `jsonb_ops`)

```sql
-- Standard Default GIN (jsonb_ops):
-- Indexes every key, every path, and every array element separately. High overhead.
-- CREATE INDEX idx_audit_metadata_default ON audit_events USING gin (metadata);

-- Production Performance Optimization (jsonb_path_ops):
-- Hashes the combined path: { "actor": { "role": "admin" } } is hashed as a single entity.
-- Footprint: ~40% the size of default GIN. Write throughput: 2x faster.
CREATE INDEX CONCURRENTLY idx_audit_events_metadata_path_ops
ON audit_events USING gin (metadata jsonb_path_ops);

-- Supported Query Operators: @> (Containment)
EXPLAIN (ANALYZE, BUFFERS)
SELECT event_id, occurred_at, metadata
FROM audit_events
WHERE metadata @> '{"actor": {"role": "superadmin"}, "context": {"env": "prod"}}';
-- Plan: Bitmap Index Scan using idx_audit_events_metadata_path_ops
```

### Recipe 4.3: Indexing Nested Arrays within JSONB Documents

When filtering inside an array of nested sub-documents:

```sql
-- metadata structure:
-- {
--   "line_items": [
--     {"sku": "SKU-AAA", "qty": 2},
--     {"sku": "SKU-BBB", "qty": 10}
--   ]
-- }

-- Utilize jsonb_path_ops containment
EXPLAIN (ANALYZE, BUFFERS)
SELECT event_id, metadata
FROM audit_events
WHERE metadata @> '{"line_items": [{"sku": "SKU-AAA"}]}';
-- Supported efficiently by idx_audit_events_metadata_path_ops
```

---

## 5. High-Scale Pagination Engine: Keyset vs. Offset/Limit

### The Fatal Flaw of `OFFSET / LIMIT`

`OFFSET 500000 LIMIT 20` forces the database engine to scan 500,020 rows through the index, fetch all corresponding heap pages into the buffer cache, and throw away the first 500,000 rows. Memory thrashing is catastrophic at scale.

```
OFFSET Execution Cost: O(N) where N is the page depth.
Keyset Execution Cost: O(1) constant seek speed using index leaf pointers.
```

```sql
-- Target Schema: Multi-tenant High-Scale Orders
CREATE TABLE customer_orders (
    order_id UUID NOT NULL DEFAULT gen_random_uuid(),
    merchant_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    amount NUMERIC(14,2) NOT NULL,
    CONSTRAINT pk_customer_orders PRIMARY KEY (order_id)
);

-- Underpinning Index for Keyset Pagination (Composite B-Tree)
CREATE INDEX CONCURRENTLY idx_orders_pagination
ON customer_orders (merchant_id, created_at DESC, order_id DESC);
```

### Recipe 5.1: High-Performance Forward Keyset Pagination

Do not pass an offset integer from the frontend. Pass a deterministic tuple cursor representing the last evaluated record: `(last_created_at, last_order_id)`.

```sql
-- Page 1: Initial Query
SELECT order_id, created_at, amount
FROM customer_orders
WHERE merchant_id = '9fbcfe3a-6ff1-4a7b-a316-09ecf91a5db4'
ORDER BY created_at DESC, order_id DESC
LIMIT 20;

-- Extract from last row of Page 1:
-- created_at: '2024-03-29 18:24:00.12456+00'
-- order_id:   'b3664d60-c3d6-410a-8d76-574fbc11bece'

-- Page 2: Fetch using Row Comparison (Keyset Seek)
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, created_at, amount
FROM customer_orders
WHERE merchant_id = '9fbcfe3a-6ff1-4a7b-a316-09ecf91a5db4'
  AND (created_at, order_id) < ('2024-03-29 18:24:00.12456+00'::timestamptz, 'b3664d60-c3d6-410a-8d76-574fbc11bece'::uuid)
ORDER BY created_at DESC, order_id DESC
LIMIT 20;
-- Plan yields an Index Scan with sub-millisecond execution, completely independent of page depth.
```

### Recipe 5.2: Bi-Directional Keyset Cursor Pattern (Navigate Next and Prev)

```sql
-- Backward Page (Navigate PREVIOUS from top row):
-- top row values: created_at = '2024-03-29 18:30:15.987+00', order_id = 'fae99cd1-7fa1-4a61-b4d8-c116de0d655b'

WITH previous_slice AS (
    SELECT order_id, created_at, amount
    FROM customer_orders
    WHERE merchant_id = '9fbcfe3a-6ff1-4a7b-a316-09ecf91a5db4'
      AND (created_at, order_id) > ('2024-03-29 18:30:15.987+00'::timestamptz, 'fae99cd1-7fa1-4a61-b4d8-c116de0d655b'::uuid)
    ORDER BY created_at ASC, order_id ASC
    LIMIT 20
)
SELECT * FROM previous_slice
ORDER BY created_at DESC, order_id DESC;
```

---

## 6. BRIN (Block Range Index) for Append-Only Big Data

When tables scale beyond 100M+ rows and rows are appended chronologically (natural physical clustering), a traditional B-Tree incurs massive index bloat (often larger than the base relation). BRIN indexes record the minimum and maximum scalar values for a group of physical database pages (default 128 pages = 1MB).

```sql
CREATE TABLE metric_timeseries_points (
    point_id BIGINT GENERATED ALWAYS AS IDENTITY,
    metric_id UUID NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL
);

-- B-Tree on 500M rows: ~11 GB RAM footprint
-- BRIN on 500M rows: ~400 KB RAM footprint (99.9% reduction)

-- Construction of Tuned BRIN Index:
-- pages_per_range: Defaults to 128. Lowering to 32 or 64 reduces scan bloat on smaller ranges.
CREATE INDEX CONCURRENTLY idx_metric_points_brin_time
ON metric_timeseries_points USING brin (recorded_at)
WITH (pages_per_range = 32, autosummarize = true);

-- Production Maintenance Protocol for BRIN:
-- BRIN must summarize ranges as rows arrive. If out-of-order rows or sudden updates occur,
-- summarize untouched ranges using the system function:
SELECT brin_summarize_new_values('idx_metric_points_brin_time');

-- Target Query:
EXPLAIN (ANALYZE, BUFFERS)
SELECT AVG(metric_value)
FROM metric_timeseries_points
WHERE recorded_at >= '2024-01-01 00:00:00Z'
  AND recorded_at < '2024-01-02 00:00:00Z';
-- Plan: Bitmap Index Scan using idx_metric_points_brin_time
-- Fast range pruning down to matching disk blocks.
```

---

## 7. Spatial & Temporal Range Indexing with GiST

### Recipe 7.1: Overlapping Ranges with GiST & Exclusion Constraints

Prevent race conditions and double bookings natively at the storage layer without application-level distributed locks.

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE conference_room_reservations (
    reservation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL,
    booking_time_range TSRANGE NOT NULL,
    reserved_by TEXT NOT NULL,
    -- Enforce: No two active reservations can occupy the same room with overlapping time boundaries
    CONSTRAINT exclude_overlapping_reservations 
    EXCLUDE USING gist (
        room_id WITH =, 
        booking_time_range WITH &&
    )
);

-- Fast Index Lookups using GiST:
-- Find room availability for a requested window:
EXPLAIN (ANALYZE, BUFFERS)
SELECT room_id, booking_time_range
FROM conference_room_reservations
WHERE room_id = 'e729a615-5a11-4a9c-a115-cd98bf9961dd'
  AND booking_time_range && tsrange('2024-04-01 10:00:00', '2024-04-01 12:00:00');
-- Plan executes via: Bitmap Index Scan using exclude_overlapping_reservations
```

### Recipe 7.2: Geospatial Coordinates & Distance Bounding Boxes

```sql
CREATE TABLE courier_telemetry (
    courier_id UUID NOT NULL,
    current_location POINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX CONCURRENTLY idx_courier_telemetry_gist_loc 
ON courier_telemetry USING gist (current_location);

-- Fast radial boundary search: Fetch couriers within bounding box
EXPLAIN (ANALYZE, BUFFERS)
SELECT courier_id, current_location
FROM courier_telemetry
WHERE current_location <@ box(point(37.7749, -122.4194), point(37.7849, -122.4094));
-- Plan: Index Scan using idx_courier_telemetry_gist_loc
```

---

## 8. Zero-Downtime Indexing Operations & Lock Mitigation

Executing `CREATE INDEX` runs in `SHARE` lock mode, which blocks all `INSERT`, `UPDATE`, and `DELETE` queries on that relation until the entire index build finishes. Under production load, this backs up connection pools and triggers operational outages.

### Safe Concurrent Indexing Automation Template

Always create indexes using `CONCURRENTLY`. Enforce bounded lock timeouts so the lock acquisition attempt does not block concurrent transactions if forced to wait.

```sql
-- Step 1: Configure aggressive timeout protections for this session only.
-- This ensures that waiting for lock acquisition NEVER cascades and locks incoming writes.
SET lock_timeout = '2s';
SET statement_timeout = '0'; -- Allow build to run without query time-limit once lock is granted

-- Step 2: Create the index concurrently
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_stripe_customer_id 
ON users (stripe_customer_id);

-- Step 3: Check for index creation validity.
-- If CONCURRENTLY fails (due to duplicate key or statement cancellation),
-- an INVALID index remains on disk, consuming resources and breaking query plans.
DO $$
DECLARE
    invalid_index_record RECORD;
BEGIN
    FOR invalid_index_record IN
        SELECT indexrelid::regclass AS index_name, indrelid::regclass AS table_name
        FROM pg_index
        WHERE indisvalid = false
    LOOP
        RAISE WARNING 'CRITICAL: Index % on Table % is marked INVALID. Dropping...',
            invalid_index_record.index_name,
            invalid_index_record.table_name;
        
        EXECUTE 'DROP INDEX CONCURRENTLY ' || invalid_index_record.index_name;
    END LOOP;
END;
$$;
```

---

## 9. EXPLAIN ANALYZE Optimization Diagnostic Prompt

Use this system prompt within your local LLM or developer interface when evaluating non-performant query plans.

```markdown
You are an expert PostgreSQL DBA and Database Engine Engineer. 
Analyze the provided EXPLAIN (ANALYZE, BUFFERS, SETTINGS, WAL) output and accompanying schema definition.

Execute these diagnostic passes and respond using this exact markdown structure:

1. BOTTLENECK IDENTIFICATION
   - Point out the specific node consuming >30% of Total Runtime.
   - Flag any node where Actual Rows deviates from Estimated Rows by >5x (indicates stale statistics).
   - Identify memory spills: Sort nodes using "external merge Disk" or Hash joins using "Batches > 1".

2. CACHE & BUFFER ANALYSIS
   - Calculate hit ratio: (Shared Hit Blocks / (Shared Hit Blocks + Shared Read Blocks)) * 100.
   - List relations causing excessive disk access (`Shared Read Blocks`).
   - Flag any high `Dirtied` or `Written` buffer metrics indicating checkpoint/flush bottlenecks.

3. ACCESS PATH & OPERATOR REMEDIATIONS
   - If a "Seq Scan" is active: Provide the exact `CREATE INDEX CONCURRENTLY` statement using ESR column ordering.
   - If an "Index Scan" is doing excessive Heap Fetches: Provide the updated `INCLUDE` clause index definition.
   - If a Sort node exists: Restructure the compound index ordering to eliminate the runtime sort.

4. PARAMETER TUNING RECOMMENDATIONS
   - Recommend localized session parameters (e.g., `work_mem`, `random_page_cost`) to fix the target execution tree without risking global server memory limits.
```

---

## 10. Index Cleanliness, Bloat, and Pruning Queries

Run this production query to identify dead, redundant, and completely unused indexes draining system write capacity.

```sql
-- Identify completely unused indexes (Excludes Primary Keys & Constraints)
SELECT
    schemaname || '.' || relname AS table_name,
    indexrelname AS index_name,
    pg_size_pretty(pg_relation_size(i.indexrelid)) AS index_size,
    idx_scan AS index_scans_total,
    idx_tup_read AS tuples_read,
    idx_tup_fetch AS tuples_fetched
FROM pg_stat_user_indexes ui
JOIN pg_index i ON ui.indexrelid = i.index
