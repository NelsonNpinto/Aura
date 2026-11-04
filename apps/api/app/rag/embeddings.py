"""In-process ONNX embeddings and cross-encoder rerank via fastembed (no torch, §B4)."""

from __future__ import annotations

import asyncio
import hashlib
import math
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.models.tables import EMBED_DIM


class Embedder(Protocol):
    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, docs: list[str]) -> list[float]: ...


class FastEmbedder:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        self._m = TextEmbedding(model_name=model, cache_dir=cache_dir, threads=1)

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        def run() -> list[list[float]]:
            gen = self._m.query_embed(texts) if query else self._m.embed(texts, batch_size=16)
            return [v.tolist() for v in gen]

        return await asyncio.to_thread(run)


class FastReranker:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._m = TextCrossEncoder(model_name=model, cache_dir=cache_dir, threads=1)

    async def rerank(self, query: str, docs: list[str]) -> list[float]:
        return await asyncio.to_thread(lambda: [float(x) for x in self._m.rerank(query, docs)])


class HashEmbedder:
    """Deterministic bag-of-words hashing embedder for tests (no model download)."""

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * EMBED_DIM
            for tok in t.lower().split():
                h = int(
                    hashlib.md5(tok.strip(".,:;!?()").encode(), usedforsecurity=False).hexdigest(),
                    16,
                )
                v[h % EMBED_DIM] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class OverlapReranker:
    async def rerank(self, query: str, docs: list[str]) -> list[float]:
        q = set(query.lower().split())
        return [len(q & set(d.lower().split())) / (len(q) or 1) for d in docs]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    return FastEmbedder(s.embed_model, s.fastembed_cache_dir)


@lru_cache
def get_reranker() -> Reranker:
    s = get_settings()
    return FastReranker(s.rerank_model, s.fastembed_cache_dir)
