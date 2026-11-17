# Module 4: RAGAS Evaluation Frameworks & Production Troubleshooting

This production playbook contains production-grade evaluation pipelines, latency optimization runbooks, semantic cache implementations, and operational audit matrices. Use these frameworks to transition retrieval-augmented generation (RAG) systems from prototype validation into automated, regression-tested enterprise deployments.

---

## 1. Automated Evaluation Harness: RAGAS & Deterministic Audits

A resilient evaluation pipeline executes two layers of defense: **Deterministic Audits** (structural regex, citation validation, context boundary compliance) and **LLM-as-a-Judge Audits** (semantic faithfulness, context recall, context precision, and hallucination rate).

### 1.1 Complete CI/CD Evaluation Pipeline (`eval_harness.py`)

This script executes against test datasets, runs asynchronous multi-metric scoring, and enforces strict build-breaking thresholds for CI/CD automation.

```python
"""
Production Evaluation Harness for Enterprise RAG.
Dependencies: ragas>=0.1.9, datasets, langchain-openai, pydantic>=2.0
"""

import os
import sys
import json
import asyncio
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from datasets import Dataset

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from ragas.metrics.critique import harmfulness

# ---------------------------------------------------------
# 1. EVALUATION SCHEMAS & CONFIGURATION
# ---------------------------------------------------------

class EvalSample(BaseModel):
    question: str
    ground_truth: str
    contexts: List[str]
    answer: str

class EvalThresholds:
    MIN_FAITHFULNESS: float = 0.88
    MIN_CONTEXT_PRECISION: float = 0.82
    MIN_CONTEXT_RECALL: float = 0.85
    MIN_ANSWER_RELEVANCY: float = 0.85
    MAX_HALLUCINATION_RATE: float = 0.05

# ---------------------------------------------------------
# 2. DETERMINISTIC HEURISTIC SCORER
# ---------------------------------------------------------

class DeterministicAuditor:
    """Evaluates syntactic constraints without invoking external models."""

    @staticmethod
    def verify_citations(answer: str, retrieved_contexts: List[str]) -> float:
        """
        Validates that every citation bracket [Doc X] points to an existing index.
        Returns score from 0.0 to 1.0.
        """
        import re
        citations = re.findall(r'\[Doc\s+(\d+)\]', answer)
        if not citations:
            return 0.0
        
        valid_contexts_count = len(retrieved_contexts)
        valid = 0
        for citation in citations:
            idx = int(citation) - 1
            if 0 <= idx < valid_contexts_count:
                valid += 1
                
        return valid / len(citations) if citations else 0.0

    @staticmethod
    def verify_negative_rejection(question: str, answer: str, unanswerable: bool) -> bool:
        """
        Verifies that the engine explicitly states inability to answer
        when contexts lack supporting facts.
        """
        rejection_phrases = [
            "i am unable to find",
            "the provided context does not contain",
            "there is insufficient information",
            "not mentioned in the provided documents"
        ]
        if unanswerable:
            return any(phrase in answer.lower() for phrase in rejection_phrases)
        return True

# ---------------------------------------------------------
# 3. LLM-AS-A-JUDGE: DUAL-PHASE EVALUATION HARNESS
# ---------------------------------------------------------

class ProductionEvalHarness:
    def __init__(self, model_name: str = "gpt-4o", temperature: float = 0.0):
        self.eval_llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=os.environ.get("OPENAI_API_KEY")
        )
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=os.environ.get("OPENAI_API_KEY")
        )
        self.metrics = [
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
            harmfulness
        ]

    def build_dataset(self, samples: List[EvalSample]) -> Dataset:
        payload = {
            "question": [s.question for s in samples],
            "contexts": [s.contexts for s in samples],
            "answer": [s.answer for s in samples],
            "ground_truth": [s.ground_truth for s in samples]
        }
        return Dataset.from_dict(payload)

    def execute_ragas(self, dataset: Dataset) -> Dict[str, float]:
        results = evaluate(
            dataset=dataset,
            metrics=self.metrics,
            llm=self.eval_llm,
            embeddings=self.embeddings,
            raise_exceptions=True
        )
        return results

    def run_full_suite(self, raw_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        samples = [EvalSample(**s) for s in raw_samples]
        dataset = self.build_dataset(samples)
        
        # Step 1: Run deterministic sweeps
        citation_scores = []
        for sample in samples:
            c_score = DeterministicAuditor.verify_citations(sample.answer, sample.contexts)
            citation_scores.append(c_score)
        
        avg_citation_precision = sum(citation_scores) / len(citation_scores) if citation_scores else 0.0

        # Step 2: Run RAGAS pipeline
        ragas_scores = self.execute_ragas(dataset)

        # Step 3: Aggregate
        final_report = {
            "faithfulness": ragas_scores["faithfulness"],
            "context_precision": ragas_scores["context_precision"],
            "context_recall": ragas_scores["context_recall"],
            "answer_relevancy": ragas_scores["answer_relevancy"],
            "citation_precision": avg_citation_precision,
            "harmfulness": ragas_scores["harmfulness"]
        }
        
        return final_report

# ---------------------------------------------------------
# 4. CI/CD INTEGRATION & GATING
# ---------------------------------------------------------

def run_ci_gate():
    # Production golden test set fixtures
    golden_dataset = [
        {
            "question": "What is the memory retention SLA for cache node write failures?",
            "ground_truth": "Cache node write failures fall back to local disk spooling with a 4-hour retention SLA before dropped records occur.",
            "contexts": [
                "Secondary Redis replicates maintain a heartbeat interval of 250ms. If a master node rejects a write, the proxy diverts records to a local WAL (write-ahead log).",
                "Disk spooling guarantees a 4-hour retention SLA under system degraded states. After 4 hours without upstream cluster recovery, oldest spool blocks are systematically unlinked."
            ],
            "answer": "Under cache node write failures, the proxy redirects data to a local write-ahead log that guarantees a 4-hour memory retention SLA prior to dropped records [Doc 2]."
        },
        {
            "question": "What is the maximum allowed query timeout for vector hybrid search?",
            "ground_truth": "The maximum allowed query timeout across dense and sparse fusion is 650 milliseconds.",
            "contexts": [
                "Sparse query scoring runs synchronously alongside dense ANN search via HNSW indices.",
                "Global search dispatch enforces a strict 650 millisecond termination deadline across all hybrid fusion branches."
            ],
            "answer": "The maximum query timeout permitted for vector hybrid search is 650ms [Doc 2]."
        }
    ]

    auditor = ProductionEvalHarness()
    results = auditor.run_full_suite(golden_dataset)
    print("\n--- TEST SUITE EVALUATION RESULTS ---")
    print(json.dumps(results, indent=2))

    failures = []
    if results["faithfulness"] < EvalThresholds.MIN_FAITHFULNESS:
        failures.append(f"Faithfulness {results['faithfulness']:.3f} below target {EvalThresholds.MIN_FAITHFULNESS}")
    if results["context_precision"] < EvalThresholds.MIN_CONTEXT_PRECISION:
        failures.append(f"Context Precision {results['context_precision']:.3f} below target {EvalThresholds.MIN_CONTEXT_PRECISION}")
    if results["context_recall"] < EvalThresholds.MIN_CONTEXT_RECALL:
        failures.append(f"Context Recall {results['context_recall']:.3f} below target {EvalThresholds.MIN_CONTEXT_RECALL}")
    if results["answer_relevancy"] < EvalThresholds.MIN_ANSWER_RELEVANCY:
        failures.append(f"Relevancy {results['answer_relevancy']:.3f} below target {EvalThresholds.MIN_ANSWER_RELEVANCY}")

    if failures:
        print("\n❌ CI/CD GATE REJECTED - Production Quality Thresholds Not Met:")
        for fail in failures:
            print(f"  - {fail}")
        sys.exit(1)
    
    print("\n✅ CI/CD GATE PASSED - Model and Retrieval parameters within tolerance.")
    sys.exit(0)

if __name__ == "__main__":
    run_ci_gate()
```

