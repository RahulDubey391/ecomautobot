# Module 1: AI SDK 4.x Core Runtime & Streaming Architecture

This playbook establishes the core architectural standard for deploying production-grade, enterprise-scale streaming Large Language Model (LLM) backends using Vercel AI SDK 4.x and Next.js App Router. It covers the streaming pipeline, the wire-level Data Stream Protocol, connection drop lifecycles, and resilient client-side state hydration.

---

## 1. Architectural Foundations: The AI SDK 4.x Streaming Pipeline

The Vercel AI SDK 4.x streaming pipeline decouples LLM inference from HTTP response generation through a standardized primitives layer (`streamText`, `streamUI`, `createDataStreamResponse`).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 NEXT.JS EDGE / NODE RUNTIME                            │
│                                                                                        │
│  ┌───────────────────────────┐         ┌────────────────────────────────────────────┐  │
│  │   Incoming Request        │         │              LLM Provider                  │  │
│  │   (POST /api/chat)        │         │   (Anthropic Claude 3.5 / OpenAI GPT-4o)   │  │
│  └─────────────┬─────────────┘         └─────────────────────┬──────────────────────┘  │
│                │                                             │                         │
│                ▼                                             ▼                         │
│  ┌───────────────────────────┐    Prompt / Messages     ┌────────────────────────────┐ │
│  │ Request Validation        ├─────────────────────────►│ Raw Provider SSE Stream    │ │
│  │ (Zod Schema Engine)       │                          │ (Delta Chunks / Tool Calls)│ │
│  └───────────────────────────┘                          └────────────┬───────────────┘ │
│                                                                      │                 │
│                                                                      ▼                 │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ AI SDK Core Transform Layer (`streamText` Engine)                                │  │
│  │                                                                                  │  │
│  │  - Merges Raw Text Tokens                                                        │  │
│  │  - Normalizes Multi-Provider Tool Invocations (`execute` / `onStepFinish`)       │  │
│  │  - Enforces JSON Schema Constraints for Structured Outputs                       │  │
│  │  - Injects Custom Metadata Frames via `DataStreamWriter`                         │  │
│  └──────────────────────────────────────────┬───────────────────────────────────────┘  │
│                                             │                                          │
│                                             ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Wire Protocol Serialization (`toDataStreamResponse`)                             │  │
│  │ Format: Server-Sent Events (SSE) / Chunked HTTP 1.1 or HTTP/2 Data Stream        │  │
│  └──────────────────────────────────────────┬───────────────────────────────────────┘  │
└─────────────────────────────────────────────┼──────────────────────────────────────────┘
                                              │ 
                                              │ HTTP 200 Streaming Response (Wire Protocol)
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 BROWSER / CLIENT RUNTIME                               │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Wire Parser (`ai/react` Engine / `useChat` / `readDataStream`)                   │  │
│  │                                                                                  │  │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────────────┐  │  │
│  │  │ '0': Text    │   │ '2': Data    │   │ '3': Error   │   │ '9': Tool Results │  │  │
│  │  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └─────────┬─────────┘  │  │
│  └─────────┼──────────────────┼──────────────────┼─────────────────────┼────────────┘  │
│            ▼                  ▼                  ▼                     ▼               │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Hydration-Safe React State Tree (`messages`, `data`, `status`, `error`)          │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### The AI SDK Data Stream Wire Protocol Specification

When `toDataStreamResponse()` or `createDataStreamResponse()` is invoked, the HTTP layer transmits chunks encoded using the Vercel AI SDK Data Stream Protocol. Each chunk is formatted as:

```text
<STREAM_TYPE_ID>:<SERIALIZED_JSON_OR_STRING>\n
```

| Type ID | Designation | Payload Schema / Example | Description |
| :--- | :--- | :--- | :--- |
| `0` | Text Part | `0:"Hello, world!"\n` | Raw token increment for assistant text. Quoted string. |
| `1` | Function Call | `1:{"name": "fn", "arguments": "{}"}\n` | Legacy provider-specific function call payload. |
| `2` | Custom Data | `2:[{"citationId": "c_123", "score": 0.98}]\n` | Array of arbitrary JSON objects injected via stream data writer. |
| `3` | Error | `3:"Database connection timed out."\n` | Unrecoverable error string; terminates or flags stream state. |
| `8` | Tool Call Part | `8:{"toolCallId":"tc_1","toolName":"search","args":{"q":"ai"}}\n` | Complete or partial tool call definition dispatched to the client. |
| `9` | Tool Result Part | `9:{"toolCallId":"tc_1","result":{"status":"ok"}}\n` | Output from the server-executed tool resolution. |
| `d` | Finish Message | `d:{"finishReason":"stop","usage":{"promptTokens":12,"completionTokens":45}}\n` | Stream completion telemetry and provider-reported token usage. |

---

## 2. Production Runtime Engine: Next.js Route Handler

The following enterprise route handler executes `streamText` against Claude 3.5 Sonnet, provides dynamic request payload schema validation, integrates client disconnect handlers, tracks token consumption, and appends custom metadata directly onto the stream.

Create `app/api/chat/route.ts`:

```typescript
import { anthropic } from '@ai-sdk/anthropic';
import { streamText, createDataStreamResponse, Message } from 'ai';
import { z } from 'zod';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 60; // 60s max execution duration (Pro tier requirement)

// 1. Strict Request Body Validation Schema
const chatRequestSchema = z.object({
  id: z.string().uuid({ message: 'Invalid conversation UUID' }),
  messages: z.array(
    z.object({
      id: z.string(),
      role: z.enum(['user', 'assistant', 'system']),
      content: z.string().min(1).max(32000),
    })
  ),
  modelTier: z.enum(['standard', 'reasoning']).default('standard'),
});

export async function POST(req: Request) {
  // Enforce abort signal propagation from incoming client connection
  const abortController = new AbortController();
  req.signal.addEventListener('abort', () => {
    abortController.abort();
    console.warn('[AI_STREAM] Inbound client connection dropped. Aborting inference.');
  });

  let parsedBody: z.infer<typeof chatRequestSchema>;

  try {
    const rawBody = await req.json();
    parsedBody = chatRequestSchema.parse(rawBody);
  } catch (error) {
    return new Response(
      JSON.stringify({
        error: 'Unprocessable Entity',
        details: error instanceof z.ZodError ? error.errors : 'Malformed JSON payload',
      }),
      { status: 422, headers: { 'Content-Type': 'application/json' } }
    );
  }

  const { messages, modelTier } = parsedBody;

  // Use createDataStreamResponse to retain complete control over the SSE stream buffer
  return createDataStreamResponse({
    execute: async (dataStream) => {
      // Send trace/session metadata to the client via Data stream (Type 2)
      dataStream.writeData({
        type: 'session_init',
        traceId: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
      });

      const selectedModel =
        modelTier === 'reasoning'
          ? anthropic('claude-3-5-sonnet-20241022')
          : anthropic('claude-3-haiku-20240307');

      const result = streamText({
        model: selectedModel,
        messages: messages as Message[],
        abortSignal: abortController.signal,
        temperature: 0.2,
        system: `You are an elite enterprise software architect. Provide direct, highly structured technical analysis with zero generic boilerplate.`,
        onStepFinish: async (step) => {
          console.info(`[AI_STEP] Completed step. Tokens used: ${step.usage.totalTokens}`);
        },
        onFinish: async (event) => {
          // Asynchronously record billing/telemetry in downstream infrastructure
          console.info('[AI_FINISH] Final Stream Metrics:', {
            finishReason: event.finishReason,
            usage: event.usage,
            rawResponseHeaders: event.response?.headers,
          });

          // Append telemetry payload to the client before closing
          dataStream.writeData({
            type: 'metrics',
            usage: event.usage,
          });
        },
      });

      // Merge the text and tool stream directly into the HTTP response stream
      result.mergeIntoDataStream(dataStream);
    },
    onError: (error: unknown) => {
      // Prevents process crashes on unhandled stream rejections
      console.error('[AI_STREAM_FATAL]', error);
      return error instanceof Error ? error.message : 'Unknown internal streaming failure';
    },
  });
}
```

---

## 3. Structured Outputs: `generateObject` Engine

For workflows requiring strict JSON output conforming to deterministic application schemas (e.g., dynamic database migrations, automated workflows, and parsing tasks), use `generateObject`.

This pattern includes an internal validation-retry loop to resolve transient format breaks without crashing caller threads.

Create `lib/ai/structured-generator.ts`:

```typescript
import { openai } from '@ai-sdk/openai';
import { generateObject, NoObjectGeneratedError } from 'ai';
import { z } from 'zod';

// Define the authoritative target schema
export const DatabaseMigrationPlanSchema = z.object({
  planId: z.string().uuid(),
  databaseEngine: z.enum(['postgresql', 'mysql', 'sqlite']),
  breakingChanges: z.boolean(),
  estimatedDowntimeSeconds: z.number().int().nonnegative(),
  executionSteps: z.array(
    z.object({
      stepNumber: z.number().int().positive(),
      sql: z.string().min(5),
      rollbackSql: z.string().min(5),
      safetyRisk: z.enum(['low', 'medium', 'high', 'critical']),
    })
  ),
});

export type DatabaseMigrationPlan = z.infer<typeof DatabaseMigrationPlanSchema>;

interface GenerationOptions {
  prompt: string;
  maxRetries?: number;
}

export async function generateResilientMigrationPlan(
  options: GenerationOptions
): Promise<DatabaseMigrationPlan> {
  const { prompt, maxRetries = 2 } = options;
  let attempt = 0;

  while (attempt <= maxRetries) {
    try {
      const { object, usage } = await generateObject({
        model: openai('gpt-4o', { structuredOutputs: true }),
        schema: DatabaseMigrationPlanSchema,
        schemaName: 'DatabaseMigrationPlan',
        schemaDescription: 'A structured, executable database migration script sequence with safety telemetry.',
        mode: 'json', // Forces explicit JSON validation mode
        temperature: 0, // Deterministic zero-temperature for data structures
        system: `You are an expert Principal Database Administrator. You output ONLY valid, production-ready DDL and DML operations.`,
        prompt: attempt === 0 
          ? prompt 
          : `${prompt}\n\nCRITICAL: Your previous output failed schema validation. Output ONLY adhering to the strict schema.`,
      });

      console.info(`[STRUCTURED_GENERATOR] Success on attempt ${attempt + 1}. Usage:`, usage);
      return object;
    } catch (error) {
      attempt++;
      if (NoObjectGeneratedError.isInstance(error)) {
        console.error(`[STRUCTURED_GENERATOR] Generation format failure (Attempt ${attempt}/${maxRetries + 1}):`, {
          cause: error.cause,
          text: error.text,
        });
      } else {
        console.error(`[STRUCTURED_GENERATOR] Network or Provider Exception:`, error);
      }

      if (attempt > maxRetries) {
        throw new Error(
          `Failed to generate valid structured object after ${maxRetries + 1} attempts. Root error: ${
            error instanceof Error ? error.message : String(error)
          }`
        );
      }
    }
  }

  throw new Error('Unexpected structured generator termination');
}
```

---

## 4. Resilient Client Connection & Hydration-Safe State Management

Streaming updates cause rapid DOM re-renders. If server-rendered markup drifts from dynamic client streaming updates, Next.js throws hydration errors (`Hydration failed because the initial UI does not match the server-rendered HTML`).

The pattern below implements:
1. Hydration-safe initial rendering barriers.
2. Connection break identification and user notifications.
3. Custom fetch overrides that inject dynamic client telemetry headers into the stream.

Create `components/chat/HydrationSafeChatPane.tsx`:

```tsx
'use client';

import React, { useEffect, useState, useRef } from 'react';
import { useChat, Message } from 'ai/react';
import { AlertCircle, RefreshCw, Send, CheckCircle2 } from 'lucide-react';

interface HydrationSafeChatPaneProps {
  initialConversationId: string;
  initialMessages?: Message[];
}

export function HydrationSafeChatPane({
  initialConversationId,
  initialMessages = [],
}: HydrationSafeChatPaneProps) {
  // Prevent React hydration mismatch by suppressing stream renders until mounted
  const [hasMounted, setHasMounted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    isLoading,
    error,
    reload,
    stop,
    data,
  } = useChat({
    api: '/api/chat',
    id: initialConversationId,
    initialMessages,
    body: {
      id: initialConversationId,
      modelTier: 'standard',
    },
    headers: {
      'X-Client-Session-Id': initialConversationId,
    },
    onResponse: (response) => {
      if (!response.ok) {
        console.error(`[STREAM_HTTP_ERROR] Status: ${response.status}`);
      }
    },
    onFinish: (message) => {
      console.info('[CLIENT_STREAM_COMPLETE] Finalized Assistant Message:', message.id);
    },
    onError: (streamError) => {
      console.error('[CLIENT_STREAM_FATAL]', streamError);
    },
  });

  useEffect(() => {
    setHasMounted(true);
  }, []);

  useEffect(() => {
    if (hasMounted) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, hasMounted]);

  // Server-Side Rendering fallback skeleton ensuring zero DOM drift during hydration
  if (!hasMounted) {
    return (
      <div className="w-full max-w-4xl mx-auto h-[600px] border border-neutral-200 dark:border-neutral-800 rounded-lg bg-neutral-50 dark:bg-neutral-900 animate-pulse p-4">
        <div className="h-4 w-48 bg-neutral-300 dark:bg-neutral-700 rounded mb-4" />
        <div className="h-64 w-full bg-neutral-200 dark:bg-neutral-800 rounded" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[750px] w-full max-w-4xl mx-auto border border-neutral-200 dark:border-neutral-800 rounded-xl bg-white dark:bg-neutral-950 shadow-sm overflow-hidden">
      {/* Header bar */}
      <div className="px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 flex justify-between items-center bg-neutral-50/50 dark:bg-neutral-900/50">
        <div>
          <h2 className="text-sm font-semibold text-neutral-800 dark:text-neutral-100">
            Streaming Console
          </h2>
          <span className="text-xs text-neutral-500 font-mono">
            ID: {initialConversationId}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isLoading ? (
            <span className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400 font-medium bg-amber-50 dark:bg-amber-950/40 px-2.5 py-1 rounded-full border border-amber-200 dark:border-amber-800">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-ping" />
              Streaming Active
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 font-medium bg-emerald-50 dark:bg-emerald-950/40 px-2.5 py-1 rounded-full border border-emerald-200 dark:border-emerald-800">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Ready
            </span>
          )}
        </div>
      </div>

      {/* Message Viewport */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-24 text-neutral-400 dark:text-neutral-600 text-sm">
            No message history. Dispatch an input below to initiate stream.
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex flex-col ${
              message.role === 'user' ? 'items-end' : 'items-start'
            }`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'bg-neutral-100 dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100 border border-neutral-200/50 dark:border-neutral-700/50'
              }`}
            >
              <div className="font-mono text-[10px] opacity-70 mb-1 uppercase tracking-wider">
                {message.role}
              </div>
              <div className="whitespace-pre-wrap">{message.content}</div>
            </div>
          </div>
        ))}

        {/* Display Injected Custom Stream Data (Type 2 Chunks) */}
        {data && data.length > 0 && (
          <div className="border border-neutral-200 dark:border-neutral-800 rounded p-2 text-xs font-mono bg-neutral-50 dark:bg-neutral-900/50">
            <span className="text-neutral-500 font-bold block mb-1">Attached Stream Metadata Frames:</span>
            {JSON.stringify(data, null, 2)}
          </div>
        )}

        {/* Exception / Network Failure UI */}
        {error && (
          <div className="p-4 rounded-lg bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900 flex items-center justify-between text-red-700 dark:text-red-300">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span className="text-xs font-mono">Stream Interrupted: {error.message}</span>
            </div>
            <button
              onClick={() => reload()}
              className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 bg-red-100 dark:bg-red-900/60 rounded hover:bg-red-200 transition-colors"
            >
              <RefreshCw className="w-3 h-3" /> Retry
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Control / Input Panel */}
      <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 bg-neutral-50/30 dark:bg-neutral-900/30">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            value={input}
            onChange={handleInputChange}
            placeholder="Type your message..."
            disabled={isLoading && !error}
            className="flex-1 px-4 py-2 text-sm rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          />
          {isLoading ? (
            <button
              type="button"
              onClick={stop}
              className="px-4 py-2 bg-neutral-200 dark:bg-neutral-800 hover:bg-neutral-300 dark:hover:bg-neutral-700 text-neutral-800 dark:text-neutral-200 text-sm font-medium rounded-lg transition-colors"
            >
              Cancel
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm font-medium rounded-lg flex items-center gap-1.5 transition-colors"
            >
              <Send className="w-4 h-4" />
              <span>Send</span>
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
```

---

## 5. Edge vs. Node.js Runtime Trade-Off Matrix

Configuring `export const runtime = 'edge'` vs `export const runtime = 'nodejs'` profoundly impacts network backpressure, payload buffers, and stream persistence across Vercel infrastructure.

| Vector | Edge Runtime (`export const runtime = 'edge'`) | Node.js Serverless (`export const runtime = 'nodejs'`) | Architectural Decision Driver |
| :--- | :--- | :--- | :--- |
| **Cold Start Latency** | 0ms - 15ms. Near-instant instantiation worldwide. | 150ms - 850ms dependent on bundle resolution and dependency size. | Choose **Edge** if first-token latency (TTFT) is the primary user-facing SLA metric. |
| **Execution Duration Limits** | Strictly capped by platform tier (typically 25s–30s on standard plans). | Up to 60s (Pro plan), up to 900s (Enterprise with configured maxDuration). | Choose **Node.js** if handling reasoning models (e.g. o1/o3-mini) or deep tool execution loops. |
| **Max Payload Boundaries** | ~4MB inbound JSON request body limits. | Typically up to 4.5MB request payload, configurable streaming sizes. | Choose **Node.js** when processing multi-page document context or high-resolution multimodal data. |
| **Network Backpressure & Sockets** | Direct, raw WHATWG Streams. Buffering is minimal; memory pressure scales with concurrent connections. | Standard Node streams wrapped via Web API abstractions; higher base memory utilization per connection. | **Edge** provides clean, low-overhead SSE distribution at extreme concurrency tiers. |
| **Database & SDK Compatibility** | Restricted: No standard TCP sockets without proxy wrappers (e.g. `@neondatabase/serverless`). | Unrestricted: Native access to Prisma, standard PostgreSQL (`pg`), Redis (`ioredis`), and native C++ binaries. | Choose **Node.js** if tools query internal enterprise databases without HTTP-based connection pools. |
| **Memory Ceiling** | 128MB fixed memory per compute instance. | Up to 1024MB - 3008MB configurable per function invocation. | Large tabular transformations require **Node.js**. |

---

## 6. Production Deployment Checklist: Streaming Health & Telemetry

Before shipping an AI SDK 4.x streaming route handler to production infrastructure, complete and verify every check in this operational gate.

```
AI SDK 4.x Production Pre-Flight Checklist
│
├── [ ] 1. Runtime Isolation & Quotas
│   ├── maxDuration is explicitly declared (matches Vercel plan constraints: 60s Pro / 900s Enterprise).
│   ├── Inbound Request payload is capped via schema (e.g., Zod content length bounds to prevent DoS via token starvation).
│   └── dynamic = 'force-dynamic' is configured on the route to prevent static caching of dynamic streams.
│
├── [ ] 2. Stream Drop Handling
│   ├── req.signal is bound to streamText({ abortSignal: req.signal }).
│   ├── Connection cancellation hooks are validated (verify client navigation aborts the server generation task to avoid billing runaway).
│   └── createDataStreamResponse includes explicit onError catch handlers returning sanitized strings (never expose raw stack traces).
│
├── [ ] 3. Telemetry and Billing Controls
│   ├── Token usage metrics extracted inside onFinish callback.
│   ├── Client IDs and Trace IDs injected via custom data frames (writeData) for downstream observability.
│   └── Database/KV log writes are detached or cleanly executed without blocking the stream closure.
│
├── [ ] 4. Client Hydration Security
│   ├── Client components consuming useChat implement mounted barriers to prevent SSR/DOM mismatches.
│   ├── Structured outputs use try/catch boundaries with NoObjectGeneratedError handling.
│   └── Client handles transient drops via reload primitives alongside visible UI notifications.
```

---

## 7. Complete Verification Test Harness

Use this automated script to verify your endpoint's SSE compliance, wire protocol formatting, and abort-signal propagation directly from your terminal.

Create `scripts/verify-stream.ts`:

```typescript
/**
 * Test Harness to validate AI SDK 4.x Data Stream Protocol integrity.
 * Usage: npx tsx scripts/verify-stream.ts
 */

const TARGET_URL = process.env.TEST_ENDPOINT_URL || 'http://localhost:3000/api/chat';

async function verifyStreamingProtocol() {
  console.log(`[HARNESS] Connecting to: ${TARGET_URL}`);
  const abortController = new AbortController();

  const response = await fetch(TARGET_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      id: crypto.randomUUID(),
      messages: [
        {
          id: 'test-1',
          role: 'user',
          content: 'Count to 5 slowly. Output one number per line.',
        },
      ],
      modelTier: 'standard',
    }),
    signal: abortController.signal,
  });

  if (!response.ok) {
    throw new Error(`Endpoint returned HTTP ${response.status}: ${await response.text()}`);
  }

  if (!response.body) {
    throw new Error('Response returned no readable stream body.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let textTokensReceived = 0;
  let customDataReceived = false;

  console.log('[HARNESS] Stream opened. Validating wire protocol chunks...\n');

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n').filter((line) => line.trim() !== '');

      for (const line of lines) {
        const streamType = line.slice(0, 1);
        const payload = line.slice(2);

        switch (streamType) {
          case '0':
            textTokensReceived++;
            process.stdout.write(JSON.parse(payload));
            break;
          case '2':
            customDataReceived = true;
            console.log(`\n[WIRE_DATA_FRAME] Custom data detected:`, JSON.parse(payload));
            break;
          case '3':
            console.error(`\n[WIRE_ERROR] Stream returned explicit error:`, payload);
            break;
          case 'd':
            console.log(`\n[WIRE_FINISH] Stream metrics frame received:`, JSON.parse(payload));
            break;
          default:
            console.warn(`\n[WIRE_UNKNOWN] Type ${streamType}: ${payload}`);
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      console.log('\n[HARNESS] Stream aborted intentionally via AbortController.');
    } else {
      throw err;
    }
  }

  console.log('\n------------------------------------------------------------');
  console.log('[HARNESS] Validation Complete.');
  console.log(`- Text Tokens Registered: ${textTokensReceived}`);
  console.log(`- Custom Data Frames Seen: ${customDataReceived}`);

  if (textTokensReceived === 0) {
    throw new Error('FAILED: No text tokens were parsed from the wire.');
  }
}

verifyStreamingProtocol().catch((err) => {
  console.error('\n[HARNESS_FATAL]', err.message);
  process.exit(1);
});
```

Execute this verification script during CI/CD test phases to ensure updates to models, schemas, or proxy layers never break your streaming endpoints.
