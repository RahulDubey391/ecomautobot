# Module 3: Advanced Agentic Pipelines, Tool Calling & Human-in-the-Loop Systems

Moving from simple single-prompt completions to production-grade agentic architectures requires deterministic control over non-deterministic models. In n8n, this transition demands a strict separation of concerns: execution runtime, state management, tool contracts, and validation loops.

This guide details the concrete architectural patterns, schemas, and integration points required to run fault-tolerant, autonomous agents with dynamic tool calling, strict structured output validation, Telegram/Slack approval gates, and self-correcting reflection chains.

---

## 1. Dynamic Tool Calling Architecture

The n8n AI Agent node implements the ReAct (Reasoning + Acting) and OpenAI Function Calling loops. When an agent determines it must use external capabilities, it pauses generation, emits an argument object matching the tool's registered schema, receives the tool's execution output, and continues its reasoning trace.

```
┌─────────────────────────────────────────────────────────────┐
│                       n8n AI Agent                          │
│                (Tools Agent / ReAct Loop)                   │
└──────┬──────────────────────▲─────────────────────────┬─────┘
       │                      │                         │
       │ 1. Arguments JSON    │ 3. Tool Return Payload  │ 4. Final Text
       ▼                      │                         ▼
┌──────────────┐       ┌──────┴───────┐          ┌──────────────┐
│ Schema Guard │       │ Normalization│          │ Output Parser│
└──────┬───────┘       └──────▲───────┘          └──────┬───────┘
       │ 2. Validated Invocation│                       │
       ▼                      │                         ▼
┌─────────────────────────────┴───────┐          ┌──────────────┐
│ Tool: Sub-Workflow / Code / HTTP API│          │ Downstream DB│
└─────────────────────────────────────┘          └──────────────┘
```

### 1.1 Tool Definitions: Sub-Workflow vs. Code vs. HTTP Request

n8n offers three primary mechanisms to expose tools to the AI Agent node:

| Mechanism | Latency Overhead | Isolation Level | Primary Use Case |
| :--- | :--- | :--- | :--- |
| **Custom n8n Workflow Tool** | Medium (~150-300ms) | Complete (separate execution scope) | Complex multi-step business logic, enterprise APIs, multi-table DB lookups. |
| **Custom Code Tool** | Low (~5-15ms) | In-process (sandboxed V8 runtime) | Pure data transformations, cryptographic operations, math, local JSON restructuring. |
| **HTTP Request Tool** | Low-Medium (~50-200ms) | Network boundary | Direct integration with third-party microservices and internal REST endpoints. |

### 1.2 Deterministic JSON Schema Contracts for Custom Tools

Ambiguous descriptions cause catastrophic model hallucination. Tool declarations must specify property boundaries, types, and descriptions explaining both *what* the argument is and *how* it must be formatted.

Attach this JSON Schema directly to an n8n **Custom Workflow Tool** or **Custom Code Tool** configuration interface under the `Specification (JSON Schema)` field:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["query", "archive", "quarantine"],
      "description": "The exact database operation to perform. 'query' reads record state. 'archive' flags records as inactive. 'quarantine' immediately revokes user token access and moves the record to the compliance review pool."
    },
    "target_entity": {
      "type": "string",
      "enum": ["user_account", "api_key", "workspace"],
      "description": "The entity scope of the operation."
    },
    "entity_id": {
      "type": "string",
      "pattern": "^[a-f0-9]{8}-[a-f0-9]{4}-[4][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$",
      "description": "The UUIDv4 identifier of the target entity. Must adhere strictly to standard 36-character hyphenated UUID notation."
    },
    "reason": {
      "type": "string",
      "minLength": 10,
      "maxLength": 255,
      "description": "Human-readable justification for running this tool. Required for enterprise audit logging."
    }
  },
  "required": ["action", "target_entity", "entity_id", "reason"],
  "additionalProperties": false
}
```

### 1.3 Production Custom Code Tool: Zero-Dependency Sandbox

When using the **Code Tool**, do not rely on implicit return structures. The AI Agent expects a flat string or structured JSON stringified return. 

Place this code inside the n8n **Code Tool** node:

```javascript
// n8n Code Tool: Entity Security Interceptor
// Inputs are populated into the execution scope via $fromAI()

const action = $fromAI('action');
const targetEntity = $fromAI('target_entity');
const entityId = $fromAI('entity_id');
const reason = $fromAI('reason');

