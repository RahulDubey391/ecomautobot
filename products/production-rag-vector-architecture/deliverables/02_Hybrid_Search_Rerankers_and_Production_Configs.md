# Module 2: Copy-Paste Hybrid Search, Cross-Encoders & DB Configs

Hybrid retrieval—combining dense semantic embeddings with sparse lexical tokens (BM25/SPLADE)—is the baseline architecture required to eliminate retrieval-induced hallucinations in enterprise RAG systems. Dense embeddings capture conceptual meaning and semantic parity, but consistently fail on exact alphanumeric lookups, part numbers, stock keeping units (SKUs), and rare acronyms. Sparse inverted indexes capture precise lexical tokens, but fail completely when queries exhibit vocabulary mismatch.

This module provides 25+ production-tested configurations, database schemas, and orchestration scripts across **pgvector**, **Qdrant**, **Pinecone**, and **Weaviate**, coupled with local and managed cross-encoder rerankers and dynamic context-compression algorithms.

---

## 1. Mathematical Foundations: RRF vs. Relative Score Fusion

When merging dense and sparse candidate sets, simple score addition fails because dense distance metrics (Cosine similarity: $[-1, 1]$, L2 distance: $[0, \infty)$) and sparse scoring algorithms (BM25: $[0, \infty)$) exist across completely incompatible scales and distributions.

### Reciprocal Rank Fusion (RRF)
RRF discards raw similarity scores entirely and operates solely on the ordinal rank of candidate documents across $M$ distinct retrieval mechanisms:

$$RRF\_Score(d \in D) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

Where:
* $D$ is the union of all candidate documents retrieved by dense and sparse systems.
* $M$ is the set of rankers (e.g., $M = \{\text{dense}, \text{sparse}\}$).
* $r_m(d)$ is the 1-based ordinal rank of document $d$ in retrieval method $m$. If document $d$ is not present in ranker $m$, $r_m(d) \to \infty$, rendering $\frac{1}{k + r_m(d)} = 0$.
* $k$ is the smoothing constant (canonical value: $k = 60$). Setting $k = 60$ prevents top-ranked outliers in one retrieval list from disproportionately dominating items that appear reliably within the top 5–20 of all retrieval lists. Lower values ($k \in [10, 20]$) bias results heavily toward items ranked #1 or #2 in either list.

### Relative Score Fusion (RSF / Min-Max Normalized Fusion)
When linear control over retrieval modalities is strictly necessary, apply min-max score normalization before computing a convex combination using weight parameter $\alpha \in [0, 1]$:

$$S_{\text{dense}}'(d) = \frac{S_{\text{dense}}(d) - \min(S_{\text{dense}})}{\max(S_{\text{dense}}) - \min(S_{\text{dense}}) + \epsilon}$$

$$S_{\text{sparse}}'(d) = \frac{S_{\text{sparse}}(d) - \min(S_{\text{sparse}})}{\max(S_{\text{sparse}}) - \min(S_{\text{sparse}}) + \epsilon}$$

$$Score_{\text{final}}(d) = \alpha \cdot S_{\text{dense}}'(d) + (1 - \alpha) \cdot S_{\text{sparse}}'(d)$$

### Pure Python Reciprocal Rank Fusion Implementation

```python
from typing import Dict, List, Any
from collections import defaultdict

def reciprocal_rank_fusion(
    ranked_lists: List[List[Dict[str, Any]]], 
    k: int = 60,
    id_key: str = "id"
) -> List[Dict[str, Any]]:
    """
    Executes Reciprocal Rank Fusion (RRF) over an arbitrary number of ranked candidate lists.
    
    :param ranked_lists: List of candidate document lists, each ordered by descending relevance.
    :param k: RRF smoothing constant (industry standard: 60).
    :param id_key: Unique identifier key present within each document dictionary.
    :return: Consolidated list of documents sorted in descending order by RRF score.
    """
    rrf_scores: Dict[str, float] = defaultdict(float)
    doc_lookup: Dict[str, Dict[str, Any]] = {}

    for ranking_list in ranked_lists:
        for rank, doc in enumerate(ranking_list, start=1):
            doc_id = doc[id_key]
            doc_lookup[doc_id] = doc
            rrf_scores[doc_id] += 1.0 / (k + rank)

    # Sort documents by calculated RRF score descending
    sorted_doc_ids = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)

    fused_results: List[Dict[str, Any]] = []
    for doc_id, score in sorted_doc_ids:
        merged_doc = doc_lookup[doc_id].copy()
        merged_doc["rrf_score"] = score
        fused_results.append(merged_doc)

    return fused_results
```

