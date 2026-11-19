# Module 3: Edge Caching, Streaming Suspense & Multi-Tenant Routing

## 1. Architectural Overview & System Topography

Modern web scale requires decoupling dynamic user context from static asset distribution. Next.js 15 redefines caching defaults by shifting fetch requests from aggressive automatic caching to `no-store` by default, putting cache control explicitly back into developer control. 

This module provides the production blueprint for combining edge middleware, wildcard multi-tenancy, granular tag-based cache revalidation, and React Server Component (RSC) streaming.

```
                          ┌───────────────────────────┐
                          │   Global Anycast Edge     │
                          │ (Cloudflare / Vercel Edge)│
                          └─────────────┬─────────────┘
                                        │
                         Incoming Request: tenant.domain.com
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │    Next.js 15 Middleware  │
                          │   - Subdomain Extraction  │
                          │   - Host Header Rewrite   │
                          │   - Edge Context Injection│
                          └─────────────┬─────────────┘
                                        │
                                Path Rewrite:
                     /_tenants/tenant-slug/dashboard
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │ Server Component Pipeline │
                          └──────┬─────────────┬──────┘
                                 │             │
                    Fast / Cached Data      Slow Data Stream
                                 │             │
                                 ▼             ▼
                     ┌───────────────┐  ┌───────────────────┐
                     │ Shell Render  │  │ <Suspense> Yield  │
                     │  (Instant)    │  │ (Flushed via HTTP)│
                     └───────┬───────┘  └─────────┬─────────┘
                             │                    │
                             └──────────┬─────────┘
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │ Client Browser DOM Hydrate│
                          └───────────────────────────┘
```

### Next.js 14 vs. Next.js 15 Cache Defaults

| Feature / Mechanism | Next.js 14 Paradigm | Next.js 15 Paradigm | Operational Impact |
| :--- | :--- | :--- | :--- |
| **`fetch()` Requests** | `force-cache` by default | `no-store` by default | Eliminates stale data leaks; requires explicit cache tags for ISR. |
| **Route Handlers (`GET`)** | Cached by default unless using dynamic functions | Uncached (`no-store`) by default | Static webhooks or health checks must explicitly define `revalidate`. |
| **Client Navigation Cache** | 30s cache for dynamic pages, 5m for static | 0s cache for dynamic pages (`staleTimes.dynamic: 0`) | Instant consistency on client navigations; stops visual desync. |
| **Streaming Compilation** | Prone to waterfall blocking on uncached tags | Decoupled via Server Component Fiber splits | Faster Time-to-First-Byte (TTFB) on edge node responses. |

---

## 2. Advanced Multi-Tenant Dynamic Subdomain Routing

This blueprint implements wildcard subdomain isolation (e.g., `acme.platform.com` or custom domains like `dashboard.acme.com`) routing internally to dynamic route parameters without causing client-side redirection loops or leaking tenant contexts.

### 2.1. Edge Middleware with Custom Domain Mapping

Create or replace `middleware.ts` in the project root:

```typescript
// middleware.ts
import { NextRequest, NextResponse } from 'next/server';

export const config = {
  matcher: [
    /*
     * Match all paths except:
     * 1. /api routes
     * 2. /_next (Next.js internals)
     * 3. /_static (inside /public)
     * 4. Static files (e.g. /favicon.ico, /sitemap.xml, robots.txt, etc.)
     */
    '/((?!api/|_next/|_static/|[\\w-]+\\.\\w+).*)',
  ],
};

const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN || 'platform.com';

export default async function middleware(req: NextRequest) {
  const url = req.nextUrl;
  const hostname = req.headers.get('host') || '';

  // Extract clean tenant hostname by removing root domain and port numbers
  const currentHost = hostname
    .replace(`.${ROOT_DOMAIN}`, '')
    .replace(`:${url.port}`, '');

  // Detect custom domain vs. root domain vs. subdomain
  const isRootDomain =
    hostname === ROOT_DOMAIN ||
    hostname === `www.${ROOT_DOMAIN}` ||
    hostname === 'localhost:3000';

  // Rewrites for public marketing site on the root domain
  if (isRootDomain) {
    return NextResponse.rewrite(new URL(`/marketing${url.pathname}`, req.url));
  }

  // App routing: Inject the detected tenant identifier into internal path
  // Custom domains map to their tenant slug; subdomains map directly
  const tenantSlug = currentHost.toLowerCase();

  // Rewrite internal routes to the tenant folder structure
  // e.g., acme.platform.com/analytics -> /app/[tenant]/analytics
  const rewriteUrl = new URL(`/app/${tenantSlug}${url.pathname}${url.search}`, req.url);

  const response = NextResponse.rewrite(rewriteUrl);

  // Set internal security and context headers for Server Components
  response.headers.set('x-tenant-slug', tenantSlug);
  response.headers.set('x-forwarded-host', hostname);

  return response;
}
```

