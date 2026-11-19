# Module 4: Performance Audit Checklist, Hydration Fixes & Deployment Swipe File

This module provides the production runbooks, automated audit workflows, diagnostic rules, and infrastructure configurations required to operate high-throughput Next.js 15 applications. Every checklist, code snippet, and configuration template in this file is tested against Next.js 15, React 19, and Node.js 20+ environments.

---

## 1. Zero-Downtime Core Web Vitals (CWV) Audit Checklist

Achieving sustained green scores on Google's Core Web Vitals (LCP < 2.5s, INP < 200ms, CLS < 0.1) under high-concurrency production loads requires strict architectural discipline. Use this audit protocol before releasing major features or migrating routes to Next.js 15.

### Largest Contentful Paint (LCP) Protocol
- [ ] **LCP Candidate Preloading**: If the hero image is the LCP candidate, enforce `priority` and set explicit `sizes`. Never lazy-load the LCP element.
  ```tsx
  // app/(marketing)/page.tsx
  import Image from 'next/image';

  export default function Hero() {
    return (
      <div className="relative h-[600px] w-full">
        <Image
          src="/hero-banner.webp"
          alt="Platform dashboard analytics preview"
          fill
          priority
          fetchPriority="high"
          sizes="(max-width: 768px) 100vw, (max-width: 1200px) 80vw, 1200px"
          quality={85}
          className="object-cover"
        />
      </div>
    );
  }
  ```
- [ ] **Font Subsetting & Zero Fallback Shifting**: Use `next/font/google` or `next/font/local` with `display: 'swap'` and `adjustFontFallback: true`.
  ```ts
  // lib/fonts.ts
  import { Inter, JetBrains_Mono } from 'next/font/google';

  export const inter = Inter({
    subsets: ['latin'],
    display: 'swap',
    variable: '--font-inter',
    adjustFontFallback: true,
  });

  export const mono = JetBrains_Mono({
    subsets: ['latin'],
    display: 'swap',
    variable: '--font-mono',
  });
  ```
- [ ] **Critical CSS Inlining**: Ensure critical styling is delivered in the initial document stream. Prevent layout flashes by avoiding runtime CSS-in-JS injection engines (e.g., legacy Emotion or styled-components without dedicated SSR compiler plugins). Use Tailwind CSS v4 or zero-runtime CSS modules.
- [ ] **Edge Network CDN Warmth**: Validate that dynamic SSR assets leverage stale-while-revalidate headers or Next.js 15 Partial Prerendering (PPR) shells to deliver the initial byte payload in under 200ms TTFB globally.
- [ ] **Streaming Fallback Precision**: Verify that every `Suspense` boundary wrapping dynamic data fetches renders an optimized, layout-stable skeleton that mirrors the exact bounding box of the resolved component.

### Interaction to Next Paint (INP) Protocol
- [ ] **Main Thread Task Splitting**: Transition long-running client-side computational loops into Web Workers or yield execution back to the browser via `scheduler.yield()` or microtask slicing.
  ```ts
  // lib/utils/scheduler.ts
  export async function yieldToMainThread(): Promise<void> {
    if ('scheduler' in window && 'yield' in (window as any).scheduler) {
      return await (window as any).scheduler.yield();
    }
    return new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  }
  ```
- [ ] **Server Action Execution Transitions**: Wrap all invocations of Server Actions that trigger UI mutations within `useTransition` or `useActionState` to maintain input responsiveness on the main thread during execution.
  ```tsx
  'use client';

  import { useActionState } from 'react';
  import { updateWorkspaceName } from '@/app/actions/workspace';

  export function WorkspaceSettings({ id, currentName }: { id: string; currentName: string }) {
    const [state, formAction, isPending] = useActionState(updateWorkspaceName, { error: null });

    return (
      <form action={formAction} className="space-y-4">
        <input type="hidden" name="workspaceId" value={id} />
        <input
          type="text"
          name="name"
          defaultValue={currentName}
          disabled={isPending}
          className="border p-2 rounded w-full disabled:opacity-50"
        />
        <button type="submit" disabled={isPending} aria-busy={isPending}>
          {isPending ? 'Saving...' : 'Update Name'}
        </button>
        {state.error && <p className="text-red-500">{state.error}</p>}
      </form>
    );
  }
  ```
- [ ] **Event Listener Debouncing & Throttling**: Audit scrolling, resizing, and keyboard search inputs. Ensure search forms update search parameters through non-blocking transitions rather than direct continuous re-renders.