---

## 2. Production Database Configurations & Hybrid Pipelines

### 2.1 PostgreSQL 16 + pgvector (v0.7.0+)
Production setups combine HNSW indexes on dense vectors with PostgreSQL's native `tsvector` engine indexed via GIN. The unified query executes both searches concurrently in a Common Table Expression (CTE) and merges candidates using deterministic SQL-level RRF.

#### Schema Setup & Optimization Flags
```sql
-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Set maintenance work mem to allow high-throughput HNSW indexing
SET maintenance_work_mem = '2GB';

DROP TABLE IF EXISTS production_documents;
CREATE TABLE production_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id VARCHAR(255) NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    dense_embedding vector(1536) NOT NULL,
    tsv_content tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);

-- HNSW Cosine Distance Index
-- m: max outgoing links per node (16-32 balanced, 64 high precision)
-- ef_construction: size of the dynamic candidate list (64-128 balanced, 256 high precision)
CREATE INDEX idx_prod_docs_hnsw_cosine 
ON production_documents 
USING hnsw (dense_embedding vector_cosine_ops) 
WITH (m = 24, ef_construction = 128);

-- Generalized Inverted Index (GIN) on English Text Vector
CREATE INDEX idx_prod_docs_tsv 
ON production_documents 
USING gin (tsv_content);

-- Index on document_id and metadata for pre-filtered lookups
CREATE INDEX idx_prod_docs_metadata 
ON production_documents 
USING gin (metadata jsonb_path_ops);
```

#### Production Hybrid SQL Query with RRF
```sql
-- Runtime query tuning for HNSW retrieval breadth
SET hnsw.ef_search = 80;

WITH dense_search AS (
    SELECT 
        id,
        content,
        metadata,
        ROW_NUMBER() OVER () as dense_rank
    FROM (
        SELECT 
            id, 
            content, 
            metadata
        FROM production_documents
        WHERE metadata @> '{"tenant_id": "enterprise_corp"}'
        ORDER BY dense_embedding <=> '[0.0125, -0.0432, ... 1536 dims]'::vector
        LIMIT 60
    ) sub_dense
),
sparse_search AS (
    SELECT 
        id,
        content,
        metadata,
        ROW_NUMBER() OVER () as sparse_rank
    FROM (
        SELECT 
            id, 
            content, 
            metadata
        FROM production_documents,
             plainto_tsquery('english', 'ACME-9021 system failure') query
        WHERE tsv_content @@ query
          AND metadata @> '{"tenant_id": "enterprise_corp"}'
        ORDER BY ts_rank_cd(tsv_content, query) DESC
        LIMIT 60
    ) sub_sparse
)
SELECT 
    COALESCE(d.id, s.id) AS id,
    COALESCE(d.content, s.content) AS content,
    COALESCE(d.metadata, s.metadata) AS metadata,
    d.dense_rank,
    s.sparse_rank,
    (
        COALESCE(1.0 / (60 + d.dense_rank), 0.0) + 
        COALESCE(1.0 / (60 + s.sparse_rank), 0.0)
    ) AS rrf_score
FROM dense_search d
FULL OUTER JOIN sparse_search s ON d.id = s.id
ORDER BY rrf_score DESC
LIMIT 20;
```

---

### 2.2 Qdrant (v1.8.0+)
Qdrant provides native sparse-dense hybrid search using dual vectors (dense float32 and sparse indices) executed through server-side Prefetch operations and built-in RRF fusion.

#### Collection Initialization (Python)
```python
import os
from qdrant_client import QdrantClient, models

client = QdrantClient(
    url=os.getenv("QDRANT_URL", "http://localhost:6333"),
    api_key=os.getenv("QDRANT_API_KEY", None),
    timeout=10.0
)

COLLECTION_NAME = "enterprise_knowledge_base"

if not client.collection_exists(COLLECTION_NAME):
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense_vector": models.VectorParams(
                size=1536,
                distance=models.Distance.COSINE,
                hnsw_config=models.HnswConfigDiff(
                    m=24,
                    ef_construct=128,
                    on_disk=False
                )
            )
        },
        sparse_vectors_config={
            "sparse_vector": models.SparseVectorParams(
                index=models.SparseIndexParams(
                    on_disk=False,
                    full_scan_threshold=1000
                )
            )
        },
        optimizers_config=models.OptimizersConfigDiff(
            indexing_threshold=20000,
            memmap_threshold=50000
        ),
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(
                type=models.ScalarType.INT8,
                quantile=0.99,
                always_ram=True
            )
        )
    )
```

#### Complete Hybrid Pipeline Execution with Prefetch
```python
from typing import Dict, List, Any
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

def execute_qdrant_hybrid_query(
    client: QdrantClient,
    collection_name: str,
    query_text: str,
    dense_vector: List[float],
    tenant_id: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    # Generate BM25 sparse representation
    sparse_embeddings = list(sparse_model.query_embed(query_text))
    sparse_indices = sparse_embeddings[0].indices.tolist()
    sparse_values = sparse_embeddings[0].values.tolist()

    tenant_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=tenant_id)
            )
        ]
    )

    # Execute server-side Hybrid Search via RRF Prefetch
    response = client.query_points(
        collection_name=collection_name,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using="dense_vector",
                filter=tenant_filter,
                limit=limit * 2
            ),
            models.Prefetch(
                query=models.SparseVector(
                    indices=sparse_indices,
                    values=sparse_values
                ),
                using="sparse_vector",
                filter=tenant_filter,
                limit=limit * 2
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit
    )

    return [
        {
            "id": point.id,
            "score": point.score,
            "payload": point.payload
        }
        for point in response.points
    ]
```

---

### 2.3 Pinecone Serverless
Pinecone Serverless requires dotproduct metric indices to support hybrid search with dense and sparse values in a single vector record. Alpha controls the trade-off: `alpha = 1.0` is purely dense, `alpha = 0.0` is purely sparse.

#### Client Setup & Alpha Hybrid Scale Function
```python
import os
from typing import Dict, List, Tuple, Any
from pinecone.grpc import PineconeGRPC as Pinecone

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY", "prod-key-placeholder"))
index = pc.Index(host=os.getenv("PINECONE_HOST", "https://prod-index.pinecone.io"))

def scale_hybrid_vectors(
    dense: List[float], 
    sparse: Dict[str, Any], 
    alpha: float
) -> Tuple[List[float], Dict[str, Any]]:
    """
    Applies convex combination scaling to dense and sparse vectors.
    Score = alpha * dense + (1 - alpha) * sparse
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("Alpha must be between 0.0 and 1.0 inclusive.")
    
    scaled_dense = [v * alpha for v in dense]
    scaled_sparse = {
        "indices": sparse["indices"],
        "values": [v * (1.0 - alpha) for v in sparse["values"]]
    }
    return scaled_dense, scaled_sparse

def hybrid_query_pinecone(
    query_dense: List[float],
    query_sparse: Dict[str, Any],
    alpha: float = 0.7,
    top_k: int = 25,
    namespace: str = "production"
) -> List[Dict[str, Any]]:
    scaled_dense, scaled_sparse = scale_hybrid_vectors(query_dense, query_sparse, alpha)
    
    response = index.query(
        namespace=namespace,
        vector=scaled_dense,
        sparse_vector=scaled_sparse,
        top_k=top_k,
        include_metadata=True
    )
    
    return [
        {
            "id": match["id"],
            "score": match["score"],
            "metadata": match["metadata"]
        }
        for match in response.get("matches", [])
    ]
```

---

### 2.4 Weaviate (v4 Python Client)
Weaviate features an engine-native BM25 and vector hybrid integration utilizing relative score fusion or reciprocal rank fusion directly at query compilation.

