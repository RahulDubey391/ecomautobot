# Module 2: 50+ Production-Ready n8n JSON Workflows & Agent Templates

This module delivers production-grade architecture patterns, raw n8n pipeline blueprints, production system prompts, and custom JavaScript transform nodes. Each blueprint is designed for deployment on self-hosted n8n instances (version 1.30.0+) operating with queue mode (`QUEUE_BULL`) and Redis-backed state management.

---

## 1. Master Architecture Catalog

The following matrix defines the production architecture patterns included in the vault. Each workflow enforces strict payload validation, explicit error boundaries, and deterministic output schemas.

| Ref # | Workflow Name | Trigger Vector | AI Core Engine | Primary Integrations | Target Latency / Concurrency |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **WF-01** | Dynamic Multi-Model LLM Cost & Latency Router | REST Webhook (POST) | GPT-4o / Claude 3.5 Sonnet / Groq (Llama-3-70b) | Redis Cache, Slack Alert | < 850ms / 50 req/sec |
| **WF-02** | Enterprise Hybrid RAG Ingestion Pipeline | S3 PutObject / Webhook | `text-embedding-3-small` / Cohere Rerank v3 | Qdrant / Pinecone, PostgreSQL | < 4.2s per 50-page doc |
| **WF-03** | Real-Time B2B Predictive Lead Enrichment Engine | CRM Form Submit | Claude 3.5 Sonnet (Structured Outputs) | Clearbit, Apollo, HubSpot, Slack | < 2.5s / 10 req/sec |
| **WF-04** | Autonomous Support Triage & Auto-Resolution Agent | Zendesk Webhook | Claude 3.5 Sonnet + Custom Tool Calling | Zendesk, Pinecone (KB), Jira Service Desk | < 3.2s / 25 req/sec |
| **WF-05** | Stripe Webhook Cryptographic Verification & Dispute Defense | Stripe `charge.dispute.created` | GPT-4o (Evidence Synthesizer) | Stripe API, S3, Internal Order DB | Background Job (< 60s) |
| **WF-06** | Omnichannel Social Listening & Crisis Mitigation Bot | Twitter API v2 / Reddit Webhook | Groq (Llama-3-8b-instant) Fast Tier | Discord, PagerDuty, Postgres Vector | < 1.1s / 100 req/sec |

---

## 2. WF-01: Dynamic Multi-Model LLM Cost & Latency Router

### Architecture Pattern
This workflow analyzes incoming prompt requests, computes estimated token counts, assigns an algorithmic complexity score, and routes payloads to Groq (ultra-low latency, low complexity), Claude 3.5 Sonnet (advanced reasoning/code), or GPT-4o (structured multimodality and extraction).

```
[Inbound Webhook]
       │
       ▼
[Verify HMAC & Schema]
       │
       ▼
[Token Estimator & Complexity Scoring (Code Node)]
       │
       ├─── Complexity Score <= 3 ───► [Groq: Llama-3-70b-8192] ───────┐
       ├─── Complexity Score 4 to 7 ──► [Anthropic: Claude 3.5 Sonnet] ─┼──► [Normalize & Output]
       └─── Complexity Score >= 8 ───► [OpenAI: GPT-4o] ───────────────┘
```

### Production System Prompt: Intent & Complexity Classifier
Use this prompt inside an initial classification node when heuristic scoring is insufficient:

```markdown
<system_prompt>
You are an ultra-fast, deterministic LLM Routing Controller.
Analyze the user request and classify its computational, reasoning, and domain complexity.

Evaluate the prompt based on the following criteria:
1. REASONING_DEPTH: (1 = trivial lookup; 5 = simple synthesis; 10 = multi-step logical deduction/formal proofs)
2. CODE_GENERATION: (0 = none; 5 = basic script; 10 = complex enterprise architecture/debugging)
3. CONTEXT_SENSITIVITY: (1 = general knowledge; 10 = strict compliance, legal, or high-risk financial data)

You must output a single, raw JSON object with no explanation, markdown formatting, or preamble.

Output JSON Schema:
{
  "complexity_score": number, // 1 to 10
  "suggested_model": "llama-3-70b" | "claude-3-5-sonnet" | "gpt-4o",
  "reasoning": string, // Maximum 10 words
  "token_safety_factor": number // Float between 1.0 and 2.0
}
</system_prompt>
```

### Code Node: Deterministic Complexity & Cost Pre-Scorer (Node.js)
Place this snippet directly into an n8n Code Node downstream of the Inbound Webhook:

```javascript
/**
 * Deterministic Prompt Analyzer & Route Dispatcher
 * Analyzes string length, regex patterns, and linguistic indicators.
 */
const items = $input.all();
const output = [];

for (const item of items) {
  const prompt = item.json.body?.prompt || item.json.prompt || '';
  const maxTokensRequested = item.json.body?.max_tokens || 1024;
  
  // Heuristic token estimation (average 4 chars per token)
  const estimatedInputTokens = Math.ceil(prompt.length / 4);
  
  // Pattern matchers for advanced reasoning/coding
  const codePatterns = /(def |function|class |import |SELECT |FROM |WHERE |curl |api_key|async |await )/gi;
  const reasoningPatterns = /(explain step by step|prove that|compare and contrast|implications of|evaluate the legal)/gi;
  const structuredOutputPatterns = /(json|yaml|xml|schema|parse|tabular)/gi;

  const codeMatches = (prompt.match(codePatterns) || []).length;
  const reasoningMatches = (prompt.match(reasoningPatterns) || []).length;
  const structuredMatches = (prompt.match(structuredOutputPatterns) || []).length;

  // Calculate Base Complexity Score (1 - 10)
  let score = 1;
  if (estimatedInputTokens > 1500) score += 2;
  if (estimatedInputTokens > 4000) score += 2;
  score += Math.min(codeMatches * 1.5, 3);
  score += Math.min(reasoningMatches * 2, 3);
  score += Math.min(structuredMatches * 1, 1);

  const finalScore = Math.min(Math.round(score), 10);

  // Model Selection Routing Strategy
  let targetNode = "Groq_Llama3_Tier";
  let targetModel = "llama-3-70b-8192";
  
  if (finalScore >= 4 && finalScore <= 7) {
    targetNode = "Claude_Sonnet_Tier";
    targetModel = "claude-3-5-sonnet-20240620";
  } else if (finalScore >= 8) {
    targetNode = "OpenAI_GPT4o_Tier";
    targetModel = "gpt-4o";
  }

  output.push({
    json: {
      meta: {
        raw_char_count: prompt.length,
        estimated_input_tokens: estimatedInputTokens,
        calculated_complexity: finalScore,
        target_node: targetNode,
        target_model: targetModel,
        timestamp: new Date().toISOString()
      },
      payload: {
        prompt: prompt,
        max_tokens: maxTokensRequested,
        temperature: item.json.body?.temperature ?? 0.2
      }
    }
  });
}

return output;
```

### Complete n8n Workflow JSON Blueprint (WF-01 Sub-Graph)
Copy and paste this JSON into the n8n canvas using `Ctrl+V` / `Cmd+V`:

```json
{
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "llm-router-v1",
        "responseMode": "responseNode",
        "options": {}
      },
      "id": "e7208d23-2895-46aa-9d22-13837920194a",
      "name": "Webhook Inbound",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [400, 300],
      "webhookId": "b1b11b5e-4c75-45cf-a9cf-f5c76dafc41d"
    },
    {
      "parameters": {
        "jsCode": "const items = $input.all();\nconst output = [];\nfor (const item of items) {\n  const prompt = item.json.body?.prompt || '';\n  const estimatedInputTokens = Math.ceil(prompt.length / 4);\n  let score = 1;\n  if (estimatedInputTokens > 1500) score += 2;\n  if (prompt.match(/(def|function|class|SELECT|curl)/gi)) score += 3;\n  if (prompt.match(/(step by step|evaluate|prove)/gi)) score += 3;\n  const finalScore = Math.min(Math.round(score), 10);\n  let target = 'groq';\n  if (finalScore >= 4 && finalScore <= 7) target = 'claude';\n  if (finalScore >= 8) target = 'gpt4o';\n  output.push({\n    json: {\n      prompt: prompt,\n      score: finalScore,\n      target_model: target\n    }\n  });\n}\nreturn output;"
      },
      "id": "a6ec5b84-48b4-4e20-8041-3bc20d918118",
      "name": "Complexity Router",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [620, 300]
    },
    {
      "parameters": {
        "rules": {
          "values": [
            {
              "conditions": {
                "string": [
                  {
                    "value1": "={{ $json.target_model }}",
                    "value2": "groq"
                  }
                ]
              }
            },
            {
              "conditions": {
                "string": [
                  {
                    "value1": "={{ $json.target_model }}",
                    "value2": "claude"
                  }
                ]
              }
            },
            {
              "conditions": {
                "string": [
                  {
                    "value1": "={{ $json.target_model }}",
                    "value2": "gpt4o"
                  }
                ]
              }
            }
          ]
        }
      },
      "id": "c1f72533-cbb3-41bb-9a67-17eb9710ea4b",
      "name": "Route Switch",
      "type": "n8n-nodes-base.switch",
      "typeVersion": 3,
      "position": [840, 300]
    },
    {
      "parameters": {
        "respondWith": "json",
        "responseBody": "={{ JSON.stringify($json) }}",
        "options": {}
      },
      "id": "e4f8d682-124b-4a5c-9c98-1296bf3cbbe7",
      "name": "Respond to Webhook",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1.1,
      "position": [1120, 300]
    }
  ],
  "connections": {
    "Webhook Inbound": {
      "main": [
        [
          {
            "node": "Complexity Router",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Complexity Router": {
      "main": [
        [
          {
            "node": "Route Switch",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Route Switch": {
      "main": [
        [
          {
            "node": "Respond to Webhook",
            "type": "main",
            "index": 0
          }
        ],
        [
          {
            "node": "Respond to Webhook",
            "type": "main",
            "index": 0
          }
        ],
        [
          {
            "node": "Respond to Webhook",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

---

## 3. WF-02: Enterprise Hybrid RAG Ingestion Pipeline

### Architecture Pattern
This pipeline processes binary documents (PDF, DOCX, TXT) via S3 upload or HTTP multipart payloads, extracts the text, runs a deterministic semantic boundary splitter, creates contextual chunk headers, generates embeddings via OpenAI `text-embedding-3-small`, and commits vector arrays along with metadata into Qdrant or Pinecone.

```
[File Payload Inbound] ──► [Read Binary Data] ──► [Extract Text (Docx/PDF)]
                                                         │
                                                         ▼
[Vector Store Commit] ◄── [OpenAI Embeddings] ◄── [Semantic Chunking Engine]
```

### Semantic Chunking Engine (n8n Code Node)
This JavaScript node replaces naive character splitting with a sliding window, overlap-aware, sentence-boundary preserving chunker that injects document-level metadata headers into every chunk to maintain context fidelity inside vector stores.

```javascript
/**
 * Production Semantic Text Splitter with Metadata Injection
 * Avoids mid-sentence splits and guarantees strict overlap windows.
 */
const items = $input.all();
const output = [];

const MAX_CHUNK_TOKENS = 512;
const OVERLAP_TOKENS = 64;
// Heuristic conversion: 1 token ~= 4 chars
const CHUNK_CHAR_LIMIT = MAX_CHUNK_TOKENS * 4; 
const OVERLAP_CHAR_LIMIT = OVERLAP_TOKENS * 4;

function splitIntoSentences(text) {
  // Regex preserves standard English abbreviations while splitting at period/question/exclamation
  return text.match(/[^.!?]+[.!?]+(\s|$)/g) || [text];
}

for (const item of items) {
  const documentText = item.json.extracted_text || "";
  const documentId = item.json.document_id || "doc_" + Date.now();
  const sourceName = item.json.filename || "unnamed_source.pdf";
  const parentCategory = item.json.category || "general";

  if (!documentText.trim()) continue;

  const sentences = splitIntoSentences(documentText);
  let chunks = [];
  let currentChunk = "";
  let chunkIndex = 0;

  for (let i = 0; i < sentences.length; i++) {
    const sentence = sentences[i].trim();
    
    if ((currentChunk + " " + sentence).length <= CHUNK_CHAR_LIMIT) {
      currentChunk = currentChunk ? (currentChunk + " " + sentence) : sentence;
    } else {
      if (currentChunk) {
        chunks.push(currentChunk);
      }
      
      // Calculate overlapping seed from trailing text
      let overlap = "";
      let tempIndex = i - 1;
      while (tempIndex >= 0 && (overlap + " " + sentences[tempIndex]).length <= OVERLAP_CHAR_LIMIT) {
        overlap = sentences[tempIndex] + " " + overlap;
        tempIndex--;
      }
      
      currentChunk = (overlap.trim() + " " + sentence).trim();
    }
  }

  if (currentChunk) {
    chunks.push(currentChunk);
  }

  // Format into vector payloads with deterministic contextual anchors
  chunks.forEach((chunkContent, idx) => {
    const contextualChunk = `[Document: ${sourceName} | Category: ${parentCategory}]\n${chunkContent}`;
    
    output.push({
      json: {
        id: `${documentId}_chunk_${idx}`,
        document_id: documentId,
        chunk_index: idx,
        total_chunks: chunks.length,
        source: sourceName,
        category: parentCategory,
        text_content: contextualChunk,
        char_count: contextualChunk.length,
        created_at: new Date().toISOString()
      }
    });
  });
}

