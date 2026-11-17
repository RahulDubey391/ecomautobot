# Module 3: Advanced Corrective RAG (CRAG) & GraphRAG Workflows

Building reliable enterprise RAG requires transitioning from naive single-step retrieval to agentic loops capable of active self-reflection, automated query mutation, dynamic fallback, and multi-modal knowledge representation. This module delivers field-tested production blueprints for Corrective RAG (CRAG), high-throughput multi-query expansion, structured tabular extraction pipelines, and hybrid GraphRAG implementations.

---

## 1. Production Architecture: Corrective RAG (CRAG) Agent

Naive RAG pipelines fail catastrophically when initial vector search yields irrelevant or noisy context. The model generates confident hallucinations instead of admitting retrieval failure. Corrective RAG (CRAG) wraps retrieval in an evaluation-and-remediation state machine:

```
                  ┌──────────────────────┐
                  │    User Question     │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   Vector Retrieval   │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ Document Evaluator   │
                  │   (Grading Node)     │
                  └──────────┬───────────┘
                             │
          ┌──────────────────┴──────────────────┐
          │ Confidence Score                    │
          ▼                                     ▼
   [Score >= 0.7]                         [Score < 0.7]
   ┌─────────────┐                        ┌─────────────┐
   │ Context     │                        │ Query       │
   │ Refinement  │                        │ Transformer │
   └──────┬──────┘                        └──────┬──────┘
          │                                      │
          │                                      ▼
          │                               ┌─────────────┐
          │                               │ Web / BM25  │
          │                               │ Fallback    │
          │                               └──────┬──────┘
          │                                      │
          └──────────────────┬───────────────────┘
                             ▼
                  ┌──────────────────────┐
                  │   Final Generator    │
                  └──────────────────────┘
```

### 1.1 CRAG Graph Implementation (LangGraph)

The following state machine executes:
1. Retrieval of top-$k$ context chunks.
2. Parallel relevance evaluation with a structured JSON score.
3. Conditional branching: If any document is relevant, strip irrelevant sentences; if all fail, rewrite the query and query an external fallback provider.

