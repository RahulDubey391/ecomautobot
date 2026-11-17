# Module 4: PostgreSQL Health Audit Rubric, pg_stat Views & Triage Swipe File

Maintaining a high-throughput, low-latency PostgreSQL instance requires moving past generic metrics and implementing precise, view-level diagnostics. This deliverable serves as your production battle-plan: a formal engineering rubric for instance health, an open-source SQL diagnostic toolkit, an incident response Standard Operating Procedure (SOP) for active outages, and declarative Prometheus alert rules ready for production deployment.

---

## 1. The PostgreSQL Production Health Rubric

Use this health rubric during routine weekly database reviews, capacity planning cycles, or performance health audits.

| Metric | Healthy Range | Warning Threshold | Critical Emergency Value | Exact Diagnostic Query / Extraction Command |
| :--- | :--- | :--- | :--- | :--- |
| **Buffer Cache Hit Ratio** | $\ge 99.0\%$ (OLTP)<br>$\ge 90.0\%$ (OLAP) | $95.0\% - 98.9\%$ | $< 95.0\%$ (OLTP)<br>$< 85.0\%$ (OLAP) | `SELECT sum(heap_blks_hit) / nullif(sum(heap_blks_hit) + sum(heap_blks_read), 0) * 100 AS ratio FROM pg_statio_user_tables;` |
| **Index Usage Ratio** | $\ge 95.0\%$ on tables $> 10\text{k}$ rows | $80.0\% - 94.9\%$ | $< 80.0\%$ | `SELECT relname, 100.0 * idx_scan / nullif(seq_scan + idx_scan, 0) AS idx_pct FROM pg_stat_user_tables WHERE (seq_scan + idx_scan) > 1000;` |
| **Transaction ID Age (XID Wraparound)** | $< 200\text{M}$ transactions | $200\text{M} - 800\text{M}$ transactions | $> 1.0\text{B}$ transactions (Emergency Vacuum Required) | `SELECT datname, age(datfrozenxid) FROM pg_database WHERE datallowconn ORDER BY 2 DESC;` |
| **Table Dead Tuple Ratio (Bloat)** | $< 5.0\%$ dead tuples | $5.0\% - 19.9\%$ | $\ge 20.0\%$ dead tuples | `SELECT relname, n_dead_tup, n_live_tup, round(n_dead_tup::numeric / nullif(n_live_tup + n_dead_tup, 0) * 100, 2) AS dead_pct FROM pg_stat_user_tables;` |
| **Active Lock Wait Duration** | $0\text{ ms}$ sustained lock wait | $> 1000\text{ ms}$ wait | $> 5000\text{ ms}$ (Query Queue Building) | `SELECT max(now() - state_change) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND state = 'active';` |
| **Replication Physical Lag** | $< 16\text{ MB}$ or $< 1\text{ sec}$ | $16\text{ MB} - 1\text{ GB}$ / $1\text{s} - 30\text{s}$ | $> 1\text{ GB}$ or $> 30\text{s}$ (Replica Stale/Failing) | `SELECT client_addr, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes FROM pg_stat_replication;` |
| **Connection Pool Saturation** | $< 70\%$ of `max_connections` | $70\% - 89\%$ | $\ge 90\%$ (Exhaustion Imminent) | `SELECT count(*)::float / (SELECT setting::float FROM pg_settings WHERE name = 'max_connections') * 100 FROM pg_stat_activity;` |
| **Temp File Spills** | $0\text{ temp files / sec}$ | $> 0\text{ files}$, total size $< 1\text{GB}/ \text{hr}$ | Total size $> 10\text{ GB} / \text{hr}$ | `SELECT temp_files, pg_size_pretty(temp_bytes) FROM pg_stat_database WHERE datname = current_database();` |

---

## 2. Comprehensive `pg_stat_*` Diagnostic SQL Toolkit

Execute these production-safe queries directly against your primary database instance to isolate bottlenecks.

### 2.1 Cache Hit Ratio (Buffer Pool Efficiency)

