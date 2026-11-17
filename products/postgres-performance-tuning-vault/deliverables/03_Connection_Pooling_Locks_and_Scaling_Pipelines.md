# Module 3: PgBouncer Pooling, Lock Contention & Zero-Downtime Migrations

High-concurrency PostgreSQL instances fail under load for two primary reasons: connection thrashing exhausting backend memory, and unmanaged exclusive locks stalling the transaction pipeline. This module provides drop-in infrastructure configurations for PgBouncer, a deterministic diagnostics engine for lock contention, and battle-tested DDL migration scripts designed for tables exceeding 10,000,000 rows.

---

## 1. Production-Grade PgBouncer Deployment

PostgreSQL forks a separate backend OS process for each client connection, allocating between 2 MB and 10 MB of memory per connection depending on `work_mem` and cached query plans. Beyond 200–500 direct connections, OS context-switching overhead causes CPU saturation and throughput collapse.

### 1.1 Complete `pgbouncer.ini` (Transaction Pooling Mode)

This configuration is optimized for a dedicated 4-to-8 vCPU connection-pooling instance handling up to 10,000 incoming client connections routed to an underlying PostgreSQL 14, 15, or 16 primary.

```ini
[databases]
; Syntax: dbname = host=... port=... dbname=... auth_user=... pool_size=...
production_db = host=10.0.1.10 port=5432 dbname=production_db auth_user=pgbouncer_auth

[pgbouncer]
; Administrative settings
logfile = /var/log/postgresql/pgbouncer.log
pidfile = /var/run/postgresql/pgbouncer.pid
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
auth_query = SELECT usename, passwd FROM pgbouncer_auth.lookup_user($1)
admin_users = pgbouncer_admin
stats_users = monitoring_user,datadog

; Connection Pool Configuration
pool_mode = transaction
max_client_conn = 10000
default_pool_size = 80
min_pool_size = 20
reserve_pool_size = 10
reserve_pool_timeout = 3.0
max_db_connections = 120

; Connection Lifecycles and Timeouts
server_lifetime = 3600
server_idle_timeout = 600
server_connect_timeout = 15
server_login_retry = 5
client_idle_timeout = 0
client_login_timeout = 60
query_timeout = 0
query_wait_timeout = 120
cancel_wait_timeout = 10

; Memory and Buffer Management
pkt_buf = 4096
max_packet_size = 2147483648
listen_backlog = 4096

; TCP Tuning
tcp_defer_accept = 1
tcp_socket_buffer = 0
tcp_keepalive = 1
tcp_keepcnt = 5
tcp_keepidle = 30
tcp_keepintvl = 10

; TLS Configuration
client_tls_sslmode = require
client_tls_key_file = /etc/ssl/private/pgbouncer.key
client_tls_cert_file = /etc/ssl/certs/pgbouncer.crt
server_tls_sslmode = verify-full
server_tls_ca_file = /etc/ssl/certs/internal-ca.crt

; Protocol and Prepared Statements (PgBouncer 1.21+)
max_prepared_statements = 250
server_reset_query = DISCARD ALL
server_check_query = SELECT 1
server_check_delay = 30
```

### 1.2 User Authentication Configuration (`userlist.txt` & SCRAM-SHA-256)

To avoid hardcoding passwords inside static configuration files across container redeployments, route authentication through a secured auth function.

#### PostgreSQL Auth Schema Setup (Run on PostgreSQL Primary)
```sql
CREATE SCHEMA IF NOT EXISTS pgbouncer_auth;

CREATE OR REPLACE FUNCTION pgbouncer_auth.lookup_user(in_user text)
RETURNS TABLE (usename name, passwd text) 
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RETURN QUERY
    SELECT s.usename, s.passwd
    FROM pg_shadow s
    WHERE s.usename = in_user;
END;
$$ LANGUAGE plpgsql;

REVOKE ALL ON SCHEMA pgbouncer_auth FROM PUBLIC;
REVOKE ALL ON FUNCTION pgbouncer_auth.lookup_user(text) FROM PUBLIC;

CREATE USER pgbouncer_auth WITH PASSWORD 'GenerateStrongPasswordHere123!';
GRANT USAGE ON SCHEMA pgbouncer_auth TO pgbouncer_auth;
GRANT EXECUTE ON FUNCTION pgbouncer_auth.lookup_user(text) TO pgbouncer_auth;
```

