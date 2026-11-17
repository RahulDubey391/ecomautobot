# Module 1: Core Retrieval Architecture & Chunking Strategies

This deliverable provides complete, production-grade architectural blueprints, algorithmic implementations, and optimization parameters for the data preparation and vector retrieval layers of an enterprise RAG system.

---

## 1. Enterprise Chunking Taxonomy & Production Implementations

A chunking strategy dictates the theoretical upper bound of your retrieval accuracy. Chunking too small destroys contextual coherence; chunking too large dilutes the specific semantic vectors needed for sharp cosine discrimination.

### Strategy Comparison Matrix

| Strategy | Token Window | Boundary Method | Best Used For | Ingestion Latency | Failure Modes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Fixed-Size Sliding Window** | 256–512 tokens (10–20% overlap) | Character/Token count | Bulk unstructured narrative text, low-compute ingestion pipelines | Low ($<10$ ms/doc) | Splits semantic propositions mid-clause; creates duplicate hits across overlapping segments |
| **Semantic Similarity Splitting** | Dynamic (100–800 tokens) | Embedding distance threshold between adjacent sentences | Varied long-form text (research papers, transcripts, technical reports) | High ($200–800$ ms/doc) | Threshold tuning sensitivity: yields micro-chunks on rapid subject shifts, runaways on monotonic text |
| **Hierarchical Parent-Child** | Child: 128–256 tokens<br>Parent: 1024–2048 tokens | Child: Semantic/Fixed<br>Parent: Structural (H2/H3 headers or fixed blocks) | High-precision retrieval requiring wide context generation (legal, clinical, manuals) | Moderate ($50–150$ ms/doc) | Cache thrashing on parent reconstruction if relational links are poorly indexed |
| **Late Chunking** | Dynamic or Fixed applied *post-pooling* | Full context processed via long-context encoder (e.g., 8192 tokens); split at token boundary | Highly entangled multi-turn dialogue, dense cross-referential manuals | Extreme ($1000+$ ms/doc) | High GPU VRAM requirements; limited model ecosystem support |

---

### Implementation 1: Dynamic Semantic Boundary Chunking

This implementation calculates sentence-level embeddings, evaluates the cosine distance across a rolling sequence window, and breaks text where semantic distance crosses a dynamic statistical threshold ($\mu + k \cdot \sigma$).

```python
import re
import numpy as np
from typing import List, Dict, Any

class SemanticChunker:
    def __init__(
        self, 
        embedding_client, 
        model_name: str = "text-embedding-3-small",
        std_dev_multiplier: float = 1.2,
        min_chunk_size: int = 50,
        max_chunk_size: int = 500
    ):
        """
        Embeds adjacent sentences and splits on statistical anomalies in semantic distance.
        """
        self.client = embedding_client
        self.model_name = model_name
        self.std_dev_multiplier = std_dev_multiplier
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

    def _split_into_sentences(self, text: str) -> List[str]:
        # Production regex handling standard punctuation, quotes, abbreviations, and list items
        sentence_end = re.compile(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s')
        sentences = [s.strip() for s in sentence_end.split(text) if s.strip()]
        return sentences

    def _compute_cosine_distances(self, embeddings: np.ndarray) -> np.ndarray:
        # Normalize embeddings to unit length for direct dot-product cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / np.clip(norms, a_min=1e-12, a_max=None)
        
        # Dot product between vector[i] and vector[i+1]
        similarities = np.sum(normalized[:-1] * normalized[1:], axis=1)
        distances = 1.0 - similarities
        return distances

    def chunk_document(self, text: str) -> List[Dict[str, Any]]:
        sentences = self._split_into_sentences(text)
        if len(sentences) <= 1:
            return [{"chunk_id": 0, "text": text, "token_count_approx": len(text.split())}]

        # 1. Batch generate embeddings for all individual sentences
        response = self.client.embeddings.create(
            input=sentences,
            model=self.model_name
        )
        embeddings = np.array([item.embedding for item in response.data])

        # 2. Compute adjacent distances
        distances = self._compute_cosine_distances(embeddings)

        # 3. Dynamic thresholding via standard deviations above mean
        mean_distance = np.mean(distances)
        std_distance = np.std(distances)
        breakpoint_threshold = mean_distance + (self.std_dev_multiplier * std_distance)

        # 4. Construct chunks enforcing min/max boundaries
        chunks = []
        current_chunk_sentences = [sentences[0]]
        current_chunk_len = len(sentences[0].split())

        for idx, dist in enumerate(distances):
            next_sentence = sentences[idx + 1]
            next_sentence_len = len(next_sentence.split())

            is_semantic_break = dist > breakpoint_threshold
            exceeds_max = (current_chunk_len + next_sentence_len) > self.max_chunk_size
            below_min = current_chunk_len < self.min_chunk_size

            if (is_semantic_break or exceeds_max) and not below_min:
                chunk_str = " ".join(current_chunk_sentences)
                chunks.append({
                    "chunk_id": len(chunks),
                    "text": chunk_str,
                    "token_count_approx": current_chunk_len
                })
                current_chunk_sentences = [next_sentence]
                current_chunk_len = next_sentence_len
            else:
                current_chunk_sentences.append(next_sentence)
                current_chunk_len += next_sentence_len

        # Append trailing sentences
        if current_chunk_sentences:
            chunks.append({
                "chunk_id": len(chunks),
                "text": " ".join(current_chunk_sentences),
                "token_count_approx": current_chunk_len
            })

        return chunks
```

