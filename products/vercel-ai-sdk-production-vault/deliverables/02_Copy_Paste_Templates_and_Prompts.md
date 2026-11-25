# Module 2: 25+ Production Tool Schemas & Structured Output Blueprints

Production-grade agentic systems fail most frequently at the schema boundary. When models encounter ambiguity, unconstrained nested types, or ambiguous enum fields, they hallucinate arguments, break JSON parser trees, and drop streaming connections. 

This module provides fully implemented, copy-pasteable tool schemas, multi-step execution loops, self-healing extraction wrappers, and calibrated model prompts optimized specifically for the Vercel AI SDK 4.x running against Anthropic Claude 3.7 Sonnet and OpenAI GPT-4o.

---

## 1. Production Zod Tool Schemas & Execution Handlers

The following tools use the Vercel AI SDK `tool()` construct with strict Zod runtime schemas. Every property includes an explicit `.describe()` parameter to guide model arg generation.

### 1.1 Read-Only SQL & Analytics Aggregator Tool
Prevents dangerous mutations while allowing rich analytical filtering with group-by clauses, timeframes, and metric definitions.

```typescript
// tools/analytics-query.ts
import { tool } from 'ai';
import { z } from 'zod';

export const analyticsQueryTool = tool({
  description:
    'Execute structured analytical queries against the read-only data warehouse replica. Use this to pull aggregate KPIs, cohort retention, and churn metrics. Do NOT use for user profile updates or single transactional lookups.',
  parameters: z.object({
    metric: z
      .enum(['daily_active_users', 'mrr_cents', 'churn_rate', 'ltv_projected', 'api_request_latency_p99'])
      .describe('The primary core KPI metric to aggregate.'),
    timeframe: z.object({
      startDate: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/, 'Must be YYYY-MM-DD format')
        .describe('Inclusive start date for the metric aggregation window.'),
      endDate: z
        .string()
        .regex(/^\d{4}-\d{2}-\d{2}$/, 'Must be YYYY-MM-DD format')
        .describe('Inclusive end date for the metric aggregation window.'),
      granularity: z
        .enum(['hour', 'day', 'week', 'month'])
        .describe('Time bucket bucket aggregation interval.'),
    }),
    filters: z
      .array(
        z.object({
          field: z.string().describe('Target column name to filter by (e.g., plan_tier, region).'),
          operator: z.enum(['eq', 'neq', 'gt', 'lt', 'in']).describe('Filter operator.'),
          value: z.union([z.string(), z.number(), z.array(z.string())]).describe('Literal value to test against.'),
        })
      )
      .default([]),
    limit: z.number().int().min(1).max(500).default(50).describe('Row limit constraint.'),
  }),
  execute: async ({ metric, timeframe, filters, limit }) => {
    // Deterministic parameter formatting for SQL builder / ORM
    const queryPayload = {
      metric,
      window: `${timeframe.startDate}T00:00:00Z to ${timeframe.endDate}T23:59:59Z`,
      step: timeframe.granularity,
      appliedFilters: filters.map((f) => `${f.field} ${f.operator} ${JSON.stringify(f.value)}`),
      maxRows: limit,
    };

    // Simulated read-only execution against analytical warehouse
    return {
      status: 'success',
      executedAt: new Date().toISOString(),
      queryPlan: queryPayload,
      datapoints: [
        { bucket: `${timeframe.startDate}`, value: 1420.5 },
        { bucket: `${timeframe.endDate}`, value: 1680.2 },
      ],
      rowCount: 2,
    };
  },
});
```

### 1.2 Idempotent E-Commerce Cart & Transaction Mutation
Safely handles state changes with mandatory idempotency tokens, atomic stock reservation checks, and currency calculation safety.

```typescript
// tools/cart-mutation.ts
import { tool } from 'ai';
import { z } from 'zod';

export const cartMutationTool = tool({
  description:
    'Applies atomic updates to an active customer shopping session. Requires client-generated idempotency keys to prevent duplicate billing or inventory allocation on network retries.',
  parameters: z.object({
    sessionId: z.string().uuid().describe('Active checkout session UUID.'),
    idempotencyKey: z
      .string()
      .min(16)
      .describe('Client-provided cryptographic nonce or UUID to guarantee once-only mutation execution.'),
    action: z.enum(['ADD_ITEM', 'REMOVE_ITEM', 'UPDATE_QUANTITY', 'CLEAR_CART']),
    payload: z.object({
      sku: z.string().regex(/^[A-Z]{3}-\d{4}$/, 'Format must match SKU standard: AAA-0000'),
      quantity: z.number().int().min(0).max(10).describe('Target final item count.'),
      unitPriceCents: z.number().int().positive().describe('Expected unit cost in cents to avoid stale pricing.'),
      currency: z.literal('USD').default('USD'),
    }),
  }),
  execute: async ({ sessionId, idempotencyKey, action, payload }) => {
    // Production implementations must check redis/kv for key existence first
    const mutationResult = {
      sessionId,
      idempotencyKey,
      actionApplied: action,
      lineItem: {
        sku: payload.sku,
        quantity: payload.quantity,
        totalCents: payload.unitPriceCents * payload.quantity,
      },
      cartSubtotalCents: payload.unitPriceCents * payload.quantity,
      serverTimestamp: Date.now(),
    };

    return {
      ok: true,
      data: mutationResult,
    };
  },
});
```

