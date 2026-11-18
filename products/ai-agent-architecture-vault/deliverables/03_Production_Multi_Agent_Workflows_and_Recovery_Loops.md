# Module 3: 25+ Multi-Agent Workflows, Swarms & Self-Correction Loops

Production multi-agent systems fail when they rely on unconstrained natural language dialogues between agents. High-reliability agent systems operate as deterministic state machines that leverage Large Language Models (LLMs) strictly for bounded extraction, synthesis, and routing decisions. 

This module provides the architectural patterns, state transition schemas, self-correction algorithms, and executable implementation code required to deploy mission-critical swarms and recovery loops.

---

## 1. Architecture Topology & State Machine Primitives

Multi-agent topologies must balance autonomy with deterministic constraints. Every workflow in this module is anchored to one of four topological primitives:

```
1. Hierarchical Supervisor:
   [Supervisor] ---> [Worker A]
        |        ---> [Worker B]
        +------------ [Worker C]

2. Sequential Assembly Line:
   [Ingress] -> [Agent 1] -> [Validation Gate] -> [Agent 2] -> [Egress]
                                    | (Fail)
                                    v
                             [Self-Correction]

3. Fan-Out / Fan-In Swarm:
   [Dispatcher] ---> [Worker 1] ---\
                ---> [Worker 2] ---> [Aggregator / Consensus]
                ---> [Worker 3] ---/

4. Human-in-the-Loop Escalation:
   [Agent] <--> [Verification Loop]
                     | (Confidence < Threshold OR Policy Exception)
                     v
             [Human Triage Queue]
```

### 1.1 Multi-Agent Topology Routing Matrix

| Topology Pattern | Primary Use Case | State Persistence | Failure Mode | Recovery Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Hierarchical Supervisor** | Complex planning with open-ended execution paths | Centralized State Graph | Worker deadlocks, Supervisor hallucinations | Supervisor task timeout + dynamic re-assignment |
| **Sequential Assembly Line** | Document pipelines, code generation & linting | Monotonic Context Accumulator | Pipeline poison pills, cascading drift | Node-level validation gates + rollback to prior checkpoint |
| **Fan-Out / Fan-In Swarm** | High-throughput web research, distributed diff analysis | Ephemeral worker state, shared reducer | Straggler workers, conflicting extractions | Quorum-based consensus, outlier rejection |
| **Escalate-to-Human** | Financial actions, sensitive customer ops | Append-only audit log with interrupt status | False negatives on risk classification | Deterministic heuristic tripwires bypassing LLM triage |

### 1.2 State Transition Circuit Breaker Specification

When an agent enters an error state (e.g., tool execution error, schema validation failure, infinite semantic loop), the execution engine must not re-prompt blindly. It routes through this deterministic circuit breaker:

```
[Agent Execution State]
         |
    (Tool/Schema Error)
         v
+-------------------------------+
| Check Retry Budget (Max: 3)   |
+-------------------------------+
  |                           |
  | (Attempts < 3)            | (Attempts >= 3)
  v                           v
+-----------------------+   +------------------------------------+
| Error Classification: |   | TRIP CIRCUIT:                      |
| 1. Syntax/Schema      |   | 1. Write state snapshot to DLQ     |
| 2. Logic/Precondition |   | 2. Revert DB / state changes       |
| 3. Environment/API    |   | 3. Return Fallback OR Escalate     |
+-----------------------+   +------------------------------------+
  |
  v
+------------------------------------+
| Inject Deterministic Repair Prompt |
| + Schema Diff / Compiler Trace     |
+------------------------------------+
  |
  v
[Re-Execute Step]
```

---

## 2. Blueprint 1: Autonomous Research Swarm (Fan-Out / Fan-In)

This blueprint coordinates an Orchestrator that breaks down an ambiguous research question into isolated sub-hypotheses, parallelizes worker scraping agents, enforces fact-checking, and generates a structured research dossier.

```
                              [Research Orchestrator]
                                         |
               +-------------------------+-------------------------+
               | (Sub-Task 1)            | (Sub-Task 2)            | (Sub-Task 3)
               v                         v                         v
        [Domain Worker A]         [Domain Worker B]         [Domain Worker C]
               |                         |                         |
        (Raw Findings)            (Raw Findings)            (Raw Findings)
               +-------------------------+-------------------------+
                                         |
                                         v
                            [Fact-Checking Verification Gate]
                                         |
                                 (Pass Verification)
                                         v
                               [Synthesis Reducer]
```

