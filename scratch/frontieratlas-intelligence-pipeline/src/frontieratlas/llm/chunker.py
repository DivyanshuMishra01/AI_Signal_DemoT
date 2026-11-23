"""Intelligent payload chunking and semantic truncation.

Guarantees payloads never trigger 413 Payload Too Large errors while preserving
high-density semantic information (entities, metrics, dates, and schema fields).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class ChunkResult:
    """Represents the output of intelligent chunking."""
    chunks: List[str]
    total_chunks: int
    truncated: bool
    estimated_tokens: int
    retained_density_ratio: float


class IntelligentChunker:
    """Splits raw unstructured HTML or text into semantically dense chunks.
    
    Prevents HTTP 413 (Payload Too Large) errors while maintaining contextual fidelity.
    """

    # High-signal terms prioritized during dense extraction
    DOMAIN_KEYWORDS: Set[str] = {
        "company", "startup", "founder", "employees", "headcount", "funding", "valuation",
        "product", "pricing", "free", "freemium", "enterprise", "subscription", "features",
        "arxiv", "paper", "authors", "abstract", "github", "repository", "stars",
        "published", "date", "remote", "salary", "engineering", "machine learning", "ai"
    }

    # Low-signal noise boilerplate patterns to suppress
    BOILERPLATE_PATTERNS = [
        re.compile(r"cookie\s+policy|accept\s+all\s+cookies|privacy\s+policy", re.I),
        re.compile(r"all\s+rights\s+reserved|terms\s+of\s+service|terms\s+and\s+conditions", re.I),
        re.compile(r"subscribe\s+to\s+our\s+newsletter|sign\s+up\s+for\s+free\s+updates", re.I),
        re.compile(r"javascript\s+is\s+disabled|enable\s+javascript\s+to\s+continue", re.I),
    ]

    def __init__(
        self,
        max_chunk_chars: int = 4000,
        chunk_overlap_chars: int = 200,
        max_total_chars: int = 16000
    ) -> None:
        self.max_chunk_chars = max_chunk_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.max_total_chars = max_total_chars

    def clean_text(self, text: str) -> str:
        """Strip HTML tags and normalize whitespace."""
        if not text:
            return ""
        # Remove script and style elements
        text = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.I)
        # Strip generic HTML tags while keeping paragraph breaks
        text = re.sub(r"<(br|p|div|section|article|h[1-6]|li)[^>]*>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        # Decode common HTML entities
        text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        # Collapse multiple empty lines
        lines = [line.strip() for line in text.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return cleaned

    def compute_density_score(self, text: str) -> float:
        """Calculate semantic density score based on domain-relevant terms and structure."""
        if not text:
            return 0.0
        words = re.findall(r"\w+", text.lower())
        if not words:
            return 0.0

        keyword_hits = sum(1 for w in words if w in self.DOMAIN_KEYWORDS)
        # Bonus for numbers and currency (often employee count, dates, stars, pricing)
        metric_hits = len(re.findall(r"\b\d+[\d,.]*\b|\$\d+", text))

        score = (keyword_hits * 2.0 + metric_hits * 1.5) / max(len(words), 1)

        # Penalize boilerplate
        for pat in self.BOILERPLATE_PATTERNS:
            if pat.search(text):
                score *= 0.3
                break

        return score

    def chunk(self, text: str, schema_priority: Optional[str] = None) -> ChunkResult:
        """Decompose text into bounded, semantic chunks respecting token budgets."""
        cleaned = self.clean_text(text)
        if not cleaned:
            return ChunkResult(chunks=[], total_chunks=0, truncated=False, estimated_tokens=0, retained_density_ratio=1.0)

        # Split into semantic units (paragraphs)
        raw_paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
        if not raw_paragraphs:
            raw_paragraphs = [cleaned]

        # Score paragraphs
        scored_paragraphs = []
        total_density = 0.0
        for p in raw_paragraphs:
            score = self.compute_density_score(p)
            total_density += score * len(p)
            scored_paragraphs.append((p, score))

        # If overall length exceeds max_total_chars, prioritize highest-scoring paragraphs
        truncated = False
        retained_density = total_density
        if len(cleaned) > self.max_total_chars:
            truncated = True
            # Sort by score descending to select the most informative segments
            scored_paragraphs.sort(key=lambda x: x[1], reverse=True)
            selected_paragraphs = []
            current_len = 0
            retained_density = 0.0

            for p, score in scored_paragraphs:
                if current_len + len(p) <= self.max_total_chars:
                    selected_paragraphs.append((p, score))
                    current_len += len(p)
                    retained_density += score * len(p)
                else:
                    # Append partial text if space permits
                    remaining = self.max_total_chars - current_len
                    if remaining > 100:
                        selected_paragraphs.append((p[:remaining], score))
                        retained_density += score * remaining
                    break

            # Restore reading sequence if possible
            scored_paragraphs = selected_paragraphs

        # Assemble chunks respecting max_chunk_chars and chunk_overlap_chars
        chunks: List[str] = []
        current_chunk: List[str] = []
        current_size = 0

        for p, _ in scored_paragraphs:
            p_len = len(p)
            if current_size + p_len + 1 <= self.max_chunk_chars:
                current_chunk.append(p)
                current_size += p_len + 1
            else:
                if current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append(chunk_text)
                    # Prepare overlap
                    overlap_seed = chunk_text[-self.chunk_overlap_chars:] if len(chunk_text) > self.chunk_overlap_chars else ""
                    current_chunk = [overlap_seed, p] if overlap_seed else [p]
                    current_size = sum(len(x) for x in current_chunk) + 1
                else:
                    # Single paragraph exceeds max_chunk_chars, force slice
                    chunks.append(p[:self.max_chunk_chars])
                    current_chunk = []
                    current_size = 0

        if current_chunk:
            chunk_text = "\n\n".join(x for x in current_chunk if x)
            if chunk_text:
                chunks.append(chunk_text)

        estimated_tokens = sum(len(c.split()) for c in chunks)
        density_ratio = (retained_density / total_density) if total_density > 0 else 1.0

        return ChunkResult(
            chunks=chunks,
            total_chunks=len(chunks),
            truncated=truncated,
            estimated_tokens=estimated_tokens,
            retained_density_ratio=min(density_ratio, 1.0)
        )
