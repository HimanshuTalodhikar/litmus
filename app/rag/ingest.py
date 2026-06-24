"""
RAG ingestion script — ingests markdown product docs into Qdrant.

Usage:
    python -m app.rag.ingest /path/to/docs/

Each .md file is treated as one product. The filename (without .md)
becomes the product name.
"""

import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.rag.chunker import chunk_markdown, load_markdown_file
from app.rag.embedder import embed_texts
from app.rag.retriever import upsert_chunks, ensure_collection


def ingest_directory(directory: str, batch_size: int = 50):
    """
    Ingest all .md files from a directory into Qdrant.
    """
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a directory")
        return

    md_files = sorted([f for f in os.listdir(directory) if f.endswith(".md")])
    if not md_files:
        print(f"No .md files found in {directory}")
        return

    print(f"Found {len(md_files)} markdown files to ingest")

    all_chunks = []
    chunk_id = 0

    for filename in md_files:
        filepath = os.path.join(directory, filename)
        text, _ = load_markdown_file(filepath)
        chunks = chunk_markdown(text, filename)

        # Pre-embed all chunks for this file
        texts = [c.content for c in chunks]
        vectors = embed_texts(texts)

        for chunk, vector in zip(chunks, vectors):
            all_chunks.append({
                "id": chunk_id,
                "content": chunk.content,
                "source": chunk.source,
                "heading": chunk.heading,
                "vector": vector,
            })
            chunk_id += 1

        print(f"  {filename}: {len(chunks)} chunks")

    print(f"\nIngesting {len(all_chunks)} total chunks into Qdrant...")
    ensure_collection()
    upsert_chunks(all_chunks, batch_size=batch_size)
    print(f"Done. {len(all_chunks)} chunks indexed.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.rag.ingest <docs_directory>")
        sys.exit(1)
    ingest_directory(sys.argv[1])
