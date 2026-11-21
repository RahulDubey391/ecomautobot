# Module 1: Multi-Tenant Architecture & Data Isolation Mental Models

Building multi-tenant Software-as-a-Service (SaaS) on PostgreSQL and Supabase requires strict isolation guarantees without introducing unsustainable operational overhead. This module covers the architectural trade-offs between physical and logical isolation, provides a production-grade relational schema foundation, establishes high-throughput permission evaluation models (RBAC vs. PBAC), and details connection pooler configurations using Supavisor.

---

## 1. Multi-Tenancy Patterns: Physical vs. Logical Separation

When architecting a multi-tenant system on PostgreSQL, you must choose between three distinct isolation models:

1. **Database-per-tenant (Physical Isolation)**
2. **Schema-per-tenant (Logical/Namespace Isolation)**
3. **Shared-Database, Shared-Schema with Row-Level Security (RLS) (Row-Level Logical Isolation)**

### Architectural Trade-Off Matrix

| Evaluation Dimension | Database-per-Tenant | Schema-per-Tenant | Shared-Schema with RLS |
| :--- | :--- | :--- | :--- |
| **Max Scalable Tenants** | ~100–500 per cluster | ~1,000–5,000 per DB (catalog bloat) | 1,000,000+ (partition-dependent) |
| **RLS Performance Cost** | None | None | Low to Moderate (Indexed overhead: 3–8%) |
| **Operational Overhead** | Extremely High (Migration sync failure risk) | High (Postgres `pg_catalog` bloat, slow DDL) | Minimal (Single migration pipeline) |
| **Noisy Neighbor Mitigation** | Hard hardware isolation | Shared buffer cache, resource contention | Shared buffer cache; requires statement timeouts |
| **Cross-Tenant Analytics** | Requires ETL / FDW / Logical Replication | Complex cross-schema `UNION ALL` queries | Direct `GROUP BY tenant_id` |
| **Backup / Point-In-Time Restore** | Per-tenant native restore | Difficult (table-level extraction required) | Requires row-level export or tenant cloning logic |
| **Supabase Compatibility** | Poor (Requires managing separate Supabase instances) | Partial (Supabase Studio and Auth break with dynamic schemas) | **Native / Recommended standard architecture** |

### Why Shared-Schema with RLS is the Production Standard for Supabase

PostgreSQL's internal catalog (`pg_class`, `pg_attribute`, `pg_type`) degrades when dynamic DDL exceeds roughly 10,000 tables. A schema-per-tenant architecture with 50 tables reaches this limit at just 200 tenants, causing:
- Catastrophic autovacuum lock contention.
- Elevated memory consumption via `relcache` invalidations across worker backends.
- Broken tooling: Supabase Studio, GoTrue (Auth), and PostgREST depend on a unified schema structure to generate APIs and manage connections.

In contrast, the **Shared-Schema RLS Pattern** uses a single relational schema where every entity table contains a deterministic `organization_id` or `workspace_id`. Isolation is enforced by PostgreSQL's native Row-Level Security engine, which rewrites the query abstract syntax tree (AST) prior to query planning. This yields zero architectural catalog drift, predictable cold-cache performance, and out-of-the-box compatibility with the PostgREST API compiler.

---

## 2. Canonical Multi-Tenant Schema Architecture

The blueprint below models a hierarchical multi-tenant structure:
- **Organization (Tenant Root):** Holds the commercial contract, billing, domain configs, and root-level users.
- **Workspace (Logical Division):** Isolates environments (e.g., "Production", "Staging") or subsidiary business units.
- **Resources:** Child entities scoped strictly to an organization or workspace.

### Deterministic Indexing Strategy: UUIDv7 vs. UUIDv4

Standard `uuid_generate_v4()` outputs pseudo-random 128-bit values, causing random page insertions across high-cardinality B-Tree indexes. This thrashes PostgreSQL's `shared_buffers` cache once indexes exceed RAM.

For production multi-tenancy, use **time-ordered UUIDv7**. UUIDv7 combines a 48-bit millisecond timestamp with 74 bits of cryptographically secure randomness. This guarantees sequential inserts, preserves index locality, eliminates B-Tree page splits, and speeds up tenant-scoped index traversals by up to 35%.

```
┌────────────────────────────────────────────────────────┐
│                   UUIDv7 (128 bits)                    │
├────────────────────┬──────────┬────────┬───────────────┤
│ 48-bit Timestamp   │  4-bit   │ 12-bit │ 2-bit │ 62-bit│
│ (Unix Epoch ms)    │ Version  │ Sub-ms │  Var  │ Rand  │
│                    │  (0111)  │ /Seq   │ (10)  │       │
└────────────────────┴──────────┴────────┴───────┴───────┘
  ◄── Monotonically Increasing Key ──►◄── Collision Res ─►
```

### Production DDL: Foundation Schema

```sql
-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Native UUIDv7 implementation for PostgreSQL 15/16
CREATE OR REPLACE FUNCTION public.generate_uuid_v7()
RETURNS uuid
LANGUAGE plpgsql
PARALLEL SAFE
AS $$
DECLARE
  v_time timestamp with time zone := clock_timestamp();
  v_epoch_ms bigint;
  v_uuid bytea;
BEGIN
  -- Extract millisecond timestamp
  v_epoch_ms := (extract(epoch FROM v_time) * 1000)::bigint;

  -- Build UUIDv7 byte array
  v_uuid := set_byte(
    set_byte(
      set_byte(
        set_byte(
          set_byte(
            set_byte(
              gen_random_bytes(16),
              0, (v_epoch_ms >> 40)::integer
            ),
            1, (v_epoch_ms >> 32)::integer
          ),
          2, (v_epoch_ms >> 24)::integer
        ),
        3, (v_epoch_ms >> 16)::integer
      ),
      4, (v_epoch_ms >> 8)::integer
    ),
    5, (v_epoch_ms)::integer
  );

  -- Set Version to 7 (0111 in high 4 bits of byte 6)
  v_uuid := set_byte(v_uuid, 6, (get_byte(v_uuid, 6) & 15) | 112);
  -- Set Variant to RFC 4122 (10 in high 2 bits of byte 8)
  v_uuid := set_byte(v_uuid, 8, (get_byte(v_uuid, 8) & 63) | 128);

  RETURN encode(v_uuid, 'hex')::uuid;
END;
$$;

-- 1. Organizations (Top-level billing entity)
CREATE TABLE public.organizations (
    id UUID PRIMARY KEY DEFAULT public.generate_uuid_v7(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT org_slug_format CHECK (slug ~* '^[a-z0-9]+(?:-[a-z0-9]+)*$')
);

-- 2. Workspaces (Sub-divisions within an organization)
CREATE TABLE public.workspaces (
    id UUID PRIMARY KEY DEFAULT public.generate_uuid_v7(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT workspace_slug_org_unique UNIQUE(organization_id, slug)
);

-- 3. App User Profiles (Linked to auth.users)
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    full_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- 4. Organization Memberships (Tenancy Binding Layer)
CREATE TABLE public.organization_memberships (
    id UUID PRIMARY KEY DEFAULT public.generate_uuid_v7(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT org_user_unique UNIQUE(organization_id, user_id)
);

-- 5. Tenant Documents (Example Multi-Tenant Resource)
CREATE TABLE public.documents (
    id UUID PRIMARY KEY DEFAULT public.generate_uuid_v7(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    created_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Critical High-Concurrency Composite Indexes
CREATE INDEX idx_workspaces_org_id ON public.workspaces (organization_id);
CREATE INDEX idx_org_memberships_user_org ON public.organization_memberships (user_id, organization_id);
CREATE INDEX idx_documents_org_workspace ON public.documents (organization_id, workspace_id);
CREATE INDEX idx_documents_created_by ON public.documents (created_by);
```

---

## 3. Access Control Models: RBAC vs. PBAC on PostgreSQL

A multi-tenant system requires an access control model that scales with organizational complexity. Hardcoding static roles into application logic or RLS policies introduces security debt and prevents custom roles from being defined dynamically by customers.

```
RBAC (Coarse-grained)
User ──► Organization Membership ──► Role ("Editor") ──► Static Capabilities

PBAC (Fine-grained, Dynamic)
User ──► Membership ──► Role Assignment ──► Role ──► Permissions ("documents:write")
                                                ▲
                                                └── Policy Constraints (e.g. workspace_id)
```

### The Limitations of Simple RBAC
Traditional RBAC ties users to roles (`admin`, `editor`, `viewer`) and uses checks like `WHERE role = 'admin'`. This fails when:
- Enterprise plans demand custom roles with mixed capabilities (e.g., "Billing Viewer + Document Approver").
- Scopes must vary between parent organizations and child workspaces.
- Permissions require contextual attributes (ABAC), such as restricting document edits to users who own the record.

### Permission-Based Access Control (PBAC) Engine
PBAC decouples roles from access checks. RLS policies verify whether a user possesses an atomic permission string (e.g., `documents:create`, `documents:read`, `org:delete`), while roles simply act as logical permission groupings.

```sql
-- Permissions Dictionary
CREATE TABLE public.permissions (
    id TEXT PRIMARY KEY, -- e.g., 'documents:read', 'documents:write', 'billing:manage'
    description TEXT NOT NULL
);

-- Organization Custom & System Roles
CREATE TABLE public.roles (
    id UUID PRIMARY KEY DEFAULT public.generate_uuid_v7(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    is_system_role BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT org_role_name_unique UNIQUE(organization_id, name)
);

-- Role-to-Permission Join Table
CREATE TABLE public.role_permissions (
    role_id UUID NOT NULL REFERENCES public.roles(id) ON DELETE CASCADE,
    permission_id TEXT NOT NULL REFERENCES public.permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- Membership-to-Role Assignment
CREATE TABLE public.member_roles (
    membership_id UUID NOT NULL REFERENCES public.organization_memberships(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES public.roles(id) ON DELETE CASCADE,
    PRIMARY KEY (membership_id, role_id)
);

-- Indexes for lightning-fast join traversals
CREATE INDEX idx_role_permissions_role ON public.role_permissions(role_id);
CREATE INDEX idx_member_roles_membership ON public.member_roles(membership_id);
```

### Seed Fundamental Permissions
```sql
INSERT INTO public.permissions (id, description) VALUES
  ('org:manage', 'Full control over organization settings'),
  ('documents:read', 'Ability to view documents in workspace'),
  ('documents:write', 'Ability to create and update documents in workspace'),
  ('documents:delete', 'Ability to drop documents');
```

---

## 4. Supavisor & PgBouncer Connection Pooler Tuning

Multi-tenant architectures run many client connections concurrently. Unpooled Postgres backends consume roughly 2–10MB of memory per connection, and context-switching overhead grows significantly beyond a few hundred direct connections. Using a connection pooler like **Supavisor** (Supabase's Elixir-based pooler) or **PgBouncer** is mandatory.

```
                    ┌────────────────────────┐
                    │ Multi-Tenant Clients   │
                    │ Edge Functions / Web   │
                    └───────────┬────────────┘
                                │ ~1,000 to 10,000 HTTP clients
                                ▼
                    ┌────────────────────────┐
                    │ Supavisor (Port 6543)  │
                    │ Pool Mode: TRANSACTION │
                    └───────────┬────────────┘
                                │ Strictly Mapped: e.g., 60 Shared Connections
                                ▼
                    ┌────────────────────────┐
                    │   PostgreSQL Engine    │
                    │  `max_connections=100` │
                    └────────────────────────┘
```

### Pool Mode Mechanics: Session vs. Transaction

| Pool Mode | Behavior | Multi-Tenant Safety & Operational Rules |
| :--- | :--- | :--- |
| **Session** | Client holds a physical Postgres backend from connect to disconnect. | Inefficient for serverless environments. Preserves Postgres session state (`SET LOCAL`, listen/notify, prepared statements). |
| **Transaction** | Client holds a backend connection *only* for the lifetime of a transaction (`BEGIN...COMMIT`). PostgREST defaults to this mode. | **Required for Serverless/Scale.** Highly efficient. Any state set outside a transaction leaks to other tenants or is dropped entirely. |

### The `SET LOCAL` Dilemma in Transaction Pooling

In pure PostgreSQL, tenancy can be set dynamically per session:
```sql
-- DANGEROUS IN TRANSACTION-POOLED MULTI-TENANCY IF NOT SCOPED PROPERLY:
SET app.current_tenant_id = '018f3d1b-15b5-707b-a25e-3c22adfece74';
```
If this command runs on a shared connection without an explicit transaction block, the setting persists on that connection. A subsequent request by a different tenant using the same physical connection might inherit the prior tenant's ID.

#### The Safe Pattern: Bound Transactions
If using session parameters for multi-tenancy, wrap every request in a single atomic transaction using `SET LOCAL`:

```sql
BEGIN;
-- SET LOCAL automatically resets on COMMIT or ROLLBACK
SET LOCAL app.current_tenant_id = '018f3d1b-15b5-707b-a25e-3c22adfece74';
SELECT * FROM public.documents;
COMMIT;
```

When building on PostgREST and Supabase Auth, **bypass `SET LOCAL` entirely**. Instead, resolve identity directly inside RLS policies using `auth.uid()` alongside database joins, or parse tenant claims directly out of signed JWTs via `auth.jwt()`. This avoids connection poisoning risks altogether.

### Supavisor Resource Calculation for High-Load SaaS

Use these formulas to size your connection pool parameters on a 100k+ MAU multi-tenant platform:

$$Total\,DB\,Connections = max\_connections - superuser\_reserved (default: 3)$$

$$Active\,Pool\,Size = \lfloor Total\,DB\,Connections \times 0.70 \rfloor$$

$$Direct\,Pool\,Size = \lfloor Total\,DB\,Connections \times 0.20 \rfloor$$

The remaining 10% should stay reserved for background tasks, autovacuum workers, and edge functions.

#### Worked Example: 8 vCPU, 32GB RAM Instance
- `max_connections` = `120`
- `pool_size` (Supavisor Transaction Pool) = `80`
- `direct_connections` (Migrations, Dashboard Admin) = `20`
- `reserve_pool_size` = `5`
- `max_client_conn` (Client-side concurrency limit) = `10,000`
- `default_pool_timeout` = `5` seconds (Fast-fail queries instead of letting queues grow indefinitely)

---

## 5. Production Blueprint: Secure Functions & Hardened RLS Policies

This complete, production-grade migration establishes an optimized security boundary using dynamic PBAC with Row-Level Security.

### Architectural Rules for Secure RLS:
1. **Always Set `search_path = public`**: Prevents search-path hijacking attacks on `SECURITY DEFINER` functions.
2. **Mark Functions `STABLE`**: Informs the query planner that function results can be cached across rows within the same statement, turning what would be an $O(N)$ query into an $O(1)$ scalar lookup.
3. **Use Subqueries Over `IN (...)`**: Formulate cross-table membership checks using `EXISTS (SELECT 1 ...)`. This ensures PostgreSQL executes a correlated semi-join instead of materializing intermediate collections into memory.

### Complete Production Migration

```sql
-- ============================================================================
-- 1. UTILITY FUNCTIONS & TENANT IDENTIFICATION
-- ============================================================================

-- Fast-path lookup to get current tenant memberships for an authenticated user
CREATE OR REPLACE FUNCTION public.get_auth_user_organizations()
RETURNS SETOF uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT organization_id
  FROM public.organization_memberships
  WHERE user_id = auth.uid();
$$;

-- PBAC Validation: Check if the current user holds a specific permission in a specific org
CREATE OR REPLACE FUNCTION public.has_permission(
  _organization_id uuid,
  _permission_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.organization_memberships om
    JOIN public.member_roles mr ON mr.membership_id = om.id
    JOIN public.role_permissions rp ON rp.role_id = mr.role_id
    WHERE om.user_id = auth.uid()
      AND om.organization_id = _organization_id
      AND rp.permission_id = _permission_id
  );
$$;

-- ============================================================================
-- 2. ENABLE ROW-LEVEL SECURITY ON ALL CORE TABLES
-- ============================================================================

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organizations FORCE ROW LEVEL SECURITY;

ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspaces FORCE ROW LEVEL SECURITY;

ALTER TABLE public.organization_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_memberships FORCE ROW LEVEL SECURITY;

ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents FORCE ROW LEVEL SECURITY;

ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.roles FORCE ROW LEVEL SECURITY;

ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_permissions FORCE ROW LEVEL SECURITY;

ALTER TABLE public.member_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.member_roles FORCE ROW LEVEL SECURITY;

-- ============================================================================
-- 3. RLS POLICIES: ORGANIZATIONS
-- ============================================================================

-- Users can see organizations they belong to
CREATE POLICY "org_select_members"
  ON public.organizations
  FOR SELECT
  TO authenticated
  USING (
    id IN (SELECT public.get_auth_user_organizations())
  );

-- Only members with org:manage can update the organization
CREATE POLICY "org_update_managed"
  ON public.organizations
  FOR UPDATE
  TO authenticated
  USING (
    public.has_permission(id, 'org:manage')
  )
  WITH CHECK (
    public.has_permission(id, 'org:manage')
  );

-- ============================================================================
-- 4. RLS POLICIES: WORKSPACES
-- ============================================================================

CREATE POLICY "workspaces_select_member"
  ON public.workspaces
  FOR SELECT
  TO authenticated
  USING (
    organization_id IN (SELECT public.get_auth_user_organizations())
  );

CREATE POLICY "workspaces_insert_admin"
  ON public.workspaces
  FOR INSERT
  TO authenticated
  WITH CHECK (
    public.has_permission(organization_id, 'org:manage')
  );

CREATE POLICY "workspaces_delete_admin"
  ON public.workspaces
  FOR DELETE
  TO authenticated
  USING (
    public.has_permission(organization_id, 'org:manage')
  );

-- ============================================================================
-- 5. RLS POLICIES: DOCUMENTS (RESOURCE-LEVEL PBAC)
-- ============================================================================

-- Read: Must belong to tenant and hold 'documents:read'
CREATE POLICY "documents_select_tenant"
  ON public.documents
  FOR SELECT
  TO authenticated
  USING (
    organization_id IN (SELECT public.get_auth_user_organizations())
    AND public.has_permission(organization_id, 'documents:read')
  );

-- Write: Must hold 'documents:write'
CREATE POLICY "documents_insert_tenant"
  ON public.documents
  FOR INSERT
  TO authenticated
  WITH CHECK (
    organization_id IN (SELECT public.get_auth_user_organizations())
    AND public.has_permission(organization_id, 'documents:write')
    AND created_by = auth.uid()
  );

-- Update: Must hold 'documents:write'
CREATE POLICY "documents_update_tenant"
  ON public.documents
  FOR UPDATE
  TO authenticated
  USING (
    organization_id IN (SELECT public.get_auth_user_organizations())
    AND public.has_permission(organization_id, 'documents:write')
  )
  WITH CHECK (
    organization_id IN (SELECT public.get_auth_user_organizations())
    AND public.has_permission(organization_id, 'documents:write')
  );

-- Delete: Must hold 'documents:delete'
CREATE POLICY "documents_delete_tenant"
  ON public.documents
  FOR DELETE
  TO authenticated
  USING (
    organization_id IN (SELECT public.get_auth_user_organizations())
    AND public.has_permission(organization_id, 'documents:delete')
  );
```

---

## 6. Security Validation Suite: Cross-Tenant Isolation Tests

To ensure tenant isolation cannot be breached, integrate automated regression tests into your migration pipeline. This transactional test suite simulates two distinct tenants and verifies that Tenant B cannot access Tenant A's resources under any circumstances.

```sql
BEGIN;

-- 1. Setup Test Fixtures within an isolated transaction
CREATE EXTENSION IF NOT EXISTS "pgtap";

-- Create Dummy Authenticated Users in auth.users
INSERT INTO auth.users (id, email)
VALUES 
  ('11111111-1111-7111-8111-111111111111', 'alice@tenant-a.com'),
  ('22222222-2222-7222-8222-222222222222', 'bob@tenant-b.com')
ON CONFLICT DO NOTHING;

INSERT INTO public.profiles (id, email, full_name)
VALUES 
  ('11111111-1111-7111-8111-111111111111', 'alice@tenant-a.com', 'Alice Tenant A'),
  ('22222222-2222-7222-8222-222222222222', 'bob@tenant-b.com', 'Bob Tenant B')
ON CONFLICT DO NOTHING;

-- Establish Tenants
INSERT INTO public.organizations (id, name, slug)
VALUES 
  ('a0000000-0000-7000-8000-000000000000', 'Tenant A Inc', 'tenant-a'),
  ('b0000000-0000-7000-8000-000000000000', 'Tenant B Inc', 'tenant-b');

INSERT INTO public.workspaces (id, organization_id, name, slug)
VALUES 
  ('a1111111-0000-7000-8000-000000000000', 'a0000000-0000-7000-8000-000000000000', 'A-Workspace', 'a-work'),
  ('b1111111-0000-7000-8000-000000000000', 'b0000000-0000-7000-8000-000000000000', 'B-Workspace', 'b-work');

-- Setup Memberships
INSERT INTO public.organization_memberships (id, organization_id, user_id)
VALUES 
  ('aaa00000-0000-7000-8000-000000000000', 'a0000000-0000-7000-8000-000000000000', '11111111-1111-7111-8111-111111111111'),
  ('bbb00000-0000-7000-8000-000000000000', 'b0000000-0000-7000-8000-000000000000', '22222222-2222-7222-8222-222222222222');

-- Setup Roles and Permissions for Tenant A
INSERT INTO public.roles (id, organization_id, name)
VALUES ('a-role-admin', 'a0000000-0000-7000-8000-000000000000', 'Admin');

INSERT INTO public.role_permissions (role_id, permission_id)
VALUES 
  ('a-role-admin', 'documents:read'),
  ('a-role-admin', 'documents:write');

INSERT INTO public.member_roles (membership_id, role_id)
VALUES ('aaa00000-0000-7000-8000-000000000000', 'a-role-admin');

-- Insert Tenant A Payload Data
INSERT INTO public.documents (id, organization_id, workspace_id, created_by, title)
VALUES ('ad0c0000-0000-7000-8000-000000000000', 'a0000000-0000-7000-8000-000000000000', 'a1111111-0000-7000-8000-000000000000', '11111111-1111-7111-8111-111111111111', 'Tenant A Secret Sauce');

-- 2. RUN TESTS AS TENANT B
-- Impersonate Bob (Tenant B) through Supabase's role layer
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claim.sub = '22222222-2222-7222-8222-222222222222';

-- TEST A: Bob should read 0 rows from organizations table matching Tenant A
DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count 
  FROM public.organizations 
  WHERE id = 'a0000000-0000-7000-8000-000000000000';

  IF v_count <> 0 THEN
    RAISE EXCEPTION 'ISOLATION BREACH: Tenant B can see Tenant A organization!';
  END IF;
END;
$$;

-- TEST B: Bob should read 0 rows from documents table matching Tenant A
DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count 
  FROM public.documents 
  WHERE id = 'ad0c0000-0000-7000-8000-0
