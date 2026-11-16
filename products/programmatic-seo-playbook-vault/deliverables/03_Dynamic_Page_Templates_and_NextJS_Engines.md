# Module 3: Dynamic Page Component Templates & Rendering Patterns

Building programmatic SEO pages at scale requires an architecture that balances three conflicting forces: zero-latency edge delivery for end users, minimal static build times across millions of URLs, and absolute programmatic uniqueness to satisfy search engine quality raters. 

This module provides the complete, production-grade codebase for multi-framework dynamic rendering, edge-generated OpenGraph assets, unified Schema.org graph generation, deterministic link matrix calculation, and automated pre-render content quality gating.

---

## 1. Rendering Architecture Matrix & Next.js 15 App Router Engine

### 1.1 Rendering Architecture Selection Matrix

Choosing the wrong rendering pattern causes catastrophic build failures at scale (e.g., attempting to generate 250,000 pages during an SSG step will exhaust memory and timeout Vercel/Cloudflare build pipelines). Use this decision framework:

| Dimension | Next.js 15 App Router (ISR) | Astro 4+ Content Engine | Remix / React Router v7 (SSR) |
| :--- | :--- | :--- | :--- |
| **Ideal Scale** | 10,000 – 1,000,000+ pages | 1,000 – 50,000 pages | 50,000 – 5,000,000+ pages |
| **Build-Time Impact** | Zero (generate top 1% at build, remainder on-demand) | High (requires full static HTML synthesis) | Zero (pure just-in-time runtime execution) |
| **Edge Cache Time** | Configurable via `stale-while-revalidate` | Permanent until next deployment | Edge Cache-Control headers |
| **TTFB (First Request)** | ~800ms (uncached) / ~35ms (cached) | ~30ms (always globally pre-cached) | ~120ms (Edge compute + Database I/O) |
| **Hydration Cost** | Partial via React Server Components (RSC) | Zero by default (Astro Islands) | Full page hydration by default |
| **Database Load** | Low (cached at data cache + CDN layers) | Zero at runtime (DB accessed only at build) | High (requires Read Replicas or Edge Caching) |
| **Recommended Use Case** | Directory engines, comparisons, localized programmatic hubs | Documentation, content-heavy blogs, glossary engines | High-volatility pricing data, dynamic inventory |

---

### 1.2 Production Next.js 15 Dynamic Template (`/app/[category]/[slug]/page.tsx`)

This template implements Next.js 15 Server Components, Incremental Static Regeneration (ISR), automated metadata resolution, and data layer fallback handling with zero client-side JavaScript overhead.

```typescript
import { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { Suspense } from 'react';

// Explicit revalidation window: 24 hours in seconds
export const revalidate = 86400;
export const dynamicParams = true;

interface PageProps {
  params: Promise<{
    category: string;
    slug: string;
  }>;
}

interface DatasetItem {
  id: string;
  category: string;
  slug: string;
  name: string;
  metaTitle: string;
  metaDescription: string;
  primaryMetric: {
    label: string;
    value: string;
  };
  comparisonData: Array<{
    feature: string;
    supported: boolean;
    notes: string;
  }>;
  faqs: Array<{
    question: string;
    answer: string;
  }>;
  relatedSlugs: string[];
}

// Simulated data access layer - replace with database client (e.g., Prisma, Kysely, Supabase)
async function getDatasetItem(category: string, slug: string): Promise<DatasetItem | null> {
  const res = await fetch(`https://api.internal.domain/v1/entities/${category}/${slug}`, {
    next: { tags: [`entity:${category}:${slug}`] },
  });

  if (!res.ok) {
    if (res.status === 404) return null;
    throw new Error(`Failed to fetch entity: ${res.statusText}`);
  }

  return res.json();
}

// Generate static params for the top 500 highest-priority landing pages at build time
export async function generateStaticParams() {
  const topEntities = await fetch('https://api.internal.domain/v1/entities/top-tier?limit=500')
    .then((res) => res.json())
    .catch(() => []);

  return topEntities.map((item: { category: string; slug: string }) => ({
    category: item.category,
    slug: item.slug,
  }));
}