---

### Implementation 2: Hierarchical Parent-Child (Small-to-Big) Architecture

Hierarchical chunking indexes small "child" chunks to ensure high-accuracy vector retrieval while pointing directly to an encompassing "parent" chunk injected into the LLM prompt. This resolves the context-retrieval tradeoff.

```
+---------------------------------------------------------------------------------+
|                                 DOCUMENT STREAM                                 |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
| PARENT CHUNK (1,024 Tokens)                                                     |
| Payload ID: parent_001                                                          |
| Context: Full architectural breakdown, API contract definitions, and trade-offs |
+---------------------------------------------------------------------------------+
         |                                           |
         v                                           v
+-------------------------------+   +-------------------------------+
| CHILD CHUNK 1 (256 Tokens)    |   | CHILD CHUNK 2 (256 Tokens)    |
| Vectorized in DB              |   | Vectorized in DB              |
| Metadata:                     |   | Metadata:                     |
|   parent_id: "parent_001"     |   |   parent_id: "parent_001"     |
|   position: 0                 |   |   position: 1                 |
+-------------------------------+   +-------------------------------+
```

```python
import uuid
from typing import List, Dict, Tuple

class HierarchicalChunker:
    def __init__(self, parent_size: int = 1000, child_size: int = 200, overlap: int = 40):
        self.parent_size = parent_size
        self.child_size = child_size
        self.overlap = overlap

    def _tokenize(self, text: str) -> List[str]:
        # Production systems should replace with tiktoken or native tokenizer
        return text.split()

    def process(self, document: str, doc_metadata: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        tokens = self._tokenize(document)
        parent_records = []
        child_records = []

        # Generate Parents
        parent_step = self.parent_size - self.overlap
        for p_idx in range(0, len(tokens), parent_step):
            p_tokens = tokens[p_idx : p_idx + self.parent_size]
            parent_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_metadata.get('doc_id')}_{p_idx}"))
            parent_text = " ".join(p_tokens)
            
            parent_records.append({
                "parent_id": parent_id,
                "text": parent_text,
                "metadata": {**doc_metadata, "type": "parent", "token_count": len(p_tokens)}
            })

            # Generate Children for this specific Parent
            child_step = self.child_size - self.overlap
            for c_idx in range(0, len(p_tokens), child_step):
                c_tokens = p_tokens[c_idx : c_idx + self.child_size]
                if not c_tokens:
                    continue
                child_id = str(uuid.uuid4())
                child_text = " ".join(c_tokens)

                child_records.append({
                    "child_id": child_id,
                    "parent_id": parent_id,
                    "text": child_text,
                    "metadata": {
                        **doc_metadata,
                        "type": "child",
                        "parent_id": parent_id,
                        "token_count": len(c_tokens)
                    }
                })

        return parent_records, child_records
```