### 2.1 Lead Orchestrator System Prompt & Schema

```yaml
role: "Lead Research Orchestrator"
objective: "Deconstruct research requests into independent, non-overlapping search hypotheses."
execution_rules:
  - "Produce exactly between 2 and 4 sub-tasks based on topic complexity."
  - "Every task must target an orthogonal dimension (e.g., Architecture, Benchmarks, Failure Modes)."
  - "Explicitly define required search vectors and acceptance criteria for each worker."
  - "Return output matching the orchestrator_schema exactly."
```

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OrchestratorDecompositionPlan",
  "type": "object",
  "properties": {
    "research_objective": { "type": "string" },
    "sub_tasks": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "task_id": { "type": "string" },
          "target_dimension": { "type": "string" },
          "directed_queries": {
            "type": "array",
            "items": { "type": "string" }
          },
          "required_evidence_keys": {
            "type": "array",
            "items": { "type": "string" }
          }
        },
        "required": ["task_id", "target_dimension", "directed_queries", "required_evidence_keys"]
      }
    }
  },
  "required": ["research_objective", "sub_tasks"]
}
```

### 2.2 Sub-Agent Worker System Prompts

#### Domain Search Worker
```markdown
You are a Targeted Search Worker. You receive a task ID, a targeted dimension, and directed search queries.
Your responsibilities:
1. Emulate execution of targeted search queries against available search APIs.
2. Extract exact technical claims, system performance metrics, and implementation trade-offs.
3. Reject marketing prose, generic definitions, and circular commentary.
4. Output your extractions in the required structured evidence format.

Output Format:
```json
{
  "task_id": "<TASK_ID>",
  "dimension": "<DIMENSION>",
  "extracted_evidence": [
    {
      "source_url": "https://...",
      "claim": "Specific performance metric or architecture constraint",
      "confidence_score": 0.95,
      "raw_quote": "Exact substring from source"
    }
  ]
}
```
```

#### Fact-Checking Verification Agent
```markdown
You are an Adversarial Fact-Checker. You evaluate extracted evidence from Workers before aggregation.
Verification Rules:
1. Check if the claim is fully supported by the raw quote. If the raw quote does not explicitly support the claim, set `verified: false`.
2. Check for numeric consistency across sources. If source A states latency is 10ms and source B states 100ms for the same setup, flag as `CONTRADICTION`.
3. If more than 30% of claims fail verification, reject the batch and flag the worker output for re-querying.

Output Format:
```json
{
  "batch_passed": true,
  "invalid_claims": [],
  "retained_evidence": [
    {
      "claim": "Verified statement",
      "source_url": "https://...",
      "verification_notes": "Quote strictly supports claim."
    }
  ]
}
```
```

### 2.3 Deterministic Python Orchestrator Implementation

```python
import asyncio
from typing import List, Dict, Any
from pydantic import BaseModel, Field

class SubTask(BaseModel):
    task_id: str
    target_dimension: str
    directed_queries: List[str]
    required_evidence_keys: List[str]

class DecompositionPlan(BaseModel):
    research_objective: str
    sub_tasks: List[SubTask]

class RawEvidence(BaseModel):
    source_url: str
    claim: str
    confidence_score: float
    raw_quote: str

class WorkerResult(BaseModel):
    task_id: str
    dimension: str
    extracted_evidence: List[RawEvidence]

class VerifiedEvidence(BaseModel):
    claim: str
    source_url: str
    verification_notes: str

class VerificationResult(BaseModel):
    batch_passed: bool
    retained_evidence: List[VerifiedEvidence]
    invalid_claims: List[str]

# --- Mock LLM Interface Callers (Replace with your direct model provider client) ---

async def call_orchestrator(query: str) -> DecompositionPlan:
    # Simulates decomposition of user prompt into structured tasks
    return DecompositionPlan(
        research_objective=query,
        sub_tasks=[
            SubTask(
                task_id="task_1",
                target_dimension="Engine Architecture",
                directed_queries=["vLLM PagedAttention architecture paper", "TGI continuous batching spec"],
                required_evidence_keys=["memory_allocation", "throughput_multiplier"]
            ),
            SubTask(
                task_id="task_2",
                target_dimension="Latency Benchmarks",
                directed_queries=["vLLM vs TGI token latency Llama 3 70B A100"],
                required_evidence_keys=["ttft", "tpot"]
            )
        ]
    )