#### PgBouncer Bootstrap File (`/etc/pgbouncer/userlist.txt`)
Only the `pgbouncer_auth` lookup user needs to exist statically inside the local file:

```text
"pgbouncer_auth" "SCRAM-SHA-256$4096:5x...==$1w...:2y..."
"pgbouncer_admin" "SCRAM-SHA-256$4096:8z...==$9q...:4a..."
```

### 1.3 Pooling Modes Comparison Matrix

| Operational Capability | Session Pooling | Transaction Pooling | Statement Pooling |
| :--- | :--- | :--- | :--- |
| **Connection Binding Scope** | Lifetime of TCP connection | Lifetime of single `BEGIN...COMMIT` block | Single SQL statement |
| **Max Scale of App Clients** | Low (Bound by PG `max_connections`) | Very High (10k+ clients mapped to 50–100 backends) | Ultra High (Read-only distributed workloads) |
| **Named Prepared Statements** | Full native support | Supported in PgBouncer 1.21+ (`max_prepared_statements`) | Broken (Fails on execution) |
| **`SET LOCAL` Variables** | Fully persistent across queries | Valid only inside explicit transaction blocks | Broken / Ignored |
| **Advisory Locks** | Supported | Broken (Lock stays bound to PG backend process) | Broken |
| **`LISTEN` / `NOTIFY`** | Supported | Not supported | Not supported |
| **Temporary Tables** | Supported | Leaks state to next client / Throws errors | Leaks state / Throws errors |

---

## 2. Lock Contention Diagnostics and Profiling

High-throughput systems suffer cascaded downtime when slow read queries hold shared locks, blocking DDL or write operations that require exclusive locks. This results in an immediate queue buildup that consumes all available database connection slots.

### 2.1 Complete PostgreSQL Lock Compatibility Matrix

| Requested Mode \ Existing Mode | Access Share | Row Share | Row Exclusive | Share Update Exclusive | Share | Share Row Exclusive | Exclusive | Access Exclusive |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Access Share** (`SELECT`) | OK | OK | OK | OK | OK | OK | OK | **CONFLICT** |
| **Row Share** (`SELECT FOR UPDATE`) | OK | OK | OK | OK | OK | OK | **CONFLICT** | **CONFLICT** |
| **Row Exclusive** (`UPDATE`, `DELETE`) | OK | OK | OK | OK | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** |
| **Share Update Exclusive** (`VACUUM`, `ANALYZE`, `CREATE INDEX CONCURRENTLY`)| OK | OK | OK | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** |
| **Share** (`CREATE INDEX`) | OK | OK | **CONFLICT** | **CONFLICT** | OK | **CONFLICT** | **CONFLICT** | **CONFLICT** |
| **Share Row Exclusive** | OK | OK | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** |
| **Exclusive** | OK | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** |
| **Access Exclusive** (`ALTER TABLE`, `DROP`) | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** | **CONFLICT** |

### 2.2 Blocking Lock Diagnostic Engine

Run this diagnostic query to inspect root blockers, chained victims, wait times, and exact queries causing queue stalls:

```sql
WITH RECURSIVE lock_tree AS (
    SELECT 
        pg_blocking_pids(blocked_act.pid) AS direct_blockers,
        blocked_act.pid AS blocked_pid,
        blocked_act.usename AS blocked_user,
        blocked_act.client_addr AS blocked_client,
        blocked_act.query AS blocked_query,
        blocked_act.wait_event_type,
        blocked_act.wait_event,
        now() - blocked_act.query_start AS blocked_query_duration,
        now() - blocked_act.xact_start AS blocked_xact_duration,
        1 AS depth
    FROM pg_stat_activity blocked_act
    WHERE cardinality(pg_blocking_pids(blocked_act.pid)) > 0

    UNION ALL

    SELECT 
        pg_blocking_pids(blocker_act.pid) AS direct_blockers,
        blocker_act.pid AS blocked_pid,
        blocker_act.usename AS blocked_user,
        blocker_act.client_addr AS blocked_client,
        blocker_act.query AS blocked_query,
        blocker_act.wait_event_type,
        blocker_act.wait_event,
        now() - blocker_act.query_start AS blocked_query_duration,
        now() - blocker_act.xact_start AS blocked_xact_duration,
        lt.depth + 1
    FROM pg_stat_activity blocker_act
    JOIN lock_tree lt ON blocker_act.pid = ANY(lt.direct_blockers)
    WHERE blocker_act.pid <> ALL(lt.direct_blockers)
)
SELECT 
    DISTINCT ON (blocked_pid)
    depth,
    direct_blockers AS root_cause_pids,
    blocked_pid,
    blocked_user,
    blocked_client,
    wait_event_type || ':' || wait_event AS wait_reason,
    round(EXTRACT(EPOCH FROM blocked_query_duration)::numeric, 2) AS query_duration_sec,
    round(EXTRACT(EPOCH FROM blocked_xact_duration)::numeric, 2) AS xact_duration_sec,
    LEFT(REGEXP_REPLACE(blocked_query, '\s+', ' ', 'g'), 120) AS clean_query
FROM lock_tree
ORDER BY blocked_pid, depth DESC;
```

