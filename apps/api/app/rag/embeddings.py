"""In-process ONNX embeddings and cross-encoder rerank via fastembed (no torch, §B4)."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.models.tables import EMBED_DIM


class Embedder(Protocol):
    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, docs: list[str]) -> list[float]: ...


# int8 build of bge-small-en-v1.5 (same model, quantized): ~33 MB instead of ~66 MB.
INT8_EMBEDDER = "aura/bge-small-en-v1.5-int8"


def _register_int8_embedder() -> None:
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    if any(m["model"] == INT8_EMBEDDER for m in TextEmbedding.list_supported_models()):
        return
    TextEmbedding.add_custom_model(
        model=INT8_EMBEDDER,
        pooling=PoolingType.CLS,
        normalization=True,
        sources=ModelSource(hf="Xenova/bge-small-en-v1.5"),
        dim=EMBED_DIM,
        model_file="onnx/model_quantized.onnx",
        description="BAAI bge-small-en-v1.5, int8 ONNX",
        license="mit",
        size_in_gb=0.034,
    )


class FastEmbedder:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed import TextEmbedding

        if model == INT8_EMBEDDER:
            _register_int8_embedder()
        self._m = TextEmbedding(model_name=model, cache_dir=cache_dir, threads=1)

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        def run() -> list[list[float]]:
            gen = self._m.query_embed(texts) if query else self._m.embed(texts, batch_size=16)
            return [v.tolist() for v in gen]

        return await asyncio.to_thread(run)


# int8 build of the same cross-encoder: 23 MB instead of 91 MB, keeps the api bundle < 450 MB.
INT8_RERANKER = "aura/ms-marco-MiniLM-L-6-v2-int8"


def _register_int8_reranker() -> None:
    from fastembed.common.model_description import ModelSource
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    if any(m["model"] == INT8_RERANKER for m in TextCrossEncoder.list_supported_models()):
        return
    TextCrossEncoder.add_custom_model(
        model=INT8_RERANKER,
        sources=ModelSource(hf="Xenova/ms-marco-MiniLM-L-6-v2"),
        model_file="onnx/model_quantized.onnx",
        description="ms-marco-MiniLM-L-6-v2 cross-encoder, int8 ONNX",
        license="apache-2.0",
        size_in_gb=0.023,
    )


class FastReranker:
    def __init__(self, model: str, cache_dir: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        if model == INT8_RERANKER:
            _register_int8_reranker()
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


def _cache_dir() -> str:
    """Bundled cache when present; otherwise /tmp (the only writable path on Vercel)."""
    s = get_settings()
    if os.path.isdir(s.fastembed_cache_dir) or not s.is_deployed:
        return s.fastembed_cache_dir
    return "/tmp/model_cache"  # noqa: S108


@lru_cache
def get_embedder() -> Embedder:
    return FastEmbedder(get_settings().embed_model, _cache_dir())


@lru_cache
def get_reranker() -> Reranker:
    return FastReranker(get_settings().rerank_model, _cache_dir())