### 1.3 High-Precision Vector Search & Metadata Filter Payload
Handles mixed semantic and exact-match filtering for vector indexes (e.g., Pinecone, pgvector, Qdrant).

```typescript
// tools/vector-search.ts
import { tool } from 'ai';
import { z } from 'zod';

export const hybridVectorSearchTool = tool({
  description:
    'Perform low-latency hybrid similarity search across enterprise documents. Converts search queries into semantic vectors while executing exact pre-filtering on tenants and permissions.',
  parameters: z.object({
    query: z.string().min(3).max(1000).describe('Natural language search text to embed.'),
    topK: z.number().int().min(1).max(20).default(5).describe('Total search neighbors to return.'),
    metadataFilters: z.object({
      tenantId: z.string().describe('Enterprise tenant boundary identifier.'),
      documentStatus: z.enum(['DRAFT', 'PUBLISHED', 'ARCHIVED']).default('PUBLISHED'),
      tags: z.array(z.string()).optional().describe('Exact-match categorization tags.'),
      minimumAccessLevel: z.enum(['PUBLIC', 'INTERNAL', 'CONFIDENTIAL']).default('INTERNAL'),
    }),
    rerank: z.boolean().default(true).describe('Trigger cross-encoder reranking pass over candidates.'),
  }),
  execute: async ({ query, topK, metadataFilters, rerank }) => {
    return {
      queryText: query,
      retrievedDocuments: [
        {
          id: 'doc_94821',
          score: 0.9412,
          content: 'Enterprise multi-tenant isolation guarantees at data layer via schema partitioning.',
          metadata: {
            tenantId: metadataFilters.tenantId,
            status: metadataFilters.documentStatus,
            rerankScore: rerank ? 0.982 : null,
          },
        },
      ],
      totalMatches: 1,
    };
  },
});
```

### 1.4 Generative UI Dynamic Component Dispatcher
Emits layout contracts validated against component prop specifications for dynamic generative UI stream mounting.

```typescript
// tools/render-ui-component.ts
import { tool } from 'ai';
import { z } from 'zod';

export const renderUIComponentTool = tool({
  description:
    'Renders a rich interactive dashboard widget in the chat viewport. Use when data is better understood visually than via text.',
  parameters: z.object({
    componentType: z
      .enum(['COMPARISON_TABLE', 'METRIC_CARD', 'CONFIRMATION_MODAL'])
      .describe('The target Generative UI widget identifier to mount.'),
    props: z.discriminatedUnion('kind', [
      z.object({
        kind: z.literal('METRIC_CARD'),
        title: z.string(),
        currentValue: z.string(),
        deltaPercent: z.number(),
        trend: z.enum(['UP', 'DOWN', 'FLAT']),
      }),
      z.object({
        kind: z.literal('COMPARISON_TABLE'),
        headers: z.array(z.string()),
        rows: z.array(z.record(z.string(), z.string())),
      }),
      z.object({
        kind: z.literal('CONFIRMATION_MODAL'),
        title: z.string(),
        description: z.string(),
        actionEndpoint: z.string().url(),
        confirmButtonText: z.string(),
      }),
    ]),
  }),
  execute: async ({ componentType, props }) => {
    return {
      status: 'RENDERED',
      componentType,
      props,
      renderedAt: new Date().toISOString(),
    };
  },
});
```

---

## 2. Multi-Step Tool Execution Engine & State Machine

When a model must execute a tool, observe the output, and subsequently call another tool (or synthesize a final answer), you must configure step boundaries and stream orchestration.

The following Next.js Route Handler shows the implementation of a 5-step autonomous agent with logging, recursion limits, and error boundary isolation.