### 2.3 Automated Blocker Mitigation Script

This procedure isolates and cancels backend connections holding locks on a critical target table for longer than an explicit threshold.

```sql
CREATE OR REPLACE PROCEDURE public.terminate_blockers_on_relation(
    target_table_name text,
    max_duration interval DEFAULT interval '10 seconds',
    dry_run boolean DEFAULT true
)
LANGUAGE plpgsql
AS $$
DECLARE
    target_oid oid;
    blocker_record RECORD;
BEGIN
    SELECT c.oid INTO target_oid
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' 
      AND c.relname = target_table_name;

    IF target_oid IS NULL THEN
        RAISE EXCEPTION 'Table % not found', target_table_name;
    END IF;

    FOR blocker_record IN
        SELECT 
            a.pid,
            a.usename,
            a.query,
            now() - a.query_start AS runtime,
            l.mode
        FROM pg_locks l
        JOIN pg_stat_activity a ON l.pid = a.pid
        WHERE l.relation = target_oid
          AND a.pid <> pg_backend_pid()
          AND (now() - a.query_start) > max_duration
          AND a.state IN ('active', 'idle in transaction')
    LOOP
        IF dry_run THEN
            RAISE NOTICE '[DRY RUN] Would terminate PID % (User: %, Mode: %, Runtime: %): %',
                blocker_record.pid, blocker_record.usename, blocker_record.mode, 
                blocker_record.runtime, blocker_record.query;
        ELSE
            RAISE WARNING 'Terminating PID % (Runtime: %)', 
                blocker_record.pid, blocker_record.runtime;
            PERFORM pg_terminate_backend(blocker_record.pid);
        END IF;
    END LOOP;
END;
$$;
```

---

## 3. Deadlock Prevention and Engine Mitigation

Deadlocks occur when two or more transactions hold locks that the other transactions need to proceed, forming a cyclical dependency graph. PostgreSQL breaks deadlocks via its background engine worker after `deadlock_timeout` expires (default: 1 second), forcibly rolling back one of the transactions.

### 3.1 PostgreSQL Engine Configuration for Deadlock Tracing

Add these settings directly to `postgresql.conf`:

```ini
# Deadlock Detection and Logging Settings
deadlock_timeout = 100ms
log_lock_waits = on
log_recovery_conflict_waits = on
log_line_prefix = '%m [%p:%l] user=%u,db=%d,app=%a,client=%h '
```

### 3.2 Mitigation Pattern: Deterministic Sort Ordering

The most frequent source of application deadlocks is multi-row record updates executed in non-deterministic orders across concurrent application threads.

#### The Problematic Application Pattern
```sql
-- Thread A (Updating Batch X)
UPDATE accounts SET balance = balance - 100 WHERE id = 42;
UPDATE accounts SET balance = balance + 100 WHERE id = 99;

-- Concurrent Thread B (Updating Batch Y)
UPDATE accounts SET balance = balance - 50 WHERE id = 99;
UPDATE accounts SET balance = balance + 50 WHERE id = 42;
-- Result: Deadlock detected if transactions interleave.
```

#### The Production-Safe Blueprint (Deterministic `SELECT FOR UPDATE`)

Before running batch updates, enforce strict, ascending row-level lock acquisition using an array or subquery with an explicit `ORDER BY`:

```sql
BEGIN;

-- Lock rows in strict ascending key order
WITH target_accounts AS (
    SELECT id
    FROM accounts
    WHERE id IN (42, 99)
    ORDER BY id ASC
    FOR UPDATE
)
SELECT count(*) FROM target_accounts;

-- Proceed with batch updates safely
UPDATE accounts 
SET balance = balance - 100 
WHERE id = 42;

UPDATE accounts 
SET balance = balance + 100 
WHERE id = 99;

COMMIT;
```

---

## 4. Zero-Downtime DDL Migration Playbook (10M+ Rows)

Any direct DDL operation (`ALTER TABLE`, `ADD COLUMN`, `ADD CONSTRAINT`) requests an `ACCESS EXCLUSIVE` lock. If a long-running analytical query or batch update is active, the DDL command queues up behind it, blocking **all** subsequent reads and writes to that table until it executes.

### 4.1 Safe DDL Migration Wrapper Standard

Every migration executed on a production database with over 10M rows must be wrapped within a scoped transaction envelope containing strict timeouts and dynamic back-off retries.

```sql
-- Standard Production DDL Envelope Template
SET lock_timeout = '2s';
SET statement_timeout = '30s';

-- Step 1: Attempt non-blocking alter
DO $$
DECLARE
    attempts int := 0;
    max_attempts CONSTANT int := 5;
    success boolean := false;
BEGIN
    WHILE NOT success AND attempts < max_attempts LOOP
        BEGIN
            attempts := attempts + 1;
            
            -- Place target DDL statement here:
            ALTER TABLE orders ADD COLUMN notes text;
            
            success := true;
        EXCEPTION WHEN lock_not_available THEN
            IF attempts >= max_attempts THEN
                RAISE EXCEPTION 'Failed to acquire lock after % attempts', max_attempts;
            END IF;
            RAISE NOTICE 'Lock unavailable, sleeping before retry %...', attempts;
            PERFORM pg_sleep(3.0 * attempts);
        END;
    END LOOP;
END;
$$;

RESET lock_timeout;
RESET statement_timeout;
```

---

### 4.2 Pattern A: Safe Index Creation & Replacement

Direct `CREATE INDEX` acquires a `SHARE` lock, blocking all `INSERT`, `UPDATE`, and `DELETE` queries on a 10M+ row table for the entire duration of the build (often 10–60+ minutes).

#### Step-by-Step Safe Execution

1. Build index concurrently (takes `SHARE UPDATE EXCLUSIVE` lock, allows concurrent DML).
2. Catch and drop invalid indexes if interrupted.

```sql
-- Step 1: Create index concurrently (MUST run outside a transaction block)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id_created_at
ON orders (customer_id, created_at DESC);

-- Step 2: Validate the index was successfully built and is not marked invalid
DO $$
DECLARE
    is_valid boolean;
BEGIN
    SELECT indisvalid INTO is_valid
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    WHERE c.relname = 'idx_orders_customer_id_created_at';

    IF is_valid IS NOT TRUE THEN
        RAISE EXCEPTION 'Index build failed or marked INVALID. Run DROP INDEX CONCURRENTLY.';
    END IF;
END;
$$;
```

If an error occurs during build, an invalid index record remains, consuming disk space and degrading write performance. Recover using:

```sql
DROP INDEX CONCURRENTLY IF EXISTS idx_orders_customer_id_created_at;
```

---

### 4.3 Pattern B: Safe `NOT NULL` Column Additions

Prior to PostgreSQL 11, adding a column with a default value rewrote the entire table. In PostgreSQL 11+, non-volatile default values update only catalog metadata instantly. However, adding `NOT NULL` without a default value still requires a full-table table-scan with an `ACCESS EXCLUSIVE` lock.

```sql
-- Safe Step 1: Add the column as NULLABLE (Instant metadata operation)
SET lock_timeout = '2s';
ALTER TABLE orders ADD COLUMN fulfillment_status varchar(32);
RESET lock_timeout;

-- Safe Step 2: Add check constraint marked as NOT VALID (Instant metadata operation)
SET lock_timeout = '2s';
ALTER TABLE orders 
    ADD CONSTRAINT chk_orders_fulfillment_status_not_null 
    CHECK (fulfillment_status IS NOT NULL) NOT VALID;
RESET lock_timeout;

-- Safe Step 3: Validate constraint concurrently (Acquires SHARE UPDATE EXCLUSIVE - Writes permitted)
ALTER TABLE orders VALIDATE CONSTRAINT chk_orders_fulfillment_status_not_null;

-- Safe Step 4 (Optional - Postgres 12+): Transition constraint to standard NOT NULL
-- Since the CHECK constraint proves all rows are valid, this runs instantly.
SET lock_timeout = '2s';
ALTER TABLE orders ALTER COLUMN fulfillment_status SET NOT NULL;
ALTER TABLE orders DROP CONSTRAINT chk_orders_fulfillment_status_not_null;
RESET lock_timeout;
```