// Dynamic SEO Metadata Generation
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { category, slug } = await params;
  const data = await getDatasetItem(category, slug);

  if (!data) {
    return {
      title: 'Item Not Found | Platform Engine',
      robots: { index: false, follow: false },
    };
  }

  const canonicalUrl = `https://www.domain.com/${data.category}/${data.slug}`;

  return {
    title: `${data.metaTitle} | Exhaustive Benchmark`,
    description: data.metaDescription,
    alternates: {
      canonical: canonicalUrl,
    },
    openGraph: {
      title: data.metaTitle,
      description: data.metaDescription,
      url: canonicalUrl,
      type: 'website',
      images: [
        {
          url: `https://www.domain.com/og/${data.category}/${data.slug}.png`,
          width: 1200,
          height: 630,
          alt: data.name,
        },
      ],
    },
    twitter: {
      card: 'summary_large_image',
      title: data.metaTitle,
      description: data.metaDescription,
      images: [`https://www.domain.com/og/${data.category}/${data.slug}.png`],
    },
    robots: {
      index: true,
      follow: true,
      googleBot: {
        index: true,
        follow: true,
        'max-video-preview': -1,
        'max-image-preview': 'large',
        'max-snippet': -1,
      },
    },
  };
}

export default async function ProgrammaticPage({ params }: PageProps) {
  const { category, slug } = await params;
  const data = await getDatasetItem(category, slug);

  if (!data) {
    notFound();
  }

  return (
    <article className="max-w-4xl mx-auto px-4 py-8">
      {/* Breadcrumb Navigation Hierarchy */}
      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-gray-500">
        <ol className="flex items-center space-x-2">
          <li><a href="/" className="hover:underline">Home</a></li>
          <li><span>/</span></li>
          <li><a href={`/${data.category}`} className="hover:underline capitalize">{data.category}</a></li>
          <li><span>/</span></li>
          <li className="text-gray-900 font-semibold" aria-current="page">{data.name}</li>
        </ol>
      </nav>

      <header className="border-b border-gray-200 pb-8 mb-8">
        <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
          {data.name}
        </h1>
        <div className="mt-4 flex items-center gap-4">
          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-100 text-blue-800">
            {data.primaryMetric.label}: {data.primaryMetric.value}
          </span>
          <span className="text-sm text-gray-500">Verified System Data</span>
        </div>
      </header>

      {/* Primary Data Feature Breakdown */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-gray-900 mb-4">Core Feature Specifications</h2>
        <div className="overflow-x-auto border rounded-lg">
          <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-6 py-3 font-semibold text-gray-700">Feature</th>
                <th scope="col" className="px-6 py-3 font-semibold text-gray-700">Status</th>
                <th scope="col" className="px-6 py-3 font-semibold text-gray-700">Verification Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {data.comparisonData.map((row, idx) => (
                <tr key={idx}>
                  <td className="px-6 py-4 font-medium text-gray-900">{row.feature}</td>
                  <td className="px-6 py-4">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${row.supported ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                      {row.supported ? 'Supported' : 'Unsupported'}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-500">{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Programmatic FAQ Component */}
      <section className="mb-12">
        <h2 className="text-2xl font-bold text-gray-900 mb-6">Frequently Asked Questions</h2>
        <dl className="space-y-6">
          {data.faqs.map((faq, idx) => (
            <div key={idx} className="bg-gray-50 p-6 rounded-lg">
              <dt className="text-lg font-semibold text-gray-900">{faq.question}</dt>
              <dd className="mt-2 text-base text-gray-700 leading-relaxed">{faq.answer}</dd>
            </div>
          ))}
        </dl>
      </section>
    </article>
  );
}
```

---

## 2. Dynamic OpenGraph Image Generation

Programmatic pages without custom OpenGraph (OG) images suffer up to a 60% reduction in click-through rates across social platforms and messaging apps (Slack, Twitter, LinkedIn). The Next.js Edge Runtime with `@vercel/og` renders these images dynamically with sub-50ms execution times.

### 2.1 Edge Image Route Handler (`/app/og/[category]/[slug]/route.tsx`)

```typescript
import { ImageResponse } from 'next/og';
import { NextRequest } from 'next/server';

export const runtime = 'edge';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ category: string; slug: string }> }
) {
  try {
    const { category, slug } = await context.params;

    // Fetch entity data directly at edge with lightweight payload
    const res = await fetch(`https://api.internal.domain/v1/entities/${category}/${slug}/preview`);
    if (!res.ok) {
      return new Response('Entity Not Found', { status: 404 });
    }
    const item = await res.json();

    return new ImageResponse(
      (
        <div
          style={{
            height: '100%',
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            backgroundColor: '#0F172A',
            padding: '60px 80px',
            fontFamily: 'sans-serif',
          }}
        >
          {/* Top Brand & Category Pill */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  backgroundColor: '#38BDF8',
                  borderRadius: '6px',
                }}
              />
              <span style={{ fontSize: '24px', fontWeight: 800, color: '#F8FAFC', letterSpacing: '-0.5px' }}>
                INDEXSCALE ENGINE
              </span>
            </div>
            <div
              style={{
                display: 'flex',
                padding: '8px 20px',
                backgroundColor: '#1E293B',
                borderRadius: '9999px',
                border: '1px solid #334155',
                color: '#38BDF8',
                fontSize: '18px',
                fontWeight: 600,
                textTransform: 'uppercase',
              }}
            >
              {category}
            </div>
          </div>

          {/* Central Subject Header */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <span style={{ fontSize: '20px', color: '#94A3B8', fontWeight: 500 }}>
              Benchmarked Analysis & Performance
            </span>
            <h1
              style={{
                fontSize: '64px',
                fontWeight: 900,
                color: '#FFFFFF',
                lineHeight: 1.1,
                letterSpacing: '-1.5px',
                margin: 0,
              }}
            >
              {item.name}
            </h1>
          </div>

          {/* Bottom Metric Panel */}
          <div
            style={{
              display: 'flex',
              backgroundColor: '#1E293B',
              borderRadius: '16px',
              padding: '24px 32px',
              border: '1px solid #334155',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '14px', color: '#94A3B8', textTransform: 'uppercase' }}>
                Primary Score
              </span>
              <span style={{ fontSize: '32px', fontWeight: 800, color: '#38BDF8' }}>
                {item.score || '99.4/100'}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '14px', color: '#94A3B8', textTransform: 'uppercase' }}>
                Market Status
              </span>
              <span style={{ fontSize: '32px', fontWeight: 800, color: '#F8FAFC' }}>
                {item.status || 'Verified Active'}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '14px', color: '#94A3B8', textTransform: 'uppercase' }}>
                Updated
              </span>
              <span style={{ fontSize: '32px', fontWeight: 800, color: '#22C55E' }}>
                {new Date().toISOString().split('T')[0]}
              </span>
            </div>
          </div>
        </div>
      ),
      {
        width: 1200,
        height: 630,
      }
    );
  } catch (error) {
    return new Response(`OG Generator Error: ${error instanceof Error ? error.message : 'Unknown'}`, {
      status: 500,
    });
  }
}
```

---

## 3. Schema.org JSON-LD Structured Graph Engine

Search engines rely on unified Schema graphs rather than disjointed microdata tags. The following TypeScript builder generates a clean JSON-LD object connecting `BreadcrumbList`, `SoftwareApplication` (or `Product`), and `FAQPage` nodes within a single graph.

```typescript
// /lib/seo/schemaEngine.ts

