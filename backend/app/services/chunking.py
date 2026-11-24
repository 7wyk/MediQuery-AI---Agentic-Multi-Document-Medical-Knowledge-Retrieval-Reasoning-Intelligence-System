"""Structure-aware chunking for text, tables, charts and images."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.extraction import ExtractedBlock

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


class ChunkingError(RuntimeError):
    pass


@dataclass
class ChunkDraft:
    content: str
    content_type: str
    page: Optional[int]
    section: Optional[str]
    table_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _split_text(text: str, size: int, overlap: int) -> List[str]:
    """Paragraph/sentence-aware splitter with a character overlap."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    pieces: List[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        sentences = _SENTENCE_BOUNDARY.split(paragraph)
        buffer = ""
        for sentence in sentences:
            if len(sentence) > size:
                if buffer:
                    pieces.append(buffer.strip())
                    buffer = ""
                for start in range(0, len(sentence), size - overlap):
                    pieces.append(sentence[start : start + size].strip())
                continue
            if len(buffer) + len(sentence) + 1 <= size:
                buffer = f"{buffer} {sentence}".strip()
            else:
                if buffer:
                    pieces.append(buffer.strip())
                buffer = sentence
        if buffer.strip():
            pieces.append(buffer.strip())

    if overlap <= 0 or len(pieces) <= 1:
        return [p for p in pieces if p]

    merged: List[str] = []
    for index, piece in enumerate(pieces):
        if index == 0:
            merged.append(piece)
            continue
        tail = merged[-1][-overlap:] if merged else ""
        merged.append((tail + " " + piece).strip())
    return [p for p in merged if p]


def _split_table(block: ExtractedBlock, size: int) -> List[str]:
    lines = [line for line in block.content.splitlines() if line.strip()]
    if not lines:
        return []
    header, body = lines[0], lines[1:]
    if len(block.content) <= size:
        return [block.content]
    groups: List[str] = []
    current: List[str] = []
    current_len = len(header)
    for line in body:
        if current and current_len + len(line) + 1 > size:
            groups.append(header + "\n" + "\n".join(current))
            current, current_len = [], len(header)
        current.append(line)
        current_len += len(line) + 1
    if current:
        groups.append(header + "\n" + "\n".join(current))
    return groups or [block.content]


def build_chunks(
    blocks: List[ExtractedBlock],
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 120,
    max_chunks: int = 4000,
) -> List[ChunkDraft]:
    drafts: List[ChunkDraft] = []
    size = max(300, int(chunk_size))
    overlap = max(0, min(int(chunk_overlap), size // 2))

    for block in blocks:
        if not block.content.strip():
            continue
        if block.content_type == "table":
            pieces = _split_table(block, size)
        elif block.content_type in {"chart", "image"}:
            pieces = [block.content]
        else:
            pieces = _split_text(block.content, size, overlap)

        for piece in pieces:
            if not piece.strip():
                continue
            drafts.append(
                ChunkDraft(
                    content=piece.strip(),
                    content_type=block.content_type,
                    page=block.page,
                    section=block.section,
                    table_id=block.table_id,
                    metadata={
                        "char_count": len(piece),
                        "token_estimate": estimate_tokens(piece),
                        **block.metadata,
                    },
                )
            )
        if len(drafts) > max_chunks:
            raise ChunkingError(
                f"Document produced more than {max_chunks} chunks; reduce its size or split it."
            )

    if not drafts:
        raise ChunkingError("No chunkable content was found in this document.")
    return drafts