### 2.2. Production App Router File Architecture

Organize the `app` directory to separate public, root-level marketing interfaces from dynamically resolved tenant spaces:

```
app/
├── app/
│   └── [tenant]/
│       ├── layout.tsx              # Tenant context hydration, tenant auth checks
│       ├── page.tsx                # Tenant primary dashboard view
│       ├── settings/
│       │   └── page.tsx            # Tenant settings
│       └── analytics/
│           ├── loading.tsx         # Route-level fallback
│           └── page.tsx            # Async streaming analytics
├── marketing/
│   ├── layout.tsx                  # Public marketing layout
│   └── page.tsx                    # Landing page
├── api/
│   └── revalidate/
│       └── route.ts                # Cache tag invalidation webhook
└── layout.tsx                      # Root HTML and base providers
```

### 2.3. Tenant Layout with Security Enforcement

```tsx
// app/app/[tenant]/layout.tsx
import { ReactNode } from 'react';
import { notFound } from 'next/navigation';
import { headers } from 'next/headers';

interface TenantLayoutProps {
  children: ReactNode;
  params: Promise<{ tenant: string }>;
}

interface TenantMetadata {
  id: string;
  name: string;
  slug: string;
  plan: 'free' | 'pro' | 'enterprise';
  isActive: boolean;
}

// Database validation layer (Memoized at the edge/data tier)
async function getTenant(slug: string): Promise<TenantMetadata | null> {
  const res = await fetch(`https://api.internal.platform.com/v1/tenants/${slug}`, {
    headers: {
      'Authorization': `Bearer ${process.env.INTERNAL_SERVICE_KEY}`,
      'Content-Type': 'application/json',
    },
    next: {
      revalidate: 3600, // Cache for 1 hour; manually purged via webhooks
      tags: [`tenant:${slug}`, 'all-tenants'],
    },
  });

  if (!res.ok) {
    if (res.status === 404) return null;
    throw new Error(`Failed to fetch tenant context for ${slug}: ${res.statusText}`);
  }

  return res.json();
}

export default async function TenantLayout({ children, params }: TenantLayoutProps) {
  const { tenant } = await params;
  const headerList = await headers();
  const headerTenant = headerList.get('x-tenant-slug');

  // Verify that the route param strictly matches the rewritten header
  if (!headerTenant || headerTenant !== tenant) {
    notFound();
  }

  const tenantData = await getTenant(tenant);

  if (!tenantData || !tenantData.isActive) {
    notFound();
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <header className="border-b bg-white px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <span className="font-bold text-lg text-slate-900">{tenantData.name}</span>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-800 font-mono">
            {tenantData.plan.toUpperCase()}
          </span>
        </div>
        <div className="text-sm text-slate-500 font-mono">Workspace: {tenantData.slug}</div>
      </header>
      <main className="flex-1 p-8 max-w-7xl mx-auto w-full">
        {children}
      </main>
    </div>
  );
}
```

---

## 3. High-Performance Tag-Based ISR and Revalidation Pipelines

Next.js 15 requires an explicit cache invalidation architecture using Next-specific options within `fetch` and direct calls to `revalidateTag` inside Server Actions and Route Handlers.

### 3.1. Tag Architecture Taxonomy

Structure your cache tags uniformly across the application to prevent unintentional broad invalidations or stale reads:

| Scope | Tag Structure | Example | Invalidation Trigger |
| :--- | :--- | :--- | :--- |
| **Entity-Level** | `[entity]:[id]` | `user:usr_99812` | User updates their profile. |
| **Tenant-Level** | `tenant:[slug]:[resource]` | `tenant:acme:billing` | Subscription checkout webhook completes. |
| **Collection-Level** | `tenant:[slug]:[collection]` | `tenant:acme:invoices` | New invoice generated. |
| **Global System** | `system:[resource]` | `system:currencies` | Global exchange rates update daily. |

### 3.2. Concrete Revalidation Route Handler

```typescript
// app/api/revalidate/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { revalidateTag } from 'next/cache';
import crypto from 'crypto';

interface InvalidationPayload {
  tags: string[];
  tenant?: string;
  timestamp: number;
}

export async function POST(req: NextRequest) {
  try {
    const rawBody = await req.text();
    const signature = req.headers.get('x-vault-signature');
    const secret = process.env.CACHE_WEBHOOK_SECRET;

    if (!secret) {
      console.error('Missing CACHE_WEBHOOK_SECRET environment variable.');
      return NextResponse.json({ error: 'Server configuration error' }, { status: 500 });
    }

    if (!signature) {
      return NextResponse.json({ error: 'Missing security signature' }, { status: 401 });
    }

    // Cryptographic validation of incoming webhook
    const expectedSignature = crypto
      .createHmac('sha256', secret)
      .update(rawBody)
      .digest('hex');

    if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expectedSignature))) {
      return NextResponse.json({ error: 'Invalid HMAC signature' }, { status: 403 });
    }

    const payload: InvalidationPayload = JSON.parse(rawBody);

    if (!Array.isArray(payload.tags) || payload.tags.length === 0) {
      return NextResponse.json(
        { error: 'Invalid payload: "tags" must be a non-empty array' },
        { status: 400 }
      );
    }

    // Process invalidations across the Edge cluster
    const invalidationResults = payload.tags.map((tag) => {
      try {
        revalidateTag(tag);
        return { tag, status: 'purged' };
      } catch (err) {
        return { tag, status: 'error', error: (err as Error).message };
      }
    });

    return NextResponse.json({
      revalidated: true,
      timestamp: Date.now(),
      results: invalidationResults,
    });
  } catch (error) {
    return NextResponse.json(
      { error: 'Internal operational error', details: (error as Error).message },
      { status: 500 }
    );
  }
}
```

### 3.3. Cache Invalidation in Server Actions

```typescript
// app/actions/billing.ts
'use server';

import { revalidateTag } from 'next/cache';
import { headers } from 'next/headers';

interface UpdatePlanResult {
  success: boolean;
  error?: string;
}

export async function updateTenantPlan(
  tierId: string,
  targetTenant: string
): Promise<UpdatePlanResult> {
  const headerList = await headers();
  const callerTenant = headerList.get('x-tenant-slug');

  // Verify the tenant context matches the operation target
  if (callerTenant !== targetTenant) {
    return { success: false, error: 'Unauthorized tenancy boundary breach.' };
  }

  try {
    const res = await fetch(`https://api.internal.platform.com/v1/billing/${targetTenant}`, {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${process.env.INTERNAL_SERVICE_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ tier: tierId }),
    });

    if (!res.ok) {
      throw new Error(`Plan update failed with status: ${res.status}`);
    }

    // Invalidate the tenant configuration and the billing details explicitly
    revalidateTag(`tenant:${targetTenant}`);
    revalidateTag(`tenant:${targetTenant}:billing`);

    return { success: true };
  } catch (error) {
    return { success: false, error: (error as Error).message };
  }
}
```

---

## 4. Deep-Tier Streaming Suspense Boundaries

Streaming Suspense allows Server Components to stream chunks of UI over an active HTTP response as database and network calls resolve, bypassing the slowest bottleneck on the page.

### 4.1. Streaming Architecture Pipeline

```
Client -> HTTP Request -> Edge Router -> Server Renders Outer Layout
                                            │
                                            ├─> Render Shell HTML Immediately --> Browser displays loading
                                            │
                                            ├─> Stream 1: Fast Component Resolves --> Browser renders cards
                                            │
                                            └─> Stream 2: Slow Component Resolves --> Browser renders charts
```

### 4.2. Implementation Blueprint

```tsx
// app/app/[tenant]/analytics/page.tsx
import { Suspense } from 'react';
import { SkeletonMetricCard, SkeletonChart } from '@/components/skeletons';