#### Global Instance Cache Hit Ratio
```sql
SELECT
    round(100.0 * sum(heap_blks_hit) / NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0), 3) AS instance_heap_hit_ratio,
    round(100.0 * sum(idx_blks_hit) / NULLIF(sum(idx_blks_hit) + sum(idx_blks_read), 0), 3) AS instance_idx_hit_ratio,
    round(100.0 * (sum(heap_blks_hit) + sum(idx_blks_hit)) / 
        NULLIF(sum(heap_blks_hit) + sum(heap_blks_read) + sum(idx_blks_hit) + sum(idx_blks_read), 0), 3) AS combined_hit_ratio
FROM pg_statio_user_tables;
```

#### Worst 10 Tables by Cache Miss Volume (Disk Read Bottlenecks)
```sql
SELECT
    schemaname,
    relname AS table_name,
    heap_blks_read AS disk_reads,
    heap_blks_hit AS cache_hits,
    round(100.0 * heap_blks_hit / NULLIF(heap_blks_hit + heap_blks_read, 0), 2) AS cache_hit_pct,
    pg_size_pretty(pg_relation_size(relid)) AS table_size
FROM pg_statio_user_tables
WHERE heap_blks_read + heap_blks_hit > 5000
ORDER BY heap_blks_read DESC
LIMIT 10;
```

### 2.2 Unused, Duplicate, and High-Overhead Index Detection

#### Completely Unused Indexes (Excluding Primary/Unique Constraints)
```sql
SELECT
    s.schemaname,
    s.relname AS table_name,
    s.indexrelname AS index_name,
    s.idx_scan AS number_of_scans,
    pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size,
    s.idx_tup_read,
    s.idx_tup_fetch
FROM pg_stat_user_indexes s
JOIN pg_index i ON s.indexrelid = i.indexrelid
WHERE s.idx_scan = 0
  AND i.indisunique = FALSE
  AND i.indisprimary = FALSE
ORDER BY pg_relation_size(s.indexrelid) DESC;
```

#### Redundant / Duplicate Indexes (Identical Column Definitions)
```sql
SELECT
    pg_size_pretty(sum(pg_relation_size(idx))) AS total_wasted_size,
    array_agg(idx::regclass) AS duplicate_indexes,
    table_name
FROM (
    SELECT
        indexrelid AS idx,
        indrelid::regclass AS table_name,
        (indrelid::text || ' ' || indkey::text || ' ' || indclass::text || ' ' || 
         coalesce(indpredicate::text, '')) AS key_signature
    FROM pg_index
) sub
GROUP BY table_name, key_signature
HAVING count(*) > 1
ORDER BY sum(pg_relation_size(idx)) DESC;
```

#### High-Maintenance Write-Overhead Indexes (Low Read/Write Ratio)
```sql
SELECT
    s.schemaname,
    s.relname AS table_name,
    s.indexrelname AS index_name,
    s.idx_scan AS total_reads,
    (stat.n_tup_ins + stat.n_tup_upd + stat.n_tup_del) AS total_writes,
    round(s.idx_scan::numeric / NULLIF(stat.n_tup_ins + stat.n_tup_upd + stat.n_tup_del, 0), 4) AS read_to_write_ratio,
    pg_size_pretty(pg_relation_size(s.indexrelid)) AS index_size
FROM pg_stat_user_indexes s
JOIN pg_stat_user_tables stat ON s.relid = stat.relid
JOIN pg_index i ON s.indexrelid = i.indexrelid
WHERE (stat.n_tup_ins + stat.n_tup_upd + stat.n_tup_del) > 100000
  AND s.idx_scan < 1000
  AND i.indisunique = FALSE
  AND i.indisprimary = FALSE
ORDER BY read_to_write_ratio ASC;
```

### 2.3 Heavyweight `pg_stat_statements` Deep-Dive

*Prerequisite: `pg_stat_statements` must be loaded in `shared_preload_libraries`.*