#### Schema Setup & Hybrid Query Configuration
```python
import os
import weaviate
import weaviate.classes.config as wvc
from weaviate.classes.query import MetadataQuery, HybridFusion

client = weaviate.connect_to_custom(
    http_host=os.getenv("WEAVIATE_HOST", "localhost"),
    http_port=int(os.getenv("WEAVIATE_HTTP_PORT", "8080")),
    http_secure=False,
    grpc_host=os.getenv("WEAVIATE_GRPC_HOST", "localhost"),
    grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
    grpc_secure=False
)

def configure_schema():
    client.collections.delete("KnowledgeBase")
    client.collections.create(
        name="KnowledgeBase",
        vectorizer_config=wvc.Configure.Vectorizer.none(),
        properties=[
            wvc.Property(name="content", data_type=wvc.DataType.TEXT),
            wvc.Property(name="tenant_id", data_type=wvc.DataType.TEXT, index_filterable=True),
            wvc.Property(name="source", data_type=wvc.DataType.TEXT, index_filterable=True),
        ],
        vector_index_config=wvc.Configure.VectorIndex.hnsw(
            distance_metric=wvc.VectorDistances.COSINE,
            ef_construction=128,
            max_connections=24,
            ef=64
        ),
        inverted_index_config=wvc.Configure.inverted_index(
            bm25_b=0.75,
            bm25_k1=1.2,
            index_null_state=True
        )
    )

def execute_weaviate_hybrid(
    query_text: str,
    dense_vector: list[float],
    tenant_id: str,
    alpha: float = 0.65,
    limit: int = 20
):
    collection = client.collections.get("KnowledgeBase")
    
    results = collection.query.hybrid(
        query=query_text,
        vector=dense_vector,
        alpha=alpha,  # 1.0 = Pure Vector, 0.0 = Pure BM25
        fusion_type=HybridFusion.RELATIVE_SCORE,
        filters=wvc.Filter.by_property("tenant_id").equal(tenant_id),
        limit=limit,
        return_metadata=MetadataQuery(score=True, explain_score=True)
    )
    
    return [
        {
            "uuid": str(obj.uuid),
            "content": obj.properties["content"],
            "score": obj.metadata.score,
            "explain_score": obj.metadata.explain_score
        }
        for obj in results.objects
    ]
```

---

## 3. Cross-Encoder Reranking Engines

Bi-encoders generate embeddings for documents and queries separately, calculating similarity via simple vector products. Cross-encoders feed the query and candidate chunk simultaneously into self-attention layers ($[CLS] + Query + [SEP] + Document + [SEP]$), evaluating token-to-token interactions directly.

```
+-------------------------------------------------------------------------------------------------------+
|                                    Cross-Encoder Inference Flow                                        |
|                                                                                                       |
|  Query: "Database deadlock on table lock"                                                             |
|  Doc 1: "PostgreSQL row locks vs table-level deadlocks..."  --> [ Cross-Encoder ] --> Score: 0.9841   |
|                                                                                                       |
|  Query: "Database deadlock on table lock"                                                             |
|  Doc 2: "Hardware requirements for database engines..."     --> [ Cross-Encoder ] --> Score: 0.0012   |
+-------------------------------------------------------------------------------------------------------+
```

### 3.1 Local High-Performance: BAAI/bge-reranker-large
Runs a local cross-encoder using PyTorch, FP16 inference, optimized batching, and dynamic chunk truncation to maximize throughput and avoid out-of-memory errors on GPU instances.

```python
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import List, Dict, Any, Tuple

class LocalCrossEncoderReranker:
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-large",
        max_length: int = 512,
        batch_size: int = 32,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        
        if self.device == "cuda":
            self.model = self.model.half().to(self.device)
        else:
            self.model = self.model.to(self.device)
            
        self.model.eval()

    @torch.no_grad()
    def rerank(
        self, 
        query: str, 
        documents: List[Dict[str, Any]], 
        text_key: str = "content", 
        top_n: int = 5
    ) -> List[Dict[str, Any]]:
        if not documents:
            return []

        pairs: List[Tuple[str, str]] = [(query, doc[text_key]) for doc in documents]
        all_scores: List[float] = []

        for i in range(0, len(pairs), self.batch_size):
            batch_pairs = pairs[i : i + self.batch_size]
            inputs = self.tokenizer(
                batch_pairs,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt"
            ).to(self.device)

            logits = self.model(**inputs).logits.squeeze(dim=-1)
            # Apply sigmoid if the model outputs raw uncalibrated unbounded logits
            batch_scores = torch.sigmoid(logits).detach().cpu().tolist()
            
            if isinstance(batch_scores, float):
                batch_scores = [batch_scores]
            all_scores.extend(batch_scores)

        # Attach scores and rank
        scored_docs = []
        for doc, score in zip(documents, all_scores):
            item = doc.copy()
            item["rerank_score"] = float(score)
            scored_docs.append(item)

        scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored_docs[:top_n]
```