```python
import os
from typing import List, Literal, TypedDict
from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END


# --- Schemas ---

class GradeHallucinations(BaseModel):
    """Binary score for document relevance check."""
    binary_score: Literal["yes", "no"] = Field(
        description="Documents are relevant to the question, 'yes' or 'no'"
    )
    confidence_score: float = Field(
        description="Confidence between 0.0 and 1.0 indicating relevance certainty."
    )
    explanation: str = Field(description="One-sentence technical reasoning for the grade.")


class AgentState(TypedDict):
    question: str
    generation: str
    documents: List[Document]
    retry_count: int
    fallback_needed: bool


# --- Nodes ---

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
evaluator_llm = llm.with_structured_output(GradeHallucinations)

GRADE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert enterprise retrieval grader. Evaluate whether the retrieved "
            "document contains facts directly useful for answering the user question.\n"
            "Strict grading rubric:\n"
            "- 'yes': Contains overlapping semantic facts, definitions, or direct figures.\n"
            "- 'no': Entirely tangentially related, off-topic, or completely generic.",
        ),
        (
            "human",
            "Retrieved Document:\n\n{context}\n\nUser Question: {question}",
        ),
    ]
)

REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an enterprise search optimizer. Transform the input query into a "
            "keyword-optimized search engine query. Strip conversational filler. "
            "Output ONLY the optimized query string.",
        ),
        ("human", "Original Query: {question}"),
    ]
)

GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an enterprise knowledge base assistant. Answer the question using ONLY "
            "the provided context. If the context does not supply the answer, state that "
            "the data is unavailable. Do not use outside knowledge.\n\nContext:\n{context}",
        ),
        ("human", "{question}"),
    ]
)


def retrieve_documents(state: AgentState):
    """Vector database retrieval mock wrapper."""
    query = state["question"]
    # Production call: vectorstore.as_retriever(k=4).invoke(query)
    # Using deterministic mock for production architecture validation:
    retrieved_docs = [
        Document(
            page_content="Global Corp Q3 2024 operating income reached $4.2B, an 8% YoY increase.",
            metadata={"source": "q3_report.pdf", "page": 12},
        ),
        Document(
            page_content="The brand guidelines recommend using Helvetica Neue for corporate logos.",
            metadata={"source": "brand_guide.pdf", "page": 2},
        ),
    ]
    return {"documents": retrieved_docs, "fallback_needed": False}


def grade_documents(state: AgentState):
    """Evaluates retrieved chunks and filters out noise."""
    question = state["question"]
    docs = state["documents"]
    valid_docs: List[Document] = []
    has_relevant = False

    for doc in docs:
        result: GradeHallucinations = evaluator_llm.invoke(
            GRADE_PROMPT.format(context=doc.page_content, question=question)
        )
        if result.binary_score == "yes" and result.confidence_score >= 0.70:
            valid_docs.append(doc)
            has_relevant = True

    return {
        "documents": valid_docs,
        "fallback_needed": not has_relevant,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def query_rewrite_fallback(state: AgentState):
    """Executes when local retrieval yields zero relevant documents."""
    question = state["question"]
    rewriter = REWRITE_PROMPT | llm
    new_query = rewriter.invoke({"question": question}).content.strip()

    # Fallback to secondary retrieval (e.g., BM25 keyword store or Tavily/Google Search)
    fallback_doc = Document(
        page_content=f"Fallback search result for expanded query: '{new_query}'. "
        "Global Corp announced their total liabilities are $12.1B as of Q3 2024.",
        metadata={"source": "external_api"},
    )
    return {"documents": [fallback_doc], "question": new_query}


def generate(state: AgentState):
    """Synthesizes final answer from verified documents."""
    context = "\n\n".join([d.page_content for d in state["documents"]])
    prompt = GENERATION_PROMPT.format(context=context, question=state["question"])
    response = llm.invoke(prompt)
    return {"generation": response.content}


# --- Routing Logic ---

def route_evaluation(state: AgentState) -> str:
    if state["fallback_needed"]:
        if state.get("retry_count", 0) >= 2:
            return "generate"  # Terminate early to prevent infinite execution loops
        return "query_rewrite_fallback"
    return "generate"


# --- Workflow Graph Definition ---

workflow = StateGraph(AgentState)

workflow.add_node("retrieve", retrieve_documents)
workflow.add_node("grade_documents", grade_documents)
workflow.add_node("query_rewrite_fallback", query_rewrite_fallback)
workflow.add_node("generate", generate)

workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "grade_documents")
workflow.add_conditional_edges(
    "grade_documents",
    route_evaluation,
    {
        "query_rewrite_fallback": "query_rewrite_fallback",
        "generate": "generate",
    },
)
workflow.add_edge("query_rewrite_fallback", "grade_documents")
workflow.add_edge("generate", END)

crag_pipeline = workflow.compile()
```

---

## 2. Multi-Query Expansion & Hypothetical Document Embeddings (HyDE)

Complex queries often mismatch the semantic representation of raw reference texts. Two strategies neutralize this vector distance:

1. **Multi-Query Decomposition:** Splitting complex multi-hop queries into 3–5 search variants, retrieving contexts for each, and unifying them via **Reciprocal Rank Fusion (RRF)**.
2. **Hypothetical Document Embeddings (HyDE):** Generating a plausible, hallucinated answer chunk and embedding *that* answer instead of the query, matching target document geometry directly.

### 2.1 Multi-Query Fan-Out with Reciprocal Rank Fusion (RRF)

```
User Query: "What was the EBITDA variance between our APAC and EMEA logistics units?"
                                  │
                 ┌────────────────┴────────────────┐
                 │ Multi-Query Decomposition (LLM)  │
                 └────────────────┬────────────────┘
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
 Query 1 (APAC)           Query 2 (EMEA)           Query 3 (EBITDA Variance)
         │                        │                        │
         ▼                        ▼                        ▼
 Vector Search (Rank 1-K) Vector Search (Rank 1-K) Vector Search (Rank 1-K)
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  │
                                  ▼
                    Reciprocal Rank Fusion (RRF)
                  RRF Score = Σ [ 1 / (60 + Rank) ]
                                  │
                                  ▼
                         Deduplicated Top-K
```

The mathematical formula for Reciprocal Rank Fusion is:

$$RRF(d \in D) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

where $k$ is a smoothing constant (standard: $k = 60$), $M$ is the set of retrieval passes, and $r_m(d)$ is the 1-based rank of document $d$ in system $m$.

```python
import asyncio
from typing import Dict, List, Tuple
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
import numpy as np


class MultiQueryRRFEngine:
    def __init__(self, k_constant: int = 60):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.k_constant = k_constant

    async def generate_query_variants(self, original_query: str, num_variants: int = 4) -> List[str]:
        prompt = (
            f"You are an enterprise search specialist. Decompose the following user question "
            f"into {num_variants} distinct, highly specific sub-queries or semantic alternative queries.\n"
            f"Focus on extracting standalone entities, domain vocabulary, and isolated comparison metrics.\n"
            f"Return ONLY the {num_variants} queries separated by newlines, with no bullet points.\n\n"
            f"Original Question: {original_query}"
        )
        response = await self.llm.ainvoke(prompt)
        variants = [line.strip() for line in response.content.split("\n") if line.strip()]
        return [original_query] + variants[:num_variants]

    async def mock_vector_retrieval(self, query: str, top_k: int = 5) -> List[Tuple[str, str]]:
        """
        Simulates index lookups. Returns list of (doc_id, text).
        Replace this method with your actual client call (Pinecone, Qdrant, Milvus).
        """
        await asyncio.sleep(0.05)  # Simulate I/O latency
        # Generating deterministic document IDs based on keyword hash simulation
        results = [
            (f"doc_{abs(hash(query + str(i))) % 1000}", f"Context snippet {i} addressing {query}")
            for i in range(top_k)
        ]
        return results

    def compute_rrf(
        self, ranked_results: List[List[Tuple[str, str]]]
    ) -> List[Tuple[str, str, float]]:
        """
        Applies Reciprocal Rank Fusion across parallel search results.
        Returns: [(doc_id, doc_text, rrf_score), ...] sorted descending.
        """
        rrf_scores: Dict[str, float] = {}
        doc_content_map: Dict[str, str] = {}

        for search_pass in ranked_results:
            for rank_idx, (doc_id, content) in enumerate(search_pass, start=1):
                doc_content_map[doc_id] = content
                incremental_score = 1.0 / (self.k_constant + rank_idx)
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + incremental_score

        sorted_docs = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
        return [
            (doc_id, doc_content_map[doc_id], score)
            for doc_id, score in sorted_docs
        ]

    async def run(self, query: str, final_top_n: int = 5) -> List[Tuple[str, str, float]]:
        queries = await self.generate_query_variants(query)
        tasks = [self.mock_vector_retrieval(q) for q in queries]
        all_ranks = await asyncio.gather(*tasks)
        fused_results = self.compute_rrf(all_ranks)
        return fused_results[:final_top_n]
```

### 2.2 Hypothetical Document Embeddings (HyDE) Pipeline

HyDE replaces input vectors with generated context vectors to match the target index topology:

```python
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate

class HyDEPipeline:
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        
        self.prompt = PromptTemplate(
            input_variables=["question"],
            template=(
                "You are an enterprise system technical writer. Write an authoritative, "
                "factual paragraph answering the following question. Do not add introductory phrases "
                "like 'Here is the answer'. Write as if this text was extracted directly "
                "from a verified corporate manual or financial disclosure.\n\n"
                "Question: {question}\n\n"
                "Passage:"
            ),
        )
        self.chain = self.prompt | self.llm

    def generate_hypothetical_embedding(self, question: str) -> List[float]:
        # Step 1: Synthesize a plausible hypothetical document
        hypothetical_doc = self.chain.invoke({"question": question}).content
        
        # Step 2: Embed the generated text rather than the user's raw query
        dense_vector = self.embeddings.embed_query(hypothetical_doc)
        return dense_vector
```

---

## 3. Complex Tabular Data Ingestion Engine

Chunking structured tabular data (CSV, Excel, financial tables) using raw token-based splitters destroys column-row relationships. Splitting a table mid-row makes quantitative extraction impossible.

### 3.1 Dual-State Multi-Vector Ingestion

To index tables reliably:
1. **Preserve full fidelity:** Render tables as standardized Markdown or HTML.
2. **Generate Semantic Metadata Summaries:** LLMs summarize the primary insights, totals, schema, and anomalies.
3. **Multi-Vector Indexing:** Index the *summary* for vector search. Return the *raw table* to the LLM context.

```
                      Raw Table (CSV / HTML / XLSX)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
       Deterministic Linearizer       LLM Semantic Summarizer
       (Row/Col preservation)        (Schema, Key Metrics, Min/Max)
                    │                             │
                    │                             ▼
                    │                  Embedding Pipeline
                    │                             │
                    │                             ▼
                    │                   Vector Store Index
                    │               (Metadata: parent_doc_id)
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                           Document Store
             (doc_id: Full Raw Markdown Table context)
```

```python
import io
import pandas as pd
from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.documents import Document


class ProductionTableIngestionEngine:
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def extract_and_linearize_csv(self, file_bytes: bytes) -> str:
        """Parses CSV and generates a uniform, dense Markdown table."""
        df = pd.read_csv(io.BytesIO(file_bytes))
        df = df.dropna(how="all")
        df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]
        return df.to_markdown(index=False)

    def generate_table_summary(self, markdown_table: str, metadata_context: str) -> str:
        """
        Creates dense, searchable semantic summaries of tabular data
        specifically targeting vector similarity alignment.
        """
        prompt = (
            "You are a quantitative data analyst. Provide a comprehensive semantic summary "
            "for the following corporate table so that an internal search engine can retrieve it.\n"
            "Include:\n"
            "1. The table's primary topic, metrics, and entities.\n"
            "2. Notable maximums, minimums, aggregate totals, and date ranges.\n"
            "3. The explicit list of all column headers and their units.\n\n"
            f"Context: {metadata_context}\n\n"
            f"Table Data:\n{markdown_table}\n\n"
            "Summary Output:"
        )
        response = self.llm.invoke(prompt)
        return response.content

    def process_table_for_index(
        self, table_csv_bytes: bytes, file_name: str, sheet_name: str = "Sheet1"
    ) -> Dict[str, Any]:
        """
        Returns two objects:
        1. Search Document (Summary to be embedded into the Vector DB)
        2. Storage Document (Raw Markdown table to place in context upon match)
        """
        markdown_representation = self.extract_and_linearize_csv(table_csv_bytes)
        context_hint = f"Source Document: {file_name}, Sheet/Section: {sheet_name}"
        
        table_summary = self.generate_table_summary(
            markdown_representation, context_hint
        )
        
        doc_id = f"table_{abs(hash(file_name + sheet_name + markdown_representation[:50]))}"

        # Embedding target document
        search_document = Document(
            page_content=table_summary,
            metadata={
                "doc_id": doc_id,
                "type": "table_summary",
                "source": file_name,
                "sheet": sheet_name,
            },
        )

        # Parent retrieval document
        storage_document = {
            "doc_id": doc_id,
            "raw_table": markdown_representation,
            "source": file_name,
            "sheet": sheet_name,
        }

        return {
            "search_document": search_document,
            "storage_document": storage_document,
        }
```

---

## 4. Hybrid Knowledge Graph (GraphRAG) Integration

Vector searches isolate matching chunks but cannot trace indirect relationships, multi-hop dependencies, or organizational hierarchies. GraphRAG pairs high-dimensional embeddings with explicit knowledge graph traversals.

```
       User Question: "Which suppliers of Battery Cell X have facilities in regions with water risk?"
                                                  │
                 ┌────────────────────────────────┴────────────────────────────────┐
                 │ Hybrid Extraction & Translation Engine                         │
                 └────────────────┬───────────────────────────────────────────────┘
                                  │
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
   Dense Vector Search                             Cypher Query Generation
  (Similarity lookup)                             (Deterministic Structural Graph)
         │                                                 │
         │ (e.g., Doc chunks describing                    MATCH (p:Product {name: 'Battery Cell X'})
         │  suppliers and water risks)                           -[:SUPPLIED_BY]->(s:Supplier)
         │                                                 MATCH (s)-[:OPERATES_IN]->(r:Region)
         │                                                 WHERE r.water_risk = 'High'
         │                                                 RETURN s.name, r.name
         │                                                 │
         └────────────────────────┬────────────────────────┘
                                  │
                                  ▼
                     Context Stitching Engine
         - Graph Structure: Verified factual relationships
         - Vector Text: Semantic color, nuance, prose quotes
                                  │
                                  ▼
                         Generator (LLM)
```

### 4.1 Automated Cypher Extraction Prompt & Schema

This prompt transforms natural-language queries into read-only Cypher commands while enforcing schema constraints:

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class CypherQueryGeneration(BaseModel):
    cypher_statement: str = Field(
        description="The read-only Cypher query to execute against Neo4j. Zero write operations permitted."
    )
    entities_extracted: List[str] = Field(
        description="List of primary business entities identified in query."
    )


GRAPH_SCHEMA = """
Node Types and Properties:
- Organization {name: STRING, ticker: STRING, sector: STRING}
- Facility {name: STRING, location: STRING, water_risk_index: FLOAT}
- Product {name: STRING, sku: STRING}
- Supplier {name: STRING, tier: INTEGER}

Relationship Types:
- (:Supplier)-[:SUPPLIES]->(:Product)
- (:Supplier)-[:OPERATES_FACILITY]->(:Facility)
- (:Organization)-[:ACQUIRED]->(:Organization)
- (:Organization)-[:OWNS]->(:Product)
"""

CYPHER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            f"You are a Neo4j Cypher and Graph Database expert. Translate the user query into "
            f"an optimized, read-only Cypher statement conforming exactly to this graph schema:\n"
            f"{GRAPH_SCHEMA}\n"
            f"Guidelines:\n"
            f"- Use case-insensitive matching where applicable (e.g., toLower(n.name) CONTAINS toLower('...')).\n"
            f"- Do not mutate the database (no CREATE, MERGE, SET, DELETE).\n"
            f"- Always return clear variable names with a limit of 25 results.",
        ),
        ("human", "User Question: {question}"),
    ]
)
```

### 4.2 Production Hybrid Vector + Neo4j Graph Retrieval

This implementation queries Neo4j via Cypher alongside a local vector store, then merges both sources into a unified context payload:

```python
import os
from typing import Dict, Any, List
from neo4j import GraphDatabase
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.documents import Document


class HybridGraphRAGPipeline:
    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_pass: str):
        self.driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0)

    def close(self):
        self.driver.close()

    def execute_graph_query(self, cypher_statement: str) -> List[Dict[str, Any]]:
        """Executes Cypher read transactions safely."""
        with self.driver.session() as session:
            def _read_tx(tx):
                result = tx.run(cypher_statement)
                return [record.data() for record in result]
            return session.execute_read(_read_tx)

    def execute_vector_retrieval(self, query: str, top_k: int = 3) -> List[Document]:
        """
        Executes dense vector search.
        In a production implementation, leverage Neo4j's native vector index:
        `CALL db.index.vector.queryNodes('chunk_vector_index', $top_k, $query_embedding)`
        """
        # Mock snippet for demonstration
        return [
            Document(
                page_content="Supplier Apex Industrial has historically had water scarcity challenges at its Nevada facility.",
                metadata={"source": "risk_audit_2023.pdf", "page": 44},
            )
        ]

    def stitch_hybrid_context(
        self, graph_data: List[Dict[str, Any]], text_docs: List[Document]
    ) -> str:
        """Merges structured graph relationships and unstructured text chunks."""
        context_parts = []
        
        context_parts.append("=== STRUCTURED GRAPH RELATIONSHIPS ===")
        if graph_data:
            for record in graph_data:
                context_parts.append(str(record))
        else:
            context_parts.append("No explicit structural relationships found in graph.")

        context_parts.append("\n=== SEMANTIC RELEVANT TEXT EXCERPTS ===")
        for i, doc in enumerate(text_docs, start=1):
            src = doc.metadata.get("source", "unknown")
            pg = doc.metadata.get("page", "?")
            context_parts.append(f"[{i}] (Source: {src}, Page: {pg}):\n{doc.page_content}")

        return "\n".join(context_parts)

    def query(self, question: str) -> str:
        # Step 1: Generate Cypher query
        structured_generator = self.llm.with_structured_output(CypherQueryGeneration)
        query_analysis: CypherQueryGeneration = structured_generator.invoke(
            CYPHER_PROMPT.format(question=question)
        )

        # Step 2: Fetch graph data
        try:
            graph_data = self.execute_graph_query(query_analysis.cypher_statement)
        except Exception as e:
            # Fallback for invalid Cypher syntax
            graph_data = [{"error": f"Graph query execution failed: {str(e)}"}]

        # Step 3: Fetch vector data
        vector_docs = self.execute_vector_retrieval(question)

        # Step 4: Stitch context together
        complete_context = self.stitch_hybrid_context(graph_data, vector_docs)

        # Step 5: Generate answer
        final_generation_prompt = (
            "You are a GraphRAG Enterprise Copilot. Synthesize an authoritative answer to the question "
            "using both the structured graph entities and unstructured documents provided below. "
            "Highlight both direct operational connections from the graph and qualitative factors from the text.\n\n"
            f"Context Payload:\n{complete_context}\n\n"
            f"Question: {question}\n\n"
            "Final Production Response:"
        )

        response = self.llm.invoke(final_generation_prompt)
        return response.content
```

---

## 5. Enterprise Production Readiness & Fallback Matrix

Production deployments must isolate failures across every retrieval path. The table below outlines root causes, automated fallbacks, and maximum latency envelopes:

| Failure Vector | Detection Signal | Automated Mitigation Routing | Maximum Latency SLA |
| :--- | :--- | :--- | :--- |
| **Complete Retrieval Nullity** | Evaluator returns `binary_score: no` for all top-$k$ docs. | Re-write query via LLM fan-out, trigger BM25 sparse keyword fallback, query cold-tier storage. | < 2,200 ms |
| **Cypher Syntax Failure** | Neo4j engine raises `CypherSyntaxError` or `UnknownRelationship`. | Catch exception, fall back to pure dense-vector retrieval, queue Cypher prompt log for fine-tuning. | < 600 ms |
| **Tabular Schema Mismatch** | LLM Hallucinates column totals due to irregular whitespace or broken tokens. | Ingest raw HTML/Markdown fallback format, route to deterministic Code Interpreter / DuckDB query engine. | < 3,500 ms |
| **High Latency Degradation** | Upstream vector DB $P_{99}$ latency exceeds 1,500 ms threshold. | Circuit-breaker drops reranking node; switches to high-speed cached hybrid index; disables HyDE. | < 800 ms |

### 5.1 Deployment Configuration Checklist (Production YAML)

Save this configuration as `rag_production_config.yaml` to govern agent timeouts, thresholds, and fallback parameters across runtime nodes:

```yaml
version: "2.4"
system_metadata:
  environment: "production"
  pipeline_id: "agentic_crag_graph_hybrid_v1"

nodes:
  evaluator:
    model: "gpt-4o-mini"
    temperature: 0.0
    timeout_ms: 1200
    confidence_threshold: 0.70
    max_retries_on_relevance_failure: 2
    
  hyde_engine:
    enabled: true
    model: "gpt-4o-mini"
    temperature: 0.3
    max_tokens: 200
    skip_on_latency_alert: true

  rrf_fanout:
    enabled: true
    num_query_variants: 3
    k_constant: 60
    per_query_top_k: 5
    concurrency_limit: 5