export interface BreadcrumbNode {
  name: string;
  url: string;
}

export interface FAQItem {
  question: string;
  answer: string;
}

export interface SoftwareSchemaInput {
  name: string;
  description: string;
  url: string;
  category: string;
  operatingSystem?: string;
  price?: string;
  currency?: string;
  ratingValue: number;
  reviewCount: number;
  breadcrumbs: BreadcrumbNode[];
  faqs: FAQItem[];
}

export function generateStructuredDataGraph(input: SoftwareSchemaInput) {
  return {
    '@context': 'https://schema.org',
    '@graph': [
      // 1. Breadcrumb List Structure
      {
        '@type': 'BreadcrumbList',
        '@id': `${input.url}#breadcrumb`,
        'itemListElement': input.breadcrumbs.map((crumb, index) => ({
          '@type': 'ListItem',
          'position': index + 1,
          'name': crumb.name,
          'item': crumb.url,
        })),
      },

      // 2. Main Software Entity
      {
        '@type': 'SoftwareApplication',
        '@id': `${input.url}#software`,
        'name': input.name,
        'description': input.description,
        'applicationCategory': input.category,
        'operatingSystem': input.operatingSystem || 'Web Platform, iOS, Android',
        'url': input.url,
        ...(input.price && {
          'offers': {
            '@type': 'Offer',
            'price': input.price,
            'priceCurrency': input.currency || 'USD',
            'availability': 'https://schema.org/InStock',
          },
        }),
        'aggregateRating': {
          '@type': 'AggregateRating',
          'ratingValue': input.ratingValue.toFixed(1),
          'ratingCount': input.reviewCount,
          'bestRating': '5',
          'worstRating': '1',
        },
      },

      // 3. FAQPage Structure
      {
        '@type': 'FAQPage',
        '@id': `${input.url}#faq`,
        'isPartOf': { '@id': input.url },
        'mainEntity': input.faqs.map((faq) => ({
          '@type': 'Question',
          'name': faq.question,
          'acceptedAnswer': {
            '@type': 'Answer',
            'text': faq.answer,
          },
        })),
      },
    ],
  };
}
```

### 3.1 Implementation inside Component

Inject the graph inside the dynamic page component:

```tsx
// Inside your /app/[category]/[slug]/page.tsx
import { generateStructuredDataGraph } from '@/lib/seo/schemaEngine';