interface AnalyticsPageProps {
  params: Promise<{ tenant: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function AnalyticsPage({ params, searchParams }: AnalyticsPageProps) {
  const { tenant } = await params;
  const resolvedSearchParams = await searchParams;
  const range = (resolvedSearchParams.range as string) || '30d';

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Analytics Overview
        </h1>
        <p className="text-slate-500 text-sm">Real-time usage and financial throughput.</p>
      </div>

      {/* Boundary 1: Metrics resolve quickly (low network cost) */}
      <Suspense fallback={<MetricsFallback />}>
        <FastMetricsSection tenant={tenant} range={range} />
      </Suspense>

      {/* Boundary 2: Deep compute analytical graphs stream independently */}
      <Suspense fallback={<ChartFallback />}>
        <SlowTimeSeriesSection tenant={tenant} range={range} />
      </Suspense>
    </div>
  );
}

// -------------------------------------------------------------
// Component Stream 1: High Priority / Low Latency
// -------------------------------------------------------------
async function FastMetricsSection({ tenant, range }: { tenant: string; range: string }) {
  // Simulates 150ms DB call
  const metrics = await fetchTenantMetrics(tenant, range);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      <div className="bg-white p-6 rounded-lg border border-slate-200">
        <span className="text-xs font-semibold text-slate-400 uppercase">Requests</span>
        <p className="text-3xl font-extrabold text-slate-800 mt-2">
          {metrics.totalRequests.toLocaleString()}
        </p>
      </div>
      <div className="bg-white p-6 rounded-lg border border-slate-200">
        <span className="text-xs font-semibold text-slate-400 uppercase">P99 Latency</span>
        <p className="text-3xl font-extrabold text-slate-800 mt-2">{metrics.p99Latency}ms</p>
      </div>
      <div className="bg-white p-6 rounded-lg border border-slate-200">
        <span className="text-xs font-semibold text-slate-400 uppercase">Total Bandwidth</span>
        <p className="text-3xl font-extrabold text-slate-800 mt-2">{metrics.bandwidthGb} GB</p>
      </div>
    </div>
  );
}

// -------------------------------------------------------------
// Component Stream 2: Slow Heavy Analytic Pipeline (Streamed Late)
// -------------------------------------------------------------
async function SlowTimeSeriesSection({ tenant, range }: { tenant: string; range: string }) {
  // Simulates an intensive aggregation query taking 1200ms
  const chartData = await fetchDeepTimeSeries(tenant, range);

  return (
    <div className="bg-white p-6 rounded-lg border border-slate-200">
      <h3 className="font-semibold text-slate-800 mb-4">Ingestion vs Output (Time-Series)</h3>
      <div className="h-64 flex items-end space-x-2">
        {chartData.points.map((point) => (
          <div
            key={point.timestamp}
            className="flex-1 bg-indigo-500 rounded-t hover:bg-indigo-600 transition-colors"
            style={{ height: `${point.percentage}%` }}
            title={`${point.date}: ${point.value}`}
          />
        ))}
      </div>
    </div>
  );
}

// Fallback Shells
function MetricsFallback() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      <SkeletonMetricCard />
      <SkeletonMetricCard />
      <SkeletonMetricCard />
    </div>
  );
}

function ChartFallback() {
  return <SkeletonChart />;
}

// Fetch stubs with intentional Next.js 15 cache assertions
async function fetchTenantMetrics(tenant: string, range: string) {
  const res = await fetch(
    `https://api.internal.platform.com/v1/tenants/${tenant}/metrics?range=${range}`,
    {
      next: {
        revalidate: 60, // SWR: Dynamic update max once a minute
        tags: [`tenant:${tenant}:analytics`],
      },
    }
  );
  if (!res.ok) throw new Error('Failed to load metrics data');
  return res.json() as Promise<{ totalRequests: number; p99Latency: number; bandwidthGb: number }>;
}

async function fetchDeepTimeSeries(tenant: string, range: string) {
  const res = await fetch(
    `https://api.internal.platform.com/v1/tenants/${tenant}/timeseries?range=${range}`,
    {
      next: {
        revalidate: 300, // Expensive query: hold for 5 minutes
        tags: [`tenant:${tenant}:timeseries`],
      },
    }
  );
  if (!res.ok) throw new Error('Failed to load analytical charts');
  return res.json() as Promise<{ points: Array<{ timestamp: string; date: string; percentage: number; value: number }> }>;
}
```

```tsx
// components/skeletons.tsx
export function SkeletonMetricCard() {
  return (
    <div className="bg-white p-6 rounded-lg border border-slate-200 animate-pulse">
      <div className="h-3 w-16 bg-slate-200 rounded mb-4" />
      <div className="h-8 w-28 bg-slate-200 rounded" />
    </div>
  );
}