### 3.2 Enterprise Production: Cohere Rerank v3.5
Cohere's managed model (`rerank-v3.5`) handles up to 4,096 tokens per document. The implementation below features robust exponential backoff, relevance thresholding, and token budget bounds.

```python
import os
import time
import logging
from typing import List, Dict, Any, Optional
import cohere
from cohere.errors import TooManyRequestsError, InternalServerError

logger = logging.getLogger(__name__)

class CohereRerankPipeline:
    def __init__(
        self, 
        api_key: Optional[str] = None, 
        model: str = "rerank-v3.5",
        relevance_threshold: float = 0.35
    ):
        self.client = cohere.ClientV2(api_key=api_key or os.getenv("COHERE_API_KEY"))
        self.model = model
        self.relevance_threshold = relevance_threshold

    def rerank_with_retry(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        text_key: str = "content",
        top_n: int = 5,
        max_retries: int = 4
    ) -> List[Dict[str, Any]]:
        if not documents:
            return []

        doc_texts = [d[text_key] for d in documents]
        
        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.rerank(
                    model=self.model,
                    query=query,
                    documents=doc_texts,
                    top_n=top_n
                )
                
                reranked_results: List[Dict[str, Any]] = []
                for result in response.results:
                    # Filter out low-confidence chunks
                    if result.relevance_score >= self.relevance_threshold:
                        original_doc = documents[result.index].copy()
                        original_doc["rerank_score"] = result.relevance_score
                        reranked_results.append(original_doc)
                
                return reranked_results

            except (TooManyRequestsError, InternalServerError) as e:
                sleep_time = (2 ** attempt) + (0.1 * attempt)
                logger.warning(
                    "Cohere Rerank hit error: %s. Retrying attempt %d/%d after %.2fs", 
                    str(e), attempt, max_retries, sleep_time
                )
                if attempt == max_retries:
                    logger.error("Cohere Rerank retries exhausted. Falling back to input ordering.")
                    return documents[:top_n]
                time.sleep(sleep_time)
            except Exception as ex:
                logger.error("Unrecoverable error in Cohere Rerank: %s", str(ex))
                return documents[:top_n]
        return documents[:top_n]
```

---

## 4. Dynamic Context-Compression & Window-Expansion Engine

Raw candidate retrieval often results in chunks that cut off midway through an explanation, or retrieve large chunks where only 5% of the text is relevant. The following pipeline expands reranked hits into adjacent sentences for clarity, then compresses the unified context to fit token budgets.

```
                                  Dynamic Pipeline Flow
                                  
 [ Hybrid Retrieval: Top 60 ]
              |
              v
 [ Cross-Encoder Rerank: Top 5 ]
              |
              v
 [ Sentence Window Expansion ]  --> (Pull -2 and +2 sibling sentences from source)
              |
              v
 [ Deduplication & Overlap Merge ]
              |
              v
 [ Dynamic Extractive Compression ] --> (Preserve sentences exceeding relevance threshold)
              |
              v
 [ Final Structured LLM Prompt ]
```

```python
import re
from typing import List, Dict, Any

class ContextCompressionEngine:
    def __init__(self, tokenizer_model=None):
        # Fallback to precise whitespace/punctuation token heuristic if tokenizer is omitted
        self.tokenizer = tokenizer_model

    def _split_into_sentences(self, text: str) -> List[str]:
        sentence_endings = r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s'
        return [s.strip() for s in re.split(sentence_endings, text) if s.strip()]

    def expand_sentence_window(
        self,
        selected_chunk: Dict[str, Any],
        full_document_text: str,
        window_size: int = 2
    ) -> str:
        """
        Locates the retrieved chunk within its source document and expands it
        by `window_size` sentences in both directions.
        """
        all_sentences = self._split_into_sentences(full_document_text)
        chunk_sentences = self._split_into_sentences(selected_chunk["content"])
        
        if not chunk_sentences:
            return selected_chunk["content"]

        start_probe = chunk_sentences[0]
        try:
            match_index = next(i for i, s in enumerate(all_sentences) if start_probe in s)
        except StopIteration:
            return selected_chunk["content"]

        start_idx = max(0, match_index - window_size)
        end_idx = min(len(all_sentences), match_index + len(chunk_sentences) + window_size)

        return " ".join(all_sentences[start_idx:end_idx])

    def compress_by_relevance(
        self,
        expanded_context: str,
        query: str,
        cross_encoder: LocalCrossEncoderReranker,
        token_budget: int =