// Runtime validation guard
if (!action || !targetEntity || !entityId || !reason) {
  return JSON.stringify({
    success: false,
    error: "MISSING_MANDATORY_PARAMETERS",
    message: "Parameters [action, target_entity, entity_id, reason] must all be provided."
  });
}

const executionTimestamp = new Date().toISOString();

try {
  // Deterministic mock routing for sandboxed tool execution
  const auditReceipt = {
    receipt_id: `rcpt_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
    status: "PROCESSED",
    action_applied: action,
    target: `${targetEntity}:${entityId}`,
    compliance_reason: reason,
    executed_at: executionTimestamp
  };

  if (action === "quarantine") {
    auditReceipt.access_revocation_event_emitted = true;
    auditReceipt.state_override = "LOCKED";
  } else if (action === "archive") {
    auditReceipt.state_override = "SOFT_DELETED";
  } else {
    auditReceipt.state_override = "ACTIVE";
    auditReceipt.read_count = 1;
  }

  // Always return stringified JSON to the agent
  return JSON.stringify({
    success: true,
    data: auditReceipt
  });

} catch (error) {
  return JSON.stringify({
    success: false,
    error: "INTERNAL_TOOL_EXECUTION_FAILURE",
    details: error.message
  });
}
```

---

## 2. Deterministic Structured Output Parsing

AI Agents are notoriously unreliable when generating naked JSON, frequently including conversational preambles, trailing commas, or missing brackets. To enforce deterministic schema compliance, apply a combined approach: **Model-Level Schema Enforcement** backed by an **Idempotent Repair Engine**.

### 2.1 Schema Definition for the Structured Output Parser

Attach the **Structured Output Parser** sub-node to the **OpenAI Chat Model** or **Anthropic Chat Model** node. Configure the JSON Schema property with this rigorous definition:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AgentIncidentResolutionPayload",
  "type": "object",
  "properties": {
    "incident_id": {
      "type": "string",
      "pattern": "^INC-[0-9]{6}$"
    },
    "severity": {
      "type": "string",
      "enum": ["SEV-1", "SEV-2", "SEV-3", "SEV-4"]
    },
    "root_cause_analysis": {
      "type": "string",
      "minLength": 20
    },
    "impacted_systems": {
      "type": "array",
      "items": { "type": "string" },
      "minItems": 1
    },
    "remediation_steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "order": { "type": "integer" },
          "command": { "type": "string" },
          "automated": { "type": "boolean" }
        },
        "required": ["order", "command", "automated"],
        "additionalProperties": false
      },
      "minItems": 1
    },
    "resolution_confidence_score": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0
    }
  },
  "required": [
    "incident_id",
    "severity",
    "root_cause_analysis",
    "impacted_systems",
    "remediation_steps",
    "resolution_confidence_score"
  ],
  "additionalProperties": false
}
```

### 2.2 System Prompt Directive for Structured Outputs

LLMs must be instructed on how to structure their chain of thought without contaminating the output payload:

```text
You are an advanced incident management runtime. 
You MUST analyze the input telemetry and emit your final response exclusively conforming to the provided JSON Schema.

OPERATIONAL INSTRUCTIONS:
1. Do not prefix your response with "```json" or backticks.
2. Do not append commentary, markdown, or apologies after the JSON.
3. Validate all fields against constraints before outputting:
   - incident_id must match regex: ^INC-[0-9]{6}$
   - severity must be strictly one of: ["SEV-1", "SEV-2", "SEV-3", "SEV-4"]
   - resolution_confidence_score must be a float between 0.0 and 1.0
4. Any deviation from the schema triggers an immediate hard rejection by the runtime parser.
```

### 2.3 Resilient JSON Repair Engine (Code Node Fallback)

If the parser fails or you are using open models via Ollama/LocalAI that do not support strict grammar masks, insert this **Code Node** immediately after the model response:

```javascript
// Node: Resilient JSON Parsing & Structural Repair Engine
const rawInput = $input.first().json.output || $input.first().json.text || "";