#### Top 10 Queries by Cumulative Execution Time (Total Burn Rate)
```sql
SELECT
    queryid,
    left(query, 100) AS truncated_query,
    calls,
    round(total_exec_time::numeric / 1000, 2) AS total_exec_time_sec,
    round(mean_exec_time::numeric, 2) AS mean_exec_ms,
    round(stddev_exec_time::numeric, 2) AS stddev_exec_ms,
    round(100.0 * total_exec_time / sum(total_exec_time) OVER (), 2) AS percent_total_time,
    rows
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

#### Top 10 High-Variance Queries (Unstable Execution Plans)
```sql
SELECT
    queryid,
    left(query, 100) AS truncated_query,
    calls,
    round(mean_exec_time::numeric, 2) AS mean_ms,
    round(stddev_exec_time::numeric, 2) AS stddev_ms,
    round((stddev_exec_time / NULLIF(mean_exec_time, 0))::numeric, 2) AS coefficient_of_variation
FROM pg_stat_statements
WHERE calls > 500
ORDER BY coefficient_of_variation DESC
LIMIT 10;
```

#### Top 10 Queries by Direct Disk I/O Bottleneck (Shared Buffer Misses)
```sql
SELECT
    queryid,
    left(query, 100) AS truncated_query,
    calls,
    shared_blks_read AS disk_blocks_read,
    shared_blks_hit AS cache_blocks_hit,
    round(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 2) AS query_cache_hit_pct,
    round((blk_read_time + blk_write_time)::numeric, 2) AS total_io_time_ms
FROM pg_stat_statements
WHERE shared_blks_read > 0
ORDER BY shared_blks_read DESC
LIMIT 10;
```

### 2.4 Dead Tuples, Autovacuum Health, and Table Bloat Estimation

#### Autovacuum Lag and Dead Tuple Accumulation
```sql
SELECT
    schemaname,
    relname AS table_name,
    n_live_tup,
    n_dead_tup,
    round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_tuple_pct,
    last_vacuum,
    last_autovacuum,
    vacuum_count,
    autovacuum_count
FROM pg_stat_user_tables
WHERE n_dead_tup > 10000
ORDER BY dead_tuple_pct DESC;
```

#### Real Table and Index Bloat Estimator
```sql
WITH constants AS (
    SELECT current_setting('block_size')::numeric AS bs, 23 AS hdr, 8 AS ma
),
table_estimates AS (
    SELECT
        schemaname, tableName, tblpages, reclen,
        ceil((cc.reltuples * reclen) / (bs - hdr)) AS est_pages
    FROM (
        SELECT
            schemaname,
            tablename AS tableName,
            c.reltuples,
            c.relpages AS tblpages,
            SUM((1 - null_frac) * avg_width) + 24 AS reclen
        FROM pg_stats s
        JOIN pg_class c ON s.tablename = c.relname
        JOIN pg_namespace n ON c.relnamespace = n.oid AND s.schemaname = n.nspname
        WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
        GROUP BY schemaname, tablename, c.reltuples, c.relpages
    ) cc, constants
)
SELECT
    schemaname,
    tableName,
    pg_size_pretty((tblpages * 8192)::bigint) AS real_size,
    pg_size_pretty((CASE WHEN tblpages > est_pages THEN (tblpages - est_pages) * 8192 ELSE 0 END)::bigint) AS estimated_bloat,
    round(100.0 * (CASE WHEN tblpages > est_pages THEN (tblpages - est_pages) ELSE 0 END) / NULLIF(tblpages, 0), 2) AS bloat_pct
FROM table_estimates
WHERE tblpages > 100
ORDER BY (tblpages - est_pages) DESC
LIMIT 15;
```

---

## 3. Incident Response Triage SOP & Command Matrix

### Emergency Triage Flowchart

```
                 +-----------------------------------+
                 | P0/P1 High Latency / Lock Outage  |
                 +-----------------------------------+
                                   |
                                   v
             [ Execute Query 3.1: Active Lock Tree ]
                                   |
       +---------------------------+---------------------------+
       |                                                       |
       v                                                       v
