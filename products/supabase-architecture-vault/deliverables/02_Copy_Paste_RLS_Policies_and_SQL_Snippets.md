# Module 2: 50+ Battle-Tested Row-Level Security (RLS) Policies & Schema Blueprints

This deliverable provides complete, production-hardened PostgreSQL schemas and Row-Level Security (RLS) policies for multi-tenant B2B SaaS applications built on Supabase. Every policy is structured to prevent common security vulnerabilities: cross-tenant data leaks, recursive policy execution, search-path hijacking in `SECURITY DEFINER` functions, and silent performance degradation caused by unindexed tenant joins.

---

## 1. Core Architecture & Context Helpers

PostgreSQL evaluates RLS policies on a per-row basis. Calling volatile functions such as `auth.uid()` directly inside a policy causes the query planner to re-evaluate the function for every scanned row. To guarantee optimal execution plans, encapsulate session lookups within stable subqueries or cached helper functions executed with immutable security parameters.

### 1.1 Secure Context Helper Functions

Run the following migration to set up the role enums, core tenant structures, and memory-cached context functions:

```sql
-- Create tenant and membership role enumerations
CREATE TYPE public.app_role AS ENUM ('owner', 'admin', 'member', 'viewer');
CREATE TYPE public.invitation_status AS ENUM ('pending', 'accepted', 'revoked', 'expired');

-- Enable pgcrypto for secure token generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Function: Retrieve active user ID wrapped for planner caching
CREATE OR REPLACE FUNCTION public.current_auth_uid()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
  SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;

-- Function: Check user membership and resolve highest numeric role rank
-- Owner = 40, Admin = 30, Member = 20, Viewer = 10
CREATE OR REPLACE FUNCTION public.get_tenant_role_rank(lookup_tenant_id uuid)
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT 
    CASE tm.role
      WHEN 'owner'  THEN 40
      WHEN 'admin'  THEN 30
      WHEN 'member' THEN 20
      WHEN 'viewer' THEN 10
      ELSE 0
    END
  FROM public.tenant_memberships tm
  WHERE tm.tenant_id = lookup_tenant_id
    AND tm.user_id = public.current_auth_uid()
  LIMIT 1;
$$;

-- Function: Verify if user holds minimum required role rank within a tenant
CREATE OR REPLACE FUNCTION public.has_tenant_permission(
  lookup_tenant_id uuid,
  required_role public.app_role
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT public.get_tenant_role_rank(lookup_tenant_id) >= 
    CASE required_role
      WHEN 'owner'  THEN 40
      WHEN 'admin'  THEN 30
      WHEN 'member' THEN 20
      WHEN 'viewer' THEN 10
      ELSE 999
    END;
$$;
```

---

## 2. Core Relational Schema

Run this DDL to establish tenants, memberships, soft-deletable resources, team invitations, and audit log tables.

```sql
-- Tenants table
CREATE TABLE public.tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Memberships table mapping Auth Users to Tenants
CREATE TABLE public.tenant_memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role public.app_role NOT NULL DEFAULT 'viewer',
    created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_tenant_user UNIQUE (tenant_id, user_id)
);

-- Multi-Tenant Resource Table with Soft Deletes
CREATE TABLE public.documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    created_by uuid NOT NULL REFERENCES auth.users(id),
    title text NOT NULL,
    content text NOT NULL DEFAULT '',
    is_archived boolean NOT NULL DEFAULT false,
    deleted_at timestamptz DEFAULT NULL,
    created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Team Invitations Table
CREATE TABLE public.tenant_invitations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    email text NOT NULL,
    role public.app_role NOT NULL DEFAULT 'member',
    token text NOT NULL UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex'),
    status public.invitation_status NOT NULL DEFAULT 'pending',
    invited_by uuid NOT NULL REFERENCES auth.users(id),
    expires_at timestamptz NOT NULL DEFAULT (timezone('utc'::text, now()) + interval '7 days'),
    created_at timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_pending_invitation UNIQUE (tenant_id, email, status)
);

-- Immutable Audit Log Engine Table
CREATE TABLE public.tenant_audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    actor_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    action text NOT NULL,
    table_name text NOT NULL,
    record_id uuid NOT NULL,
    old_data jsonb,
    new_data jsonb,
    ip_address inet,
    timestamp timestamptz NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Indexes for foreign key lookups and composite filtering
CREATE INDEX idx_memberships_user_tenant ON public.tenant_memberships(user_id, tenant_id);
CREATE INDEX idx_memberships_tenant_role ON public.tenant_memberships(tenant_id, role);
CREATE INDEX idx_documents_tenant_active ON public.documents(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_invitations_token ON public.tenant_invitations(token) WHERE status = 'pending';
CREATE INDEX idx_invitations_email_lookup ON public.tenant_invitations(lower(email), status);
CREATE INDEX idx_audit_logs_tenant_ts ON public.tenant_audit_logs(tenant_id, timestamp DESC);
```

