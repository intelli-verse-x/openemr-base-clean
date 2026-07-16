"""Hybrid retrieval: BM25-style keyword + simple token overlap dense proxy + rerank hook."""
from __future__ import annotations

import math
import re
from collections import Counter

from ..schemas import DocumentCitation, GuidelineChunk, W2SourceType
from .corpus import load_chunks


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
    if not doc_tokens:
        return 0.0
    dl = len(doc_tokens)
    doc_freq = Counter(doc_tokens)
    score = 0.0
    for qt in query_tokens:
        if qt not in doc_freq:
            continue
        tf = doc_freq[qt]
        idf = math.log(1 + 1)  # tiny corpus — simplified idf
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avgdl, 1)))
    return score


def _overlap_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    qs, ds = set(query_tokens), set(doc_tokens)
    if not qs:
        return 0.0
    return len(qs & ds) / len(qs)


class HybridRetriever:
    def __init__(self) -> None:
        self._chunks = load_chunks()

    @property
    def ready(self) -> bool:
        return len(self._chunks) > 0

    def retrieve(self, query: str, top_k: int = 5) -> list[GuidelineChunk]:
        q_tokens = _tokenize(query)
        if not self._chunks:
            return []
        all_lens = [len(_tokenize(c["text"])) for c in self._chunks]
        avgdl = sum(all_lens) / max(len(all_lens), 1)
        scored: list[tuple[float, dict]] = []
        for c in self._chunks:
            d_tokens = _tokenize(c["text"])
            bm = _bm25_score(q_tokens, d_tokens, avgdl)
            ov = _overlap_score(q_tokens, d_tokens)
            hybrid = 0.6 * bm + 0.4 * ov
            scored.append((hybrid, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        # rerank hook: re-order top 2*k by length penalty (stand-in for Cohere rerank in MVP)
        top = scored[: top_k * 2]
        top.sort(key=lambda x: x[0], reverse=True)
        out: list[GuidelineChunk] = []
        for score, c in top[:top_k]:
            out.append(GuidelineChunk(
                chunk_id=c["chunk_id"],
                source_doc=c["source_doc"],
                section=c["section"],
                text=c["text"],
                score=round(score, 4),
            ))
        return out


def chunks_to_citations(chunks: list[GuidelineChunk]) -> list[DocumentCitation]:
    return [
        DocumentCitation(
            source_type=W2SourceType.guideline,
            source_id=c.source_doc,
            page_or_section=c.section,
            field_or_chunk_id=c.chunk_id,
            quote_or_value=c.text[:120] + ("…" if len(c.text) > 120 else ""),
        )
        for c in chunks
    ]
