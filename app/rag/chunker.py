"""
Markdown document chunker for RAG ingestion.
Splits markdown files into semantic chunks by heading sections.
"""

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    content: str
    source: str  # filename
    heading: str  # nearest heading above the chunk


def chunk_markdown(text: str, source: str, max_chars: int = 500) -> list[Chunk]:
    """
    Split markdown into chunks at ## headings.
    Each chunk starts at a ## heading and collects content until the next ##.
    If a section is longer than max_chars, split it further by paragraph.
    """
    # Split on ## headings (keep the heading text)
    sections = re.split(r"(?=^## .+)$", text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    chunks = []
    for section in sections:
        lines = section.split("\n")
        heading = ""
        if lines and lines[0].startswith("## "):
            heading = lines[0].lstrip("#").strip()
            body_lines = lines[1:]
        else:
            body_lines = lines

        body = "\n".join(body_lines).strip()
        if not body:
            continue

        # If under limit, emit as single chunk
        if len(body) <= max_chars:
            chunks.append(Chunk(content=body, source=source, heading=heading))
            continue

        # Split by paragraphs
        paras = [p.strip() for p in body.split("\n\n") if p.strip()]
        current = ""
        for para in paras:
            if len(current) + len(para) + 2 <= max_chars:
                current += ("\n\n" if current else "") + para
            else:
                if current:
                    chunks.append(Chunk(content=current, source=source, heading=heading))
                current = para
        if current:
            chunks.append(Chunk(content=current, source=source, heading=heading))

    return chunks


def load_markdown_file(path: str) -> tuple[str, str]:
    """Load a markdown file and return (raw_text, filename)."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    import os
    filename = os.path.basename(path)
    return content, filename