async def execute_worker_node(sub_task: SubTask) -> WorkerResult:
    # Simulates worker fan-out: search execution + extraction
    await asyncio.sleep(0.1) # Network I/O simulation
    return WorkerResult(
        task_id=sub_task.task_id,
        dimension=sub_task.target_dimension,
        extracted_evidence=[
            RawEvidence(
                source_url="https://arxiv.org/abs/2309.06180",
                claim="PagedAttention reduces KV cache fragmentation to below 4%.",
                confidence_score=0.98,
                raw_quote="KV cache memory fragmentation is reduced to under 4% in production workloads."
            )
        ]
    )

async def execute_verification_gate(worker_results: List[WorkerResult]) -> List[VerifiedEvidence]:
    # Aggregates across all workers and executes verification
    verified_pool: List[VerifiedEvidence] = []
    for wr in worker_results:
        for ev in wr.extracted_evidence:
            # Deterministic check: Raw quote must contain the core subject of the claim
            if "under 4%" in ev.raw_quote and "fragmentation" in ev.claim.lower():
                verified_pool.append(
                    VerifiedEvidence(
                        claim=ev.claim,
                        source_url=ev.source_url,
                        verification_notes="Claim substantiated by exact substring matching."
                    )
                )
    return verified_pool

async def execute_reducer_synthesis(objective: str, evidence: List[VerifiedEvidence]) -> str:
    # Synthesis over verified nodes only
    summary_lines = [f"- {e.claim} (Source: {e.source_url})" for e in evidence]
    return f"# Research Report: {objective}\n\n## Verified Key Findings\n" + "\n".join(summary_lines)

# --- Orchestration Runner ---

async def run_autonomous_research_swarm(objective: str) -> str:
    # Step 1: Decomposition
    plan = await call_orchestrator(objective)
    
    # Step 2: Fan-Out Execution
    worker_coroutines = [execute_worker_node(task) for task in plan.sub_tasks]
    worker_outputs: List[WorkerResult] = await asyncio.gather(*worker_coroutines)
    
    # Step 3: Verification Gate
    verified_evidence = await execute_verification_gate(worker_outputs)
    
    if not verified_evidence:
        raise RuntimeError("Quality Gate Failed: No claims survived verification.")
        
    # Step 4: Fan-In Synthesis
    final_report = await execute_reducer_synthesis(plan.research_objective, verified_evidence)
    return final_report

if __name__ == "__main__":
    report = asyncio.run(run_autonomous_research_swarm("Production LLM Inference Optimization 2024"))
    print(report)
```

---

## 3. Blueprint 2: Self-Correcting SQL Query Generator & Execution Loop

This blueprint implements a multi-step generator-reflector-executor loop. If a database query fails compilation, engine-level execution, or fails empty-result invariants, the system traps the database error and enters a bounded repair cycle.

```
       [User Natural Language Query]
                     |
                     v
      +------------------------------+
      |  Schema Introspection Context |
      +------------------------------+
                     |
                     v
          [SQL Generator Agent]
                     |
                     v
            (Run in Sandboxed DB)
                     |
          +----------+----------+
          |                     |
     (Success)               (Engine/Syntax Error)
          |                     |
          v                     v
    [Row Count Check]    [Diagnostic Error Formatter]
          |                     |
     (Rows > 0)                 v
          |              [SQL Fixer Agent]
          |                     |
          |                     +---- (Attempts < 3) ----+
          |                     |                         |
          |                     v                         |
          |              (Attempts >= 3)                  |
          |                     |                         |
          |                     v                         |
          |             [Circuit Breaker]                 |
          |             (Return Error Context)            |
          |                                               |
          +-----------------------------------------------+
```

### 3.1 SQL Fixer Agent System Prompt

```markdown
You are a Database Reliability Engineer specializing in SQL dialect error correction.
You receive:
1. The target schema (DDL).
2. The user's semantic request.
3. The previously failed SQL query.
4. The exact database runtime error string or empty-result warning.

Your Operational Invariants:
1. Correct dialect-specific syntax errors (e.g., SQLite vs PostgreSQL window functions).
2. Fix joins missing appropriate foreign keys.
3. Never invent column names; use ONLY columns present in the provided DDL.
4. If an ambiguous column name error occurs, qualify all columns with their table or alias.
5. If the runtime error indicates type mismatch, introduce explicit `CAST()` operations.