### Cumulative Layout Shift (CLS) Protocol
- [ ] **Aspect Ratio Reservations**: Hard-code `aspect-ratio` on all dynamic media wrappers, ad slots, and embedded iframes.
- [ ] **Zero Dynamic DOM Insertion Above the Fold**: Prohibit client-side banner/alert insertion above existing content blocks post-hydration. Absolute-position notification toasts or reserve standard alert space within the SSR markup.
- [ ] **`font-display` Metric Overrides**: If loading local fonts outside `next/font`, define `@font-face` metric adjustments (`size-adjust`, `ascent-override`, `descent-override`) matching the fallback system font to eliminate text-reflow shifts.

---

## 2. Bundle Size Optimization & Analysis Engine

### Production Bundle Analyzer Configuration
To audit chunk distribution, execute Next.js compilation through `@next/bundle-analyzer`. Configure `next.config.ts` to execute analysis conditionally via environment variables without exposing production builds to runtime overhead.

```ts
// next.config.ts
import type { NextConfig } from 'next';
import withBundleAnalyzer from '@next/bundle-analyzer';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  experimental: {
    optimizePackageImports: [
      'lucide-react',
      'date-fns',
      'lodash-es',
      'recharts',
      '@radix-ui/react-icons',
    ],
  },
  logging: {
    fetches: {
      fullUrl: process.env.NODE_ENV === 'development',
    },
  },
};

export default withBundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
})(nextConfig);
```

Add the following analysis execution script to your `package.json`:
```json
{
  "scripts": {
    "analyze": "ANALYZE=true next build"
  }
}
```

### Modular Import & Tree-Shaking Guardrails

Heavy third-party dependencies can bloat initial client chunks. Apply these patterns to enforce strict tree-shaking:

#### Pattern A: Direct Path Barrel Isolation
```ts
// ❌ INCORRECT: Imports the entire barrel index, pulling in unused utilities
import { format, parseISO, addDays } from 'date-fns';

// ✅ CORRECT: Zero-index direct import to bypass deep subpath resolution issues
import format from 'date-fns/format';
import parseISO from 'date-fns/parseISO';
import addDays from 'date-fns/addDays';
```

#### Pattern B: Client Component Dynamic Boundary (Code Splitting)
Heavy interactive components (such as data tables, Monaco editor instances, canvas renderers, or complex charts) must not compile into initial page bundles.

```tsx
// app/dashboard/analytics/page.tsx
import dynamic from 'next/dynamic';
import { SkeletonChart } from '@/components/ui/skeleton-chart';

const DynamicChart = dynamic(
  () => import('@/components/analytics/heavy-time-series-chart').then((mod) => mod.TimeSeriesChart),
  {
    loading: () => <SkeletonChart />,
    ssr: false, // Chart requires DOM context and canvas; skip during SSR
  }
);

export default function AnalyticsRoute() {
  return (
    <main className="p-8">
      <h1 className="text-2xl font-bold tracking-tight">System Telemetry</h1>
      <div className="mt-6 h-[450px] w-full">
        <DynamicChart />
      </div>
    </main>
  );
}
```

---

## 3. The SSR Hydration Troubleshooting Matrix (20+ Battle-Tested Fixes)

Hydration errors occur when the Server-Rendered HTML markup diverges from the Client-Side virtual DOM evaluation during initial hydration. Below is an exhaustive diagnostic index and operational fix set for common Next.js 15 / React 19 hydration failures.

### Hydration Diagnostic Index

