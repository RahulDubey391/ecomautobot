# Module 1: Next.js 15 App Router & Server Component Architecture

---

## 1. Enterprise Directory Structure & Layering Strategy

In Next.js 15, directory layout is not an aesthetic preference—it defines the physical boundary between your Node.js runtime and the browser runtime. This blueprint establishes a scalable, domain-driven structure optimized for strict Server/Client Component isolation, sub-second Fast Refresh, and minimal client-side bundle allocation.

```
project-root/
├── app/
│   ├── (auth)/
│   │   ├── login/
│   │   │   └── page.tsx
│   │   └── layout.tsx
│   ├── (dashboard)/
│   │   ├── analytics/
│   │   │   └── page.tsx
│   │   ├── settings/
│   │   │   └── page.tsx
│   │   ├── @modal/
│   │   │   ├── (.)photos/[id]/
│   │   │   │   └── page.tsx
│   │   │   └── default.tsx
│   │   ├── photos/[id]/
│   │   │   └── page.tsx
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── api/
│   │   └── webhooks/
│   │       └── stripe/
│   │           └── route.ts
│   ├── favicon.ico
│   ├── globals.css
│   └── layout.tsx
├── components/
│   ├── ui/                       # Pure design system (stateless primitive UI)
│   │   ├── button.tsx
│   │   ├── dialog.tsx
│   │   └── input.tsx
│   └── feedback/
│       ├── error-boundary.tsx
│       └── skeleton-grid.tsx
├── features/                     # Domain-driven feature modules
│   ├── analytics/
│   │   ├── actions/              # Module-scoped Server Actions
│   │   │   └── export-report.ts
│   │   ├── components/           # Mixed RSC and Client interactive blocks
│   │   │   ├── chart-container.client.tsx
│   │   │   └── metric-card.server.tsx
│   │   ├── queries/              # Server-only read infrastructure
│   │   │   └── get-metrics.ts
│   │   ├── schemas/              # Zod validation models
│   │   │   └── metrics-filter.ts
│   │   └── types/
│   │       └── index.ts
│   └── media/
│       ├── actions/
│       │   └── mutate-photo.ts
│       ├── components/
│       │   ├── photo-frame.tsx
│       │   └── photo-modal.client.tsx
│       └── queries/
│           └── get-photo.ts
├── lib/                          # Framework-agnostic infrastructure
│   ├── auth/
│   │   ├── session.ts
│   │   └── token.ts
│   ├── db/
│   │   ├── client.ts
│   │   └── schema.ts
│   ├── env/
│   │   └── server.ts
│   └── utils/
│       └── cn.ts
├── hooks/                        # Universal custom client hooks
│   ├── use-intersection-observer.ts
│   └── use-window-size.ts
├── types/                        # Global ambient and Next.js internal type overrides
│   └── next.d.ts
├── next.config.ts
├── tsconfig.json
└── package.json
```

### Configuration: Strict Path Aliases & Server-Isolation Guarantees