You must respond ONLY with the corrected query wrapped in an ```sql code block. No explanations.
```

### 3.2 Complete Self-Correction Loop Implementation

```python
import sqlite3
import re
from typing import Optional, Tuple, Dict, Any

class SQLiteSelfCorrectionEngine:
    def __init__(self, db_connection: sqlite3.Connection):
        self.conn = db_connection
        self.max_retries = 3

    def get_schema_context(self) -> str:
        cursor = self.conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        return "\n".join([t[0] for t in tables if t[0] is not None])

    def execute_query_safely(self, query: str) -> Tuple[bool, Optional[list], Optional[str]]:
        cursor = self.conn.cursor()
        try:
            # Deterministic Guard: Disallow mutations in extraction pipeline
            clean_query = query.strip().upper()
            if any(clean_query.startswith(verb) for verb in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
                return False, None, "Mutation queries are blocked by policy."
            
            cursor.execute(query)
            rows = cursor.fetchall()
            if len(rows) == 0:
                return False, None, "EMPTY_RESULT_SET: Query ran successfully but returned 0 rows. Verify join predicates and WHERE conditions."
            return True, rows, None
        except sqlite3.Error as e:
            return False, None, f"SQLITE_ENGINE_ERROR: {str(e)}"

    def mock_llm_sql_generator(self, prompt: str, schema: str) -> str:
        # Intentionally generates a query with a column name error on first pass for demonstration
        return "SELECT customer_id, order_value, created_at FROM orders WHERE order_total > 500;"

    def mock_llm_sql_fixer(self, failed_query: str, error: str, schema: str) -> str:
        # Deterministically parses the error and swaps the invalid column
        if "no such column: order_total" in error or "order_value" in failed_query:
            return "SELECT customer_id, order_value, created_at FROM orders WHERE order_value > 500;"
        return failed_query

    def run_query_with_self_correction(self, user_request: str) -> Dict[str, Any]:
        schema = self.get_schema_context()
        current_query = self.mock_llm_sql_generator(user_request, schema)
        attempts = 0
        execution_trace = []

        while attempts < self.max_retries:
            attempts += 1
            success, results, error_msg = self.execute_query_safely(current_query)
            
            trace_entry = {
                "attempt": attempts,
                "query": current_query,
                "success": success,
                "error": error_msg
            }
            execution_trace.append(trace_entry)

            if success:
                return {
                    "status": "SUCCESS",
                    "final_query": current_query,
                    "rows": results,
                    "attempts": attempts,
                    "trace": execution_trace
                }
            
            # Circuit breaker trip condition
            if attempts >= self.max_retries:
                break

            # Self-Correction Step: Inject error into the repair agent
            current_query = self.mock_llm_sql_fixer(current_query, error_msg, schema)

        return {
            "status": "CIRCUIT_BREAKER_TRIPPED",
            "final_query": current_query,
            "last_error": error_msg,
            "attempts": attempts,
            "trace": execution_trace
        }

# --- Initialization and Verification ---

def init_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE orders (
            customer_id INTEGER,
            order_value REAL,
            created_at TEXT
        );
    """)
    cur.execute("INSERT INTO orders VALUES (1, 650.50, '2024-01-15');")
    cur.execute("INSERT INTO orders VALUES (2, 120.00, '2024-01-16');")
    conn.commit()
    return conn

if __name__ == "__main__":
    db = init_test_db()
    engine = SQLiteSelfCorrectionEngine(db)
    result = engine.run_query_with_self_correction("Find all orders over $500")
    print(f"Status: {result['status']}, Attempts: {result['attempts']}")
    print(f"Final Query: {result['final_query']}")
    print(f"Retrieved Rows: {result['rows']}")
```

---

## 4. Blueprint 3: Automated GitHub PR Reviewer & Linter Swarm

This workflow employs three domain-specific evaluation agents running against a code diff, followed by a Consolidation Gate that outputs deterministic GitHub-compatible review comments and merge verdicts.