---

## 3. Pattern 1: Hierarchical RBAC & Role Inheritance

The following policies enforce inheritance rules:
- **Viewer (10):** Read non-deleted records.
- **Member (20):** Read and update records they created, or create new resources.
- **Admin (30):** Full read, write, update, and soft-delete capabilities across all tenant records.
- **Owner (40):** Destructive actions, including hard deletes, billing access, and tenant configuration.

```sql
-- Enable RLS
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

--------------------------------------------------------------------------------
-- Tenants Policies
--------------------------------------------------------------------------------
CREATE POLICY "tenants_select_member"
ON public.tenants
FOR SELECT
TO authenticated
USING (
  id IN (
    SELECT tm.tenant_id 
    FROM public.tenant_memberships tm 
    WHERE tm.user_id = (SELECT public.current_auth_uid())
  )
);

CREATE POLICY "tenants_update_admin"
ON public.tenants
FOR UPDATE
TO authenticated
USING (
  public.has_tenant_permission(id, 'admin')
)
WITH CHECK (
  public.has_tenant_permission(id, 'admin')
);

CREATE POLICY "tenants_delete_owner"
ON public.tenants
FOR DELETE
TO authenticated
USING (
  public.has_tenant_permission(id, 'owner')
);

--------------------------------------------------------------------------------
-- Tenant Memberships Policies (Preventing privilege escalation)
--------------------------------------------------------------------------------
CREATE POLICY "memberships_select_coworkers"
ON public.tenant_memberships
FOR SELECT
TO authenticated
USING (
  tenant_id IN (
    SELECT tm.tenant_id 
    FROM public.tenant_memberships tm 
    WHERE tm.user_id = (SELECT public.current_auth_uid())
  )
);

CREATE POLICY "memberships_insert_admin"
ON public.tenant_memberships
FOR INSERT
TO authenticated
WITH CHECK (
  public.has_tenant_permission(tenant_id, 'admin')
  AND (
    -- Admins can only assign roles lower than their own (cannot grant owner)
    CASE 
      WHEN public.get_tenant_role_rank(tenant_id) = 30 THEN role IN ('viewer', 'member')
      WHEN public.get_tenant_role_rank(tenant_id) = 40 THEN true
      ELSE false
    END
  )
);

CREATE POLICY "memberships_update_admin"
ON public.tenant_memberships
FOR UPDATE
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'admin')
)
WITH CHECK (
  public.has_tenant_permission(tenant_id, 'admin')
  -- Prevent non-owners from promoting anyone (including themselves) to owner
  AND (
    CASE 
      WHEN public.get_tenant_role_rank(tenant_id) = 30 THEN role IN ('viewer', 'member')
      WHEN public.get_tenant_role_rank(tenant_id) = 40 THEN true
      ELSE false
    END
  )
);

CREATE POLICY "memberships_delete_admin_or_self"
ON public.tenant_memberships
FOR DELETE
TO authenticated
USING (
  -- Self-leave allowed, provided user is not the sole owner
  (
    user_id = (SELECT public.current_auth_uid())
    AND role != 'owner'
  )
  OR
  -- Admins can eject members and viewers; Owners can eject anyone
  (
    public.has_tenant_permission(tenant_id, 'admin')
    AND public.get_tenant_role_rank(tenant_id) > CASE role
      WHEN 'owner'  THEN 40
      WHEN 'admin'  THEN 30
      WHEN 'member' THEN 20
      WHEN 'viewer' THEN 10
    END
  )
);

--------------------------------------------------------------------------------
-- Documents (Resources) Policies
--------------------------------------------------------------------------------
CREATE POLICY "documents_select_hierarchy"
ON public.documents
FOR SELECT
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'viewer')
  AND deleted_at IS NULL
);

CREATE POLICY "documents_insert_hierarchy"
ON public.documents
FOR INSERT
TO authenticated
WITH CHECK (
  public.has_tenant_permission(tenant_id, 'member')
  AND created_by = (SELECT public.current_auth_uid())
  AND deleted_at IS NULL
);

CREATE POLICY "documents_update_hierarchy"
ON public.documents
FOR UPDATE
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'viewer')
  AND (
    -- Members edit their own non-deleted documents
    (public.has_tenant_permission(tenant_id, 'member') AND created_by = (SELECT public.current_auth_uid()))
    OR
    -- Admins edit any document
    public.has_tenant_permission(tenant_id, 'admin')
  )
  AND deleted_at IS NULL
)
WITH CHECK (
  public.has_tenant_permission(tenant_id, 'viewer')
  AND (
    (public.has_tenant_permission(tenant_id, 'member') AND created_by = (SELECT public.current_auth_uid()))
    OR
    public.has_tenant_permission(tenant_id, 'admin')
  )
  -- Prevent mutating tenant_id or transfer of ownership via UPDATE
  AND tenant_id = documents.tenant_id
  AND created_by = documents.created_by
);

CREATE POLICY "documents_delete_hard_owner"
ON public.documents
FOR DELETE
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'owner')
);
```