#### `tsconfig.json`
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [
      {
        "name": "next"
      }
    ],
    "paths": {
      "@/*": ["./*"],
      "@components/*": ["./components/*"],
      "@features/*": ["./features/*"],
      "@lib/*": ["./lib/*"],
      "@ui/*": ["./components/ui/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

#### `next.config.ts`
```typescript
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    typedRoutes: true,
    // Optimize bundle boundaries by enforcing barrel file tree-shaking
    optimizePackageImports: ['lucide-react', '@radix-ui/react-icons', 'date-fns'],
  },
  logging: {
    fetches: {
      fullUrl: true,
    },
  },
};

export default nextConfig;
```

---

## 2. RSC vs. Client Component Mental Model & Boundary Enforcement

React Server Components (RSC) execute **only once** on the server (or at build-time). They generate a structural virtual DOM representation streamed as JSON-like flight data to the browser. Client Components are traditional React components that execute on both the server (during the initial SSR pass) and on the client (during hydration and user interactions).

### Architectural Decision Matrix

| Dimension | React Server Component (Default) | Client Component (`'use client'`) |
| :--- | :--- | :--- |
| **Execution Environment** | Node.js / Edge Runtime | Initial SSR pass on Server + Browser |
| **Data Fetching Access** | Direct access to DB, Redis, filesystem, secrets | Network-only (via HTTP Fetch, Server Actions) |
| **Bundle Impact** | 0 KB added to JavaScript client bundle | Hydration code + dependencies shipped to client |
| **Allowed React APIs** | `async/await`, `React.use()` for promises | `useState`, `useEffect`, `useReducer`, DOM events |
| **Browser APIs** | ❌ Never (`window`, `localStorage`, `navigator`) | ✅ Accessible inside lifecycle hooks & event handlers |
| **Re-rendering Trigger** | On server re-validation / path dynamic transitions | Reactive state changes, parent re-renders, contexts |

### Component Composition Patterns: The Leaf & Sandwich Rules

A common architectural flaw is placing `'use client'` high up the DOM tree, converting all child components into Client Components and shipping their code downstream.

```
INCORRECT: Monolithic Client Boundary
App
 └─ Layout (Server)
     └─ DashboardView ('use client') <--- Entire tree converted to client bundle
         ├─ MetricDisplay (Read-only data)
         ├─ InteractiveFilter (Needs state)
         └─ ComplexDataGrid (Huge JS library)

CORRECT: Sandwich Pattern (Children as Props)
App
 └─ Layout (Server)
     └─ MetricDisplay (Server - 0KB JS)
     └─ InteractiveFilterWrapper ('use client' - Tiny JS)
         └─ ComplexDataGrid (Server Component injected as `children`)
```

### Production Implementation: Strict Boundary Isolation

Prevent database credentials and internal APIs from accidentally leaking into the client bundle by employing the `server-only` and `client-only` guard packages.

#### 1. Data Layer Enforcement (`lib/db/queries.ts`)
```typescript
import 'server-only';
import { db } from '@/lib/db/client';

export interface UserMetric {
  id: string;
  label: string;
  value: number;
  delta: number;
}

export async function fetchSystemMetrics(workspaceId: string): Promise<UserMetric[]> {
  // Direct database query without exposing connection details to client
  const records = await db.query(
    'SELECT id, label, value, delta FROM metrics WHERE workspace_id = $1 ORDER BY created_at DESC LIMIT 5',
    [workspaceId]
  );
  
  return records.rows.map((row) => ({
    id: String(row.id),
    label: String(row.label),
    value: Number(row.value),
    delta: Number(row.delta),
  }));
}
```

#### 2. The Server Container (`features/analytics/components/metrics-dashboard.server.tsx`)
```typescript
import { fetchSystemMetrics } from '@/lib/db/queries';
import { MetricsFilterShell } from './metrics-filter-shell.client';
import { MetricTable } from './metric-table.server';

interface MetricsDashboardProps {
  workspaceId: string;
}

export async function MetricsDashboard({ workspaceId }: MetricsDashboardProps) {
  // Data fetched on server. Zero serialization overhead down to the client.
  const data = await fetchSystemMetrics(workspaceId);

  return (
    <section className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-bold tracking-tight">System Performance</h2>
      </div>
      {/* 
        Sandwich Pattern: Client shell accepts an RSC via standard `children` prop.
        The interactive shell manages state (search, filters), but doesn't force 
        MetricTable's parsing libraries into the client bundle.
      */}
      <MetricsFilterShell>
        <MetricTable metrics={data} />
      </MetricsFilterShell>
    </section>
  );
}
```

#### 3. The Interactive Client Shell (`features/analytics/components/metrics-filter-shell.client.tsx`)
```typescript
'use client';

import React, { useState, useTransition } from 'react';
import { Input } from '@/components/ui/input';

interface MetricsFilterShellProps {
  children: React.ReactNode;
}

export function MetricsFilterShell({ children }: MetricsFilterShellProps) {
  const [filterQuery, setFilterQuery] = useState('');
  const [isPending, startTransition] = useTransition();

  const handleFilterChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    startTransition(() => {
      setFilterQuery(e.target.value);
    });
  };

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6 shadow-sm">
      <div className="mb-4 max-w-sm">
        <Input
          placeholder="Filter view metrics..."
          value={filterQuery}
          onChange={handleFilterChange}
          aria-label="Filter Metrics"
        />
        {isPending && <span className="text-xs text-neutral-400">Updating view...</span>}
      </div>
      {/* Dynamic DOM display modified via client state, preserving Server Child payload */}
      <div className={isPending ? 'opacity-50 transition-opacity' : 'opacity-100'}>
        {children}
      </div>
    </div>
  );
}
```

#### 4. The Leaf Component (`features/analytics/components/metric-table.server.tsx`)
```typescript
import type { UserMetric } from '@/lib/db/queries';

export function MetricTable({ metrics }: { metrics: UserMetric[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-neutral-200 bg-neutral-50 text-neutral-600">
          <tr>
            <th className="px-4 py-3">Metric</th>
            <th className="px-4 py-3">Value</th>
            <th className="px-4 py-3">Trend</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {metrics.map((m) => (
            <tr key={m.id} className="hover:bg-neutral-50/50">
              <td className="px-4 py-3 font-medium">{m.label}</td>
              <td className="px-4 py-3">{m.value.toLocaleString()}</td>
              <td className={`px-4 py-3 ${m.delta >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                {m.delta >= 0 ? `+${m.delta}%` : `${m.delta}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

---

## 3. Advanced Routing Engine: Nested Layouts, Parallel Routes & Intercepting Routes

Next.js 15 routing handles nested state preservation via subtrees, side-by-side slot rendering via **Parallel Routes**, and route masquerading via **Intercepting Routes**.

### Deep Dive: Production-Grade Hard/Soft Navigation Modal Pattern

When a user selects a gallery image:
1. **Soft Navigation (Client Router Transition)**: The URL updates to `/photos/123`. The current page remains intact behind a modal dialog rendered via the parallel route slot `@modal/(.)photos/[id]`.
2. **Hard Navigation (Direct Link / Refresh)**: The user visits `/photos/123` directly or reloads the tab. The interception is bypassed, rendering the full standalone view at `photos/[id]/page.tsx`.

```
Dashboard Segment
  ├── layout.tsx                <- Contains: props.children and props.modal
  ├── @modal/
  │   ├── default.tsx           <- Fallback when no modal is active (returns null)
  │   └── (.)photos/[id]/
  │       └── page.tsx          <- Intercepted soft-route modal
  ├── photos/
  │   └── [id]/
  │       └── page.tsx          <- Dedicated hard-route standalone page
  └── page.tsx                  <- Main gallery view
```

#### 1. The Layout Slot Host (`app/(dashboard)/layout.tsx`)
```typescript
import React from 'react';

interface DashboardLayoutProps {
  children: React.ReactNode;
  modal: React.ReactNode;
}

export default function DashboardLayout({ children, modal }: DashboardLayoutProps) {
  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900">
      <header className="border-b bg-white px-8 py-4">
        <h1 className="text-lg font-semibold tracking-wide">Enterprise Image Console</h1>
      </header>
      <main className="container mx-auto p-8">
        {children}
      </main>
      {/* The parallel slot renders here when route matches; otherwise defaults to default.tsx */}
      {modal}
    </div>
  );
}
```

#### 2. The Modal Fallback Catch-All (`app/(dashboard)/@modal/default.tsx`)
```typescript
// Essential: Returns null to ensure the @modal slot mounts nothing on baseline routes.
export default function DefaultModalSlot() {
  return null;
}
```

#### 3. The Intercepted Route Modal (`app/(dashboard)/@modal/(.)photos/[id]/page.tsx`)
*Note: In Next.js 15, `params` is an asynchronous `Promise` that must be unwrapped using `await`.*

```typescript
import { notFound } from 'next/navigation';
import { PhotoModalClient } from '@/features/media/components/photo-modal.client';

interface InterceptedPhotoProps {
  params: Promise<{ id: string }>;
}

async function getPhotoData(id: string) {
  // Simulated localized server fetch
  const mockDb: Record<string, { title: string; src: string; resolution: string }> = {
    '1': { title: 'Architecture Main', src: 'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab', resolution: '4K' },
    '2': { title: 'System Engine', src: 'https://images.unsplash.com/photo-1518770660439-4636190af475', resolution: 'Raw' },
  };

  return mockDb[id] ?? null;
}

export default async function InterceptedPhotoModal({ params }: InterceptedPhotoProps) {
  const { id } = await params;
  const photo = await getPhotoData(id);

  if (!photo) {
    notFound();
  }

  return (
    <PhotoModalClient title={photo.title}>
      <div className="space-y-4">
        <img
          src={photo.src}
          alt={photo.title}
          className="h-96 w-full rounded-md object-cover"
        />
        <div className="flex justify-between text-sm text-neutral-500">
          <span>Identifier: {id}</span>
          <span>Quality: {photo.resolution}</span>
        </div>
      </div>
    </PhotoModalClient>
  );
}
```

#### 4. The Interactive Modal Wrapper (`features/media/components/photo-modal.client.tsx`)
```typescript
'use client';

import React, { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

interface PhotoModalClientProps {
  title: string;
  children: React.ReactNode;
}

export function PhotoModalClient({ title, children }: PhotoModalClientProps) {
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
    }
  }, []);

  const handleDismiss = () => {
    // Navigates one step backward, clearing the interception slot back to @modal/default.tsx
    router.back();
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={handleDismiss}
      className="backdrop:bg-black/80 fixed inset-0 z-50 m-auto w-full max-w-2xl rounded-xl border border-neutral-200 bg-white p-6 shadow-2xl open:animate-in open:fade-in-0 open:zoom-in-95"
    >
      <div className="flex items-center justify-between border-b pb-3">
        <h3 className="text-lg font-semibold">{title}</h3>
        <button
          onClick={handleDismiss}
          className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-900"
          aria-label="Close dialog"
        >
          ✕
        </button>
      </div>
      <div className="mt-4">{children}</div>
    </dialog>
  );
}
```

#### 5. The Hard Standalone Page (`app/(dashboard)/photos/[id]/page.tsx`)
```typescript
import Link from 'next/link';
import { notFound } from 'next/navigation';

interface DedicatedPhotoPageProps {
  params: Promise<{ id: string }>;
}

export default async function DedicatedPhotoPage({ params }: DedicatedPhotoPageProps) {
  const { id } = await params;

  // Direct fetch fallback for hard loads/page reloads
  if (id !== '1' && id !== '2') {
    notFound();
  }

  return (
    <article className="mx-auto max-w-3xl rounded-xl border border-neutral-200 bg-white p-8">
      <Link
        href="/"
        className="mb-6 inline-block text-sm font-medium text-blue-600 hover:underline"
      >
        ← Return to Gallery Overview
      </Link>
      <header className="mb-6">
        <h1 className="text-3xl font-extrabold tracking-tight">Resource Entity: {id}</h1>
        <p className="text-neutral-500">Standalone Hard Load Rendering Mode</p>
      </header>
      <div className="aspect-video w-full rounded-lg bg-neutral-100 flex items-center justify-center border">
        <span className="text-neutral-400 font-mono">Render Payload Visualizer [{id}]</span>
      </div>
    </article>
  );
}
```

---

## 4. Next.js 15 Async Request APIs & Breaking Changes Migration Playbook

Next.js 15 makes runtime context APIs explicitly **asynchronous**. In previous versions, dynamic route arguments and HTTP metadata could be accessed synchronously during render execution. Now, synchronicity is removed to unlock continuous streaming, speculative microtask execution, and fine-grained partial rendering.

### The Async API Shift

```
// NEXT.JS 14 (LEGACY PATTERN)
export default function Page({ params, searchParams }: { params: { id: string } }) {
  const id = params.id;
  const cookieJar = cookies();
  const token = cookieJar.get('session');
}

// NEXT.JS 15 (CANONICAL ARCHITECTURE)
export default async function Page(props: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { id } = await props.params;
  const search = await props.searchParams;
  const cookieJar = await cookies();
  const token = cookieJar.get('session');
}
```

### Complete Implementation: Async Request Context Extraction

The following production pattern shows how to unpack asynchronous cookies, headers, and dynamic route params inside an authenticated sub-resource route:

```typescript
// app/(dashboard)/workspaces/[workspaceId]/audit/page.tsx
import { cookies, headers } from 'next/headers';
import { notFound, redirect } from 'next/navigation';

interface AuditRouteProps {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<{ page?: string; limit?: string }>;
}

export async function generateMetadata({ params }: AuditRouteProps) {
  const { workspaceId } = await params;
  return {
    title: `Audit Log Analysis | Workspace ${workspaceId}`,
  };
}

export default async function WorkspaceAuditPage({ params, searchParams }: AuditRouteProps) {
  // Await route segment params and search parameters concurrently
  const [{ workspaceId }, query] = await Promise.all([params, searchParams]);

  // Await dynamic request headers and cookies
  const [cookieStore, headerList] = await Promise.all([cookies(), headers()]);

  const authToken = cookieStore.get('auth_token')?.value;
  const userAgent = headerList.get('user-agent') ?? 'Unknown Client';
  const clientIp = headerList.get('x-forwarded-for') ?? '127.0.0.1';

  if (!authToken) {
    redirect('/login');
  }

  const currentPage = Number(query.page ?? '1');
  const pageSize = Number(query.limit ?? '25');

  if (Number.isNaN(currentPage) || currentPage < 1) {
    notFound();
  }

  return (
    <div className="space-y-6">
      <header className="border-b pb-4">
        <h1 className="text-2xl font-bold">Audit Log Ledger</h1>
        <p className="text-sm text-neutral-500 font-mono">Workspace ID: {workspaceId}</p>
      </header>

      <section className="grid grid-cols-2 gap-4 text-xs font-mono">
        <div className="rounded border bg-neutral-50 p-4">
          <p className="font-semibold text-neutral-700">Client Headers</p>
          <p className="truncate mt-1">IP: {clientIp}</p>
          <p className="truncate">Agent: {userAgent}</p>
        </div>
        <div className="rounded border bg-neutral-50 p-4">
          <p className="font-semibold text-neutral-700">Session Context</p>
          <p className="truncate mt-1">Token: {authToken.slice(0, 8)}...[redacted]</p>
          <p className="truncate">Paging: Page {currentPage} (Size {pageSize})</p>
        </div>
      </section>
    </div>
  );
}
```

---

## 5. Architectural Quality Checklist & Automated Boundary Auditor

Run this pre-flight checklist and audit script through your CI/CD pipeline to verify component boundaries before deployment.

### Architecture Pre-Flight Checklist

- [ ] **Boundary Integrity**: Every file importing native database clients (`pg`, `prisma`, `drizzle-orm`) has `import 'server-only'` at Line 1.
- [ ] **Next.js 15 Dynamic Contexts**: All page and layout definitions access `params` and `searchParams` via `await` or `React.use()`.
- [ ] **Leaf Pruning**: All components marked with `'use client'` are strictly leaves in the render tree, importing zero business logic query files.
- [ ] **Slots Sealed**: Every parallel route directory (e.g., `@modal`) has a sibling `default.tsx` exporting a component returning `null` or a static fallback.
- [ ] **Client State Escapes**: No client-side `useEffect` is utilized purely to fetch initial render-critical data; initial data must originate from Server Components.
- [ ] **Fetch Cache Declarations**: All runtime Next.js 15 `fetch()` requests specify explicit cache semantics (`cache: 'force-cache'`, `cache: 'no-store'`, or `next: { revalidate: N }`), as Next.js 15 defaults to un-cached fetches.

### Automated CI Guard: Client Bundle Leak Auditor

This Node.js audit script runs during CI (`npm run audit:boundaries`) to catch missing boundary statements, forbidden client imports, and synchronous `params` usages across the codebase.

```javascript
// scripts/audit-boundaries.mjs
import fs from 'node:fs';
import path from 'node:path';

const APP_DIR = path.resolve(process.cwd(), 'app');
const FEATURES_DIR = path.resolve(process.cwd(), 'features');
const LIB_DIR = path.resolve(process.cwd(), 'lib');

const FORBIDDEN_CLIENT_IMPORTS = [
  'server-only',
  'prisma',
  '@prisma/client',
  'drizzle-orm',
  'pg',
  'jsonwebtoken',
  'bcrypt',
];

let totalViolations = 0;

function walkDirectory(dir, callback) {
  if (!fs.existsSync(dir)) return;
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      walkDirectory(fullPath, callback);
    } else if (file.endsWith('.tsx') || file.endsWith('.ts')) {
      callback(fullPath);
    }
  }
}

