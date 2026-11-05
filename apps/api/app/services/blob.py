"""File storage: Vercel Blob (private store) in prod, local filesystem otherwise (§B4).

Never call `list` (advanced op quota); metadata lives in Postgres.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import datasets_root, get_settings

_API = "https://vercel.com/api/blob"
_API_VERSION = "13"
_SAFE = re.compile(r"^[A-Za-z0-9/_.-]{1,200}$")


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


def _check_key(key: str) -> None:
    if not _SAFE.match(key) or ".." in key:
        raise ValueError("invalid blob key")


class BundledPolicyStore:
    """Only the versioned, public synthetic policy corpus; never a private-upload fallback."""

    async def get(self, key: str) -> bytes:
        _check_key(key)
        if not re.fullmatch(r"kb/[A-Za-z0-9_-]+/[a-f0-9]{64}", key):
            raise FileNotFoundError(key)
        digest = key.rsplit("/", 1)[-1]
        for path in (datasets_root() / "policies").glob("*.md"):
            if path.name.startswith("._"):
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == digest:
                return data
        raise FileNotFoundError(key)

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        if await self.get(key) != data:
            raise ValueError("Only bundled synthetic policies may use this store")
        return key

    async def delete(self, key: str) -> None:
        raise PermissionError("Bundled policies are immutable")


class LocalBlobStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        _check_key(key)
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes:
        _check_key(key)
        try:
            return (self.root / key).read_bytes()
        except FileNotFoundError:
            return await BundledPolicyStore().get(key)

    async def delete(self, key: str) -> None:
        _check_key(key)
        (self.root / key).unlink(missing_ok=True)


class VercelBlobStore:
    def __init__(self, token: str) -> None:
        self.token = token
        parts = token.split("_")
        if len(parts) < 4 or not parts[3]:
            raise ValueError("BLOB_READ_WRITE_TOKEN has unexpected format")
        self.store_id = parts[3]

    def _headers(self) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.token}",
            "x-api-version": _API_VERSION,
            "x-vercel-blob-store-id": self.store_id,
        }

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        _check_key(key)
        headers = self._headers() | {
            "x-vercel-blob-access": "private",
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-content-type": content_type,
            "x-content-length": str(len(data)),
        }
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.put(f"{_API}/?pathname={quote(key)}", content=data, headers=headers)
            r.raise_for_status()
        return key

    async def get(self, key: str) -> bytes:
        _check_key(key)
        url = f"https://{self.store_id.lower()}.private.blob.vercel-storage.com/{quote(key)}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url, headers={"authorization": f"Bearer {self.token}"})
            if r.status_code == 404:
                return await BundledPolicyStore().get(key)
            r.raise_for_status()
            return r.content

    async def delete(self, key: str) -> None:
        _check_key(key)
        url = f"https://{self.store_id.lower()}.private.blob.vercel-storage.com/{quote(key)}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{_API}/delete", json={"urls": [url]}, headers=self._headers())
            r.raise_for_status()


@lru_cache
def get_blob_store() -> BlobStore:
    s = get_settings()
    if s.blob_read_write_token:
        return VercelBlobStore(s.blob_read_write_token.get_secret_value())
    if s.is_deployed:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN required outside local/test")
    return LocalBlobStore(s.local_blob_dir)