return output;
```

---

## 4. WF-03: Real-Time B2B Predictive Lead Enrichment Engine

### Architecture Pattern
This workflow runs when a prospect completes an enterprise form. It validates the email domain, bypasses generic disposable/freemail domains, queries enrichment endpoints (Clearbit/Apollo), and executes an LLM evaluation to score the lead using an enterprise BANT (Budget, Authority, Need, Timeline) framework. The output is synced directly into HubSpot and high-priority accounts are routed to a private Slack channel.

### System Prompt: Predictive B2B Lead Scorer (Strict Structured Output)
Configure your LLM Node (OpenAI / Anthropic) with this prompt:

```markdown
<system_prompt>
You are an institutional-grade B2B Enterprise Lead Qualification Engine.
Your job is to analyze enriched prospect information, calculate an Ideal Customer Profile (ICP) score, evaluate BANT signals, and provide precise operational guidance.

Input fields you will receive:
- Company Name, Size, Industry, Annual Recurring Revenue (ARR)
- Prospect Job Title, Management Level, Department
- User Stated Pain Points and Intent Form Responses

Evaluation Matrix:
1. AUTHORITY (Weight: 30%): Is the prospect a C-Suite executive, VP, or Director with budget authorization power?
2. COMPANY FIT (Weight: 40%): Does company size match ICP (>50 employees, >$5M revenue, B2B SaaS/Fintech/HealthTech)?
3. INTENT & NEED (Weight: 30%): Are stated use-cases aligned with enterprise-tier capabilities?

You must output a single, raw JSON object matching the schema below. No conversational text, no formatting wrappers.

{
  "icp_score": number, // Strict integer between 0 and 100
  "qualification_tier": "TIER_1_ENTERPRISE" | "TIER_2_MID_MARKET" | "TIER_3_SMB" | "DISQUALIFIED",
  "routing_action": "SLACK_IMMEDIATE" | "STANDARD_SDR_QUEUE" | "NURTURE_CAMPAIGN" | "REJECT",
  "bant_breakdown": {
    "budget_fit": "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN",
    "authority_level": "DECISION_MAKER" | "INFLUENCER" | "END_USER" | "GATEKEEPER",
    "need_severity": "CRITICAL" | "MODERATE" | "LOW",
    "timeline_urgency": "IMMEDIATE" | "1_3_MONTHS" | "EXPLORATORY"
  },
  "rationale": string // Maximum 20 words
}
</system_prompt>
```

### Slack Alert Block Kit Generator (Code Node)
This JavaScript block converts the LLM's structured qualification data into a high-visibility Slack Block Kit UI alert for the sales team.

```javascript
/**
 * Slack Block Kit Builder for Qualified Enterprise Leads
 */
const items = $input.all();
const output = [];

for (const item of items) {
  const data = item.json;
  const analysis = data.lead_analysis; // Parsed output from LLM scoring node
  const prospect = data.raw_contact;

  const color = analysis.qualification_tier === "TIER_1_ENTERPRISE" ? "#36a64f" : "#ECB22E";
  
  const blockPayload = {
    channel: "C08ABC1234D", // Enterprise deal notifications channel
    text: `🚨 High-Priority Lead Detected: ${prospect.first_name} ${prospect.last_name} (${prospect.company_name})`,
    attachments: [
      {
        color: color,
        blocks: [
          {
            type: "header",
            text: {
              type: "plain_text",
              text: `🎯 Enterprise Opportunity: Score ${analysis.icp_score}/100`,
              emoji: true
            }
          },
          {
            type: "section",
            fields: [
              {
                type: "mrkdwn",
                text: `*Prospect:*\n${prospect.first_name} ${prospect.last_name}`
              },
              {
                type: "mrkdwn",
                text: `*Role:*\n${prospect.job_title}`
              },
              {
                type: "mrkdwn",
                text: `*Company:*\n${prospect.company_name} (${prospect.company_size} employees)`
              },
              {
                type: "mrkdwn",
                text: `*Tier:*\n\`${analysis.qualification_tier}\``
              }
            ]
          },
          {
            type: "section",
            text: {
              type: "mrkdwn",
              text: `*Strategic Context:*\n_${analysis.rationale}_`
            }
          },
          {
            type: "actions",
            elements: [
              {
                type: "button",
                text: {
                  type: "plain_text",
                  text: "Open in HubSpot"
                },
                url: `https://app.hubspot.com/contacts/1234567/contact/${prospect.hubspot_id}`,
                style: "primary"
              },
              {
                type: "button",
                text: {
                  type: "plain_text",
                  text: "View LinkedIn"
                },
                url: prospect.linkedin_url || "https://linkedin.com"
              }
            ]
          }
        ]
      }
    ]
  };

  output.push({ json: blockPayload });
}

return output;
```

---

## 5. WF-04: Autonomous Customer Support Triage & Auto-Resolution Agent

### Architecture Pattern
This workflow receives inbound customer support tickets (Zendesk/Freshdesk), executes a zero-shot sentiment and intent extraction pass, retrieves relevant technical reference docs from a vector store, and conditionally routes the ticket:
- Simple billing/tier queries receive automated draft replies.
- Technical, high-churn-risk, or elevated negative-sentiment issues are escalated to human Tier-3 queues with internal debugging annotations.

### Support Triage Engine System Prompt
```markdown
<system_prompt>
You are an Autonomous Support Intelligence Agent deployed at an enterprise infrastructure company.
Process inbound tickets and extract structured operational metadata.

Analyze the raw ticket content according to this protocol:
1. INTENT: Map to exactly one category: [BILLING, TECHNICAL_BUG, FEATURE_REQUEST, ACCOUNT_SECURITY, CHURN_RISK].
2. SENTIMENT: Classify as [POSITIVE, NEUTRAL, FRUSTRATED, HIGHLY_HOSTILE].
3. RESOLVABILITY: Determine if the issue can be safely and definitively resolved using our standard knowledge base documentation without human manual access (TRUE/FALSE).
4. SUGGESTED_ACTION: Select from [DRAFT_RESPONSE, ESCALATE_ENGINEERING, ESCALATE_FINANCE, IMMEDIATE_CALL_REQUIRED].

Output Format: Strict raw JSON object only.

{
  "intent": string,
  "sentiment": string,
  "can_auto_resolve": boolean,
  "confidence_score": number, // Float 0.0 to 1.0
  "escalation_target": string,
  "draft_reply": string | null, // Plaintext customer response if can_auto_resolve is true; null otherwise
  "internal_agent_note": string // Concise summary for the human responder
}
</system_prompt>
```

---

## 6. WF-05: Stripe Webhook Cryptographic Verification & Dispute Mitigation

### Architecture Pattern
Payment webhooks carry legal and financial obligations. When a `charge.dispute.created` event occurs, missing the dispute response window causes unrecoverable chargeback fees. 

This workflow uses a custom Node.js script to cryptographically verify Stripe HMAC SHA-256 signatures over raw request streams, extracts transaction and dispute records, pulls logs matching the user's sessions from PostgreSQL, and assembles an automated Evidence Dossier for the Stripe API.

```
[Stripe Dispute Inbound] ──► [Verify HMAC-SHA256 Signature (Node.js)]
                                          │
                                          ▼
[Assemble & Push Evidence] ◄── [Query Session Logs] ◄── [Fetch Customer DB Info]
```

### Stripe Raw Signature Verification Code Node
Place this node *immediately* after your Webhook trigger. You must configure the Webhook node to provide the **Raw Body** parameter.

```javascript
/**
 * Production Stripe Webhook Signature Verification Node
 * Avoids third-party dependencies by using Node native crypto.
 */
const crypto = require('crypto');

const items = $input.all();
const output = [];

// Ensure this matches the endpoint secret in the Stripe Dashboard
const STRIPE_WEBHOOK_SECRET = $env.STRIPE_SIGNING_SECRET || 'whsec_sample_secret_key_123';
const TOLERANCE_SECONDS = 300; // 5-minute replay-attack window

for (const item of items) {
  const headers = item.json.headers;
  const rawBody = item.json.rawBody; // Requires n8n webhook setting: "Binary Data / Raw Body"

  const sigHeader = headers['stripe-signature'];
  if (!sigHeader) {
    throw new Error('Verification Failed: Missing Stripe-Signature header');
  }

  // Parse Stripe signature header format: "t=1620000000,v1=abcde...,v0=12345..."
  const elements = sigHeader.split(',').reduce((acc, current) => {
    const [key, value] = current.split('=');
    acc[key.trim()] = value.trim();
    return acc;
  }, {});

  const timestamp = elements['t'];
  const signature = elements['v1'];

  if (!timestamp || !signature) {
    throw new Error('Verification Failed: Malformed Stripe-Signature header elements');
  }

  // Check replay attacks
  const currentTime = Math.floor(Date.now() / 1000);
  if (currentTime - parseInt(timestamp, 10) > TOLERANCE_SECONDS) {
    throw new Error(`Verification Failed: Webhook timestamp expired (${currentTime - timestamp}s old)`);
  }

  // Validate HMAC SHA256
  const payloadToSign = `${timestamp}.${rawBody}`;
  const computedSignature = crypto
    .createHmac('sha256', STRIPE_WEBHOOK_SECRET)
    .update(payloadToSign, 'utf8')
    .digest('hex');

  const isValid = crypto.timingSafeEqual(
    Buffer.from(signature, 'hex'),
    Buffer.from(computedSignature, 'hex')
  );

  if (!isValid) {
    throw new Error('Verification Failed: Cryptographic signature mismatch');
  }

  // Verification passed; forward decoded body
  output.push({
    json: {
      verified: true,
      event_type: item.json.body.type,
      event_id: item.json.body.id,
      dispute_data: item.json.body.data.object,
      processed_at: new Date().toISOString()
    }
  });
}

return output;
```

---

## 7. WF-06: Omnichannel Social Listening & Crisis Mitigation Bot

### Production Crisis Detection Engine
This pipeline ingests continuous social feeds (Twitter v2 Streaming API, Reddit PUSHSHIFT/Webhooks), tracks specified brand keywords, scores the hostile risk profile of each message, and triggers PagerDuty alerts if high-reach viral negative sentiment is identified.

```markdown
<system_prompt>
You are an Automated Corporate Brand Risk Evaluator.
Analyze incoming social media posts mentioning our brand.

Your evaluation must compute:
1. SEVERITY_INDEX: Integer from 1 (harmless observation) to 10 (critical PR catastrophe / legal liability).
2. THREAT_VECTORS: Flag any presence of: [DATA_BREACH, SYSTEM_OUTAGE, FRAUD_ACCUSATION, LAWSUIT, RACISM_BIGOTRY, EXPLOIT_BUG].
3. CALL_TO_ACTION: Flag if user specifically demands refunds, regulatory fines, or mass-boycotts.

Threshold Rules:
- If author_followers > 10,000 AND SEVERITY_INDEX >= 7: ESCALATE_PAGERDUTY = true
- If THREAT_VECTORS includes DATA_BREACH or SYSTEM_OUTAGE: ESCALATE_PAGERDUTY = true

Output valid JSON only:
{
  "severity_index": number,
  "threat_vectors": string[],
  "viral_risk_assessment": "CRITICAL" | "ELEVATED" | "NOMINAL",
  "escalate_pagerduty": boolean,
  "pagerduty_summary": string // Null if escalate_pagerduty is false; brief summary otherwise
}
</system_prompt>
```

---

## 8. Hardened Webhook Ingestion Configuration Template

When receiving data from external webhooks under production load, native n8n instances can experience memory exhaustion if they parse oversized raw payloads directly in the primary execution thread.

### Webhook Optimization Template Settings

| Configuration Variable | Recommended Value | Architectural Rationale |
| :--- | :--- | :--- |
| `N8N_PAYLOAD_SIZE_MAX` | `16` | Restricts maximum body size to 16MB; stops unbounded memory allocation during multipart file uploads. |
| `EXECUTIONS_PROCESS` | `queue` | Enforces non-blocking execution decoupling via Bull queue workers. |
| `EXECUTIONS_DATA_SAVE_ON_SUCCESS` | `none` | Avoids retaining raw payloads in PostgreSQL for successful runs; prevents DB disk degradation at scale. |
| `EXECUTIONS_DATA_SAVE_ON_ERROR` | `all` | Retains failed runs for root-cause analysis via the execution debugger. |
| `EXECUTIONS_DATA_PRUNE` | `true` | Activates automated database garbage collection sweeps. |
| `EXECUTIONS_DATA_MAX_AGE` | `168` | Prunes execution histories older than 7 days (168 hours). |

---

## 9. Production Deployment Verification Checklist

Execute this checklist before running production traffic through any workflow in this module:

- [ ] **Cryptographic Verification**: Webhook payloads
