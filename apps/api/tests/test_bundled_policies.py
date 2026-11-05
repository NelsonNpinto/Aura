import hashlib

import pytest

from app.services.blob import BundledPolicyStore, LocalBlobStore


@pytest.mark.asyncio
async def test_policy_seed_requires_no_blob_credentials(tmp_path, monkeypatch):
    from app.services import blob

    policies = tmp_path / "policies"
    policies.mkdir()
    data = b"Synthetic policy: two reviewers required."
    (policies / "approval.md").write_bytes(data)
    monkeypatch.setattr(blob, "datasets_root", lambda: tmp_path)
    key = "kb/demo/" + hashlib.sha256(data).hexdigest()
    store = BundledPolicyStore()
    assert await store.put(key, data, "text/markdown") == key
    assert await LocalBlobStore(str(tmp_path / "missing")).get(key) == data
    with pytest.raises(ValueError):
        await store.put(key, b"different policy", "text/markdown")
    for private_key in (key.replace("kb/", "ap/"), "kb/demo/" + "0" * 64):
        with pytest.raises(FileNotFoundError):
            await store.get(private_key)
    with pytest.raises(ValueError):
        await store.get("kb/../approval.md")
    with pytest.raises(PermissionError):
        await store.delete(key)