export function SkeletonChart() {
  return (
    <div className="bg-white p-6 rounded-lg border border-slate-200 animate-pulse">
      <div className="h-4 w-48 bg-slate-200 rounded mb-8" />
      <div className="h-64 bg-slate-100 rounded flex items-center justify-center">
        <span className="text-slate-400 text-sm font-medium">Streaming metrics payload...</span>
      </div>
    </div>
  );
}
```

---

## 5. Production Configuration: Edge Caching Runtime Tuning

### Next.js Core Optimization Config

Place the following configuration inside `next.config.ts`:

```typescript
// next.config.ts
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  
  // Custom headers to enforce high security standards on edge routing
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-DNS-Prefetch-Control', value: 'on' },
          { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'origin-when-cross-origin' },
        ],
      },
      {
        // Enforce cache behavior on static images and immutable fonts
        source: '/_static/:path*',
        headers: [
          { key: 'Cache-Control', value: 'public, max-age=31536000, immutable' },
        ],
      },
    ];
  },

  // Logging behavior: Print cache hit/miss statuses in development for debugging
  logging: {
    fetches: {
      fullUrl: true,
    },
  },

  // Enable dynamic client routing optimizations (Next.js 15 cache retention)
  experimental: {
    staleTimes: {
      dynamic: 0, // Client side dynamic page cache holds 0 seconds
      static: 180, // Static layouts/pages held in browser memory for 3 mins
    },
  },
};

export default nextConfig;
```

---

## 6. Verification & Troubleshooting Runbook

### Cache Miss / Stale Data Diagnostic Table

| Symptom | Underlying Cause | Diagnostic Step | Production Resolution |
| :--- | :--- | :--- | :--- |
| Dynamic route updates fail to display after `revalidateTag()`. | In-memory Next.js 15 Client Router Cache holds static parts of the tree. | Check navigation method (`router.push` vs direct link). | Call `router.refresh()` in the client component or adjust `staleTimes.dynamic: 0`. |
| Middleware executes endless redirect loop. | `currentHost` extraction fails to strip the port or includes subpaths incorrectly. | Log `req.headers.get('host')` and `url.pathname` at top of middleware. | Use the regex pattern from Section 2.1 to sanitize host strings. |
| Streaming stops working; page hangs until all data is ready. | Data fetches occur above the `<Suspense>` boundary in parent components. | Inspect parent RSCs for blocking `await` statements. | Move data fetch functions down into the child components wrapped by `<Suspense>`. |
| Subdomain context leakage across concurrent requests. | Shared Node.js global state or closure variables hold tenant IDs. | Search codebase for globally scoped tenant variables. | Use `headers()` or `React.cache()` to scope data access per request. |

### CLI Cache Verification Script

Run this verification suite from your CI/CD runner or locally via terminal to test edge header resolution and invalidation APIs:

```bash
#!/usr/bin/env bash
# run-edge-diagnostics.sh
set -eo pipefail

TARGET_DOMAIN="http://localhost:3000"
REVALIDATE_SECRET="test-secret-value-32-chars-minimum"
TENANT="acme"

echo "=== 1. Checking Tenant Context Ingestion ==="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: ${TENANT}.platform.localhost:3000" "${TARGET_DOMAIN}/analytics")
if [ "$STATUS" -eq 200 ] || [ "$STATUS" -eq 307 ]; then
  echo "✔ Subdomain rewrite active: Returned HTTP $STATUS"
else
  echo "✖ Failed Subdomain rewrite: Returned HTTP $STATUS"
  exit 1
fi

echo "=== 2. Testing Cryptographic Revalidation Webhook ==="
PAYLOAD='{"tags":["tenant:acme:analytics"],"timestamp":1700000000}'
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$REVALIDATE_SECRET" | sed 's/^.* //')

REV_RESPONSE=$(curl -s -X POST "${TARGET_DOMAIN}/api/revalidate" \
  -H "Content-Type: application/json" \
  -H "x-vault-signature: ${SIGNATURE}" \
  -d "$PAYLOAD")

echo "Edge Response: $REV_RESPONSE"
if [[ $REV_RESPONSE == *"\"revalidated\":true"* ]]; then
  echo "✔ Cache invalidation pipeline confirmed operational."
else
  echo "✖ Cache invalidation rejected."
  exit 1
fi

echo "All tests passed successfully."
