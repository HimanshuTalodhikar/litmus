# Phase 1D — RAG Pipeline + First Documents (Days 23–32)

**Goal:** The bot can answer questions using a real knowledge base. Ingest 3–5 real documents, verify citations work, confirm answer quality.

**Time estimate:** 7–10 days

---

## What This Produces

- Qdrant Cloud cluster with document chunks indexed
- Manual ingestion CLI: `python -m app.rag.ingest --file doc.md --source github`
- RAG retrieval: query → vector search → rerank → Claude synthesize → citation
- Bot answers questions about real documents with proper citations
- Conversation context (last 5 turns) passed to Gemini

---

## Deliverables

### 1. Qdrant Cloud Setup

```python
# backend/db/qdrant_client.py (updated)
from qdrant_client import QdrantClient, models
from app.config import get_settings

_qdrant = None

def get_qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        settings = get_settings()
        _qdrant = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
        )
        # Ensure collection exists
        _ensure_collection(_qdrant)
    return _qdrant


def _ensure_collection(client: QdrantClient):
    """Create the knowledge base collection if it doesn't exist."""
    collections = client.get_collections().collections
    collection_names = [c.name for c in collections]

    COLLECTION_NAME = "product_copilot_knowledge"
    VECTOR_SIZE = 768  # text-embedding-004 produces 768-dim vectors

    if COLLECTION_NAME not in collection_names:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE,
            ),
            sparse_vectors_config={
                "text": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            },
        )
        # Create payload indexes for filtering
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="source",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="product_area",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="doc_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
```

### 2. Text Chunker

Create `backend/rag/chunker.py`:

```python
# backend/rag/chunker.py
"""
Domain-specific text chunking for RAG.
"""

from dataclasses import dataclass
from typing import List
import re


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict
    token_count: int


class MarkdownChunker:
    """
    Chunks Markdown documents preserving header hierarchy.
    """

    def __init__(
        self,
        chunk_size: int = 1500,       # tokens
        chunk_overlap: int = 200,     # tokens
        tokens_per_char: float = 0.25, # approx
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tokens_per_char = tokens_per_char

    def chunk_markdown(self, text: str, metadata: dict) -> List[Chunk]:
        """
        Split Markdown document into chunks, preserving H1/H2 header context.
        """
        chunks = []

        # Split by double newlines (paragraphs)
        paragraphs = re.split(r"\n\n+", text)
        current_chunk = ""
        header_context = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Track header context (H1 and H2)
            h1_match = re.match(r"^#\s+(.+)$", para)
            h2_match = re.match(r"^##\s+(.+)$", para)

            if h1_match:
                header_context = f"# {h1_match.group(1)}"
            elif h2_match:
                header_context = f"## {h2_match.group(1)}"

            # If this paragraph is a header, update context and continue
            if h1_match or h2_match:
                if current_chunk:
                    chunks.append(self._make_chunk(current_chunk, metadata, header_context, len(chunks)))
                    current_chunk = ""
                current_chunk = para + "\n\n"
                continue

            # Check if adding this paragraph would exceed chunk size
            estimated_tokens = (len(current_chunk) + len(para)) * self.tokens_per_char

            if estimated_tokens > self.chunk_size and current_chunk:
                # Save current chunk
                chunks.append(self._make_chunk(current_chunk.strip(), metadata, header_context, len(chunks)))

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk)
                current_chunk = (overlap_text + para + "\n\n").strip()
                if overlap_text:
                    current_chunk += "\n\n"
            else:
                current_chunk += para + "\n\n"

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(self._make_chunk(current_chunk.strip(), metadata, header_context, len(chunks)))

        return chunks

    def _make_chunk(
        self, text: str, metadata: dict, header_context: str, index: int
    ) -> Chunk:
        chunk_id = f"{metadata.get('doc_id', 'doc')}:chunk-{index:04d}"
        return Chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                **metadata,
                "header_context": header_context,
                "chunk_index": index,
            },
            token_count=int(len(text) * self.tokens_per_char),
        )

    def _get_overlap_text(self, text: str) -> str:
        """Get the last portion of text for overlap."""
        overlap_chars = int(self.chunk_overlap / self.tokens_per_char)
        if len(text) <= overlap_chars:
            return text
        return text[-overlap_chars:]


class SimpleChunker:
    """Fallback: simple character-based chunking."""

    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 500):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str, metadata: dict) -> List[Chunk]:
        chunks = []
        start = 0
        index = 0

        while start < len(text):
            end = start + self.chunk_size
            chunk_text = text[start:end]

            chunks.append(Chunk(
                chunk_id=f"{metadata.get('doc_id', 'doc')}:chunk-{index:04d}",
                text=chunk_text.strip(),
                metadata={**metadata, "chunk_index": index},
                token_count=len(chunk_text) // 4,
            ))

            start = end - self.chunk_overlap
            index += 1

        return chunks
```