export default async function ProgrammaticPage({ params }: PageProps) {
  const { category, slug } = await params;
  const data = await getDatasetItem(category, slug);
  if (!data) notFound();

  const jsonLd = generateStructuredDataGraph({
    name: data.name,
    description: data.metaDescription,
    url: `https://www.domain.com/${data.category}/${data.slug}`,
    category: data.category,
    ratingValue: 4.8,
    reviewCount: 1240,
    breadcrumbs: [
      { name: 'Home', url: 'https://www.domain.com' },
      { name: data.category, url: `https://www.domain.com/${data.category}` },
      { name: data.name, url: `https://www.domain.com/${data.category}/${data.slug}` },
    ],
    faqs: data.faqs,
  });

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {/* Visual Component Render */}
    </>
  );
}
```

---

## 4. Deterministic Internal Linking Matrix Engine

Programmatic engines must avoid flat taxonomies where pages only link back to the root category. This produces orphan pages and dilutes PageRank distribution. 

The deterministic linking matrix below calculates cross-links mathematically using entity taxonomies, category-level relationships, and a hash distribution algorithm. This ensures:
1. Every page receives a bounded minimum of internal links (e.g., exactly 6 related nodes).
2. The linking graph is **deterministic**: identical builds yield identical internal links without recalculating massive database queries.

```typescript
// /lib/seo/linkingMatrix.ts
import { createHash } from 'crypto';

export interface EntityRecord {
  id: string;
  slug: string;
  category: string;
  tags: string[];
  tier: number; // Tier 1: Highest priority, Tier 3: Lowest
}

export interface LinkNode {
  anchorText: string;
  href: string;
  relationship: 'sibling' | 'parent-hub' | 'cross-category' | 'tier-escalation';
}

/**
 * Calculates a deterministic set of internal links for any given entity.
 */