---

### 4.4 Pattern C: Zero-Downtime Data Backfill Engine

Updating 10,000,000 rows in a single `UPDATE` statement creates huge write amplification, generates gigabytes of WAL logs, exhausts `max_locks_per_transaction`, blocks concurrent vacuuming, and induces massive replica lag.

Use a keyset-pagination, batched-loop worker that explicitly releases locks after each chunk and throttles execution:

```sql
DO $$
DECLARE
    batch_size CONSTANT int := 5000;
    current_min_id bigint;
    current_max_id bigint;
    rows_updated int;
    total_updated bigint := 0;
BEGIN
    SELECT min(id) INTO current_min_id FROM orders;
    SELECT max(id) INTO current_max_id FROM orders;

    RAISE NOTICE 'Starting batch update from ID % to %', current_min_id, current_max_id;

    WHILE current_min_id <= current_max_id LOOP
        WITH batch AS (
            SELECT id 
            FROM orders
            WHERE id >= current_min_id 
              AND id < (current_min_id + batch_size)
              AND fulfillment_status IS NULL
            FOR UPDATE SKIP LOCKED
        )
        UPDATE orders o
        SET fulfillment_status = 'pending_processing'
        FROM batch b
        WHERE o.id = b.id;

        GET DIAGNOSTICS rows_updated = ROW_COUNT;
        total_updated := total_updated + rows_updated;

        -- Commit changes, release row locks, clean dead tuples
        COMMIT;

        -- Log progress and sleep briefly to allow replication stream to catch up
        RAISE NOTICE 'Processed chunk up to ID %. Total rows updated: %', 
            (current_min_id + batch_size), total_updated;

        current_min_id := current_min_id + batch_size;
        PERFORM pg_sleep(0.05); -- 50ms pause to throttle disk I/O and replication lag
    END LOOP;

    RAISE NOTICE 'Backfill complete. Total records updated: %', total_updated;
END;
$$;
```

---

### 4.5 Pattern D: Safe Foreign Key Addition

A naive `ALTER TABLE ... ADD CONSTRAINT FOREIGN KEY` triggers a full-table validation scan while holding an `ACCESS EXCLUSIVE` lock on the child table and a `SHARE ROW EXCLUSIVE` lock on the parent table.

```sql
-- Step 1: Add the Foreign Key constraint without validating existing rows
SET lock_timeout = '2s';
ALTER TABLE orders 
    ADD CONSTRAINT fk_orders_customer_id 
    FOREIGN KEY (customer_id) 
    REFERENCES customers(id) 
    NOT VALID;
RESET lock_timeout;

-- Step 2: Validate existing rows concurrently
-- Acquires only SHARE UPDATE EXCLUSIVE: Writes to both tables proceed unimpeded.
ALTER TABLE orders VALIDATE CONSTRAINT fk_orders_customer_id;
```

---

### 4.6 Pattern E: Live Column Type Conversion (e.g., `INT` to `BIGINT`)

Changing a column type directly via `ALTER TABLE orders ALTER COLUMN user_id TYPE bigint` requires an `ACCESS EXCLUSIVE` lock and rewrites the entire physical table, locking out users for hours on a 10M+ row dataset. 

Use the **Dual-Write Expansion & Contraction Pattern**:

```sql
-- =========================================================================
-- PHASE 1: EXPANSION (Add new column & create synchronizing trigger)
-- =========================================================================

-- 1.1 Add new column (metadata-only update)
SET lock_timeout = '2s';
ALTER TABLE orders ADD COLUMN user_id_v2 bigint;
RESET lock_timeout;

-- 1.2 Create trigger function to mirror real-time writes
CREATE OR REPLACE FUNCTION public.sync_orders_user_id()
RETURNS TRIGGER 
LANGUAGE plpgsql 
AS $$
BEGIN
    NEW.user_id_v2 := NEW.user_id;
    RETURN NEW;
END;
$$;

-- 1.3 Apply trigger to maintain dual writes
SET lock_timeout = '2s';
CREATE OR REPLACE TRIGGER trg_sync_orders_user_id
BEFORE INSERT OR UPDATE OF user_id ON orders
FOR EACH ROW
EXECUTE FUNCTION public.sync_orders_user_id();
RESET lock_timeout;

-- =========================================================================
-- PHASE 2: HISTORICAL BACKFILL (Run concurrently in background)
-- =========================================================================
DO $$
DECLARE
    batch_size CONSTANT int := 10000;
    max_id bigint;
    start_id bigint;
BEGIN
    SELECT min(id), max(id) INTO start_id, max_id FROM orders;
    
    WHILE start_id <= max_id LOOP
        UPDATE orders
        SET user_id_v2 = user_id
        WHERE id >= start_id 
          AND id < (start_id + batch_size) 
          AND user_id_v2 IS NULL;

        COMMIT;
        start_id := start_id + batch_size;
        PERFORM pg_sleep(0.02);
    END LOOP;
END;
$$;

-- =========================================================================
-- PHASE 3: INDEX CREATION & CONSTRAINTS (Concurrently)
-- =========================================================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_user_id_v2 ON orders(user_id_v2);

-- =========================================================================
-- PHASE 4: ATOMIC SWAP
-- =========================================================================
-- Note: Re-point your application queries to user_id_v2 prior to this step,
-- or execute atomic name swapping under an explicit lock envelope:

SET lock_timeout = '2s';
BEGIN;
    -- Drop synchronization trigger
    DROP TRIGGER trg_sync_orders_user_id ON orders;
    DROP FUNCTION public.sync_orders_user_id();

    -- Atomic rename swap
    ALTER TABLE orders RENAME COLUMN user_id TO user_id_old;
    ALTER TABLE orders RENAME COLUMN user_id_v2 TO user_id;
    
    -- Rename index to original name standard
    ALTER INDEX idx_orders_user_id_v2 RENAME TO idx_orders_user_id;
COMMIT;
RESET lock_timeout;

-- =========================================================================
-- PHASE 5: CONTRACTION (Cleanup after application verification)
-- =========================================================================
-- Dropping the column does not lock reads/writes on PostgreSQL 11+
SET lock_timeout = '2s';
ALTER TABLE orders DROP COLUMN user_id_old;
RESET lock_timeout;
```

---

## 5. Production Zero-Downtime Migration Checklist

Execute this verification sequence prior to applying any schema changes on production tables exceeding 10,000,000 rows:

```
[ ] 1. ENVIRONMENT VALIDATION
    [ ] Migration has run against an obfuscated production replica of equal scale.
    [ ] WAL generation rates and replication lag limits have been calculated.
    [ ] Target table bloat levels checked via pg_stat_user_tables (live vs dead tuples).

[ ] 2. LOCK SAFETY PROTOCOL
    [ ] Explicit SET lock_timeout = '2s' is defined at the start of every migration step.
    [ ] Explicit SET statement_timeout is configured.
    [ ] No direct table-rewriting operations exist in the migration transaction.
    [ ] Long-running analytical/ETL queries are paused during the deployment window.

[ ] 3. INDEXES & CONSTRAINTS
    [ ] All new indexes specify CONCURRENTLY.
    [ ] All Foreign Keys and CHECK constraints specify NOT VALID.
    [ ] VALIDATE CONSTRAINT is executed in a separate, decoupled step.
    [ ] Verification step queries pg_index.indisvalid to confirm build integrity.

[ ] 4. BATCHED DATA MANIPULATION
    [ ] Data backfills execute via deterministic keyset batches (<10,000 rows per loop).
    [ ] Dynamic COMMIT statements exist inside loop bodies to release table/row locks.
    [ ] Throttling sleep delay (pg_sleep) is present to prevent I/O and replication bottlenecks.

[ ] 5. ROLLBACK & OBSERVABILITY
    [ ] Active monitor running: blocking locks diagnostic query (Section 2.2).
    [ ] Clean DROP INDEX CONCURRENTLY command is prepared if the index build fails.
    [ ] PgBouncer connection queue wait times (SHOW POOLS) are monitored in real-time.