```
                    [Inbound PR Diff]
                            |
        +-------------------+-------------------+
        |                   |                   |
        v                   v                   v
[Security Auditor]  [Performance Critic]  [Style Enforcer]
        |                   |                   |
 (Vulnerabilities)   (Complexity Issues)  (Conventions)
        +-------------------+-------------------+
                            |
                            v
              [Consolidation Gate Evaluator]
                            |
         +------------------+------------------+
         |                                     |
  (Any Critical Flags)                  (All Flags Minor/None)
         |                                     |
         v                                     v
   Verdict: REQUEST_CHANGES              Verdict: APPROVE
```

### 4.1 Domain-Specific Critic Prompts

#### 1. Security Auditor Agent
```markdown
Analyze the provided Unified Git Diff strictly for application security vulnerabilities:
- Injection points (SQL, command, path traversal)
- Exposure of sensitive credentials, JWT secrets, or hardcoded API keys
- Insecure direct object references (IDOR)
- Missing authorization/authentication boundaries

Ignore styling, typing, formatting, and performance nuances.
Return JSON output only:
{
  "agent": "SecurityAuditor",
  "issues_found": [
    {
      "file": "path/to/file.py",
      "line_number": 42,
      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
      "rule_id": "SEC-SQLI-001",
      "description": "Unescaped string formatting in query builder.",
      "suggested_patch": "cursor.execute('SELECT * FROM t WHERE id = ?', (user_id,))"
    }
  ]
}
```

#### 2. Performance & Resource Allocation Critic
```markdown
Analyze the provided Unified Git Diff strictly for runtime efficiency and system resource bottlenecks:
- O(N^2) or greater complexity algorithms on collections
- N+1 database queries inside loop contexts
- Unbounded memory allocations (missing batching/pagination)
- Thread contention, missing async IO, or unbuffered reads

Return JSON output only:
{
  "agent": "PerformanceCritic",
  "issues_found": [
    {
      "file": "path/to/file.py",
      "line_number": 105,
      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
      "rule_id": "PERF-NPLUSONE-004",
      "description": "Database query executed inside a loop across external IDs.",
      "suggested_patch": "Use SELECT ... WHERE id IN (...) before loop."
    }
  ]
}
```

#### 3. Style & Engineering Convention Enforcer
```markdown
Analyze the provided Unified Git Diff strictly for codebase maintainability and idioms:
- Missing types or incorrect type hints
- Function complexity exceeding reasonable bounds (>25 lines, excessive nesting)
- Non-idiomatic patterns or broken conventions

Return JSON output only:
{
  "agent": "StyleEnforcer",
  "issues_found": [
    {
      "file": "path/to/file.py",
      "line_number": 15,
      "severity": "LOW",
      "rule_id": "STYLE-TYPE-MISSING",
      "description": "Function definition lacks return type signature.",
      "suggested_patch": "def parse_payload(data: bytes) -> dict:"
    }
  ]
}
```

### 4.2 Consolidation Gate and Output Formatter

```python
import json
from typing import List, Literal
from pydantic import BaseModel, Field

class CriticIssue(BaseModel):
    file: str
    line_number: int
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    rule_id: str
    description: str
    suggested_patch: str

class AgentReport(BaseModel):
    agent: str
    issues_found: List[CriticIssue]

class GitHubReviewPayload(BaseModel):
    verdict: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"]
    summary_body: str
    inline_comments: List[dict]

class PRReviewConsolidationGate:
    def __init__(self, block_on_severity: List[str] = None):
        self.block_on_severity = block_on_severity or ["CRITICAL", "HIGH"]

    def consolidate(self, reports: List[AgentReport]) -> GitHubReviewPayload:
        all_issues: List[CriticIssue] = []
        for report in reports:
            all_issues.extend(report.issues_found)

        # Evaluation Gate Logic
        has_blocking_failures = any(
            issue.severity in self.block_on_severity for issue in all_issues
        )
        
        verdict: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = (
            "REQUEST_CHANGES" if has_blocking_failures else "APPROVE"
        )
        
        if not all_issues:
            return GitHubReviewPayload(
                verdict="APPROVE",
                summary_body="All automated critic agents passed with zero issues identified.",
                inline_comments=[]
            )

        # Format GitHub Inline comments
        inline_comments = []
        for issue in all_issues:
            inline_comments.append({
                "path": issue.file,
                "line": issue.line_number,
                "body": (
                    f"**[{issue.severity}] {issue.rule_id}**: {issue.description}\n\n"
                    f"```suggestion\n{issue.suggested_patch}\n```"
                )
            })

        summary = (
            f"### Automated Review Summary\n"
            f"- **Verdict**: {verdict}\n"
            f"- **Total Issues**: {len(all_issues)}\n"
            f"- **Blocking Issues**: {sum(1 for i in all_issues if i.severity in self.block_on_severity)}\n"
        )

        return GitHubReviewPayload(
            verdict=verdict,
            summary_body=summary,
            inline_comments=inline_comments
        )

# Pipeline Execution Demonstration
if __name__ == "__main__":
    mock_security_report = AgentReport(
        agent="SecurityAuditor",
        issues_found=[
            CriticIssue(
                file="services/auth.py",
                line_number=54,
                severity="CRITICAL",
                rule_id="SEC-RAW-EXEC",
                description="Raw database call without bind parameters allows arbitrary injection.",
                suggested_patch="db.session.execute(text('SELECT * FROM users WHERE id = :id'), {'id': uid})"
            )
        ]
    )

    mock_style_report = AgentReport(
        agent="StyleEnforcer",
        issues_found=[
            CriticIssue(
                file="services/auth.py",
                line_number=20,
                severity="LOW",
                rule_id="STYLE-DOC-001",
                description="Public service method missing docstring documentation.",
                suggested_patch='"""Authenticate credentials and generate JWT."""'
            )
        ]
    )

    gate = PRReviewConsolidationGate()
    review = gate.consolidate([mock_security_report, mock_style_report])
    print(f"Action: {review.verdict}")
    print(f"Report:\n{review.summary_body}")
    print(f"Inline Comment Targets: {len(review.inline_comments)}")
```