[ Blocking Root Found? ]                             [ No Locks, CPU/IO Maxed ]
       |                                                       |
       +-----------------------+                               v
       |                       |                    [ Query 2.3: `pg_stat_statements` ]
       v                       v                               |
[ Read Query ]         [ DDL / Long Transaction ]              v
       |                       |                    [ Cancel Top Resource Consumer ]
       v                       v                               |
[ pg_cancel_backend ]   [ pg_terminate_backend ]               v
                                                    [ Tune Work Mem / Set Limits ]
```

---

### Triage Step-by-Step Operations Guide

#### Step 1: Detect Root Blocking Backend (Lock Tree Resolution)
Do **not** randomly kill backends. Use this recursive query to map the exact dependency tree of blocked processes down to the single root offender.

```sql
WITH RECURSIVE lock_tree AS (
    SELECT
        blocking_l.pid AS blocking_pid,
        blocked_l.pid AS blocked_pid,
        blocked_a.query AS blocked_query,
        blocking_a.query AS blocking_query,
        1 AS depth
    FROM pg_catalog.pg_locks blocked_l
    JOIN pg_catalog.pg_stat_activity blocked_a ON blocked_a.pid = blocked_l.pid
    JOIN pg_catalog.pg_locks blocking_l 
        ON blocking_l.locktype = blocked_l.locktype
        AND blocking_l.database IS NOT DISTINCT FROM blocked_l.database
        AND blocking_l.relation IS NOT DISTINCT FROM blocked_l.relation
        AND blocking_l.page IS NOT DISTINCT FROM blocked_l.page
        AND blocking_l.tuple IS NOT DISTINCT FROM blocked_l.tuple
        AND blocking_l.virtualxid IS NOT DISTINCT FROM blocked_l.virtualxid
        AND blocking_l.transactionid IS NOT DISTINCT FROM blocked_l.transactionid
        AND blocking_l.classid IS NOT DISTINCT FROM blocked_l.classid
        AND blocking_l.objid IS NOT DISTINCT FROM blocked_l.objid
        AND blocking_l.objsubid IS NOT DISTINCT FROM blocked_l.objsubid
        AND blocking_l.pid != blocked_l.pid
    JOIN pg_catalog.pg_stat_activity blocking_a ON blocking_a.pid = blocking_l.pid
    WHERE NOT blocked_l.granted
)
SELECT 
    l.blocking_pid,
    l.blocking_query,
    l.blocked_pid,
    l.blocked_query,
    l.depth
FROM lock_tree l
ORDER BY l.depth ASC;
```

#### Step 2: Gracefully Interrupt or Terminate the Root Offender
If the root blocker is a long-running read query, issue a soft cancellation:

```sql
-- Attempt graceful query cancellation (SIGINT)
SELECT pg_cancel_backend(12345);
```

If the root blocker is an abandoned `idle in transaction` process, an unindexed migration, or does not respond to `pg_cancel_backend` within 10 seconds, forcefully terminate the process:

```sql
-- Force connection termination (SIGTERM)
SELECT pg_terminate_backend(12345);
```

#### Step 3: Mitigation of Sudden Connection Exhaustion
If the application pool exhausts `max_connections`, dynamically drop idle connections before restarting application servers:

```sql
-- Terminate all connections idling for longer than 5 minutes
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction' 
  AND state_change < now() - INTERVAL '5 minutes';