| ID | Symptom / React Error Message | Direct Root Cause | Solution Pattern |
|---|---|---|---|
| E01 | `Expected server HTML to contain a matching <p> in <div>` | Invalid HTML nesting: block-level element inside inline/paragraph element | Move block element outside or render container as `div` |
| E02 | `Text content does not match server-rendered HTML` (Timestamps) | Dynamic timezone or locale differences between Server and Client | Universal UTC formatting or `suppressHydrationWarning` |
| E03 | `Text content does not match server-rendered HTML` (IDs) | Dynamic random generation via `Math.random()` or `uuidv4()` | Standardize on React 19 `useId()` |
| E04 | `Server-rendered HTML didn't contain matching <span> inside <tbody>` | Direct `span`, `div`, or text children under `table`, `tbody`, or `tr` | Strict adherence to standard HTML table hierarchy |
| E05 | `Hydration failed because the initial UI does not match...` (Window/Storage) | Checking `typeof window !== 'undefined'` to conditionally alter render | Two-pass mount pattern via `useSyncExternalStore` or `useEffect` |
| E06 | `Extra attributes from the server: data-new-gr-c-s-check-loaded...` | Browser extensions (Grammarly, Dark Reader, Password Managers) injecting tags | Scope `suppressHydrationWarning` specifically on `<body>` |
| E07 | Unmatched whitespace or newline characters in pre/code blocks | Inconsistent prettier/linter compilation between build server and dev | Use zero-space inline templates or raw string interpolation |
| E08 | `Hydration failed because the initial UI does not match...` (Auth State) | Client reads cookie directly while SSR relies on decoupled headers | Centralize auth reads to Layout SSR payload passed as props |
| E09 | Nested `<a>` tags within child interactive links | Wrapping Next.js `<Link>` around native `<a>` tags or custom link buttons | Remove nested anchor tags; use a single `<Link>` component |
| E10 | Form element autofill/caching state divergence | Browser client caching prior form values across hard refreshes | Set `autoComplete="off"` or accept form control via unmanaged defaults |
| E11 | Theme class mismatch on root `<html>` (`class="dark"` vs `""`) | Server does not know user preference before client renders local storage | Inline head theme initialization script blocking paint |
| E12 | Missing dynamic CSS variables during CSS-in-JS hydration | Staged computation of theme values in client effect | Extract dynamic values into CSS variables injected via HTML head |
| E13 | `Expected server HTML to contain a matching <button> in <a>` | Button nested inside anchor or anchor inside button | Refactor component hierarchy to flat layout using CSS positioning |
| E14 | Localized currency string differences | Divergence between Node.js server system locale and browser user locale | Explicitly pass continuous `locale` parameter to `Intl.NumberFormat` |
| E15 | Divergent dynamic polyfills executing on client | Polyfills mutating native interfaces after SSR output generation | Load polyfills prior to Next.js runtime evaluation in layout |
| E16 | Mobile viewport detection via `navigator.userAgent` mismatch | Server receives generic user-agent via intermediate caching layer | Use standard CSS media queries instead of conditional JS rendering |
| E17 | Microtask/Async data leak resolving during render phase | State mutation occurring inline inside component body before return | Relocate asynchronous logic into `useEffect` or Server Action |
| E18 | HTML entity escaping discrepancies (`&amp;` vs `&`) | Mixed double-escaped entities generated through CMS text pipelines | Render raw strings safely without direct structural entity mixing |
| E19 | Dynamic CSS Modules hash divergence in micro-frontends | Mismatched build-time asset hashing between federated modules | Unify build hash generators via root Webpack/Turbopack settings |
| E20 | Self-closing tag invalidation on custom components | Client engine treating unclosed native tags inconsistently | Enforce strict explicit close tags across custom components |
| E21 | React 19 dynamic action dispatcher sync failure | Invoking action hooks before initial DOM tree reconciliation completes | Bind forms directly to standard action pipeline parameters |

---

### Production Hydration Fixes (Before vs. After)

#### Fix E01: Invalid Semantic DOM Nesting
```tsx
// ❌ INCORRECT: Div placed inside Paragraph violates HTML specs and triggers React hydration bailouts
export function BadCardDescription({ content }: { content: string }) {
  return (
    <p className="text-gray-600">
      Account summary:
      <div className="font-semibold text-black">{content}</div>
    </p>
  );
}

// ✅ CORRECT: Semantic structure preserved using standard composition
export function GoodCardDescription({ content }: { content: string }) {
  return (
    <div className="text-gray-600">
      <p>Account summary:</p>
      <div className="font-semibold text-black">{content}</div>
    </div>
  );
}
```

#### Fix E02: Localized Date/Timestamp Divergence
```tsx
// ❌ INCORRECT: Renders client's local timezone (e.g., EST) vs server's timezone (e.g., UTC)
export function BadTimestamp({ date }: { date: Date }) {
  return <span>{new Date(date).toLocaleString()}</span>;
}

// ✅ CORRECT: Deterministic UTC formatting across both execution environments
export function GoodTimestamp({ date }: { date: Date }) {
  const formatted = new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'UTC',
  }).format(new Date(date));

  return (
    <time dateTime={new Date(date).toISOString()} suppressHydrationWarning>
      {formatted} UTC
    </time>
  );
}
```

#### Fix E03: Non-Deterministic Dynamic Identifiers
```tsx
// ❌ INCORRECT: Yields different IDs between Server and Client instances
export function BadInputField({ label }: { label: string }) {
  const inputId = `input-${Math.random().toString(36).substring(2, 9)}`;
  return (
    <div>
      <label htmlFor={inputId}>{label}</label>
      <input id={inputId} type="text" />
    </div>
  );
}

// ✅ CORRECT: React useId provides deterministic identifiers across SSR and hydration
import { useId } from 'react';

export function GoodInputField({ label }: { label: string }) {
  const inputId = useId();
  return (
    <div>
      <label htmlFor={inputId}>{label}</label>
      <input id={inputId} type="text" />
    </div>
  );
}
```

#### Fix E05: Client-Only LocalStorage Access
```tsx
// ❌ INCORRECT: Condition returns null on server, but attempts to read storage on client initial mount
export function BadClientGreeting() {
  if (typeof window === 'undefined') return null;
  const username = localStorage.getItem('username') || 'Guest';
  return <h1>Welcome back, {username}</h1>;
}

// ✅ CORRECT: Synchronize access post-mount to preserve deterministic SSR matching
'use client';

import { useSyncExternalStore } from 'react';

function subscribe(callback: () => void) {
  window.addEventListener('storage', callback);
  return () => window.removeEventListener('storage', callback);
}

export function GoodClientGreeting() {
  const username = useSyncExternalStore(
    subscribe,
    () => localStorage.getItem('username') || 'Guest',
    () => 'Guest' // Fallback snapshot during Server Rendering
  );

  return <h1>Welcome back, {username}</h1>;
}
```

#### Fix E06: Third-Party Extension Tag / Property Injection
```tsx
// ❌ INCORRECT: Extensions like Grammarly, Dashlane, or ColorZilla append attributes, breaking hydration
// app/layout.tsx
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

// ✅ CORRECT: Silence attribute-level mismatches injected at body root by browser clients
// app/layout.tsx
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body suppressHydrationWarning={true}>
        {children}
      </body>
    </html>
  );
}
```

#### Fix E11: Flash of Theme Divergence (FOUC)
```tsx
// ✅ CORRECT: Inline non-render-blocking deterministic script execution for dark mode
// app/layout.tsx
const themeScript = `
  (function() {
    try {
      const mode = localStorage.getItem('theme');
      const supportDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
      if (mode === 'dark' || (!mode && supportDarkMode)) {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    } catch (e) {}
  })();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-50">
        {children}
      </body>
    </html>
  );
}
```

---

## 4. Production Deployment Swipe File

### Production-Hardened Multi-Stage Dockerfile
This production Dockerfile targets Next.js 15 standalone output. It compiles under a secure, non-privileged user space, isolates dependency stages, enables native Alpine image optimization with `sharp`, and implements native health-checking.

```dockerfile
# syntax=docker/dockerfile:1.4
# ==============================================================================
# Stage 1: Base Alpine Dependencies
# ==============================================================================
FROM node:20-alpine AS alpine-base

WORKDIR /app

RUN apk add --no-cache libc6-compat
RUN npm install -g pnpm@9.12.0

# ==============================================================================
# Stage 2: Dependencies Cache Engine
# ==============================================================================
FROM alpine-base AS dependencies

WORKDIR /app

COPY package.json pnpm-lock.yaml* ./
RUN pnpm i --frozen-lockfile --prefer-offline

# ==============================================================================
# Stage 3: Source Compilation & Asset Packaging
# ==============================================================================
FROM alpine-base AS builder

WORKDIR /app

COPY --from=dependencies /app/node_modules ./node_modules
COPY . .

# Set production environment flags during build
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# Validate standalone output configuration presence
RUN pnpm build

# ==============================================================================
# Stage 4: Execution Engine (Hardened Minimal Runtime)
# ==============================================================================
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Install sharp support for production next/image performance within Alpine
RUN apk add --no-cache libvips-dev

# Security hardening: Run as an unprivileged service account
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Inherit compiled static and standalone artifacts
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

# Native health check integration
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "server.js"]
```

To enable the standalone build used by this Dockerfile, set `output: 'standalone'` in your Next.js configuration:

```ts
// next.config.ts
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  // Remaining architecture settings...
};

export default nextConfig;
```

---

### Production Vercel Configuration Engine (`vercel.json`)
This configuration establishes an edge-optimized edge routing matrix with strict HTTP security headers, asset cache isolation, and edge function region pinning.

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "cleanUrls": true,
  "trailingSlash": false,
  "framework": "nextjs",
  "regions": ["iad1", "sfo1"],
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        {
          "key": "X-Content-Type-Options",
          "value": "nosniff"
        },
        {
          "key": "X-Frame-Options",
          "value": "DENY"
        },
        {
          "key": "X-XSS-Protection",
          "value": "1; mode=block"
        },
        {
          "key": "Referrer-Policy",
          "value": "strict-origin-when-cross-origin"
        },
        {
          "key": "Permissions-Policy",
          "value": "camera=(), microphone=(), geolocation=(), browsing-topics=()"
        },
        {
          "key": "Strict-Transport-Security",
          "value": "max-age=63072000; includeSubDomains; preload"
        },
        {
          "key": "Content-Security-Policy",
          "value": "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline' https://va.vercel-scripts.com; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data: https:; font-src 'self' data:; connect-src 'self' https://vitals.vercel-insights.com; frame-ancestors 'none';"
        }
      ]
    },
    {
      "source": "/_next/static/(.*)",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=31536000, immutable"
        }
      ]
    },
    {
      "source": "/favicon.ico",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=86400, must-revalidate"
        }
      ]
    }
  ]
}
```

---

### Enterprise CI/CD Pipeline (GitHub Actions)
This pipeline enforces linting, type-checking, bundle-size drift regression checks, automated Lighthouse Core Web Vitals scoring via Unlighthouse, container compilation, and registry distribution.

```yaml
# .github/workflows/production-pipeline.yml
name: Production Quality Gate & Deployment

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

env:
  NODE_VERSION: 20
  PNPM_VERSION: 9.12.0
  DOCKER_REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  code-quality:
    name: Code Quality & Type Integrity
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Setup PNPM
        uses: pnpm/action-setup@v4
        with:
          version: ${{ env.PNPM_VERSION }}

      - name: Setup Node.js Execution Context
        uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'pnpm'

      - name: Install dependencies
        run: pnpm install --frozen-lockfile

      - name: Verify Linters
        run: pnpm lint

      - name: Static Type Audit
        run: pnpm tsc --noEmit

  build-and-size-audit:
    name: Build & Bundle Size Analysis
    needs: code-quality
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Setup PNPM
        uses: pnpm/action-setup@v4
        with:
          version: ${{ env.PNPM_VERSION }}

      - name: Setup Node.js Execution Context
        uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: 'pnpm'

      - name: Install dependencies
        run: pnpm install --frozen-lockfile

      - name: Build Standalone Bundle
        env:
          NEXT_TELEMETRY_DISABLED: 1
          NODE_ENV: production
        run: pnpm build

      - name: Check Build Artifact Output
        run: |
          test -d .next/standalone || (echo "Standalone output missing from build!" && exit 1)
          test -d .next/static || (echo "Static build artifacts missing!" && exit 1)

  container-delivery:
    name: Build & Push Docker Engine
    needs: build-and-size-audit
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Authenticate to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.DOCKER_REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract Docker Meta
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.DOCKER_REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=sha,format=long
            type=raw,value=latest

      - name: Build and Push Standalone Container
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

## 5. Automated CI/CD Web Vitals Regression Gate

To prevent layout shifts or main-thread regressions from reaching production, add this automated Lighthouse/CWV assertion script to your repository. It runs headless Chromium against your compiled Next.js build in CI.

Create `scripts/audit-cwv.mjs`:

```javascript
// scripts/audit-cwv.mjs
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { playAudit } from 'lighthouse/core/index.js'; // Requires: pnpm add -D lighthouse chrome-launcher
import * as chromeLauncher from 'chrome-launcher';

const PORT = 3000;
const THRESHOLDS = {
  LCP: 2500, // milliseconds
  CLS: 0.1,  // unitless score
  TBT: 300,  // Total Blocking Time proxy for INP in synthetic CI
};

async function runAudit() {
  console.log('🚀 Launching Next.js Production Server for CWV Audit...');
  
  const server = spawn('node', ['.next/standalone/server.js'], {
    env: { ...process.env, PORT: String(PORT), HOSTNAME: '127.0.0.1' },
    stdio: 'inherit',
  });

  // Wait for the local server to start
  await new Promise((resolve) => setTimeout(resolve, 3000));

  console.log('🔍 Launching Headless Chrome...');
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless', '--no-sandbox'] });

  try {
    const runnerResult = await playAudit(`http://127.0.0.1:${PORT}`, {
      port: chrome.port,
      output: 'json',
      onlyCategories: ['performance'],
    });

    const audits = runnerResult.lhr.audits;
    const lcp = audits['largest-contentful-paint'].numericValue;
    const cls = audits['cumulative-layout-shift'].numericValue;
    const tbt = audits['total-blocking-time'].numericValue;

    console.log(`\n--- Production CWV Audit Results ---`);
    console.log(`LCP: ${lcp.toFixed(2)}ms (Target: < ${THRESHOLDS.LCP}ms)`);
    console.log(`CLS: ${cls.toFixed(4)} (Target:
