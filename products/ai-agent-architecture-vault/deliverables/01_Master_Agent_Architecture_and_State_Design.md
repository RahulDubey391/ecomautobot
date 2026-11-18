# Module 1: Agent Topology & Deterministic State Machine Architecture

Production agent failures are rarely caused by model intelligence limitations; they are caused by unbounded state spaces, cyclic non-determinism, and fragile state hydration. When an agent loops indefinitely, hallucinates tool arguments, or loses contextual state mid-transaction, the root cause is almost universally an architectural failure: the state machine was treated as an open conversational thread rather than a deterministic, bounded directed graph.

This module details the architectural topologies, deterministic state transition engines, multi-tiered memory backends, and serialization primitives required to run autonomous multi-agent systems reliably in mission-critical environments.

---

## 1. Architectural Taxonomies

Selecting an agent topology requires balancing latency, reasoning depth, execution cost, and error tolerance. The table below outlines the core trade-offs between the three primary production topologies.

| Dimension | ReAct Loop | Plan-and-Solve | Hierarchical Supervisor Tree |
| :--- | :--- | :--- | :--- |
| **Typical End-to-End Latency** | Low to Medium ($1.2\text{s} - 8.5\text{s}$) | High ($6.0\text{s} - 25.0\text{s}$) | Variable / Very High ($4.0\text{s} - 60.0\text{s}+$) |
| **Input/Output Token Cost** | Linear to step count; compounding context | Front-loaded reasoning; predictable steps | High overhead; duplicated routing contexts |
| **Error Recovery Dynamics** | Step-by-step local self-correction | Requires full or partial replanning phase | Sub-tree isolation; node retry or fallback |
| **State Drift Vulnerability** | High; context accumulates raw observations | Low; steps execute against atomic sub-states | Lowest; strictly bounded agent contexts |
| **Maximum Feasible Steps** | $5 - 8$ before context saturation | $10 - 25$ structured task units | $50+$ across decomposed sub-agent trees |
| **Optimal Production Fit** | Real-time APIs, ad-hoc queries, retrieval | Multi-step data migrations, ETL, code gen | Enterprise operations, multi-department flows |

---

### ReAct Loop: Mechanical Realities and Failure Modes

The Reasoning + Acting (ReAct) pattern interleaves thought generation with tool invocation. While versatile, naked ReAct implementations suffer from three critical production failure modes:

1. **The Infinite Oscillation Loop:** The model calls a tool, receives an error or unexpected output, and issues the exact same tool call with the exact same arguments repeatedly.
2. **Context Bleed / Context Saturation:** Every tool execution observation is appended verbatim to the context window. By step 5, 80% of tokens are historical execution noise, degrading the model's instruction-following precision.
3. **Action-Observation Desynchronization:** The model generates output text containing an inferred tool result instead of waiting for runtime execution, breaking the parser.

#### Production ReAct Engine Prompt Contract

The following system prompt enforces strict parsing determinism, mandatory cycle prevention, and output format isolation:

```text
You are the Core Execution Engine. You solve problems by interleaving explicit reasoning steps with concrete tool actions.

### OPERATIONAL CONSTRAINTS:
1. You must operate strictly through Thought, Action, and Action Input cycles.
2. After emitting "Action:" and "Action Input:", you MUST IMMEDIATELY STOP generating tokens and wait for the runtime environment to supply an "Observation:".
3. NEVER fabricate, guess, or hallucinate an "Observation:". Any token generated after "Action Input:" that attempts to simulate a tool response will trigger an immediate system termination.
4. You are allotted a MAXIMUM of 6 execution turns. If you reach Turn 5 without a definitive resolution, your next Action MUST be an escalation to fallback or a graceful partial result return.
5. If an "Observation:" returns an identical error payload twice consecutively, you CANNOT repeat the previous Action. You must modify the parameters or route to an alternative strategy.

### TOOL INVOCATION SCHEMA:
You have access to the following tools:
- sql_query(query: str) -> str: Executes a read-only SQL query against the primary read replica.
- redis_lookup(key: str) -> str: Retrieves a cached session or state string.
- emit_metric(name: str, value: float) -> bool: Publishes a telemetry data point.

### OUTPUT FORMAT:
You must strictly follow this exact format:

Thought: [Single-step reasoning explaining why the specific action was selected given previous observations]
Action: [The exact tool name from the permitted list. No other text on this line.]
Action Input: [A strictly valid, single-line JSON string containing the arguments mapping to the tool parameter schema]
Observation: [WAIT FOR RUNTIME INGESTION - DO NOT EMIT]

... (this Thought/Action/Action Input/Observation sequence can repeat up to 5 times)

Thought: [Synthesis of historical observations leading to terminal answer]
Final Answer: [The direct, comprehensive payload resolving the user query]
```

---

### Plan-and-Solve: Deterministic Dynamic Replanning

Plan-and-Solve decouples the macro-reasoning (planning) from micro-execution (tool calling). Instead of reasoning on every step, a specialized Planner model generates an initial directed acyclic task list (DAG). An Executor model runs through the tasks sequentially. If an execution step fails or yields surprising results, a Replanner agent is invoked to recalculate remaining tasks.

```
       +-----------------------+
       |   User Goal / Input   |
       +-----------+-----------+
                   |
                   v
       +-----------------------+
+----->|     Planner Node      |<-----+
|      +-----------+-----------+      |
|                  |                  |
|                  | (Initial Plan)   |
|                  v                  |
|      +-----------------------+      |
|      |    Execution Node     |      |
|      |   (Processes Step)    |      |
|      +-----------+-----------+      |
|                  |                  |
|                  v                  |
|      +-----------------------+      | (Replanning
|      |    Evaluation Node    |      |  Triggered)
|      +-----------+-----------+      |
|             /         \             |
|   [Needs Replanning]  [Step Valid]  |
+------------+            +-----------+
                          |
                 [Plan Finished]
                          |
                          v
               +----------------------+
               |    Final Synthesis   |
               +----------------------+
```

#### Production Planner Schema & Prompt

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ExecutionPlan",
  "type": "object",
  "properties": {
    "goal": { "type": "string" },
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "step_id": { "type": "integer" },
          "description": { "type": "string" },
          "assigned_agent": { "type": "string", "enum": ["DataExtractor", "TransformEngine", "ValidationNode"] },
          "expected_output_type": { "type": "string" },
          "dependent_on_steps": {
            "type": "array",
            "items": { "type": "integer" }
          }
        },
        "required": ["step_id", "description", "assigned_agent", "expected_output_type", "dependent_on_steps"],
        "additionalProperties": false
      }
    }
  },
  "required": ["goal", "steps"],
  "additionalProperties": false
}
```

---

### Hierarchical Supervisor Trees

In a Hierarchical Supervisor topology, child agents are treated as black boxes with their own isolated context windows, memory tiers, and internal state graphs. The Supervisor acts as a router, router gatekeeper, and aggregator.

```
                   +----------------------------------+
                   |       Supervisor Agent Node      |
                   |   (Decides routing via Enum)     |
                   +-----------------+----------------+
                                     |
         +---------------------------+---------------------------+
         |                           |                           |
         v                           v                           v
+-----------------+         +-----------------+         +-----------------+
|   Sub-Agent A   |         |   Sub-Agent B   |         |   Sub-Agent C   |
| (DB Operations) |         | (API Operations)|         | (Code Synthesis)|
+--------+--------+         +--------+--------+         +--------+--------+
         |                           |                           |
         +---------------------------+---------------------------+
                                     |
                                     v
                   +----------------------------------+
                   | Aggregation & Verification Node  |
                   |   (Applies deterministic gates)  |
                   +----------------------------------+
```

#### Supervisor Router Implementation Contract

The Supervisor does not execute tools directly. It evaluates incoming messages against an array of worker descriptors and returns a clean, typed routing decision:

```python
from typing import Literal
from pydantic import BaseModel, Field

class SupervisorRoute(BaseModel):
    """Routing decision emitted by the Hierarchical Supervisor."""
    reasoning: str = Field(description="Architectural rationale for worker delegation.")
    next_node: Literal["DBAgent", "APIAgent", "CodeAgent", "FINAL_TRANSACTION"] = Field(
        description="The target specialized sub-agent or terminal node."
    )
    task_payload: str = Field(
        description="Self-contained execution payload containing all context required by the sub-agent."
    )
    max_budget_usd: float = Field(
        default=0.05,
        description="Strict financial ceiling for the sub-agent execution context."
    )
```

---

## 2. Deterministic State Machine Engine

The foundational failure of naive agent implementations is reliance on unbounded conversational flow. High-reliability agents require a strict **Deterministic State Machine (DSM)** where all state transitions, conditional evaluations, loops, and terminations are defined via formal schemas and compile-time graph edges.

### Production LangGraph Implementation

Below is a complete, runnable state machine featuring structured types, reducer-based state mutation, cyclic loop detection, tool routing, and programmatic checkpointing.

```python
"""
Module 1: Production State Machine Implementation
Framework: LangGraph / Pydantic V2 / TypedDict State Management
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Literal, Sequence, TypedDict, Union
from pydantic import BaseModel, Field

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage
)
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

# ============================================================================
# 1. STATE DEFINITION & REDUCERS
# ============================================================================

def merge_records(
    left: Dict[str, Any], 
    right: Dict[str, Any]
) -> Dict[str, Any]:
    """Reducer that merges state record keys deterministically."""
    merged = left.copy()
    merged.update(right)
    return merged

class MasterAgentState(TypedDict):
    """Strict typed schema for the graph's operational boundary."""
    # Messages use the operator.add reducer to append changes sequentially
    messages: Annotated[Sequence[BaseMessage], operator.add]
    # Execution records use our custom merge reducer
    context_data: Annotated[Dict[str, Any], merge_records]
    current_step: int
    step_budget: int
    retry_count: int
    is_terminal: bool
    error_trace: Annotated[List[str], operator.add]

# ============================================================================
# 2. RUNTIME NODE LOGIC
# ============================================================================

def plan_node(state: MasterAgentState) -> Dict[str, Any]:
    """Evaluates user context and establishes or updates execution plan."""
    current_step = state.get("current_step", 0)
    
    # In production, call your LLM with structured output here.
    # Simulated execution logic:
    planner_thought = AIMessage(
        content="Action: Planning next phase. Ingested state and verified prerequisites."
    )
    
    return {
        "messages": [planner_thought],
        "current_step": current_step + 1,
        "context_data": {"plan_version": 1, "target_table": "customer_records"}
    }

def executor_node(state: MasterAgentState) -> Dict[str, Any]:
    """Executes the discrete operational step (tool dispatch)."""
    current_step = state["current_step"]
    retry_count = state.get("retry_count", 0)
    
    # Mock behavior demonstrating deterministic failure recovery
    if retry_count == 0:
        # Simulate initial failure to demonstrate recovery cycle
        return {
            "retry_count": retry_count + 1,
            "error_trace": [f"Step {current_step}: Timeout connecting to primary partition."],
            "messages": [AIMessage(content="Tool execution failed: Timeout connecting to primary partition.")]
        }
    
    # Successful execution on retry
    execution_result = AIMessage(
        content="Tool execution successful: Mutated 14 matching customer records."
    )
    return {
        "messages": [execution_result],
        "current_step": current_step + 1,
        "context_data": {"records_mutated": 14, "mutation_status": "SUCCESS"},
        "retry_count": 0 # Reset retry count upon resolution
    }

def evaluator_node(state: MasterAgentState) -> Dict[str, Any]:
    """Validates the execution results against the acceptance invariants."""
    data = state.get("context_data", {})
    if data.get("mutation_status") == "SUCCESS":
        return {
            "is_terminal": True,
            "messages": [AIMessage(content="Evaluation confirmed state criteria satisfied.")]
        }
    
    return {
        "is_terminal": False,
        "messages": [AIMessage(content="Criteria not met. Re-routing required.")]
    }

# ============================================================================
# 3. CONDITIONAL ROUTING LOGIC
# ============================================================================

def route_after_executor(
    state: MasterAgentState
) -> Literal["executor_node", "evaluator_node", "error_escalation_node"]:
    """Deterministic routing function based on state invariants."""
    # Guard 1: Step budget exceeded
    if state["current_step"] >= state["step_budget"]:
        return "error_escalation_node"
    
    # Guard 2: Retry loop active
    if state.get("retry_count", 0) > 0:
        # If we have failed less than 3 times, retry
        if state["retry_count"] <= 2:
            return "executor_node"
        return "error_escalation_node"
    
    return "evaluator_node"