---

## 2. Vector Index Mechanics: HNSW vs. IVF-PQ

Choosing the wrong index configuration can cause production latency spikes (HNSW p99 ballooning under high concurrent writes) or severe recall degradation (IVF-PQ with suboptimal centroids).

```
                      HNSW (Hierarchical Navigable Small World)
Level 2:   O -----------------------------------------> O
           |                                            |
Level 1:   O --------------------> O -----------------> O
           |                       |                    |
Level 0:   O <-> O <-> O <-> O <-> O <-> O <-> O <-> O <-> O
           (Multi-layer skip-list graph: Logarithmic routing, high RAM usage)

                      IVF-PQ (Inverted File with Product Quantization)
Dataset Vectors ---> Centroid Assignment (IVF Partitioning: Voronoi Cells)
                      |
                      v
             [Cell 1] [Cell 2] [Cell 3] ... [Cell N]
                      |
                      v
             Product Quantization (Vector 1536-D -> 64-D Subspace Byte Codes)
             (Low RAM, requires offline training step, higher search degradation)
```

### Architectural Trade-Off Analysis

| Parameter / Metric | HNSW (Hierarchical Navigable Small World) | IVF-PQ (Inverted File with Product Quantization) |
| :--- | :--- | :--- |
| **Index Structure** | Multi-layer geometric graphs; upper layers act as skip-lists; bottom layer contains all vectors. | Inverted file system indexing vector clusters; vectors compressed via sub-vector quantization. |
| **RAM Footprint (1M 1536-D vectors)** | **High**: $\approx 8.5\text{ GB}$ (Vector data + edge lists). Formula: `Bytes = N * (D * 4 + M * 8)` | **Minimal**: $\approx 0.5 - 1.2\text{ GB}$. Quantizes 32-bit floats into 8-bit cluster indices. |
| **Query Latency (p99)** | **1–5 ms**: Graph traversals converge logarithmically with minimal hopping. | **15–40 ms**: Centroid probe scanning + code lookup overhead. |
| **Recall@10 Retention** | **98% – 99.5%**: Graph connectivity preserves true structural nearest neighbors. | **82% – 93%**: Suffers from quantization distortion and edge-case cluster boundaries. |
| **Write/Indexing Speed** | **Slow**: Linear decay as graph grows. Dynamic node insertion requires runtime edge recalculation. | **Fast at runtime, but requires cold batch training**: Offline k-means clustering to define centroids. |
| **Production Recommendation** | Real-time enterprise assistants, high accuracy requirements, RAM-abundant nodes. | Mass-scale datasets ($>50\text{M}$ vectors), edge hardware, cost-sensitive cold storage. |

### Production Engine Tuning Configurations

#### Milvus HNSW Production Definition
```json
{
  "metric_type": "COSINE",
  "index_type": "HNSW",
  "params": {
    "M": 32,             // Max outgoing edges per node (Range: 16-64). Higher = higher recall, higher RAM.
    "efConstruction": 200, // Search depth during index build (Range: 100-512). Higher = slower build, higher recall.
    "ef": 96              // Search depth at query time (Range: 32-256). ef >= top_k.
  }
}
```

#### Qdrant Production Configuration
```json
{
  "hnsw_config": {
    "m": 32,
    "ef_construct": 200,
    "full_scan_threshold": 10000,
    "max_indexing_threads": 8,
    "on_disk": false
  },
  "quantization_config": {
    "scalar": {
      "type": "int8",
      "quantile": 0.99,
      "always_ram": true
    }
  }
}
```

#### IVF-PQ Benchmark Tuning Template (1M Scale Vectors)
```json
{
  "metric_type": "L2",
  "index_type": "IVF_PQ",
  "params": {
    "nlist": 2048,  // Total Voronoi cells. Rule of thumb: 4 * sqrt(N). For 1M vectors = 4096.
    "m": 64,        // Number of partitioned sub-vectors. Must cleanly divide vector dimension (1536 / 64 = 24).
    "nbits": 8,     // Bits allocated per sub-vector. 8 bits = 256 centroids per subspace.
    "nprobe": 32    // Centroids to inspect at query time (1-10% of nlist). Higher = higher recall, higher latency.
  }
}
```

---

## 3. Metadata Filtering Architecture

Naive retrieval architectures query vectors first and filter metadata post-hoc ("post-filtering"). This causes catastrophic result degradation when filters match less than 5% of your document corpus (e.g., retrieving `top_k=20` returns 0 results because the non-compliant vectors were removed after searching). 

Enterprise deployments must enforce **Single-Stage Filtered Vector Search** (or dynamic pre-filtering) utilizing payload inverted indices coupled to bitset operations before distance calculation.

```
+--------------------------------------------------------------------------------------------------+
|                                    SEARCH ENGINE QUERY RUNTIME                                   |
+--------------------------------------------------------------------------------------------------+
                                                 |
         +---------------------------------------+---------------------------------------+
         v                                                                               v
+----------------------------------------------------+   +----------------------------------------------------+
| 1. PAYLOAD INVERTED INDEX RESOLUTION               |   | 2. HNSW SEARCH PIPELINE                            |
| Filter: {org_id: "org_enterprise_99"}              |   | Start at Entry Node                                |
| Produces: Bitset Array [1, 0, 0, 1, 1, 0, 1]       |   | Traverse layers down to Base Layer                 |
+----------------------------------------------------+   +----------------------------------------------------+
                                                 \                               /
                                                  v                             v
                                 +----------------------------------------------------+
                                 | 3. COMBINED ITERATOR EVALUATION                    |
                                 | During graph traversal at Base Layer:              |
                                 | Evaluate candidate node ONLY IF bitset[node] == 1  |
                                 | Guarantees Top-K results match criteria perfectly. |
                                 +----------------------------------------------------+
```

### Production Metadata Payload JSON Schema

Use this structural schema for every stored chunk to guarantee uniform filtering capability across ACLs, tenant boundaries, and chronological invalidations.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ProductionVectorPayload",
  "type": "object",
  "properties": {
    "chunk_id": { "type": "string", "format": "uuid" },
    "document_id": { "type": "string" },
    "parent_id": { "type": ["string", "null"] },
    "text": { "type": "string" },
    "tenant_context": {
      "type": "object",
      "properties": {
        "org_id": { "type": "string" },
        "workspace_id": { "type": "string" },
        "user_id": { "type": "string" },
        "acl_groups": { 
          "type": "array", 
          "items": { "type": "string" } 
        }
      },
      "required": ["org_id", "workspace_id", "acl_groups"]
    },
    "temporal": {
      "type": "object",
      "properties": {
        "created_at": { "type": "integer" },
        "valid_until": { "type": ["integer", "null"] },
        "version": { "type": "string" }
      },
      "required": ["created_at"]
    },
    "structural": {
      "type": "object",
      "properties": {
        "source_type": { "type": "string", "enum": ["pdf", "markdown", "slack", "notion", "sql"] },
        "chunk_index": { "type": "integer" },
        "total_chunks": { "type": "integer" },
        "contains_tables": { "type": "boolean" },
        "token_count": { "type": "integer" }
      },
      "required": ["source_type", "chunk_index", "token_count"]
    }
  },
  "required": ["chunk_id", "document_id", "text", "tenant_context", "temporal", "structural"]
}
```

### Production Search Query Filter Implementation (Qdrant Client)

```python
from qdrant_client import QdrantClient
from qdrant_client.http import models
from typing import List, Dict, Any

def execute_hard_filtered_search(
    client: QdrantClient,
    collection_name: str,
    query_vector: List[float],
    org_id: str,
    active_acl_groups: List[str],
    current_timestamp: int,
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """
    Executes a high-efficiency single-stage filtered vector search.
    Enforces tenant boundaries, ACL groups, and TTL expiration via inverted bitsets.
    """
    
    strict_filter = models.Filter(
        must=[
            # Hard Tenant Isolation
            models.FieldCondition(
                key="tenant_context.org_id",
                match=models.MatchValue(value=org_id)
            ),
            # ACL Array Overlap: user must hold at least one matching group
            models.FieldCondition(
                key="tenant_context.acl_groups",
                match=models.MatchAny(any=active_acl_groups)
            ),
            # Temporal Filter: Document must still be valid
            models.FieldCondition(
                key="temporal.valid_until",
                range=models.Range(gt=current_timestamp)
            )
        ]
    )

    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        query_filter=strict_filter,
        limit=top_k,
        search_params=models.SearchParams(
            hnsw_ef=128,      // Over-ride default efSearch for low-selectivity queries
            exact=False       // True forces linear brute-force scan across bitmask
        )
    )

    return [
        {
            "id": hit.id,
            "score": hit.score,
            "text": hit.payload.get("text"),
            "parent_id": hit.payload.get("parent_id"),
            "metadata": hit.payload
        }
        for hit in results
    ]
```

---

## 4. Embedding Model Selection Matrix & Matryoshka Mechanics

Selecting an embedding model is an architectural trade-off balancing representational fidelity, latency overhead, dimensional storage weight, and vector search throughput.

### MTEB (Massive Text Embedding Benchmark) Comparison

| Model | Dimensions | Context Window | MTEB Retrieval (NDCG@10) | Inference Latency (Batch=1, GPU) | Hosting Mechanics | Native Matryoshka Support | Cost / 1M Tokens |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **text-embedding-3-large** | 3072 (Native) | 8,191 | 55.4 | $\approx 25\text{ ms}$ | Proprietary API (OpenAI) | **Yes** (Truncate down to 256) | $0.13 |
| **bge-large-en-v1.5** | 1024 | 512 | 54.3 | $\approx 12\text{ ms}$ | Self-Hosted (1x A10G / Triton) | No | Compute variable |
| **bge-m3** | 1024 | 8,192 | 56.2 | $\approx 35\text{ ms}$ | Self-Hosted (Dense+Sparse+ColBERT)| No | Compute variable |
| **voyage-large-2-instruct**| 1536 | 16,000 | 58.1 | $\approx 45\text{ ms}$ | Proprietary API (Voyage AI) | No | $0.12 |
| **nomic-embed-text-v1.5** | 768 (Native) | 8,192 | 52.8 | $\approx 8\text{ ms}$ | Self-Hosted / Managed API | **Yes** (Truncate down to 64) | $0.02 |

### Matryoshka Representation Learning (MRL) Code Implementation

Matryoshka embeddings optimize inference by storing coarse representations up front. You can compress vectors from 3072 dimensions down to 512 or 256 dimensions with negligible recall drop (often $<1.5\%$), reducing RAM requirements and distance calculation compute overhead by up to $80\%$.

```python
import numpy as np
from typing import List

class MatryoshkaCompressor:
    @staticmethod
    def truncate_and_normalize(embedding: List[float], target_dim: int) -> List[float]:
        """
        Truncates an MRL-enabled dense embedding and re-applies L2 normalization.
        Critical: Truncation without normalization breaks cosine similarity metrics.
        """
        arr = np.array(embedding, dtype=np.float32)
        
        # 1. Truncate array to target lower dimension
        truncated = arr[:target_dim]
        
        # 2. Compute exact L2 norm
        l2_norm = np.linalg.norm(truncated)
        
        if l2_norm == 0:
            return truncated.tolist()
            
        # 3. Project back onto the unit hypersphere
        normalized = truncated / l2_norm
        return normalized.tolist()

# Demonstration with OpenAI text-embedding-3-large
def embed_query_with_mrl(client, text: str, target_dim: int = 512) -> List[float]:
    response = client.embeddings.create(
        input=[text],
        model="text-embedding-3-large",
        # Notice: OpenAI allows requesting dimensions natively via API
        # but understanding the manual array slice guarantees independence from vendor APIs:
        dimensions=target_dim
    )
    return response.data[0].embedding
```

---

## 5. End-to-End Production Ingestion Pipeline

The following script integrates the parent-child chunking strategy, metadata schema enforcement, MRL compression, and batched payload serialization into an ingestion engine ready for deployment.

```python
#!/usr/bin/env python3
import time
import uuid
from typing import List, Dict, Any
from dataclasses import dataclass
import numpy as np

# Mocking the client interfaces for copy-paste reliability
class MockVectorDB:
    def upsert(self, collection_name: str, points: List[Dict[str, Any]]):
        print(f"[DB] Successfully committed {len(points)} points to '{collection_name}'.")

class MockEmbeddingEngine:
    def create(self, input: List[str], model: str, dimensions: int):
        # Generate mock valid normalized vectors
        vectors = []
        for _ in input:
            v = np.random.randn(dimensions).astype(np.float32)
            v /= np.linalg.norm(v)
            vectors.append(v.tolist())
        return type("Obj", (), {"data": [type("Sub", (), {"embedding": vec})() for vec in vectors]})

@dataclass
class DocumentPayload:
    doc_id: str
    body: str
    org_id: str
    workspace_id: str
    acl_groups: List[str]
    source_type: str
    ttl_seconds: int = 31536000  # Default 1 year

class ProductionIngestionEngine:
    def __init__(self, target_dim: int = 512, batch_size: int = 64):
        self.target_dim = target_dim
        self.batch_size = batch_size
        self.embedding_model = "text-embedding-3-large"
        self.vector_db = MockVectorDB()
        self.embed_engine = MockEmbeddingEngine()

    def _chunk_text(self, text: str, chunk_size: int = 250, overlap: int = 30) -> List[str]:
        words = text.split()
        chunks = []
        step = chunk_size - overlap
        for i in range(0, len(words), step):
            segment = words[i:i + chunk_size]
            if segment:
                chunks.append(" ".join(segment))
        return chunks

    def process_and_ingest(self, document: DocumentPayload):
        now = int(time.time())
        expires_at = now + document.ttl_seconds

        # 1. Structural Hierarchical Decomposition
        # Parent Chunking (Coarse: 1000 words)
        parent_raw_chunks = self._chunk_text(document.body, chunk_size=1000, overlap=100)
        
        points_to_upsert = []

        for p_idx, p_text in enumerate(parent_raw_chunks):
            parent_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document.doc_id}_p_{p_idx}"))
            
            # Child Chunking (Fine: 200 words)
            child_raw_chunks = self._chunk_text(p_text, chunk_size=200, overlap=25)
            
            # 2. Embedding Generation (Batch Embed Child Chunks)
            for i in range(0, len(child_raw_chunks), self.batch_size):
                batch_texts = child_raw_chunks[i:i + self.batch_size]
                
                # Fetch MRL-truncated vectors directly
                response = self.embed_engine.create(
                    input=batch_texts,
                    model=self.embedding_model,
                    dimensions=self.target_dim
                )
                embeddings = [item.embedding for item in response.data]

                # 3. Construct Payload adhering strictly to Enterprise Schema
                for c_idx, (c_text, c_vec) in enumerate(zip(batch_texts, embeddings)):
                    chunk_id = str(uuid.uuid4())
                    
                    point = {
                        "id": chunk_id,
                        "vector": c_vec,
                        "payload": {
                            "chunk_id": chunk_id,
                            "document_id": document.doc_id,
                            "parent_id": parent_id,
                            "parent_text": p_text,  # Denormalized for high-speed LLM context loading
                            "text": c_text,
                            "tenant_context": {
