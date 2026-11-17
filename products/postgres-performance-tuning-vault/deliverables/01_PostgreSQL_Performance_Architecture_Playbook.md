# Module 1: Engine Architecture, Memory Models & Execution Planner Playbook

This playbook establishes the architectural baseline for configuring high-throughput PostgreSQL instances and systematically troubleshooting query plans. It targets dedicated database engines running PostgreSQL 14, 15, and 16 on modern Linux (x86_64 and ARM64) environments.

---

## 1. PostgreSQL Memory Architecture & Sizing Blueprint

PostgreSQL separates memory into two primary domains: **Shared Memory** (allocated once at postmaster startup, accessible by all backends) and **Local Backend Memory** (allocated per-process, per-query node as operations require).

```
+-----------------------------------------------------------------------------------+
| Linux Kernel Page Cache (FS Cache)                                                |
| (Absorbs double-buffering, writeout writeback, and readahead)                     |
+-----------------------------------------------------------------------------------+
                                          ▲
                                          │ Direct Block Reads / Syncs
+-----------------------------------------▼-----------------------------------------+
| PostgreSQL Shared Memory (Allocated via POSIX/SysV Shared Memory or mmap)          |
|  +------------------------------------------------------------------------------+ |
|  | shared_buffers (8KB buffer pages managed via Clock-Sweep algorithm)          | |
|  +------------------------------------------------------------------------------+ |
|  | wal_buffers (WAL records pending disk flush)                                 | |
|  +------------------------------------------------------------------------------+ |
|  | lock tables, pred_locks, prepared transactions, pg_stat tracking data        | |
|  +------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------+
       ▲                                 ▲                                 ▲
       │                                 │                                 │
+------▼--------------+           +------▼--------------+           +------▼--------------+
| Backend Process 1   |           | Backend Process 2   |           | Autovacuum Worker   |
| (Client Session)    |           | (Client Session)    |           +---------------------+
+---------------------+           +---------------------+           | maintenance_work_mem|
| work_mem (Sort)     |           | work_mem (HashJoin) |           | autovacuum_work_mem |
| work_mem (Material) |           | temp_buffers        |           +---------------------+
+---------------------+           +---------------------+
```

### Parameter Sizing Formulas and Trade-Offs

#### `shared_buffers`
- **Default:** `128MB` (Severely undersized for production).
- **Formula:** 
  $$\text{shared\_buffers} = 0.25 \times \text{Total System RAM}$$
- **Operational Reality:** On bare-metal and cloud VMs with $\ge 64\text{ GB}$ RAM, test between 25% and 40%. Beyond 40%, PostgreSQL experiences double-buffering overhead and severe eviction contention with the Linux kernel page cache. If write loads are sustained and checkpoint writeback is slow, larger `shared_buffers` prolongs dirty-page checkpoint sweeps.

#### `effective_cache_size`
- **Default:** `4GB`.
- **Formula:**
  $$\text{effective\_cache\_size} = 0.75 \times \text{Total System RAM}$$
- **Operational Reality:** This parameter does *not* allocate memory; it informs the query planner of the total memory available for caching data pages (PostgreSQL's internal buffers + OS page cache). An accurate setting biases the cost engine toward Index Scans over Sequential Scans.

#### `work_mem`
- **Default:** `4MB`.
- **Formula (Worst-Case Allocation Ceiling):**
  $$\text{work\_mem} \le \frac{\text{Total System RAM} - \text{shared\_buffers} - \text{maintenance\_work\_mem} - (2\text{GB OS overhead})}{\text{max\_connections} \times \text{max\_parallel\_workers\_per\_gather} \times 2.5}$$
- **Operational Reality:** `work_mem` is allocated **per sort/hash operation**, not per connection. A complex query containing 4 Hash Joins, a Window Function, and a Sort node can allocate $6 \times \text{work\_mem}$ concurrently within a single backend. Sizing `work_mem` globally above `64MB` invites the Linux Out-Of-Memory (OOM) Killer under concurrency spikes. Apply larger values dynamically at the transaction or session level.

#### `maintenance_work_mem`
- **Formula:** 
  $$\text{maintenance\_work\_mem} = \min(0.05 \times \text{Total RAM}, 2\text{GB})$$
- **Operational Reality:** Capped practically at `2GB` for autovacuum operations because dead tuple tracking arrays cannot exceed the 32-bit integer addressing model efficiently. Larger allocations accelerate single-threaded manual `CREATE INDEX` or `VACUUM FULL` commands, but multiple concurrent autovacuum workers will exhaust host memory if individual allocations exceed $1\text{–}2\text{ GB}$.

---

### Production Hardware Sizing Matrix

| Metric / Parameter | 16 GB RAM (Edge / Small Core) | 64 GB RAM (Mid-Tier OLTP) | 256 GB RAM (Enterprise High-Scale) |
| :--- | :--- | :--- | :--- |
| **Max Concurrent Connections** | `100` | `250` | `500` (via PgBouncer pool) |
| `shared_buffers` | `4GB` | `16GB` | `64GB` |
| `effective_cache_size` | `12GB` | `48GB` | `192GB` |
| `work_mem` (Global Default) | `16MB` | `32MB` | `64MB` |
| `maintenance_work_mem` | `512MB` | `2GB` | `2GB` |
| `min_wal_size` | `1GB` | `4GB` | `16GB` |
| `max_wal_size` | `4GB` | `16GB` | `64GB` |
| `huge_pages` | `off` / `try` | `on` | `on` |
| `max_parallel_workers_per_gather` | `2` | `4` | `4` |
| `max_worker_processes` | `4` | `8` | `16` |

---

### Critical Host-Level Overcommit & Huge Pages Configuration

PostgreSQL performance collapses under high context-switching and page-table traversal costs unless Transparent Huge Pages (THP) are disabled and Static Huge Pages are reserved.

Execute the following configuration directly on the database host OS (Debian/Ubuntu/RHEL):

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Disable Transparent Huge Pages (Causes latency spikes via background compaction)
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag

# Ensure THP changes persist across reboots
cat << 'EOF' > /etc/systemd/system/disable-thp.service
[Unit]
Description=Disable Transparent Huge Pages (THP)
DefaultDependencies=no
After=sysinit.target local-fs.target
Before=mongod.service postgresql.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag'

[Install]
WantedBy=basic.target
EOF

systemctl daemon-reload
systemctl enable --now disable-thp.service

# 2. Configure Virtual Memory Overcommit Handling
# mode 2 = Do not overcommit. Total allocation space = swap + (RAM * overcommit_ratio)
cat << 'EOF' > /etc/sysctl.d/99-postgresql.conf
vm.overcommit_memory = 2
vm.overcommit_ratio = 80
vm.swappiness = 1
vm.dirty_background_ratio = 3
vm.dirty_ratio = 10
EOF

sysctl --system
```

#### Calculating and Allocating Linux Static Huge Pages (2MB Pages)

To calculate static huge pages for a target `shared_buffers` of `16GB`:

```bash
# 16GB = 16777216 KB. Divide by 2048 KB (2MB page size) = 8192 pages.
# Add 5% overhead for non-shared_buffers shared segments (e.g., locks, tracking)
TOTAL_PAGES=8600

cat << EOF >> /etc/sysctl.d/99-postgresql.conf
vm.nr_hugepages = ${TOTAL_PAGES}
EOF

sysctl -p /etc/sysctl.d/99-postgresql.conf

# Map PostgreSQL user group (e.g., gid 999 for postgres) to hugepage access
PG_GID=$(id -g postgres)
sysctl -w vm.hugetlb_shm_group="${PG_GID}"
```

In `postgresql.conf`, set:
```ini
huge_pages = on # Forces server to fail to start if static huge pages are exhausted
```

---

## 2. Write-Ahead Logging (WAL) & Checkpoint Tuning Blueprint

Checkpoints write dirty shared buffers to disk, issue an `fsync`, and truncate the WAL. If checkpoints execute too frequently or aggressively, the storage controller experiences severe I/O stalls (checkpoint spikes), elevating p99 latencies.

### Checkpoint Spacing & Target Completion

```
Checkpoint Start                                                 Checkpoint End
       |----------------------------------------------------------------|
       |<-------------- checkpoint_completion_target (0.9) ------------>|
       |                                                                |
   WAL Generation: (max_wal_size allocated over this timeline window)    Fsync Flush
```

* **Target Rule:** Checkpoints should be driven by **time**, not by WAL volume exhaustion.
* If checkpoints are triggered by `max_wal_size` instead of `checkpoint_timeout`, PostgreSQL writes pages faster than the background writer can throttle, causing write stalls.

### Production WAL & Checkpoint Configuration Block

Append these settings to `/etc/postgresql/postgresql.conf`:

```ini
# ==========================================
# STORAGE & WRITE-AHEAD LOG (WAL) SUBSYSTEM
# ==========================================
wal_level = replica
wal_compression = zstd                      # PG 15+: Drastic WAL volume reduction with minimal CPU overhead
wal_buffers = 16MB                          # Set to max allocation size (1/32 of shared_buffers up to 16MB)
checkpoint_timeout = 15min                  # Balances crash recovery time vs write smoothing (15-30min standard)
checkpoint_completion_target = 0.9          # Spread I/O over 90% of checkpoint_timeout window
min_wal_size = 4GB                          # Retain baseline allocations to prevent filesystem reallocation overhead
max_wal_size = 32GB                         # Increase threshold to prevent checkpoint storms under heavy ingestion
checkpoint_warning = 30s                    # Alert in logs if checkpoints happen closer than 30s

# Flush behavior tuning
synchronous_commit = off                    # Enable ONLY for non-financial/transient workloads to eliminate sync waits
commit_delay = 20                           # Microsecond delay to allow group commit batching
commit_siblings = 5                         # Minimum concurrent transactions required to trigger commit_delay
```

### WAL Production Diagnostics

Run this query to identify whether checkpoints are scheduled (healthy) or forced by WAL exhaustion (unhealthy):

```sql
SELECT
    checkpoints_timed,
    checkpoints_req,
    ROUND(100.0 * checkpoints_req / NULLIF(checkpoints_timed + checkpoints_req, 0), 2) AS pct_forced_checkpoints,
    checkpoint_write_time,
    checkpoint_sync_time,
    ROUND((checkpoint_write_time + checkpoint_sync_time)::numeric / NULLIF(checkpoints_timed + checkpoints_req, 0), 2) AS avg_checkpoint_ms,
    buffers_checkpoint,
    buffers_clean,
    maxwritten_clean,
    buffers_backend,
    buffers_backend_fsync
FROM pg_stat_bgwriter;
```

#### Diagnostic Evaluation
* **`pct_forced_checkpoints` > 10%:** `max_wal_size` is too low. WAL writes are exhausting disk allocation before `checkpoint_timeout` elapses. Double `max_wal_size`.
* **`maxwritten_clean` increasing daily:** The background writer (`bgwriter`) stopped processing because it exceeded `bgwriter_lru_maxpages`. Increase `bgwriter_lru_multiplier` to `3.0` and `bgwriter_lru_maxpages` to `400`.
* **`buffers_backend` significantly higher than `buffers_clean`:** Client backend workers are cleaning dirty pages directly instead of retrieving clean pages from shared buffers. Increase `shared_buffers` or tune `bgwriter` parameters.

---

## 3. Autovacuum Architecture & Anti-Wraparound Engineering

PostgreSQL uses Multi-Version Concurrency Control (MVCC). Modifying a tuple issues an `INSERT` of the new version and sets the `xmax` metadata marker on the old row, converting it into a dead tuple. Autovacuum is responsible for three tasks:
1. Reclaiming dead tuple physical space within 8KB heap pages (creating free space for new tuples without table bloat).
2. Updating data distribution statistics via `ANALYZE` for the query planner.
3. Freezing old `Transaction IDs (XIDs)` to prevent catalog-wide database shutdown caused by transaction ID wraparound.

### Aggressive Autovacuum Tuning Configuration

The default PostgreSQL configuration allocates 1 worker with severe cost-throttling delays, causing vacuum queues to fall behind under write rates $> 500 \text{ ops/sec}$.

Apply this configuration to ensure autovacuum scales dynamically:

```ini
# ==========================================
# AUTOVACUUM SYSTEM CONCURRENCY & LIMITS
# ==========================================
autovacuum = on
autovacuum_max_workers = 6                  # Max parallel vacuum workers across disparate tables
autovacuum_naptime = 15s                    # Check catalogs every 15s for tables needing work
autovacuum_vacuum_threshold = 50            # Minimum dead tuples to trigger vacuum
autovacuum_vacuum_scale_factor = 0.05       # Trigger vacuum when dead tuples reach 5% of total rows (down from 20%)
autovacuum_analyze_threshold = 50           # Minimum row modifications to trigger analyze
autovacuum_analyze_scale_factor = 0.02      # Trigger analyze when modifications reach 2% of total rows

# Dynamic I/O cost throttle sizing
# Cost unit mapping: vacuum_cost_page_hit = 1, vacuum_cost_page_miss = 2, vacuum_cost_page_dirty = 20
autovacuum_vacuum_cost_delay = 2ms          # Sleep duration when cost limit is hit (Default 20ms is far too slow)
autovacuum_vacuum_cost_limit = 2000         # Total shared processing budget across all active workers (Default 200)

# Transaction ID Wraparound Protection
autovacuum_freeze_max_age = 200000000       # Maximum XID age before forced, unskippable autovacuum occurs
vacuum_freeze_min_age = 50000000            # Cutoff point to freeze tuples
vacuum_freeze_table_age = 150000000
```

### High-Scale Per-Table Autovacuum Overrides

High-volume tables (such as append-heavy audit logs, outbox tables, or high-update ledger records) require explicit overrides. Setting these prevents large tables from starving smaller tables of vacuum resources:

```sql
-- High-write dynamic ledger or job table (e.g., 5,000 writes/sec)
ALTER TABLE app_orders SET (
    autovacuum_vacuum_scale_factor = 0.01,    -- Trigger at 1% dead tuples
    autovacuum_vacuum_threshold = 1000,
    autovacuum_vacuum_cost_limit = 5000,      -- High dedicated I/O budget
    autovacuum_vacuum_cost_delay = 0          -- Disable throttling completely on fast NVMe storage
);

-- High-ingestion append-only event log (No UPDATEs, only INSERTs)
-- Analyze must run aggressively, but vacuuming dead rows is not needed
ALTER TABLE audit_event_stream SET (
    autovacuum_vacuum_scale_factor = 0.80,    -- Vacuum rarely (only for freeze)
    autovacuum_analyze_scale_factor = 0.005,  -- Analyze every 0.5% inserted rows
    autovacuum_vacuum_cost_delay = 2
);
```

### Vacuum Health & Wraparound Horizon Production Monitor

Use this monitor query to track dead tuple accumulation, unvacuumed table bloat, and the distance to the Transaction ID wraparound threshold:

```sql
SELECT
    c.oid::regclass AS table_name,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
    s.n_live_tup,
    s.n_dead_tup,
    ROUND(100.0 * s.n_dead_tup / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 2) AS dead_tuple_percent,
    s.last_vacuum,
    s.last_autovacuum,
    age(c.relfrozenxid) AS xid_age,
    ROUND(100.0 * age(c.relfrozenxid) / 2147483648, 2) AS pct_towards_wraparound
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE c.relkind IN ('r', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY age(c.relfrozenxid) DESC, s.n_dead_tup DESC
LIMIT 20;
```

---

## 4. The Execution Planner Decoded & EXPLAIN Rubric

The cost engine processes logical query parse trees to produce execution plans. Costs are expressed in arbitrary, normalized units anchored by:
* `seq_page_cost = 1.0` (Sequential block access from disk)
* `random_page_cost = 4.0` (Mechanical seek cost default; **reduce to 1.1 on modern NVMe drives**)
* `cpu_tuple_cost = 0.01` (CPU processing cost per physical tuple)
* `cpu_index_tuple_cost = 0.005` (CPU processing cost per index entry)
* `cpu_operator_cost = 0.0025` (Cost to evaluate expressions/predicates)

### Buffer Diagnostics Matrix

When analyzing a query plan via `EXPLAIN (ANALYZE, BUFFERS, SETTINGS, TIMING)`, match the reported buffer outputs against the following matrix:

| Metric Observed | Diagnostic Root Cause | Required Engineering Remediation |
| :--- | :--- | :--- |
| `shared read > 0` | Data block was not present in PostgreSQL `shared_buffers`; required a synchronous kernel read / disk fetch. | Increase `shared_buffers` or verify whether `random_page_cost` matches SSD latency. Create a targeted covering index to avoid reading full data pages. |
| `shared hit > 0` | Data block was resolved directly in PostgreSQL `shared_buffers`. | Optimal memory access path. No remediation required. |
| `shared dirtied > 0` | The execution node modified a page in memory (e.g., via row mutation or setting page hints). | Normal for DML; investigate if dirtying pages during `SELECT` operations due to unhinted tuple updates (run `VACUUM` to set hint bits). |
| `shared written > 0` | Backend process had to write dirty memory blocks to disk *mid-query* to free room for its own reads. | Critical bottleneck: Background writer cannot keep up. Increase `bgwriter_lru_maxpages` and verify system disk I/O bandwidth. |
| `temp read > 0` / `temp written > 0` | The query node exceeded the configured `work_mem` allocation and spilled intermediate sets (hash tables or quicksort runs) to temp disk files. | Increase `work_mem` for the query, optimize the join cardinality, or refactor CTE aggregations. |

---

### Step-by-Step EXPLAIN Analysis Playbook

#### Step 1: Execute the Plan Capture Harness
Do not run bare `EXPLAIN`. Use this diagnostic wrapper:

```sql
BEGIN;
EXPLAIN (ANALYZE, BUFFERS, SETTINGS, WAL, TIMING)
SELECT 
    o.id,
    o.customer_id,
    SUM(i.quantity * i.unit_price) AS order_total
FROM app_orders o
JOIN app_order_items i ON i.order_id = o.id
WHERE o.created_at >= NOW() - INTERVAL '30 days'
  AND o.status = 'COMPLETED'
GROUP BY o.id, o.customer_id
ORDER BY order_total DESC
LIMIT 50;
ROLLBACK; -- Ensures write queries tested under this harness revert changes safely
```

#### Step 2: Identify Cardinality Discrepancies
Inspect each node for differences between estimated rows and actual rows:
```
->  Hash Join  (cost=1254.20..14291.50 rows=125 width=24) 
               (actual time=14.210..382.112 rows=145020 loops=1)
```
* **Discrepancy:** The planner predicted `rows=125`, but the execution engine processed `rows=145020` (a $> 1000\times$ divergence).
* **Consequence:** The optimizer chose a **Nested Loop** or an undersized in-memory **Hash Join** instead of a **Merge Join** or a hash table sized to the real data volume.
* **Remediation:** Refresh stale statistics immediately:
  ```sql
  ANALYZE app_orders;
  -- If distributions are highly skewed, expand statistics collection targets
  ALTER TABLE app_orders ALTER COLUMN status SET STATISTICS 500;
  ANALYZE app_orders;
  ```

#### Step 3: Identify WorkMem Spills (Sorts & Hashes)
Check the memory profile output inside the sort or hash node:

```
Sort Method: external merge  Disk: 45840kB
-- vs --
Sort Method: quicksort  Memory: 25420kB
```
* `external merge  Disk`: The sorting set exceeded backend `work_mem`, generating physical I/O writes to disk in `pgsql_tmp`.
* **Dynamic Query-Level Remediation:**
  Do not universally expand global `work_mem`. Scope it directly to the problematic transaction:
  ```sql
  BEGIN;
  SET LOCAL work_mem = '128MB';
  -- Run problematic query here
  COMMIT;
  ```

#### Step 4: Trace High-Volume Filter Discards
Locate sequential or index scans with disproportionate filter loss:

```
->  Seq Scan on app_order_items  (cost=0.00..89240.12 rows=200000 width=16)
                                 (actual time=0.052..680.120 rows=150 loops=1)
    Filter: (status = 'CANCELLED'::text)
    Rows Removed by Filter: 4899850
```
* **Root Cause:** PostgreSQL scanned $4.9\text{ million}$ physical rows sequentially to identify 150 matching records.
* **Remediation:** Create a targeted partial index:
  ```sql
  CREATE INDEX CONCURRENTLY idx_order_items_cancelled_paged
  ON app_order_items (id) 
  WHERE status = 'CANCELLED';
  ```

---

## 5. Comprehensive Diagnostic Suite: Memory, Storage, and Worker Contention

Execute this diagnostic script against an active production environment to immediately assess system bottlenecks:

```sql
-- ==============================================================================
-- POSTGRESQL PRODUCTION ARCHITECTURAL & PLANNED BOTTLENECK AUDIT SUITE
-- ==============================================================================

-- 1. Identify Queries Spilling to Disk (Temporary File Allocation by Database)
SELECT 
    datname,
    temp_files AS temp_files_created,
    pg_size_pretty(temp_bytes) AS temp_file_volume_spilled
FROM pg_stat_database
WHERE temp_files > 0
ORDER BY temp_bytes DESC;

-- 2. Scan Type Distribution (Sequential vs Index Scans across Schemas)
SELECT
    schemaname,
    relname AS table_name,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch,
    ROUND(100.0 * idx_scan / NULLIF(seq_scan + idx_scan, 0), 2) AS index_scan_ratio
FROM pg_stat_user_tables
WHERE (seq_scan + idx_scan) > 500
ORDER BY seq_tup_read DESC
LIMIT 20;

-- 3. Cache Hit Ratio (Sustained target should exceed 99.00%)
SELECT
    'shared_buffers_hit_ratio' AS metric,
    ROUND(100.0 * sum(blks_hit) / NULLIF(sum(blks_hit + blks_read), 0), 3) AS percentage
FROM pg_stat_database;

-- 4. Active Backend Connection States and Memory Work Contention
SELECT
    pid,
    usename,
    client_addr,
    wait_event_type,
    wait_event,
    state,
    ROUND(EXTRACT(EPOCH FROM (NOW() - query_start))::numeric, 2) AS active_seconds,
    query
FROM pg_stat_activity
WHERE state != 'idle'
  AND pid <> pg_backend_pid()
ORDER BY active_seconds DESC;
```

---

## 6. Production Architecture Implementation Checklist

Use this checklist before promoting changes from staging to production:

```markdown
- [ ] 1. Host OS Kernel Configuration
  - [ ] Transparent Huge Pages (THP) explicitly set to 'never' in system initialization scripts.
  - [ ] vm.overcommit_memory set to 2; vm.overcommit_ratio set to 80.
  - [ ] Static Huge Pages (2MB) pre-calculated, verified via sysctl, and active in `postgresql.conf` (`huge_pages = on`).

- [ ] 2. Memory Baseline
  - [ ] `shared_buffers` sized accurately (25% to 40% of total host RAM).
  - [ ] `effective_cache_size` set to 75% of total system memory.
  - [ ] `work_mem` safely calculated against max_connections * parallel gather limits to avoid OOM killer events.
  - [ ] `maintenance_work_mem` allocated up to 2GB max to guard worker allocation limits.

- [ ] 3. Write-Ahead Logging & Checkpoint Safety
  - [ ] `checkpoint_completion_target` set to 0.9.
  - [ ] `checkpoint_timeout` configured between 15min and 30min.
  - [ ] `max_wal_size` expanded (16GB-64GB) to eliminate forced checkpoints (`pct_forced_checkpoints` verified < 5%).
  - [ ] `wal_compression` set to `zstd` on PostgreSQL 15+.

- [ ] 4. Autovacuum Subsystem Scalability
  - [ ] `autovacuum_vacuum_cost_delay` lowered from default 20ms to 2ms.
  - [ ] `autovacuum_vacuum_cost_limit` scaled to at least 2000.
  - [ ] Base scale factors reduced (`autovacuum_vacuum_scale_factor` = 0.05, `autovacuum_analyze_scale_factor` = 0.02).
  - [ ] Custom autovacuum thresholds mapped directly onto high-frequency insert/update tables.

- [ ] 5. Query Planning System Verification
  - [ ] `random_page_cost` set to 1.1 on NVMe enterprise SSD storage (down from mechanical default 4.0).
  - [ ] Execution plan evaluations execute via `EXPLAIN (ANALYZE, BUFFERS, SETTINGS, WAL)`.
  - [ ] Production statistics sampling verify accurate row estimations within a 1.5x factor of actual cardinality.