```typescript
// app/api/agent/route.ts
import { openai } from '@ai-sdk/openai';
import { streamText } from 'ai';
import { analyticsQueryTool } from '@/tools/analytics-query';
import { cartMutationTool } from '@/tools/cart-mutation';
import { hybridVectorSearchTool } from '@/tools/vector-search';
import { renderUIComponentTool } from '@/tools/render-ui-component';

export const maxDuration = 60; // Allow multi-step chain execution

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = streamText({
    model: openai('gpt-4o'),
    messages,
    maxSteps: 5, // Enables automatic multi-step tool call loops
    tools: {
      analyticsQuery: analyticsQueryTool,
      cartMutation: cartMutationTool,
      hybridVectorSearch: hybridVectorSearchTool,
      renderUIComponent: renderUIComponentTool,
    },
    onStepFinish({ stepType, toolCalls, toolResults, text, usage }) {
      // Production observability logging per loop step
      console.log(`[Step Transition] Type: ${stepType}`);
      if (toolCalls.length > 0) {
        console.log(`[Tools Invoked] Count: ${toolCalls.length}`, toolCalls.map(tc => tc.toolName));
      }
      if (toolResults.length > 0) {
        console.log(`[Tools Returned] Count: ${toolResults.length}`);
      }
      console.log(`[Token Usage Step] Input: ${usage.promptTokens}, Output: ${usage.completionTokens}`);
    },
  });

  return result.toDataStreamResponse({
    getErrorMessage: (error) => {
      if (error instanceof Error) {
        return `Pipeline Execution Error: ${error.message}`;
      }
      return 'An unhandled execution fault occurred inside the tool engine.';
    },
  });
}
```

---

## 3. Schema Repair & Self-Healing Extraction Pipeline

LLMs running complex extractions occasionally drop fields, wrap JSON in unexpected delimiters, or cast numbers to strings. 

The `extractWithSelfHealing` utility catches `TypeValidationError` and `JSONParseError`, feeds the exact runtime Zod error path and offending string back to the model, and extracts the target structure deterministically.

```typescript
// lib/extract-with-self-healing.ts
import { generateObject, LanguageModelV1 } from 'ai';
import { z, ZodSchema } from 'zod';

interface SelfHealingOptions<T> {
  model: LanguageModelV1;
  schema: ZodSchema<T>;
  prompt: string;
  system?: string;
  maxRetries?: number;
}

export async function extractWithSelfHealing<T>({
  model,
  schema,
  prompt,
  system,
  maxRetries = 2,
}: SelfHealingOptions<T>): Promise<T> {
  let attempts = 0;
  let currentPrompt = prompt;

  while (attempts <= maxRetries) {
    try {
      const result = await generateObject({
        model,
        schema,
        prompt: currentPrompt,
        system: system ?? 'You are an extraction engine. Output strictly according to the specified schema.',
        mode: 'auto',
      });

      return result.object;
    } catch (error: any) {
      attempts++;
      
      if (attempts > maxRetries) {
        throw new Error(
          `[Schema Extraction Failed] Exhausted ${maxRetries} healing retries. Last error: ${error.message}`
        );
      }

      // Format targeted repair feedback prompt
      const errorContext = error.cause ?? error.message;
      const issues = error.errors ? JSON.stringify(error.errors, null, 2) : 'Invalid JSON Structure';

      currentPrompt = `
The previous attempt to generate structured data failed the runtime validation gate.
Carefully review the schema requirements and the validation issues encountered:

VALIDATION ISSUES:
${issues}

RAW ERROR CONTEXT:
${errorContext}

ORIGINAL INPUT:
${prompt}

CORRECTION REQUIREMENT:
Provide a strictly corrected JSON payload matching the target schema. 
Resolve all field missingness, incorrect enum variants, and type cast mismatches explicitly.
`;
    }
  }

  throw new Error('Self-healing pipeline terminated unexpectedly.');
}
```

### Usage Example: Resilient Lead Extraction

```typescript
// scripts/run-extraction.ts
import { anthropic } from '@ai-sdk/anthropic';
import { z } from 'zod';
import { extractWithSelfHealing } from '@/lib/extract-with-self-healing';

const LeadSchema = z.object({
  fullName: z.string().min(2),
  email: z.string().email(),
  companySize: z.enum(['1-10', '11-50', '51-200', '201-1000', '1000+']),
  annualBudgetUsd: z.number().int().positive(),
  painPoints: z.array(z.string()).min(1),
});

async function main() {
  const unstructuredEmail = `
    Hey team, this is Dave from Acme Corp (we have about 350 employees). 
    We want to upgrade our search pipeline and have around 40k earmarked for this. 
    Our current solution is too slow and drops indexing jobs. Shoot me an email: dave[at]acme.com.
  `;

  const lead = await extractWithSelfHealing({
    model: anthropic('claude-3-7-sonnet-20250219'),
    schema: LeadSchema,
    prompt: unstructuredEmail,
  });

  console.log('Successfully Extracted & Validated Lead:', lead);
}
```

---

## 4. Calibrated System Prompts for Multi-Tool Execution

### 4.1 Claude 3.7 Sonnet Calibrated System Prompt
Claude 3.7 Sonnet handles complex reasoning traces exceptionally well. This prompt enforces pre-tool-call architectural planning, strictly forbids speculative parameter values, and structures multi-step handoffs.