def route_after_evaluator(
    state: MasterAgentState
) -> Literal["plan_node", "__end__"]:
    """Determines whether the cycle continues or reaches terminal graph end."""
    if state.get("is_terminal", False):
        return "__end__"
    return "plan_node"

def error_escalation_node(state: MasterAgentState) -> Dict[str, Any]:
    """Graceful degradation node when boundaries or retries are exhausted."""
    fallback_message = AIMessage(
        content="CRITICAL: Maximum retry thresholds exceeded. Transaction locked and escalated."
    )
    return {
        "messages": [fallback_message],
        "is_terminal": True
    }

# ============================================================================
# 4. GRAPH ASSEMBLY & COMPILATION
# ============================================================================

def construct_agent_graph() -> StateGraph:
    workflow = StateGraph(MasterAgentState)

    # Register Nodes
    workflow.add_node("plan_node", plan_node)
    workflow.add_node("executor_node", executor_node)
    workflow.add_node("evaluator_node", evaluator_node)
    workflow.add_node("error_escalation_node", error_escalation_node)

    # Register Static Edges
    workflow.set_entry_point("plan_node")
    workflow.add_edge("plan_node", "executor_node")
    workflow.add_edge("error_escalation_node", END)

    # Register Conditional Edges
    workflow.add_conditional_edges(
        "executor_node",
        route_after_executor,
        {
            "executor_node": "executor_node",
            "evaluator_node": "evaluator_node",
            "error_escalation_node": "error_escalation_node"
        }
    )

    workflow.add_conditional_edges(
        "evaluator_node",
        route_after_evaluator,
        {
            "__end__": END,
            "plan_node": "plan_node"
        }
    )

    return workflow

# Compile graph with thread-level state checkpointing
memory_checkpointer = MemorySaver()
compiled_app = construct_agent_graph().compile(checkpointer=memory_checkpointer)
```

---

## 3. Memory Topology & Persistence Tiering

Production agent architecture demands a clear separation of memory tiers based on lifecycle, access speed, and context size. Treating a conversation thread as a monolithic memory store leads to rapid token exhaustion and latency degradation.

```
+-----------------------------------------------------------------------------------+
|                                 APPLICATION RUNTIME                               |
+-----------------------------------------------------------------------------------+
                                         |
     +-----------------------------------+-----------------------------------+
     | (Active Context Window)           | (Checkpoints / Audit)             | (Semantic Retrieval)
     v                                   v                                   v
+-------------------------+   +-------------------------+   +-------------------------+
|   TIER 1: WORKING MEM   |   |  TIER 2: RELATIONAL DB  |   |  TIER 3: SEMANTIC STORE |
| Redis (In-Memory)       |   | Postgres (ACID / JSONB) |   | pgvector / Zep Hybrid   |
|                         |   |                         |   |                         |
| - Key-value turn state  |   | - Session checkpointing |   | - Distilled insights    |
| - Sliding window tokens |   | - Deterministic replay  |   | - Cross-session recall  |
| - Sub-millisecond read  |   | - System audit log      |   | - Semantic vector search|
| - TTL: 1 to 24 Hours    |   | - TTL: Permanent/90 Days|   | - TTL: Indefinite       |
+-------------------------+   +-------------------------+   +-------------------------+
```

### Tier 1: Ephemeral Working Memory (Redis)

Redis handles high-frequency updates, intermediate scratchpads, and sliding-window token management. It maintains strict TTLs to eliminate orphaned session storage.

```python
"""
Redis Ephemeral State Management Implementation
Handles sliding-window message compaction and sub-millisecond retrieval.
"""

import json
from typing import List, Dict, Any, Optional
import redis