### 1.2 Custom Hallucination Scoring Prompt Template

Use this raw, deterministic evaluation prompt within custom LLM judges to eliminate non-grounded outputs. It outputs structured JSON conforming to zero-tolerance hallucination boundaries.

```
You are an expert algorithmic verification system evaluating context fidelity in an enterprise Retrieval-Augmented Generation pipeline.

EVALUATION SPECIFICATION:
1. Grounding Audit: Compare every factual claim in the "Generated Answer" against the "Provided Context" blocks.
2. Contradiction Detection: Flag any claim that directly disputes or subtly mutates facts in the context.
3. Extrapolation Flagging: Mark any assertion not explicitly asserted in the context as an EXTRAPOLATION, even if factually true in the real world.
4. Citation Audit: Ensure each assertion contains a valid, matching [Doc X] citation that contains the ground truth supporting that precise statement.

INPUT DATA:
---------------------
[Provided Context]:
{context_str}
---------------------
[User Question]:
{query_str}
---------------------
[Generated Answer]:
{response_str}
---------------------

OUTPUT INSTRUCTIONS:
You must respond ONLY with a strict JSON object matching this schema. Do not include markdown code block wrappings (no ```json or ```).

{
  "claims": [
    {
      "claim_id": integer,
      "text": "Exact substring claim from answer",
      "status": "GROUNDED" | "CONTRADICTION" | "UNSUPPORTED_EXTRAPOLATION",
      "citation_valid": true | false,
      "context_reference_id": "Doc X or null",
      "reasoning": "Succinct evidence statement"
    }
  ],
  "aggregate_metrics": {
    "total_claims": integer,
    "grounded_claims": integer,
    "unsupported_claims": integer,
    "contradictory_claims": integer,
    "faithfulness_score": float (grounded_claims / total_claims),
    "pass_validation": boolean (true if faithfulness_score == 1.0, otherwise false)
  }
}
```

---

## 2. Production Latency Reduction: The P99 Kill-Chain

Target operational latency for an enterprise RAG pipeline is **< 1,200 ms total round-trip time (RTT)** at P99 under a concurrency load of 250 requests per second.

### 2.1 Latency Budget Architecture

| Pipeline Stage | P50 SLA (ms) | P95 SLA (ms) | P99 SLA (ms) | Root-Cause Latency Bottleneck | Architectural Mitigation Pattern |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Input Guardrails & Intent** | 15 | 30 | 50 | Heavy regex trees, sync LLM calls | Small embedding-classifier + Aho-Corasick automaton |
| **Query Rewriting / HyDE** | 0 | 0 | 0 | Chained sync generation steps | **Drop HyDE in critical path**; run speculative async expansion |
| **Embedding Generation** | 20 | 45 | 70 | Remote API network jitter | Localized Triton/ONNX runtime container (`bge-large-en-v1.5`) |
| **Hybrid Search (Dense+BM25)**| 35 | 85 | 130 | Deep unindexed scans, unoptimized HNSW | HNSW `ef_search=64`, dynamic partition prune, sparse Lucene index |
| **Cross-Encoder Reranking** | 60 | 140 | 250 | Full-depth cross-encoders on Top-100 | Flash-Rankers (ONNX), batched inference, prune candidate pool to Top-25 |
| **LLM Time-to-First-Token** | 180 | 350 | 500 | Dense prompt payload, cold worker nodes | Chunk pre-caching (vLLM PagedAttention), context prefix pinning |
| **LLM Token Generation** | 300 | 500 | 700 | Unbounded output length limits | Strict `max_tokens: 350`, token streaming directly to UI client |
| **TOTAL PIPELINE** | **610 ms** | **1,150 ms** | **1,700 ms** | Accumulated sequential latency | **Implement Async Concurrent Execution Fan-Out** |

### 2.2 Speculative Asynchronous Retrieval Pipeline

Eliminate serialization delays by executing dense vector retrieval, lexical keyword search, and cached context lookups concurrently using native `asyncio`.

```python
"""
Low-Latency Asynchronous Search Dispatcher.
Executes Dense, Sparse, and Entity lookups concurrently within a strict deadline envelope.
"""

import asyncio
from typing import List, Dict, Any

class LatencyOptimizedDispatcher:
    def __init__(self, dense_retriever, sparse_retriever, timeout_ms: float = 250.0):
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.timeout_budget = timeout_ms / 1000.0

    async def _fetch_dense(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        # Encapsulate client library calls in an async thread pool if non-native
        return await asyncio.to_thread(self.dense_retriever.search, query, top_k)

    async def _fetch_sparse(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.sparse_retriever.search, query, top_k)

    async def execute_parallel_retrieval(self, query: str, top_k: int = 25) -> Dict[str, Any]:
        """
        Runs dense and sparse retrieval concurrently. 
        Guarantees response within strict timeout SLA via cancellation tokens.
        """
        dense_task = asyncio.create_task(self._fetch_dense(query, top_k))
        sparse_task = asyncio.create_task(self._fetch_sparse(query, top_k))

        done, pending = await asyncio.wait(
            [dense_task, sparse_task],
            timeout=self.timeout_budget,
            return_when=asyncio.ALL_COMPLETED
        )

        # Cancel tasks breaching budget
        for task in pending:
            task.cancel()

        results = {
            "dense_results": dense_task.result() if dense_task in done and not dense_task.cancelled() else [],
            "sparse_results": sparse_task.result() if sparse_task in done and not sparse_task.cancelled() else [],
            "degraded_state": len(pending) > 0
        }
        
        return results

    @staticmethod
    def reciprocal_rank_fusion(
        dense_docs: List[Dict[str, Any]], 
        sparse_docs: List[Dict[str, Any]], 
        k: int = 60, 
        max_output: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Fuses parallel results in O(N) execution time.
        """
        scores: Dict[str, float] = {}
        doc_store: Dict[str, Dict[str, Any]] = {}

        for rank, doc in enumerate(dense_docs):
            doc_id = doc["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))
            doc_store[doc_id] = doc

        for rank, doc in enumerate(sparse_docs):
            doc_id = doc["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))
            doc_store[doc_id] = doc

        # Sort descending by cumulative RRF score
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:max_output]
        return [doc_store[doc_id] for doc_id in sorted_ids]
```

### 2.3 Reranker Batch Optimization and Pruning

Using a deep Cross-Encoder on 100 documents introduces up to 800ms of latency. Optimize reranking using quantization, smaller cross-encoders, and dynamic pool truncation:

1. **Top-K Truncation:** Limit reranker inputs to a maximum of 25-30 candidate documents from the hybrid retrieval stage.
2. **Dynamic Pruning:** If the score delta between candidate 1 and candidate 10 in the initial retrieval stage exceeds 40%, skip reranking entirely and route directly to the LLM.
3. **Model Quantization:** Deploy Cross-Encoders using ONNX Runtime with INT8 quantization (`bge-reranker-base` INT8 reduces inference latency by 3.4x over standard PyTorch FP32 on CPU instances).

---

## 3. Cache Invalidation & Hybrid Semantic Caching Architecture

Semantic caching reduces inference cost and bypasses the retrieval pipeline for common or semantically identical queries. However, dynamic document updates require aggressive cache invalidation systems to prevent serving stale contexts.

```
                      ┌──────────────────────┐
                      │    Incoming Query    │
                      └──────────┬───────────┘
                                 │
                     Compute Query Embedding
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │ Redis Semantic Cache  │
                     │  (HNSW Vector Index)  │
                     └──────────┬────────────┘
                                │
               Cosine Distance <= 0.08? (Match found)
                                │
                 ┌──────────────┴──────────────┐
                 │                             │
               YES                             NO
                 │                             │
    Validate Namespace Checksum                ▼
                 │                   Execute Full Pipeline
         ┌───────┴───────┐           (Hybrid Search -> Rerank -> LLM)
         │               │                     │
       VALID          INVALID                  ▼
         │               │              Write to Redis
         ▼               ▼              - Embeddings
    Return Cached   Purge Cache Key     - Context IDs
      Response      & Fallback to Full  - Namespace Checksum
                    Pipeline            - TTL = 28800s
```

### 3.1 Redis Semantic Cache with Invalidation Hooks

```python
"""
Redis-Powered Semantic Cache with Namespace Invalidation Engine.
Dependencies: redis>=5.0.0, numpy
"""

import json
import hashlib
from typing import Optional, Dict, Any, List
import numpy as np
import redis
from redis.commands.search.query import Query
from redis.commands.search.field import VectorField, TextField, NumericField
from redis.commands.search.index_definition import IndexDefinition, IndexType

class ProductionSemanticCache:
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_password: Optional[str] = None,
        embedding_dim: int = 1536,
        similarity_threshold: float = 0.94  # Cosine similarity cutoff
    ):
        self.r = redis.Redis(
            host=redis_host, 
            port=redis_port, 
            password=redis_password, 
            decode_responses=False
        )
        self.dim = embedding_dim
        # Distance metric: Cosine distance = 1 - Cosine Similarity
        # Distance threshold <= (1.0 - 0.94) = 0.06
        self.distance_threshold = round(1.0 - similarity_threshold, 4)
        self.index_name = "idx:semantic_cache"
        self._init_index()

    def _init_index(self):
        """Initializes the vector search index on the cache layer."""
        try:
            self.r.ft(self.index_name).info()
        except redis.ResponseError:
            schema = (
                TextField("query"),
                TextField("response"),
                TextField("namespace_hash"),
                NumericField("created_at"),
                VectorField(
                    "embedding",
                    "HNSW",
                    {
                        "TYPE": "FLOAT32",
                        "DIM": self.dim,
                        "DISTANCE_METRIC": "COSINE",
                        "M": 16,
                        "EF_CONSTRUCTION": 64
                    }
                )
            )
            definition = IndexDefinition(prefix=["cache:"], index_type=IndexType.HASH)
            self.r.ft(self.index_name).create_index(schema, definition=definition)

    @staticmethod
    def compute_namespace_hash(document_ids: List[str]) -> str:
        """
        Creates a deterministic hash representing the version of documents 
        present in the backing knowledge base.
        """
        sorted_ids = sorted(document_ids)
        raw = "|".join(sorted_ids).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, query_vector: List[float], current_namespace_hash: str) -> Optional[str]:
        """
        Queries cache using HNSW index. Enforces active namespace validation.
        """
        query_bytes = np.array(query_vector, dtype=np.float32).tobytes()
        
        # Search for 1 nearest neighbor
        search_query = (
            Query(f"*=>[KNN 1 @embedding $vec AS distance]")
            .sort_by("distance")
            .return_fields("query", "response", "namespace_hash", "distance")
            .dialect(2)
        )
        
        params = {"vec": query_bytes}
        results = self.r.ft(self.index_name).search(search_query, query_params=params)
        
        if not results.docs:
            return None
            
        top_match = results.docs[0]
        match_distance = float(top_match.distance)

        if match_distance > self.distance_threshold:
            return None  # Semantic hit missed strict threshold

        # Verify state validity
        cached_hash = top_match.namespace_hash
        if cached_hash != current_namespace_hash:
            # Stale cache detected: purge key asynchronously
            self.r.delete(top_match.id)
            return None

        return top_match.response.decode("utf-8") if isinstance(top_match.response, bytes) else top_match.response

    def set(
        self, 
        query: str, 
        query_vector: List[float], 
        response: str, 
        namespace_hash: str, 
        ttl_seconds: int = 86400
    ):
        """
        Persists a completed response alongside its vector footprint and namespace state.
        """
        key_id = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
        cache_key = f"cache:{key_id}"
        query_bytes = np.array(query_vector, dtype=np.float32).tobytes()
        
        mapping = {
            "query": query,
            "response": response,
            "namespace_hash": namespace_hash,
            "embedding": query_bytes,
        }
        
        pipeline = self.r.pipeline()
        pipeline.hset(cache_key, mapping=mapping)
        pipeline.expire(cache_key, ttl_seconds)
        pipeline.execute()

    def invalidate_namespace(self, stale_namespace_hash: str):
        """
        Hard-purges all entries registered under a modified document namespace.
        """
        query = Query(f"@namespace_hash:{stale_namespace_hash}").no_content()
        results = self.r.ft(self.index_name).search(query)
        
        if results.docs:
            pipeline = self.r.pipeline()
            for doc in results.docs:
                pipeline.delete(doc.id)
            pipeline.execute()
```

---

## 4. Production Incident Response Audit Checklist (P1/P2 Playbooks)

When production degradation strikes an enterprise RAG cluster, engineers must triage issues methodically across three isolated failure domains: **Data/Retrieval Layer**, **Orchestration/Network Layer**, and **LLM/Generation Layer**.

### 4.1 Production Emergency Triage Matrix

| Incident Profile | Root Causes | Immediate Diagnostic Command / Telemetry Check | Emergency Remediation Action |
| :--- | :--- | :--- | :--- |
| **P1: Catastrophic Context Hallucination Surge** (Faithfulness < 0.60) | 1. Vector index drift / dynamic indexing corruption.<br>2. Prompt injection bypass.<br>3. Reranker silently returning non-relevant nodes. | Run manual CLI retrieval audit:<br>`curl -X POST $SEARCH_SVC/debug/retrieval -d '{"q": "test"}'`<br>Check vector index segment status. | 1. Lock generation model system prompt to **Extractive Grounding Mode**.<br>2. Rollback knowledge index to previous validated snapshot point.<br>3. Bypass reranker: forward Dense Top-5 directly to generation. |
| **P1: P99 Pipeline Timeouts (> 5,000ms)** | 1. Reranker cross-encoder GPU resource contention (OOM thrashing).<br>2. Redis semantic cache socket starvation. | Check GPU duty cycle & VRAM allocation:<br>`nvidia-smi --query-compute-apps=pid,used_memory --format=csv`<br>Check Redis clients: `redis-cli info clients` | 1. Drop Cross-Encoder candidate depth from Top-50 down to Top-10.<br>2. Evict semantic cache node read pools.<br>3. Enforce context token limit degradation: truncate retrieval to 2,000 tokens. |
| **P2: Retrieval Silent Dropout** (Context Recall < 0.50) | 1. Chunk boundary fragmentation (text split through critical JSON/markdown tables).<br>2. Embedding API version mismatch. | Diff current document ingest chunk config against golden parser baseline:<br>`git diff deploy/config/parsers.yaml` | 1. Spin up dedicated index replica using hierarchical parent-document chunking (`ParentDocumentRetriever`).<br>2. Route queries to fallback lexical BM25 index exclusively. |
| **P2: Reranker Memory Exhaustion (OOM Alerts)** | Cross-encoder attempting dynamic batch expansion on large context chunks. | Inspect container memory exhaustion events:<br>`dmesg -T \| grep -i oom-killer` | 1. Set hard chunk truncation (`max_length=512`) on Cross-Encoder inputs.<br>2. Enforce batch size bound (`max_batch_size=16`) in inference engine. |

---

### 4.2 Comprehensive Incident Response Runbook (Step-by-Step)

Follow this end-to-end runbook when responding to alerts regarding context drift, service degradation, or elevated hallucination rates.

```
================================================================================
                    PRODUCTION INCIDENT RUNBOOK: RAG-CRIT-01
               CONTEXT RECOVERY & MITIGATION OF SILENT FAILS
================================================================================

[PHASE 1: TRIAGE & ISOLATION] (Target: < 5 Minutes)
--------------------------------------------------------------------------------
[] 1. Identify failure domain:
     a. Ingest pipeline (writes failing, documents not indexed).
     b. Search/Retrieval pipeline (queries timing out or returning zero contexts).
     c. Inference pipeline (LLM hallucinating, failing schema validation, or timing out).

[] 2. Inspect active circuit breakers:
     $ curl -H "Authorization: Bearer $ADMIN_TOKEN" https://api.rag.internal/v1/system/circuit-breakers

[] 3. Review Prometheus/Grafana alerts for anomalous metric thresholds:
     - rag_retrieval_empty_contexts_total > 1%
     - rag_context_faithfulness_ratio < 0.80
     - rag_reranker_latency_seconds_bucket{le="0.5"} dropping sharply

[PHASE 2: IMMEDIATE TRAFFIC CONTAINMENT] (Target: < 10 Minutes)
--------------------------------------------------------------------------------
[] 1. If latency is spiking:
     Enable degraded retrieval bypass (skips reranking, uses Top-5 vector search only):
     $ redis-cli SET "CONFIG:DYNAMIC:BYPASS_RERANKER" "true"

[] 2. If faithfulness has dropped precipitously:
     Enforce hyper-strict defensive prompting policy globally:
     $ redis-cli SET "CONFIG:DYNAMIC:SYSTEM_PROMPT_OVERRIDE" "STRICT_EXTRACTION"
     
     This forces the generation engine into exact string matching mode:
     "Answer the question ONLY using the direct facts quoted below. If no direct
      quote answers the question, output EXACTLY: 'INSUFFICIENT_INFORMATION'."

[] 3. If vector database index shows node corruption or unresponsiveness:
     Route all search traffic to primary OpenSearch/Elasticsearch BM25 fallback:
     $ redis-cli SET "CONFIG:DYNAMIC:RETRIEVAL_STRATEGY" "SPARSE_ONLY"

[PHASE 3: ROOT CAUSE LOCALIZATION] (Target: < 30 Minutes)
--------------------------------------------------------------------------------
[] 1. EMBEDDING DRIFT AUDIT:
     Validate that the client embedding