console.log('\x1b[34m%s\x1b[0m', '🔍 Starting App Router Architecture & Security Audit...\n');

// 1. Audit Client Components for Dangerous Server Imports
walkDirectory(APP_DIR, auditFile);
walkDirectory(FEATURES_DIR, auditFile);

function auditFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  const isClientComponent = content.startsWith("'use client'") || content.startsWith('"use client"');

  if (isClientComponent) {
    for (const forbidden of FORBIDDEN_CLIENT_IMPORTS) {
      const importRegex = new RegExp(`from\\s+['"]${forbidden}['"]`, 'g');
      if (importRegex.test(content)) {
        console.error(
          '\x1b[31m%s\x1b[0m',
          `❌ [CRITICAL] Leaked server dependency "${forbidden}" inside Client Component:`
        );
        console.error(`   File: ${filePath}\n`);
        totalViolations++;
      }
    }
  }

  // 2. Audit DB/Data access files for missing 'server-only'
  if (filePath.includes(`${path.sep}queries${path.sep}`) || filePath.includes(`${path.sep}db${path.sep}`)) {
    if (!content.includes("'server-only'") && !content.includes('"server-only"')) {
      console.warn(
        '\x1b[33m%s\x1b[0m',
        `⚠️  [WARNING] Query/Database file lacks 'server-only' isolation guard:`
      );
      console.warn(`   File: ${filePath}\n`);
    }
  }

  // 3. Audit for deprecated Next.js 14 synchronous params patterns
  if (filePath.endsWith('page.tsx') || filePath.endsWith('layout.tsx')) {
    const syncParamsRegex = /export\s+default\s+function\s+\w+\(\s*\{\s*params\s*\}\s*:\s*\{\s*params\s*:\s*\{/g;
    if (syncParamsRegex.test(content)) {
      console.error(
        '\x1b[31m%s\x1b[0m',
        `❌ [DEPRECATION] Synchronous params typing detected (Next.js 15 requires params: Promise<...>):`
      );
      console.error(`   File: ${filePath}\n`);
      totalViolations++;
    }
  }
}

// 4. Audit Parallel Route slots for sibling default.tsx
walkDirectory(APP_DIR, (filePath) => {
  if (filePath.includes(`${path.sep}@`) && filePath.endsWith('page.tsx')) {
    const slotDirectory = path.dirname(filePath);
    const parentDirectory = path.resolve(slotDirectory, '..');
    const defaultSibling = path.join(slotDirectory, 'default.tsx');
    const parentDefault = path.join(parentDirectory, 'default.tsx');

    if (!fs.existsSync(defaultSibling) && !fs.existsSync(parentDefault)) {
      console.warn(
        '\x1b[33m%s\x1b[0m',
        `⚠️  [ROUTING] Slot missing fallback "default.tsx" in slot or parent path:`
      );
      console.warn(`   Directory: ${slotDirectory}\n`);
    }
  }
});

if (totalViolations > 0) {
  console.error('\x1b[31m%s\x1