function extractAndRepairJSON(text) {
  if (typeof text === 'object' && text !== null) {
    return text;
  }

  // Step 1: Strip Markdown fences if present
  let sanitized = text.replace(/```(?:json)?/gi, '').replace(/```/g, '').trim();

  // Step 2: Extract text boundary between the first '{' and last '}'
  const firstOpenBrace = sanitized.indexOf('{');
  const lastCloseBrace = sanitized.lastIndexOf('}');

  if (firstOpenBrace === -1 || lastCloseBrace === -1) {
    throw new Error("PARSER_FATAL_NO_JSON_OBJECT_FOUND: Payload contains no root braces.");
  }

  sanitized = sanitized.substring(firstOpenBrace, lastCloseBrace + 1);

  // Step 3: Handle structural edge-cases using aggressive regex repair
  sanitized = sanitized
    .replace(/,\s*([}\]])/g, '$1')            // Remove trailing commas before closing braces/brackets
    .replace(/([{,]\s*)([a-zA-Z0-9_]+?)\s*:/g, '$1"$2":') // Wrap unquoted keys
    .replace(/:\s*'([^']*)'/g, ':"$1"');       // Convert single quoted string values to double quotes

  try {
    return JSON.parse(sanitized);
  } catch (initialErr) {
    // Step 4: Line break and unescaped character scrubbing
    sanitized = sanitized.replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t");
    try {
      return JSON.parse(sanitized);
    } catch (secondaryErr) {
      throw new Error(`PARSER_REPAIR_FAILED: Initial: [${initialErr.message}], Secondary: [${secondaryErr.message}]`);
    }
  }
}

try {
  const parsedData = extractAndRepairJSON(rawInput);
  
  // Mandatory Structural Validation Pass
  const requiredKeys = [
    "incident_id", 
    "severity", 
    "root_cause_analysis", 
    "impacted_systems", 
    "remediation_steps", 
    "resolution_confidence_score"
  ];
  
  for (const key of requiredKeys) {
    if (!(key in parsedData)) {
      throw new Error(`SCHEMA_VIOLATION: Missing mandatory root field: "${key}"`);
    }
  }

  return [{
    json: {
      parse_success: true,
      data: parsedData,
      raw_bytes: Buffer.byteLength(JSON.stringify(parsedData), 'utf8')
    }
  }];
} catch (err) {
  return [{
    json: {
      parse_success: false,
      error_code: "PAYLOAD_DESTRUCTION",
      error_message: err.message,
      original_output: rawInput
    }
  }];
}
```

---

## 3. Human-in-the-Loop (HITL) Approval Gates

Autonomous agents handling critical workflows (financial operations, database writes, user communications) require deterministic approval barriers. n8n natively manages this via the **Wait Node** in conjunction with an external webhook trigger, pausing execution threads cleanly without consuming CPU cycles.

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│ AI Agent Output │──────▶│ Telegram/Slack  │──────▶│ Wait Node       │
│ Proposes Action │       │ Interactive Msg │       │ (Resume on Hook)│
└─────────────────┘       └─────────────────┘       └────────┬────────┘
                                                             │
                  ┌──────────────────────────────────────────┘
                  ▼
         ┌───────────────────┐
         │ Webhook Execution │
         │   Verification    │
         └────────┬──────────┘
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
   [APPROVED]          [REJECTED]
        │                   │
        ▼                   ▼
 Execute Action      Halt & Notify
```

### 3.1 Slack Interactive Block Kit Configuration

When using the Slack node to construct interactive approval notifications:

1. Add a **Slack Node** configured to `Resource: Message`, `Operation: Post`.
2. Set `Authentication: Bot Token`.
3. In the **Blocks (JSON)** field, insert the following structure. It uses n8n variables to embed execution IDs and the webhook callback target:

```json
[
  {
    "type": "header",
    "text": {
      "type": "plain_text",
      "text": "🚨 Critical Agent Approval Required",
      "emoji": true
    }
  },
  {
    "type": "section",
    "fields": [
      {
        "type": "mrkdwn",
        "text": "*Execution ID:*\n`{{ $execution.id }}`"
      },
      {
        "type": "mrkdwn",
        "text": "*Confidence Score:*\n`{{ $('Code Parser').item.json.data.resolution_confidence_score }}`"
      }
    ]
  },
  {
    "type": "section",
    "text": {
      "type": "mrkdwn",
      "text": "*Proposed Remediations:*\n```{{ JSON.stringify($('Code Parser').item.json.data.remediation_steps, null, 2) }}```"
    }
  },
  {
    "type": "divider"
  },
  {
    "type": "actions",
    "elements": [
      {
        "type": "button",
        "text": {
          "type": "plain_text",
          "text": "Approve & Execute",
          "emoji": true
        },
        "style": "primary",
        "value": "approved",
        "action_id": "approve_action",
        "url": "https://n8n.yourdomain.com/webhook/hitl-resume?executionId={{ $execution.id }}&action=approved&token={{ $env.HITL_HMAC_SECRET }}"
      },
      {
        "type": "button",
        "text": {
          "type": "plain_text",
          "text": "Reject Action",
          "emoji": true
        },
        "style": "danger",
        "value": "rejected",
        "action_id": "reject_action",
        "url": "https://n8n.yourdomain.com/webhook/hitl-resume?executionId={{ $execution.id }}&action=rejected&token={{ $env.HITL_HMAC_SECRET }}"
      }
    ]
  }
]
```

### 3.2 Telegram Inline Keyboard Markup Pattern

For Telegram deployments, instantiate an **HTTP Request Node** pointing to `https://api.telegram.org/bot<TOKEN>/sendMessage`.

**Payload (Body Parameters):**

```json
{
  "chat_id": "{{ $env.TELEGRAM_ADMIN_CHAT_ID }}",
  "parse_mode": "MarkdownV2",
  "text": "*AWAITING AGENT CONFIRMATION*\n\n*Incident:* `{{ $('Code Parser').item.json.data.incident_id.replace('-', '\\-') }}`\n*Severity:* `{{ $('Code Parser').item.json.data.severity }}`\n\nApprove destructive mitigation step?",
  "reply_markup": {
    "inline_keyboard": [
      [
        {
          "text": "✅ Execute Patch",
          "url": "https://n8n.yourdomain.com/webhook/hitl-resume?executionId={{ $execution.id }}&action=approved&token={{ $env.HITL_HMAC_SECRET }}"
        },
        {
          "text": "❌ Kill Thread",
          "url": "https://n8n.yourdomain.com/webhook/hitl-resume?executionId={{ $execution.id }}&action=rejected&token={{ $env.HITL_HMAC_SECRET }}"
        }
      ]
    ]
  }
}
```

### 3.3 The Wait Node & Asynchronous Webhook Callback Receiver

The approval cycle uses two separate workflows: the **Main Execution Pipeline** and the **HITL Webhook Receiver**.

#### Workflow A: Main Execution Pipeline
1. Processing finishes at the **Wait Node**.
2. Configure **Wait Node**:
   * `Resume`: **On Webhook Call**
   * `Webhook Suffix`: `hitl-resume-{{ $execution.id }}`
   * `Limit Wait Time`: Enabled (e.g., `24 Hours`).
   * `Fallback Strategy`: Continue workflow down the "Timeout" branch, automatically setting action to `REJECTED_TIMEOUT`.

#### Workflow B: HITL Webhook Receiver (Centralized Router)
This workflow handles inbound HTTP calls from Slack/Telegram, verifies security tokens, and completes execution using the n8n REST API.

```javascript
// Webhook Router Node: Validate Callback & Resume Execution via n8n Internal API
const query = $input.first().json.query;
const headers = $input.first().json.headers;

const executionId = query.executionId;
const action = query.action;
const providedToken = query.token;
const internalSecret = $env.HITL_HMAC_SECRET;

// 1. Authenticate Request
if (!providedToken || providedToken !== internalSecret) {
  return [{
    json: {
      httpStatus: 403,
      responseBody: "ACCESS_DENIED: Invalid security validation token."
    }
  }];
}

// 2. Validate Action Inputs
if (!executionId || !["approved", "rejected"].includes(action)) {
  return [{
    json: {
      httpStatus: 400,
      responseBody: "BAD_REQUEST: Missing valid executionId or action enum."
    }
  }];
}

// 3. Construct Payload to complete the Waiting Node via n8n API
return [{
  json: {
    httpStatus: 200,
    responseBody: `Success: Action [${action.toUpperCase()}] dispatched to execution ${executionId}.`,
    targetUrl: `http://localhost:5678/rest/executions/${executionId}/resume`,
    resumePayload: {
      approved: action === "approved",
      decision_by: headers['x-forwarded-for'] || "network_admin",
      resolved_at: new Date().toISOString()
    }
  }
}];
```

Direct the output of this Code node to an **HTTP Request Node** targeting the internal n8n REST endpoint to unpause the paused thread.

---

## 4. Enterprise State Persistence & Thread Memory

Default in-memory agent buffers are ephemeral: when the container restarts or memory scales under load, all historical state is lost. Enterprise pipelines require an external, indexed persistence tier.

### 4.1 Memory Architecture Comparison

| Memory Provider | Latency | Distributed Support | Cost | Query/Filtering Capability | Production Suitability |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Window Buffer (In-Memory)** | 0ms | ❌ No | Free | None | Prototype only. Discards historical state across workers. |
| **Redis Chat Memory** | <2ms | ✅ Yes | Low | Limited (Key-Value/TTL based) | High throughput, sub-millisecond session lookup. |
| **PostgreSQL Chat Memory** | 5-15ms | ✅ Yes | Low-Medium | Complete (Full SQL, JSONB search, ACID) | Maximum resilience, auditability, structured entity tracking. |

### 4.2 Production PostgreSQL Chat Memory DDL

Deploy the following relational schema into your persistence database to host conversation memory, tool telemetry, and audit trails:

```sql
-- Migration: Create Agent Memory and Telemetry Framework
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE agent_conversations (
    session_id VARCHAR(255) PRIMARY KEY,
    organization_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_agent_conversations_org_user ON agent_conversations(organization_id, user_id);

CREATE TABLE agent_messages (
    message_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(255) NOT NULL REFERENCES agent_conversations(session_id) ON DELETE CASCADE,
    sender_type VARCHAR(32) NOT NULL CHECK (sender_type IN ('system', 'human', 'ai', 'tool')),
    content TEXT NOT NULL,
    tool_calls JSONB DEFAULT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_messages_session_lookup ON agent_messages(session_id, created_at ASC);

-- Telemetry log for analytics and debugging
CREATE TABLE agent_execution_telemetry (
    telemetry_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(255) REFERENCES agent_conversations(session_id),
    model_name VARCHAR(128) NOT NULL,
    latency_ms INTEGER NOT NULL,
    estimated_cost_usd NUMERIC(10, 6) DEFAULT 0.000000,
    error_occurred BOOLEAN DEFAULT FALSE,
    error_payload JSONB DEFAULT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_telemetry_exec_id ON agent_execution_telemetry(execution_id);
```

### 4.3 Scoped Session Identification Pattern

Never permit unpartitioned user input to dictate memory keys. Implement this deterministic scoping structure inside an n8n Code Node directly before passing `sessionId` to the **Postgres Chat Memory** node:

```javascript
// Node: Dynamic Scoped Session Identifier Resolver
const rawUserId = $input.first().json.user_id || "anonymous_user";
const organizationId = $input.first().json.org_id || "default_tenant";
const workflowContext = "incident_management";

// Create clean, collision-free deterministic keyspace
const sanitizedOrg = organizationId.toLowerCase().replace(/[^a-z0-9_-]/g, '');
const sanitizedUser = rawUserId.toLowerCase().replace(/[^a-z0-9_-]/g, '');

const compoundSessionId = `org_${sanitizedOrg}:usr_${sanitizedUser}:ctx_${workflowContext}`;

return [{
  json: {
    sessionId: compoundSessionId,
    org_id: sanitizedOrg,
    user_id: sanitizedUser,
    session_initialized: new Date().toISOString()
  }
}];
```

Wire `{{ $json.sessionId }}` directly into the **Session ID** parameter of the **Postgres Chat Memory** node.

---

## 5. Self-Correcting Retry & Reflection Chains

When an agent produces invalid structured data, breaks operational constraints, or fails code execution, it should not abort the execution run. The pipeline must route the error trace back to a critique agent to reconcile its own state.

```
                  ┌────────────────────────┐
                  ▼                        │
          ┌───────────────┐                │
          │ LLM Generator │                │
          └───────┬───────┘                │
                  │                        │
                  ▼                        │
          ┌───────────────┐                │ Retry with
          │ Code Sentinel │                │ Diagnostics
          └───────┬───────┘                │
                  │                        │
         [Is Schema Valid?]                │
            /          \                   │
          (No)        (Yes)                │
          /              \                 │
         ▼                ▼                │
┌────────────────┐  ┌───────────────────┐  │
│ Limit Checker  │  │ Next Pipeline Step│  │
│(Attempts <= 3?)│  └───────────────────┘  │
└───────┬────────┘                         │
        │                                  │
        └──────────────────────────────────┘
```

### 5.1 The Validation & Reflection Code Engine

This Code node acts as the deterministic gatekeeper. Place it directly downstream of the agent/LLM generator node:

```javascript
// Node: Structural Reflection & Schema Sentinel
const currentInput = $input.first().json;
const MAX_PERMISSIBLE_RETRIES = 3;

// Track or initialize iteration metadata
let retryCount = currentInput._retry_context?.retry_count || 0;
let diagnosticErrors = [];

const payload = currentInput.data || currentInput.output || currentInput;

// Deterministic Validation Rules
if (!payload.incident_id || !/^INC-[0-9]{6}$/.test(payload.incident_id)) {
  diagnosticErrors.push("Property 'incident_id' is missing or fails the required regex pattern: ^INC-[0-9]{6}$");
}

if (!["SEV-1", "SEV-2", "SEV-3", "SEV-4"].includes(payload.severity)) {
  diagnosticErrors.push("Property 'severity' must be one of strictly: ['SEV-1', 'SEV-2', 'SEV-3', 'SEV-4']");
}

if (!Array.isArray(payload.impacted_systems) || payload.impacted_systems.length === 0) {
  diagnosticErrors.push("Property 'impacted_systems' must be a non-empty array of strings.");
}

if (!Array.isArray(payload.remediation_steps) || payload.remediation_steps.length === 0) {
  diagnosticErrors.push("Property 'remediation_steps' must contain at least one remediation directive.");
} else {
  payload.remediation_steps.forEach((step, idx) => {
    if (typeof step.order !== 'number' || typeof step.command !== 'string' || typeof step.automated !== 'boolean') {
      diagnosticErrors.push(`Remediation step at index [${idx}] fails the schema contract: {order: integer, command: string, automated: boolean}.`);
    }
  });
}

// Route Decision
if (diagnosticErrors.length === 0) {
  // Validation Passed: Proceed to operational stages
  return [{
    json: {
      validation_status: "PASSED",
      sanitized_payload: payload,
      total_retries_required: retryCount
    }
  }];
} else {
  // Increment failure loop
  retryCount++;

  if (retryCount > MAX_PERMISSIBLE_RETRIES) {
    throw new Error(`CIRCUIT_BREAKER_TRIGGERED: Maximum agent retries (${MAX_PERMISSIBLE_RETRIES}) exhausted. Diagnostics: ${diagnosticErrors.join(' | ')}`);
  }

  // Validation Failed: Construct self-correction context for loopback
  return [{
    json: {
      validation_status: "FAILED_RETRY_REQUIRED",
      _retry_context: {
        retry_count: retryCount,
        max_retries: MAX_PERMISSIBLE_RETRIES,
        diagnostic_feedback: diagnosticErrors,
        failed_payload: payload
      }
    }
  }];
}
```

### 5.2 Reflection Sub-Prompt Directive

Feed the `FAILED_RETRY_REQUIRED` branch of an **If Node** directly into a secondary corrective LLM node or loop back to the primary agent using this prompt configuration:

```text
CRITICAL NOTICE: Your previous output failed schema validation.

VALIDATION ENGINE DIAGNOSTICS:
{{ $('Sentinel Code').item.json._retry_context.diagnostic_feedback.map((msg, i) => `${i + 1}. ${msg}`).join('\n') }}

ORIGINAL MALFORMED SUBMISSION:
```json
{{ JSON.stringify($('Sentinel Code').item.json._retry_context.failed_payload, null, 2) }}
```

INSTRUCTIONS FOR REPAIR:
1. Fix every listed diagnostic violation directly.
2. Maintain all other correct payload elements unchanged.
3. Emit exclusively the corrected JSON object.
4. Attempt Number: {{ $('Sentinel Code').item.json._retry_context.retry_count }} of {{ $('Sentinel Code').item.json._retry_context.max_retries }}.
```

---

## 6. End-to-End Orchestration Blueprint

The following system reference card provides an architectural blueprint for connecting all components of this module into a single production workflow.

### 6.1 Complete Workflow Topology

```
[Webhook: Postmortem Intake]
              │
              ▼
    [Code: Scope Session]
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│ n8n AI Agent Engine                                         │
│                                                             │
│  [OpenAI Chat Model] (Temp = 0.1)                           │
│  [Postgres Memory]   (Session = $json.sessionId)            │
│  [Structured Parser] (Incident Schema Contract)             │
│  [Code Tool]         (Entity Security Interceptor)          │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
                [Code
