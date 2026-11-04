"""Build step: download fastembed ONNX models into ./model_cache so they ship in the bundle
(§B4: no external embedding API, no download on cold start)."""

from __future__ import annotations

from app.core.config import get_settings


def main() -> None:
    from app.rag.embeddings import FastEmbedder, FastReranker

    s = get_settings()
    FastEmbedder(s.embed_model, s.fastembed_cache_dir)
    FastReranker(s.rerank_model, s.fastembed_cache_dir)
    print(f"models cached in {s.fastembed_cache_dir}")


if __name__ == "__main__":
    main()