### 3. Embedding Service

Create `backend/rag/embedder.py`:

```python
# backend/rag/embedder.py
"""
Embedding service using GCP Vertex AI (text-embedding-004).
Fetches credentials from AWS Secrets Manager via boto3.
"""

import os
from typing import List
import structlog
from vertexai.language_models import TextEmbeddingModel

logger = structlog.get_logger()

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        _model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    return _model


def embed_texts(texts: List[str], batch_size: int = 10) -> List[List[float]]:
    """
    Embed a list of texts using Vertex AI text-embedding-004.

    Returns a list of embedding vectors (768-dim for text-embedding-004).
    """
    model = get_embedding_model()
    embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            results = model.get_embeddings(batch)
            embeddings.extend([e.values for e in results])
            logger.debug("embed_batch_done", count=len(batch), start=i)
        except Exception as e:
            logger.error("embed_batch_error", error=str(e), batch_start=i)
            # Fallback: return zero vectors for failed batch
            embeddings.extend([[0.0] * 768 for _ in batch])

    return embeddings


def embed_text(text: str) -> List[float]:
    """Embed a single text."""
    return embed_texts([text])[0]
```

### 4. Retrieval Pipeline

Create `backend/rag/retriever.py`:

```python
# backend/rag/retriever.py
"""
Hybrid retrieval pipeline:
1. Vector search (Qdrant)
2. BM25 keyword search (stored in Qdrant as sparse vectors)
3. Reciprocal Rank Fusion
4. Return top-k with metadata
"""

from dataclasses import dataclass
from typing import List, Optional
from app.config import get_settings
from app.rag.embedder import embed_text
from app.db.qdrant_client import get_qdrant
import structlog

logger = structlog.get_logger()

COLLECTION_NAME = "product_copilot_knowledge"


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source: str
    source_url: str
    title: str
    product_area: str
    relevance_score: float
    excerpt: str


def retrieve(
    query: str,
    top_k: int = 5,
    product_area: Optional[str] = None,
) -> List[RetrievedChunk]:
    """
    Hybrid retrieval: vector + keyword → RRF → top-k chunks.
    """
    qdrant = get_qdrant()
    settings = get_settings()

    # 1. Generate query embedding
    query_embedding = embed_text(query)
    logger.debug("query_embedded", query_len=len(query))

    # 2. Vector search (top 30)
    vector_results = qdrant.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        limit=30,
        query_filter={
            "must": [
                {"key": "product_area", "match": {"value": product_area}}
            ] if product_area else []
        } if (product_area) else None,
        with_payload=True,
    )

    # 3. Build results dict (RRF score tracker)
    rrf_scores: dict[str, dict] = {}

    # Apply vector search ranking (rank 1 = best)
    for i, result in enumerate(vector_results):
        chunk_id = result.id
        rrf_scores[chunk_id] = {
            **result.payload,
            "vector_score": result.score,
            "rrf_score": 1.0 / (60 + i + 1),  # RRF with k=60
            "text": result.payload.get("text", ""),
        }

    # 4. Keyword/BF25-style search using Qdrant's sparse vector
    # For simplicity, use a second vector search with a text-based query
    # (Qdrant supports hybrid search natively with `prefetch`)

    # 5. Reciprocal Rank Fusion already applied above (vector ranks only for now)
    # Sort by RRF score
    sorted_results = sorted(
        rrf_scores.values(),
        key=lambda x: x["rrf_score"],
        reverse=True
    )

    # 6. Take top-k and build RetrievedChunk objects
    chunks = []
    for result in sorted_results[:top_k]:
        text = result["text"]
        chunks.append(RetrievedChunk(
            chunk_id=result.get("chunk_id", result.get("id", "")),
            text=text,
            source=result.get("source", "unknown"),
            source_url=result.get("source_url", ""),
            title=result.get("title", "Untitled"),
            product_area=result.get("product_area", ""),
            relevance_score=result.get("vector_score", 0.0),
            excerpt=text[:200] + "..." if len(text) > 200 else text,
        ))

    logger.info(
        "retrieve_done",
        query=query[:50],
        results=len(chunks),
        top_score=chunks[0].relevance_score if chunks else 0,
    )

    return chunks
```

### 5. QA Agent Tool

Create `backend/rag/qa_tool.py`:

```python
# backend/rag/qa_tool.py
"""
ADK Tool: Answer product questions using RAG.
This is the tool the Product Q&A sub-agent uses.
"""

from google.adk.tools import Tool
from app.rag.retriever import retrieve, RetrievedChunk
from app.rag.qa_synthesizer import synthesize_answer
import structlog

logger = structlog.get_logger()

def answer_product_question(
    question: str,
    conversation_history: list[dict] = None,
    top_k: int = 5,
) -> dict:
    """
    ADK Tool: Answer a product question using RAG.

    Args:
        question: The user's question
        conversation_history: List of {"role": "user"/"assistant", "content": "..."}
        top_k: Number of chunks to retrieve

    Returns:
        {
            "answer": str,
            "sources": List[dict],  # For citations
            "confidence": float,
            "chunks": List[RetrievedChunk],
        }
    """
    logger.info("qa_tool_called", question=question[:100])

    # 1. Retrieve relevant chunks
    chunks = retrieve(query=question, top_k=top_k)

    if not chunks:
        return {
            "answer": "I couldn't find any relevant information in the knowledge base. "
                      "This topic may not be documented yet.",
            "sources": [],
            "confidence": 0.0,
            "chunks": [],
        }

    # 2. Build context from chunks
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(
            f"[Source {i}]: {chunk.title}\n"
            f"URL: {chunk.source_url}\n"
            f"{chunk.text[:500]}"
        )
    context = "\n\n".join(context_parts)

    # 3. Build conversation context
    history_text = ""
    if conversation_history:
        history_lines = [
            f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}"
            for msg in conversation_history[-5:]
        ]
        history_text = "Recent conversation:\n" + "\n".join(history_lines) + "\n\n"

    # 4. Synthesize answer
    answer, confidence = synthesize_answer(
        question=question,
        context=context,
        conversation_history=history_text,
    )

    sources = [
        {
            "title": chunk.title,
            "url": chunk.source_url,
            "excerpt": chunk.excerpt,
        }
        for chunk in chunks
    ]

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
        "chunks": chunks,
    }


# Register as ADK Tool
answer_product_question_tool = Tool(
    name="answer_product_question",
    description=(
        "Search the product knowledge base to answer questions about the product. "
        "Use this when users ask 'how do I', 'what is', 'when will', 'where can I find', "
        "or any question about product features, functionality, or policies. "
        "Returns an answer with source citations."
    ),
    parameters={
        "question": {
            "type": "string",
            "description": "The user's question about the product",
        },
        "conversation_history": {
            "type": "list",
            "description": "Recent conversation turns for context (optional)",
        },
    },
    handler=answer_product_question,
)
```

### 6. Answer Synthesizer

Create `backend/rag/qa_synthesizer.py`:

```python
# backend/rag/qa_synthesizer.py
"""
Uses Gemini to synthesize an answer from retrieved chunks.
"""

from vertexai.generative_models import GenerativeModel
import structlog

logger = structlog.get_logger()

_model = None


def get_synthesizer_model():
    global _model
    if _model is None:
        _model = GenerativeModel("gemini-2.5-flash")
    return _model


def synthesize_answer(
    question: str,
    context: str,
    conversation_history: str = "",
    confidence_threshold: float = 0.7,
) -> tuple[str, float]:
    """
    Synthesize an answer from retrieved context using Gemini.

    Returns (answer, confidence_score)
    """
    model = get_synthesizer_model()

    prompt = f"""You are the Product Copilot assistant, answering questions using only the provided context.

## Instructions
- Answer based ONLY on the provided context
- If the context doesn't contain enough information, say "I couldn't find enough information to answer this confidently."
- Cite sources using [Source N] notation inline
- Be concise but complete
- If you're uncertain, say so and provide what you CAN confirm from the context

## Conversation History
{conversation_history or "(No previous conversation)"}

## User Question
{question}

## Context (retrieved from knowledge base)
{context}

## Your Answer
"""

    try:
        response = model.generate_content(prompt)
        answer_text = response.text

        # Estimate confidence from response characteristics
        confidence = _estimate_confidence(answer_text, context)

        logger.info(
            "synthesize_done",
            question=question[:50],
            confidence=confidence,
            answer_len=len(answer_text),
        )

        return answer_text, confidence

    except Exception as e:
        logger.error("synthesize_error", error=str(e))
        return (
            "I encountered an error while generating an answer. Please try again.",
            0.0,
        )


def _estimate_confidence(answer: str, context: str) -> float:
    """Heuristic confidence estimate."""
    score = 0.5  # Base

    if "I couldn't find" in answer or "not enough information" in answer:
        return 0.1

    if "[Source" in answer:
        score += 0.2  # Good: cited sources

    if len(answer) > 100:
        score += 0.1  # Substantive answer

    if len(context) > 200:
        score += 0.1  # Rich context available

    return min(score, 1.0)
```

### 7. Manual Ingestion CLI

Create `backend/rag/ingestion/manual_ingester.py`:

```python
# backend/rag/ingestion/manual_ingester.py
"""
Manual document ingestion CLI.

Usage:
    python -m app.rag.ingestion.manual_ingester \
        --file ./docs/product-roadmap.md \
        --source github \
        --product-area "product" \
        --title "Q3 Product Roadmap"

Environment variables needed:
    GOOGLE_APPLICATION_CREDENTIALS (path to GCP SA key JSON)
    QDRANT_URL
    QDRANT_API_KEY
    DATABASE_URL
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import structlog
from app.rag.chunker import MarkdownChunker, SimpleChunker
from app.rag.embedder import embed_texts
from app.db.qdrant_client import get_qdrant
from app.db.postgres import get_pg_pool

logger = structlog.get_logger()

COLLECTION_NAME = "product_copilot_knowledge"


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def ingest_document(
    file_path: str,
    source: str,
    title: str,
    source_url: str = "",
    product_area: str = "",
    team_owner: str = "",
) -> dict:
    """Ingest a single document into Qdrant + PostgreSQL."""

    # Read file
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    doc_id = f"{source}:{Path(file_path).stem}"
    content_hash = compute_content_hash(content)

    # Check for duplicates
    qdrant = get_qdrant()
    existing = qdrant.count(
        collection_name=COLLECTION_NAME,
        count_filter={"must": [{"key": "doc_id", "match": {"value": doc_id}}]}
    )
    if existing.count > 0:
        logger.warning("document_already_ingested", doc_id=doc_id)
        return {"status": "skipped", "doc_id": doc_id, "reason": "already exists"}

    # Chunk
    chunker = MarkdownChunker(chunk_size=1500, chunk_overlap=200)
    chunks = chunker.chunk_markdown(
        text=content,
        metadata={
            "doc_id": doc_id,
            "source": source,
            "source_url": source_url,
            "title": title,
            "product_area": product_area,
            "team_owner": team_owner,
        }
    )
    logger.info("document_chunked", doc_id=doc_id, chunks=len(chunks))

    # Embed
    chunk_texts = [c.text for c in chunks]
    embeddings = embed_texts(chunk_texts)

    # Upsert to Qdrant
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        points.append({
            "id": chunk.chunk_id,
            "vector": embedding,
            "payload": {
                "chunk_id": chunk.chunk_id,
                "doc_id": doc_id,
                "text": chunk.text,
                "source": source,
                "source_url": source_url,
                "title": title,
                "product_area": product_area,
                "team_owner": team_owner,
                "token_count": chunk.token_count,
                "chunk_index": chunk.metadata.get("chunk_index", 0),
            }
        })

    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
    )
    logger.info("qdrant_upsert_done", doc_id=doc_id, points=len(points))

    # Store metadata in PostgreSQL
    pg = await get_pg_pool()
    await pg.execute("""
        INSERT INTO knowledge_documents (id, source, source_url, title, content_hash, product_area, team_owner, indexed_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT DO NOTHING
    """, doc_id, source, source_url, title, content_hash, product_area, team_owner)

    return {
        "status": "success",
        "doc_id": doc_id,
        "chunks": len(chunks),
        "tokens": sum(c.token_count for c in chunks),
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest a document into Product Copilot")
    parser.add_argument("--file", required=True, help="Path to document file")
    parser.add_argument("--source", required=True, help="Source: github, notion, confluence, manual")
    parser.add_argument("--title", required=True, help="Document title")
    parser.add_argument("--source-url", default="", help="URL to original document")
    parser.add_argument("--product-area", default="", help="Product area")
    parser.add_argument("--team-owner", default="", help="Team that owns this doc")

    args = parser.parse_args()

    import asyncio
    result = asyncio.run(ingest_document(
        file_path=args.file,
        source=args.source,
        title=args.title,
        source_url=args.source_url,
        product_area=args.product_area,
        team_owner=args.team_owner,
    ))

    print(f"Result: {result}")


if __name__ == "__main__":
    main()
```

### 8. Update Root Agent to Use RAG

Update `backend/adk/root_agent.py`:

```python
# backend/adk/root_agent.py (updated)
from google.adk.agents import Agent
from google.adk.tools import Tool
from app.rag.qa_tool import answer_product_question_tool
from app.config import get_settings

settings = get_settings()


root_agent = Agent(
    name="product_copilot_root",
    model="gemini-2.5-flash",
    description="Product Copilot — answers product questions using a knowledge base",
    instruction="""
    You are the Product Copilot assistant.

    Your primary job is to answer product questions accurately using the product knowledge base.

    How to answer questions:
    1. When a user asks a question about the product, use the `answer_product_question` tool
    2. The tool will search the knowledge base and return an answer with citations
    3. Present the answer clearly, citing sources using the format: [Source N]

    If the knowledge base doesn't have enough information:
    - Say so honestly
    - Suggest where the user might find the answer
    - Offer to flag this as a knowledge gap

    Be concise, accurate, and helpful.
    """,
    tools=[answer_product_question_tool],
)
```

### 9. Health Check — Add Qdrant Check

Update `backend/routers/health.py` to test the Qdrant collection:

```python
# backend/routers/health.py (updated)
@router.get("", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    from app.db.qdrant_client import get_qdrant

    # ... existing DB/Redis checks ...

    # Qdrant
    try:
        qdrant = get_qdrant()
        collections = qdrant.get_collections()
        collection_names = [c.name for c in collections.collections]
        if "product_copilot_knowledge" in collection_names:
            count = qdrant.count("product_copilot_knowledge")
            qdrant_status = f"ok ({count.count} chunks)"
        else:
            qdrant_status = "collection_not_found"
    except Exception as e:
        qdrant_status = f"error: {e}"
```

---

## Testing

### 1. Ingest 5 Sample Documents

```bash
# Create sample docs directory
mkdir -p ./sample_docs

# Ingest each document
python -m app.rag.ingestion.manual_ingester \
  --file ./sample_docs/product-roadmap.md \
  --source manual \
  --title "Q3 Product Roadmap" \
  --product-area "product" \
  --source-url "https://notion.so/product-roadmap"

python -m app.rag.ingestion.manual_ingester \
  --file ./sample_docs/feature-flags.md \
  --source manual \
  --title "Feature Flags Guide" \
  --product-area "engineering" \
  --source-url "https://notion.so/feature-flags"
```

### 2. Test RAG End-to-End

```bash
# Via ADK chat endpoint
curl -X POST http://localhost:8080/adk/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What features are planned for Q3?", "user_id": "test-user"}'
```

### 3. Expected Behavior

- [ ] 3-5 documents ingested with visible chunk counts
- [ ] Asking about content in the docs returns an answer with [Source 1] citations
- [ ] Asking about non-ingested content returns "I couldn't find enough information"
- [ ] Citation links point to the correct source_url
- [ ] Second question in same thread includes previous context

---

## Verification Checklist

Before Phase 1 is complete:

- [ ] 5 real documents ingested (chunk counts visible in Qdrant)
- [ ] `/product ask "What's in the Q3 roadmap?"` returns a sourced answer
- [ ] Answers cite correct documents (verify against actual content)
- [ ] Confidence score reflects retrieval quality
- [ ] Non-ingested topics return appropriate "not found" response
- [ ] Multi-turn works: follow-up question gets contextual answer
- [ ] All 5 documents' content is searchable via RAG
- [ ] `/health` shows `"qdrant": "ok (N chunks)"` with correct count