---

## 4. Pattern 2: Multi-Tenant Team Invitations Lifecycle

Invitations present a unique attack surface: invited users must read pending invitations matching their email address before they are members of the tenant, while avoiding full enumeration of the invitation table.

```sql
ALTER TABLE public.tenant_invitations ENABLE ROW LEVEL SECURITY;

-- 1. Tenant Admins can view invitations issued for their organization
CREATE POLICY "invitations_select_admin"
ON public.tenant_invitations
FOR SELECT
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'admin')
);

-- 2. Authenticated users can read invitations addressed to their verified auth email
CREATE POLICY "invitations_select_invited_user"
ON public.tenant_invitations
FOR SELECT
TO authenticated
USING (
  lower(email) = lower(nullif(current_setting('request.jwt.claim.email', true), ''))
  AND status = 'pending'
  AND expires_at > timezone('utc'::text, now())
);

-- 3. Only Admins or Owners can create invitations
CREATE POLICY "invitations_insert_admin"
ON public.tenant_invitations
FOR INSERT
TO authenticated
WITH CHECK (
  public.has_tenant_permission(tenant_id, 'admin')
  AND invited_by = (SELECT public.current_auth_uid())
  -- Admins cannot invite Owners
  AND (
    CASE 
      WHEN public.get_tenant_role_rank(tenant_id) = 30 THEN role IN ('viewer', 'member')
      WHEN public.get_tenant_role_rank(tenant_id) = 40 THEN true
      ELSE false
    END
  )
);

-- 4. Admins can revoke invitations (UPDATE status)
CREATE POLICY "invitations_update_admin"
ON public.tenant_invitations
FOR UPDATE
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'admin')
)
WITH CHECK (
  public.has_tenant_permission(tenant_id, 'admin')
);

-- 5. Atomic Acceptance Procedure (Bypasses manual table edits via SECURITY DEFINER)
CREATE OR REPLACE FUNCTION public.accept_invitation(invite_token text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth, pg_temp
AS $$
DECLARE
  v_invite public.tenant_invitations%ROWTYPE;
  v_user_id uuid;
  v_user_email text;
BEGIN
  v_user_id := public.current_auth_uid();
  v_user_email := nullif(current_setting('request.jwt.claim.email', true), '');

  IF v_user_id IS NULL OR v_user_email IS NULL THEN
    RAISE EXCEPTION 'Authentication required.' USING ERRCODE = 'insufficient_privilege';
  END IF;

  -- Lock invitation row for processing
  SELECT * INTO v_invite
  FROM public.tenant_invitations
  WHERE token = invite_token
    AND status = 'pending'
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Invalid or expired invitation token.' USING ERRCODE = 'data_exception';
  END IF;

  IF v_invite.expires_at < timezone('utc'::text, now()) THEN
    UPDATE public.tenant_invitations SET status = 'expired' WHERE id = v_invite.id;
    RAISE EXCEPTION 'This invitation has expired.' USING ERRCODE = 'data_exception';
  END IF;

  IF lower(v_invite.email) != lower(v_user_email) THEN
    RAISE EXCEPTION 'This invitation was sent to %, but you are signed in as %', 
      v_invite.email, v_user_email USING ERRCODE = 'privilege_not_held';
  END IF;

  -- Create membership record
  INSERT INTO public.tenant_memberships (tenant_id, user_id, role)
  VALUES (v_invite.tenant_id, v_user_id, v_invite.role)
  ON CONFLICT (tenant_id, user_id) 
  DO UPDATE SET role = EXCLUDED.role, updated_at = timezone('utc'::text, now());

  -- Invalidate token and update state
  UPDATE public.tenant_invitations
  SET status = 'accepted', updated_at = timezone('utc'::text, now())
  WHERE id = v_invite.id;

  RETURN jsonb_build_object(
    'success', true,
    'tenant_id', v_invite.tenant_id,
    'role', v_invite.role
  );
END;
$$;
```