```

#### Step 4: Emergency Non-Blocking Vacuum for Severe Bloat or XID Age Escalation
When XID age exceeds $800\text{M}$ or dead tuple accumulation locks table access, execute a non-blocking parallel vacuum scoped strictly to the impacted table:

```sql
-- Never run plain VACUUM FULL during production traffic (it takes an AccessExclusiveLock).
-- Use optimized VACUUM ANALYZE with maximum worker parallelization.
SET LOCAL vacuum_cost_limit = 2000;
VACUUM (VERBOSE, ANALYZE, BUFFER_USAGE_LIMIT '512MB') public.orders;
```

#### Step 5: Temporary Session-Level Workaround for Query Spills
If an active emergency query is spilling heavily to disk and causing massive I/O degradation, apply a session-level operational override without restarting PostgreSQL:

```sql
-- Temporarily bump work_mem for the current maintenance connection
SET local work_mem = '512MB';
-- Apply query statement timeout to prevent unbounded queries from running over 10 seconds
SET local statement_timeout = '10000ms';
```

---

## 4. Automated Monitoring & Alerting Configuration Rules

Deploy this complete, valid `alerts.yml` file directly into your Prometheus / Alertmanager infrastructure (configured for `postgres_exporter`).

```yaml
groups:
  - name: postgresql_production_alerts
    rules:

      - alert: PostgresqlCacheHitRatioDegraded
        expr: >
          (
            sum(rate(pg_stat_database_blks_hit[5m])) 
            / 
            nullif(sum(rate(pg_stat_database_blks_hit[5m])) + sum(rate(pg_stat_database_blks_read[5m])), 0)
          ) * 100 < 95
        for: 5m
        labels:
          severity: warning
          tier: database
        annotations:
          summary: "PostgreSQL Instance Buffer Cache Hit Ratio Low"
          description: "Cache hit ratio for database '{{ $labels.datname }}' on {{ $labels.instance }} has dropped to {{ $value | printf \"%.2f\" }}%. Disk I/O is escalating."

      - alert: PostgresqlXIDWraparoundCritical
        expr: >
          (
            max(pg_database_datfrozenxid_age) by (instance, datname)
          ) > 800000000
        for: 0m
        labels:
          severity: critical
          page: true
          tier: database
        annotations:
          summary: "CRITICAL: Transaction ID Wraparound Risk Imminent"
          description: "Database '{{ $labels.datname }}' on {{ $labels.instance }} has reached an XID age of {{ $value }} transactions. Autovacuum is falling behind. System outage imminent without immediate manual intervention."

      - alert: PostgresqlSevereLockWaitEscalation
        expr: >
          sum(pg_stat_activity_count{wait_event_type="Lock", state="active"}) by (instance) > 5
        for: 1m
        labels:
          severity: critical
          page: true
          tier: database
        annotations:
          summary: "Active Lock Contention Escalation"
          description: "Instance {{ $labels.instance }} has {{ $value }} concurrent queries blocked waiting on locks for more than 60 seconds."

      - alert: PostgresqlReplicationLagCritical
        expr: >
          pg_replication_lag_bytes > 1073741824
        for: 2m
        labels:
          severity: critical
          tier: database
        annotations:
          summary: "PostgreSQL Streaming Replication Lag High"
          description: "Replication lag on replica {{ $labels.instance }} (application: {{ $labels.application_name }}) exceeds 1 GB (current: {{ $value | humanizeBytes }})."

      - alert: PostgresqlConnectionExhaustionImminent
        expr: >
          (
            sum(pg_stat_activity_count{state!="idle"}) by (instance)
            /
            sum(pg_settings_max_connections) by (instance)
          ) * 100 > 85
        for: 3m
        labels:
          severity: warning
          tier: database
        annotations:
          summary: "PostgreSQL Connection Pool Near Capacity"
          description: "Active connections on {{ $labels.instance }} reached {{ $value | printf \"%.2f\" }}% of max_connections. Consider connection pooler limits."

      - alert: PostgresqlExcessiveTempFileSpills
        expr: >
          rate(pg_stat_database_temp_bytes[10m]) > 104857600
        for: 5m
        labels:
          severity: warning
          tier: database
        annotations:
          summary: "High Volume Temp File Spill Detected"
          description: "Database '{{ $labels.datname }}' on {{ $labels.instance }} is spilling disk temp files at a rate of {{ $value | humanizeBytes }}/sec. Increase work_mem for heavy queries."