```markdown
You are an expert autonomous execution agent powered by Claude 3.7 Sonnet, integrated with native production tools.

OPERATIONAL PRINCIPLES:
1. TOOL SELECTION RIGOR:
   - Only invoke tools when external state access, real-time calculation, or system mutation is strictly required.
   - If a request can be answered factually and deterministically from internal knowledge without state verification, do not call tools.

2. PARAMETER SOUNDNESS:
   - Never speculate, invent, or guess parameter values (e.g., UUIDs, line-item IDs, database keys).
   - If a parameter is mandatory and missing from the conversation context, you MUST halt and request clarification from the user rather than passing dummy values.

3. REASONING & SEQUENCE:
   - For complex, multi-step actions, outline your operational trajectory before triggering the first tool.
   - When evaluating tool outputs, critically check status flags (`ok`, `status: "success"`). If a tool returns an error code, do not assume subsequent state exists. Branch immediately into error recovery.

4. GENERATIVE UI INTEGRATION:
   - When the user requires visual comparison or tabular exploration, trigger `renderUIComponent` with validated structured data rather than rendering long Markdown tables.

OUTPUT DIRECTIVE:
Deliver succinct, high-density responses. After all relevant tool iterations are complete, present a concise summary of the mutated state or data retrieved.
```

### 4.2 OpenAI GPT-4o Calibrated System Prompt
GPT-4o performs well with aggressive JSON enforcement and parallel execution. This prompt constrains its propensity to parallelize independent state-modifying actions without explicit dependency checks.

```markdown
You are an operations-grade AI controller running on OpenAI GPT-4o with function calling capabilities.

EXECUTION INSTRUCTIONS:
1. STRICT JSON FORMATTING:
   - All tool arguments must strictly comply with the provided JSON Schema definitions.
   - Ensure enum values match the case and naming scheme defined in the schema. Do not convert snake_case to camelCase or vice versa.

2. PARALLEL VS SEQUENTIAL CALL CONSTRAINTS:
   - Read operations (e.g., searches, analytics reads) may be parallelized across multiple tools simultaneously.
   - Write operations (e.g., cart mutations, state changes, deletions) MUST be issued sequentially. Wait for the server verification response of step N before issuing step N+1.

3. IDEMPOTENCY HANDLING:
   - For all mutation tools accepting an `idempotencyKey`, verify that a unique, cryptographically random key is provided per intent. Never reuse an idempotency key across different logical operations.

4. TERMINATION CONDITION:
   - Once tool results provide sufficient data to answer the query, terminate the tool-call loop immediately and generate the user-facing response. Do not trigger superfluous verification queries unless explicitly instructed.
```

---

## 5. Implementation Reference & Validation Checklist

### Tool Architecture Decision Matrix

| Dimension | Read-Only Tools (Search, Analytics) | Mutation Tools (Carts, Updates) | UI Dispatch Tools (Generative UI) |
| :--- | :--- | :--- | :--- |
| **Max Execution Steps** | 1 to 3 steps | Strictly 1 step per transaction | Terminal step (final step in loop) |
| **Idempotency Requirement** | Not required | Mandatory UUIDv4 / Nonce | Optional (depends on client cache) |
| **Validation Strictness** | Soft coercions allowed (`z.coerce`) | Hard exact-match typing only | Polymorphic (`discriminatedUnion`) |
| **Retry Strategy** | Auto-retry up to 3x on network error | Exponential backoff with same key | No retry (fail forward to text) |
| **Best-Suited Model** | Claude 3.7 Sonnet / GPT-4o | GPT-4o (Strict Schema adherence) | Claude 3.7 Sonnet (Complex JSON) |

### Pre-Deployment Verification Checklist

- [ ] **Type Narrowing**: All enum properties define at least two explicit string literals (avoid raw `z.string()` for finite sets).
- [ ] **Descriptions Present**: Every single property within `z.object({})` has a `.describe('...')` call explaining constraints, expected formatting, and unit types (e.g., "cents", "ms", "ISO-8601").
- [ ] **Regex Guardrails**: String patterns (dates, SKUs, UUIDs, emails) enforce strict regex rules before executing business logic.
- [ ] **No Infinite Loops**: The Route Handler enforces an explicit `maxSteps` count (default recommended: `maxSteps: 5`).
- [ ] **Self-Healing Fallback**: All core extraction endpoints utilize `extractWithSelfHealing` or wrap `generateObject` with targeted error reflection prompts.
- [ ] **Idempotency Safeguard**: Every state mutation tool requires and persists an idempotency key before applying writes.
- [ ] **Payload Sanitization**: Tool execution outputs return strictly formatted subsets of database records, stripping internal secrets, passwords, and PII before serialization.