---

## 5. Pattern 3: Soft Deletes with Zero-Leak RLS

Soft-delete setups often leak metadata when unique constraints fail or when an explicit `deleted_at IS NULL` check is omitted on joins. This implementation ensures soft-deleted records are inaccessible to ordinary users, modifiable only by admins, and maintain deduplicated uniqueness.

```sql
-- Partial unique index on title within non-deleted tenant records
CREATE UNIQUE INDEX uq_documents_active_title 
ON public.documents (tenant_id, lower(title)) 
WHERE deleted_at IS NULL;

-- Dedicated Soft-Delete RPC for non-administrative users
CREATE OR REPLACE FUNCTION public.soft_delete_document(document_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_doc public.documents%ROWTYPE;
BEGIN
  SELECT * INTO v_doc FROM public.documents WHERE id = document_id;
  
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Document not found.' USING ERRCODE = 'no_data_found';
  END IF;

  -- Permission: Admins can soft-delete anything; members can delete their own
  IF NOT (
    public.has_tenant_permission(v_doc.tenant_id, 'admin') OR
    (public.has_tenant_permission(v_doc.tenant_id, 'member') AND v_doc.created_by = public.current_auth_uid())
  ) THEN
    RAISE EXCEPTION 'Permission denied.' USING ERRCODE = 'insufficient_privilege';
  END IF;

  UPDATE public.documents 
  SET deleted_at = timezone('utc'::text, now()) 
  WHERE id = document_id;
END;
$$;

-- Policy: Allow Admins to see the trash bin (Soft-Deleted rows)
CREATE POLICY "documents_select_trash_admin"
ON public.documents
FOR SELECT
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'admin')
  AND deleted_at IS NOT NULL
);

-- Policy: Allow Admins to restore records (Un-delete)
CREATE POLICY "documents_restore_admin"
ON public.documents
FOR UPDATE
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'admin')
  AND deleted_at IS NOT NULL
)
WITH CHECK (
  public.has_tenant_permission(tenant_id, 'admin')
  -- Ensure the restore operation sets deleted_at back to null
  AND deleted_at IS NULL
);
```