class RedisWorkingMemory:
    def __init__(self, redis_client: redis.Redis, default_ttl_seconds: int = 7200):
        self.client = redis_client
        self.ttl = default_ttl_seconds

    def _format_key(self, session_id: str) -> str:
        return f"agent:working_memory:{session_id}"

    def push_message(self, session_id: str, role: str, content: str, token_cost: int) -> None:
        key = self._format_key(session_id)
        payload = json.dumps({
            "role": role,
            "content": content,
            "token_cost": token_cost
        })
        
        # Pipeline: Append to list, set expiration atomically
        pipe = self.client.pipeline()
        pipe.rpush(key, payload)
        pipe.expire(key, self.ttl)
        pipe.execute()

    def get_sliding_context(self, session_id: str, max_tokens: int = 4000) -> List[Dict[str, str]]:
        """
        Retrieves messages in reverse chronological order until max_tokens budget is met,
        then returns them in chronological order. Prevents context window overflows.
        """
        key = self._format_key(session_id)
        raw_elements = self.client.lrange(key, 0, -1)
        if not raw_elements:
            return []

        accumulated_tokens = 0
        retained_messages: List[Dict[str, str]] = []

        # Walk backwards through the conversation history
        for raw_item in reversed(raw_elements):
            item = json.loads(raw_item.decode('utf-8'))
            item_tokens = item.get("token_cost", len(item["content"]) // 4)
            
            if accumulated_tokens + item_tokens > max_tokens:
                break
                
            retained_messages.append({"role": item["role"], "content": item["content"]})
            accumulated_tokens += item_tokens

        retained_messages.reverse()
        return retained_messages

    def clear(self, session_id: str) -> None:
        self.client.delete(self._format_key(session_id))
```

---

### Tier 2: Relational Audit & Checkpoint State (PostgreSQL)

Relational memory captures atomic snapshots of the entire state machine graph at every state transition. This guarantees forensic auditability, deterministic replay capability, and recovery from catastrophic node failures.

```sql
-- DDL: Production Checkpoint & Audit Store for Multi-Agent Systems
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE agent_sessions (
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    root_agent_name VARCHAR(64) NOT NULL,
    current_status VARCHAR(32) NOT NULL DEFAULT 'INITIALIZED',
    total_tokens_consumed INT DEFAULT 0,
    total_cost_usd NUMERIC(10, 6) DEFAULT 0.000000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE agent_checkpoints (
    checkpoint_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    step_number INT NOT NULL,
    node_name VARCHAR(64) NOT NULL,
    state_payload JSONB NOT NULL,
    state_delta JSONB,
    input_message_id UUID,
    execution_latency_ms INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_session_step UNIQUE (session_id, step_number)
);

CREATE TABLE tool_execution_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    checkpoint_id UUID NOT NULL REFERENCES agent_checkpoints(checkpoint_id) ON DELETE CASCADE,
    tool_name VARCHAR(64) NOT NULL,
    arguments JSONB NOT NULL,
    response_payload JSONB,
    is_error BOOLEAN DEFAULT FALSE,
    execution_duration_ms INT NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup indexes for deterministic replay and state reconstruction
CREATE INDEX idx_checkpoints_session_step ON agent_checkpoints(session_id, step_number DESC);
CREATE INDEX idx_checkpoints_state_gin ON agent_checkpoints USING GIN (state_payload);
CREATE INDEX idx_tool_logs_checkpoint ON tool_execution_logs(checkpoint_id);
```

---

### Tier 3: Long-Term Semantic Memory (Postgres + pgvector)

Long-term memory must distill operational insights, factual corrections, and episodic summaries from historical sessions, making them accessible to future sessions via vector similarity search.

```sql
-- DDL: Long-Term Semantic Vector Memory Store
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE semantic_episodic_memories (
    memory_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES agent_sessions(session_id) ON DELETE SET NULL,
    agent_id VARCHAR(64) NOT NULL,
    memory_category VARCHAR(32) NOT NULL, -- e.g., 'USER_PREFERENCE', 'FACT', 'FAILURE_MODE'
    distilled_fact TEXT NOT NULL,
    embedding vector(1536) NOT NULL, -- OpenAI text-embedding-3-small dimension
    access_frequency INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_semantic_memory_vector ON semantic_episodic_memories 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_semantic_memory_category ON semantic_episodic_memories(agent_id, memory_category);
```

#### Production Query: Cosine Similarity with Recency Weighting

```sql
-- Semantic Memory Retrieval Function
CREATE OR REPLACE FUNCTION match_episodic_memories(
    query_embedding vector(1536),
    match_threshold FLOAT,
    match_count INT,
    p_agent_id VARCHAR(64)
)
RETURNS TABLE (
    memory_id UUID,
    distilled_fact TEXT,
    similarity FLOAT,
    adjusted_score FLOAT
)
LANGUAGE sql STABLE AS $$
    SELECT 
        m.memory_id,
        m.distilled_fact,
        (1 - (m.embedding <=> query_embedding)) AS similarity,
        -- Decay score based on age (10% weight to log-normalized recency)
        ((1 - (m.embedding <=> query_embedding)) * 0.9) + 
        (LEAST(1.0, 1.0 / (LOG(EXTRACT(EPOCH FROM (NOW() - m.created_at))/86400 + 2))) * 0.1) AS adjusted_score
    FROM semantic_episodic_memories m
    WHERE m.agent_id = p_agent_id
      AND (1 - (m.embedding <=> query_embedding)) > match_threshold
    ORDER BY adjusted_score DESC
    LIMIT match_count;
$$;
```

---

## 4. State Graph Serialization & Schema Contracts

When state machines cross network boundaries (e.g., executing asynchronous long-running jobs, surviving worker pod restarts, or emitting events over Kafka), internal Python objects must be serialized cleanly. Non-serializable constructs (client references, active database connections, stream iterators) will corrupt your state snapshots if not stripped cleanly.

### Wire Specification: State Graph Serialization Protocol (JSON Schema)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "StateSnapshotWireContract",
  "type": "object",
  "properties": {
    "version": { "type": "string", "enum": ["1.0.0"] },
    "metadata": {
      "type": "object",
      "properties": {
        "session_id": { "type": "string", "format": "uuid" },
        "graph_id": { "type": "string" },
        "step_index": { "type": "integer", "minimum": 0 },
        "timestamp_utc": { "type": "integer" }
      },
      "required": ["session_id", "graph_id", "step_index", "timestamp_utc"],
      "additionalProperties": false
    },
    "graph_state": {
      "type": "object",
      "properties": {
        "active_node": { "type": "string" },
        "retry_budget_remaining": { "type": "integer", "minimum": 0 },
        "invariants": { "type": "object" },
        "shared_context": { "type": "object" }
      },
      "required": ["active_node", "retry_budget_remaining", "invariants", "shared_context"],
      "additionalProperties": false
    },
    "history": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "message_type": { "type": "string", "enum": ["human", "ai", "tool", "system"] },
          "payload": { "type": "string" },
          "tool_call_id": { "type": ["string", "null"] }
        },
        "required": ["message_type", "payload"],
        "additionalProperties": false
      }
    }
  },
  "required": ["version", "metadata", "graph_state", "history"],
  "additionalProperties": false
}
```

### Production Hydration/Dehydration Engine

The following serializer cleanly translates internal state into a spec-compliant wire format, filtering out non-serializable objects and hydrating it back into runtime types.

```python
"""
Deterministic Hydration and Dehydration Engine
Guarantees clean state serialization over network boundaries and databases.
"""

import time
import uuid
from typing import Dict, Any, List
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage
)

class StateSerializationEngine:
    @staticmethod
    def dehydrate(
        session_id: str,
        graph_id: str,
        active_node: str,
        step_index: int,
        retry_budget: int,
        messages: List[BaseMessage],
        context_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Dehydrates active runtime state into a sanitized, JSON-compliant payload."""
        serialized_messages = []
        for msg in messages:
            msg_type = "system"
            tool_id = None
            if isinstance(msg, HumanMessage):
                msg_type = "human"
            elif isinstance(msg, AIMessage):
                msg_type = "ai"
            elif isinstance(msg, ToolMessage):
                msg_type = "tool"
                tool_id = msg.tool_call_id

            serialized_messages.append({
                "message_type": msg_type,
                "payload": str(msg.content),
                "tool_call_id": tool_id
            })

        # Strip non-serializable objects from context_data
        sanitized_context = {}
        for k, v in context_data.items():
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