export function buildDeterministicLinkMatrix(
  currentEntity: EntityRecord,
  allEntities: EntityRecord[],
  targetLinkCount: number = 6
): LinkNode[] {
  const links: LinkNode[] = [];

  // 1. Mandatory Parent Hub Link
  links.push({
    anchorText: `All ${currentEntity.category.toUpperCase()} Benchmarks`,
    href: `/${currentEntity.category}`,
    relationship: 'parent-hub',
  });

  // 2. Strict Filter: Remove the current entity from candidate pool
  const candidates = allEntities.filter((e) => e.id !== currentEntity.id);

  // 3. Sibling Links (Same Category & Shared Tags)
  const categoryCandidates = candidates.filter((e) => e.category === currentEntity.category);

  // Score candidate relevance
  const scoredCandidates = categoryCandidates.map((candidate) => {
    let score = 0;
    // Intersect tags
    const sharedTags = candidate.tags.filter((tag) => currentEntity.tags.includes(tag));
    score += sharedTags.length * 3;

    // Favor higher tiers
    if (candidate.tier === 1) score += 2;
    if (candidate.tier === 2) score += 1;

    return { candidate, score };
  });

  // Sort descending by score
  scoredCandidates.sort((a, b) => b.score - a.score);

  // Take top candidates
  for (const item of scoredCandidates) {
    if (links.length >= targetLinkCount - 1) break;
    links.push({
      anchorText: `${item.candidate.slug.replace(/-/g, ' ')} Review & Specs`,
      href: `/${item.candidate.category}/${item.candidate.slug}`,
      relationship: 'sibling',
    });
  }

  // 4. Fallback: Deterministic Cross-Category Linking via Hash
  // Ensures isolated categories still connect to the wider site graph
  if (links.length < targetLinkCount) {
    const remainingSlots = targetLinkCount - links.length;
    const crossCategoryCandidates = candidates.filter((e) => e.category !== currentEntity.category);

    // Compute consistent hash offset based on slug string
    const hash = createHash('md5').update(currentEntity.slug).digest('hex');
    const offset = parseInt(hash.substring(0, 8), 16) % (crossCategoryCandidates.length || 1);

    for (let i = 0; i < remainingSlots; i++) {
      const selectedIndex = (offset + i) % crossCategoryCandidates.length;
      const fallbackEntity = crossCategoryCandidates[selectedIndex];

      if (fallbackEntity) {
        links.push({
          anchorText: `${fallbackEntity.slug.replace(/-/g, ' ')} Overview`,
          href: `/${fallbackEntity.category}/${fallbackEntity.slug}`,
          relationship: 'cross-category',
        });
      }
    }
  }

  return links;
}
```

### 4.1 Internal Linking Matrix Visual Layout

```
                 [ ROOT / HOME ]
                  /           \
                 v             v
       [ Category Hub A ]   [ Category Hub B ]
          /     |     \        /     |     \
         v      v      v      v      v      v
      [Page 1]<--->[Page 2] [Page 3]<--->[Page 4]
         ^                    ^
         |                    |
         +---(Cross-Link)-----+
       (Via Deterministic Hash Algorithm)
```

---

## 5. Automated Pre-Render Page Quality Score Validator

To prevent Google's "Helpful Content System" and quality algorithms from de-indexing your programmatic pages, run pages through a quality validator prior to publishing or rendering.

This script executes either:
1. In a pre-build validation CLI tool.
2. In the Next.js page pipeline: If the quality score falls below 80/100, the page dynamically injects `noindex, follow` or throws a build error.

```typescript
// /lib/seo/qualityValidator.ts

export interface PagePayload {
  title: string;
  metaDescription: string;
  structuredDataCount: number;
  rawTextContent: string;
  boilerplateTextContent: string;
  dataPointsRendered: number;
  internalLinkCount: number;
}

export interface ValidationResult {
  score: number;
  passed: boolean;
  issues: string[];
  shouldNoIndex: boolean;
}

export function validateProgrammaticQuality(payload: PagePayload): ValidationResult {
  const issues: string[] = [];
  let score = 100;

  // 1. Uniqueness / Dynamic Content Ratio Check
  const totalLength = payload.rawTextContent.length;
  const boilerplateLength = payload.boilerplateTextContent.length;

  if (totalLength === 0) {
    return { score: 0, passed: false, issues: ['Payload text is completely empty.'], shouldNoIndex: true };
  }

  const uniqueRatio = (totalLength - boilerplateLength) / totalLength;
  if (uniqueRatio < 0.40) {
    const penalty = 30;
    score -= penalty;
    issues.push(`Thin unique content: Only ${(uniqueRatio * 100).toFixed(1)}% unique (Minimum required: 40%).`);
  }

  // 2. Minimum Substantive Word Count (excluding boilerplate layout)
  const words = payload.rawTextContent
    .replace(payload.boilerplateTextContent, '')
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0);

  if (words.length < 250) {
    const penalty = 25;
    score -= penalty;
    issues.push(`Substantive word count is critically low: ${words.length} words (Minimum required: 250 words).`);
  }

  // 3. Structured Data Verification
  if (payload.structuredDataCount < 2) {
    score -= 10;
    issues.push(`Missing schema density: Found ${payload.structuredDataCount} graphs, expected >= 2.`);
  }

  // 4. Data Point Density (Ensures page isn't just an empty wrapper)
  if (payload.dataPointsRendered < 8) {
    score -= 20;
    issues.push(`Low variable density: Only ${payload.dataPointsRendered} attributes rendered (Minimum required: 8).`);
  }

  // 5. Internal Link Count Check
  if (payload.internalLinkCount < 4) {
    score -= 15;
    issues.push(`Poor PageRank distribution: Contains ${payload.internalLinkCount} internal links (Minimum required: 4).`);
  }

  // Determine final threshold routing
  const passed = score >= 80;
  const shouldNoIndex = score < 70;

  return {
    score: Math.max(0, score),
    passed,
    issues,
    shouldNoIndex,
  };
}
```

### 5.1 Quality Gating CLI Script (`/scripts/validate-database.ts`)

Run this via `npm run test:seo` to audit your database before generating static pages or populating edge caches.

```typescript
import { validateProgrammaticQuality, PagePayload } from '../lib/seo/qualityValidator';

// Simulated batch query from target database
async function runPreRenderAudit() {
  console.log('--- Starting Programmatic Quality Verification Audit ---');

  const simulatedPages: Array<{ slug: string; payload: PagePayload }> = [
    {
      slug: 'crm-solutions/salesforce-enterprise',
      payload: {
        title: 'Salesforce Enterprise In-Depth Benchmark & Capabilities',
        metaDescription: 'Detailed technical analysis of Salesforce Enterprise editions, pricing components, and schemas.',
        structuredDataCount: 3,
        rawTextContent: 'Salesforce Enterprise Benchmark Analysis '.repeat(50),
        boilerplateTextContent: 'Salesforce Enterprise Benchmark Analysis '.repeat(10),
        dataPointsRendered: 24,
        internalLinkCount: 8,
      },
    },
    {
      slug: 'crm-solutions/obsolete-tool-1999',
      payload: {
        title: 'Tool 1999 Summary',
        metaDescription: 'Short description.',
        structuredDataCount: 0,
        rawTextContent: 'This is a description of an obsolete tool.',
        boilerplateTextContent: 'This is a description of an obsolete tool.',
        dataPointsRendered: 2,
        internalLinkCount: 1,
      },
    },
  ];

  let passedPages = 0;
  let flaggedPages = 0;

  for (const page of simulatedPages) {
    const result = validateProgrammaticQuality(page.payload);

    if (!result.passed) {
      flaggedPages++;
      console.warn(`\x1b[33m[FLAGGED]\x1b[0m ${page.slug} (Score: ${result.score}/100)`);
      result.issues.forEach((issue) => console.warn(`   └── ${issue}`));
      if (result.shouldNoIndex) {
        console.error(`   \x1b[31m└── CRITICAL: Page fails structural threshold. Route will append 'noindex'.\x1b[0m`);
      }
    } else {
      passedPages++;
      console.log(`\x1b[32m[PASSED]\x1b[0m ${page.slug} (Score: ${result.score}/100)`);
    }
  }

  console.log('\n--- Audit Complete ---');
  console.log(`Total Scanned: ${simulatedPages.length}`);
  console.log(`Passed: ${passedPages}`);
  console.log(`Flagged: ${flaggedPages}`);

  if (flaggedPages > 0) {
    process.exit(1);
  }
}

runPreRenderAudit();
```

---

## 6. Implementation