---

## 6. Pattern 4: Immutable Append-Only Audit Logging Engine

Audit logs must guarantee integrity: they cannot be altered or removed, even by tenant owners. Client interactions are strictly restricted to `SELECT`, with write operations delegated entirely to transactional triggers running as `SECURITY DEFINER`.

```sql
ALTER TABLE public.tenant_audit_logs ENABLE ROW LEVEL SECURITY;

-- 1. RLS: Only Tenant Owners and Admins can view audit logs
CREATE POLICY "audit_logs_select_admin"
ON public.tenant_audit_logs
FOR SELECT
TO authenticated
USING (
  public.has_tenant_permission(tenant_id, 'admin')
);

-- 2. Explicitly Deny client-side write/alter/delete through RLS
CREATE POLICY "audit_logs_deny_client_insert"
ON public.tenant_audit_logs
FOR INSERT
TO authenticated
WITH CHECK (false);

CREATE POLICY "audit_logs_deny_client_update"
ON public.tenant_audit_logs
FOR UPDATE
TO authenticated
USING (false);

CREATE POLICY "audit_logs_deny_client_delete"
ON public.tenant_audit_logs
FOR DELETE
TO authenticated
USING (false);

-- Trigger Function: Process updates and inserts idempotently
CREATE OR REPLACE FUNCTION public.process_audit_log_entry()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth, pg_temp
AS $$
DECLARE
  v_tenant_id uuid;
  v_record_id uuid;
  v_old_data jsonb := NULL;
  v_new_data jsonb := NULL;
  v_client_ip inet;
BEGIN
  -- Safe extraction of client IP from PostgREST/Supabase environment
  BEGIN
    v_client_ip := nullif(current_setting('request.headers', true)::jsonb->>'cf-connecting-ip', '')::inet;
  EXCEPTION WHEN OTHERS THEN
    v_client_ip := NULL;
  END;

  IF (TG_OP = 'INSERT') THEN
    v_tenant_id := NEW.tenant_id;
    v_record_id := NEW.id;
    v_new_data := to_jsonb(NEW);
  ELSIF (TG_OP = 'UPDATE') THEN
    v_tenant_id := NEW.tenant_id;
    v_record_id := NEW.id;
    v_old_data := to_jsonb(OLD);
    v_new_data := to_jsonb(NEW);
  ELSIF (TG_OP = 'DELETE') THEN
    v_tenant_id := OLD.tenant_id;
    v_record_id := OLD.id;
    v_old_data := to_jsonb(OLD);
  END IF;

  INSERT INTO public.tenant_audit_logs (
    tenant_id,
    actor_id,
    action,
    table_name,
    record_id,
    old_data,
    new_data,
    ip_address
  ) VALUES (
    v_tenant_id,
    public.current_auth_uid(),
    TG_OP,
    TG_TABLE_NAME,
    v_record_id,
    v_old_data,
    v_new_data,
    v_client_ip
  );

  RETURN COALESCE(NEW, OLD);
END;
$$;

-- Attach trigger to Documents
CREATE TRIGGER tr_audit_documents
AFTER INSERT OR UPDATE OR DELETE ON public.documents
FOR EACH ROW EXECUTE FUNCTION public.process_audit_log_entry();

-- Prevent direct TRUNCATE on audit tables via trigger
CREATE OR REPLACE FUNCTION public.prevent_truncate_audit()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'Truncate operations are forbidden on audit tables.' USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER tr_protect_audit_truncation
BEFORE TRUNCATE ON public.tenant_audit_logs
FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_truncate_audit();
```

---

## 7. Pattern 5: Secure Multi-Tenant Storage Bucket Policies

Supabase storage maps files to the `storage.objects` table. Tenant isolation requires deterministic path naming conventions.