---

## 5. Blueprint 4: Customer Support Escalate-to-Human Triaging Loop

Customer support agents must fail securely. This blueprint establishes a deterministic state machine containing automated risk filters that break out of the LLM conversation loop and construct a human support handoff ticket when sentiment, financial limits, or policy violations occur.

```
       [Customer Inbound Message]
                    |
                    v
    [Pre-Execution Deterministic Rules]
    - Explicit Legal Action Mention?
    - Repeated Profanity Counter >= 2?
         |                      |
      (True)                 (False)
         |                      |
         |                      v
         |            [LLM Support Resolver]
         |                      |
         |         (Tool Call: Refund or Query)
         |                      |
         |                      v
         |            [Post-Tool Evaluation]
         |            - Refund > $200?
         |            - Tool Execution Error?
         |            - Confidence < 0.85?
         |                      |
         |           +----------+----------+
         |           |                     |
         |        (Passed)             (Failed)
         |           |                     |
         v           v                     v
   +--------------------+     +---------------------------+
   | Return Final Reply |     | ESCALATE TO HUMAN QUEUE   |
   | to Customer        |     | (Freeze Session Context)  |
   +--------------------+     +---------------------------+
```

### 5.1 State Machine Context Handoff Schema

When an escalation triggers, the agent generates an immutable escalation record containing the execution trace and trigger reason:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "HumanEscalationTicket",
  "type": "object",
  "properties": {
    "ticket_id": { "type": "string" },
    "customer_id": { "type": "string" },
    "escalation_trigger": {
      "type": "string",
      "enum": [
        "FINANCIAL_LIMIT_EXCEEDED",
        "LEGAL_THREAT_DETECTED",
        "SENTIMENT_DEGRADATION",
        "TOOL_FAILURE_EXHAUSTION",
        "POLICY_UNCERTAINTY"
      ]
    },
    "trigger_context": { "type": "string" },
    "conversation_history": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "role": { "type": "string", "enum": ["customer", "agent", "system"] },
          "content": { "type": "string" }
        },
        "required": ["role", "content"]
      }
    },
    "proposed_draft_response": { "type": "string" },
    "system_state": {
      "type": "object",
      "properties": {
        "session_id": { "type": "string" },
        "active_order_id": { "type": "string" },
        "customer_tier": { "type": "string" }
      },
      "required": ["session_id", "customer_tier"]
    }
  },
  "required": [
    "ticket_id",
    "customer_id",
    "escalation_trigger",
    "trigger_context",
    "conversation_history",
    "system_state"
  ]
}
```

### 5.2 Deterministic Triage & Escalation Controller

```python
import uuid
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

class EscalationTripwire(Exception):
    def __init__(self, trigger: str, context: str):
        self.trigger = trigger
        self.context = context

class Message(BaseModel):
    role: str
    content:
