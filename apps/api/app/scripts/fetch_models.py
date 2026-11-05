"""Build step: download fastembed ONNX models into ./model_cache so they ship in the bundle
(§B4: no external embedding API, no download on cold start).

The Hugging Face cache stores each file once under blobs/ and symlinks it from snapshots/.
Bundlers that follow symlinks would ship both copies, so the cache is flattened: snapshot
symlinks become real files and the blobs are deleted.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import get_settings


def flatten(cache: Path) -> int:
    """Replace snapshot symlinks with file copies, drop blobs/. Returns bytes in the cache."""
    for link in [p for p in cache.rglob("*") if p.is_symlink()]:
        target = link.resolve()
        link.unlink()
        shutil.copyfile(target, link)
    for blobs in [p for p in cache.rglob("blobs") if p.is_dir()]:
        shutil.rmtree(blobs)
    return sum(f.stat().st_size for f in cache.rglob("*") if f.is_file())


def main() -> None:
    from app.rag.embeddings import FastEmbedder, FastReranker

    s = get_settings()
    FastEmbedder(s.embed_model, s.fastembed_cache_dir)
    FastReranker(s.rerank_model, s.fastembed_cache_dir)
    size = flatten(Path(s.fastembed_cache_dir))
    print(f"models cached in {s.fastembed_cache_dir} ({size / 1e6:.0f} MB, flattened)")


if __name__ == "__main__":
    main()