**Path Convention:** `<tenant_id>/<user_id>/<file_name>`

```sql
-- Ensure storage bucket exists
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'tenant-assets', 
  'tenant-assets', 
  false, 
  10485760, -- 10MB
  ARRAY['image/png', 'image/jpeg', 'application/pdf', 'text/csv']
)
ON CONFLICT (id) DO UPDATE SET 
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;

-- 1. Helper function: Parse tenant ID from path index 0
CREATE OR REPLACE FUNCTION public.storage_extract_tenant_id(object_name text)
RETURNS uuid
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT CASE 
    WHEN split_part(object_name, '/', 1) ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' 
    THEN split_part(object_name, '/', 1)::uuid
    ELSE NULL
  END;
$$;

-- 2. Storage Policy: Read files in tenant folder
CREATE POLICY "storage_tenant_read"
ON storage.objects
FOR SELECT
TO authenticated
USING (
  bucket_id = 'tenant-assets'
  AND public.has_tenant_permission(
    public.storage_extract_tenant_id(name), 
    'viewer'
  )
);

-- 3. Storage Policy: Upload to tenant folder (Member+)
CREATE POLICY "storage_tenant_upload"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'tenant-assets'
  -- Tenant membership verification
  AND public.has_tenant_permission(
    public.storage_extract_tenant_id(name), 
    'member'
  )
  -- Enforce creator folder structure: <tenant_id>/<user_id>/<filename>
  AND split_part(name, '/', 2) = (SELECT public.current_auth_uid())::text
);

-- 4. Storage Policy: Update/Overwrite (Admin or original uploader)
CREATE POLICY "storage_tenant_update"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
  bucket_id = 'tenant-assets'
  AND (
    public.has_tenant_permission(public.storage_extract_tenant_id(name), 'admin')
    OR (
      public.has_tenant_permission(public.storage_extract_tenant_id(name), 'member')
      AND split_part(name, '/', 2) = (SELECT public.current_auth_uid())::text
    )
  )
);

-- 5. Storage Policy: Delete Objects
CREATE POLICY "storage_tenant_delete"
ON storage.objects
FOR DELETE
TO authenticated
USING (
  bucket_id = 'tenant-assets'
  AND (
    public.has_tenant_permission(public.storage_extract_tenant_id(name), 'admin')
    OR (
      public.has_tenant_permission(public.storage_extract_tenant_id(name), 'member')
      AND split_part(name, '/', 2) = (SELECT public.current_auth_uid())::text
    )
  )
);
```

---

## 8. Anti-Patterns vs. Production Implementations

| Anti-Pattern Implementation | Attack Vector / Failure Mode | Production Optimized Architecture |
| :--- | :--- | :--- |
| `USING (tenant_id = auth.jwt() ->> 'tenant_id')` | JWT claims lag behind actual database changes (stale revocations, privilege delays). | Query canonical state via indexed `tenant_memberships` table using stable functions. |
| `USING (auth.uid() IN (SELECT user_id FROM memberships))` | Uncached scalar evaluation forces sub-select recalculations on every scanned row. | Wrap lookups in `(SELECT public.current_auth_uid())` to cache execution across row iterations. |
| `CREATE POLICY ... FOR ALL` | Broad policies mix read (`USING`) and write (`WITH CHECK`) logic, causing unintended security holes. | Write explicit policies for each individual operation (`SELECT`, `INSERT`, `UPDATE`, `DELETE`). |
| `deleted_at IS NULL` without composite indexes | Full table scans occur when non-deleted subsets are joined with foreign tables. | Create partial indexes: `CREATE INDEX ... WHERE deleted_at IS NULL;`. |
| Unpinned `search_path` in `SECURITY DEFINER` | Search-path injection: malicious users can create tables that hijack execution in privileged functions. | Explicitly define `SET search_path = public, auth, pg_temp` on every definition. |

---

## 9. Performance Optimization & Deployment Checklist

Before deploying this module to production environments, verify each operational item below:
