from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.storage import build_storage
from app.storage.base import ObjectNotFound, ObjectStorage
from app.storage.local import LocalDiskStorage
from app.storage.s3 import S3CompatibleStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(root=tmp_path, public_base_url="http://localhost:8000/media")


async def test_put_then_get_round_trips(storage: LocalDiskStorage) -> None:
    stored = await storage.put("artwork/poster/a.jpg", b"hello", "image/jpeg")
    assert stored.key == "artwork/poster/a.jpg"
    assert stored.size == 5
    assert stored.content_type == "image/jpeg"
    assert await storage.get("artwork/poster/a.jpg") == b"hello"


async def test_exists_and_delete(storage: LocalDiskStorage) -> None:
    assert await storage.exists("catalog/current.json") is False
    await storage.put("catalog/current.json", b"{}", "application/json")
    assert await storage.exists("catalog/current.json") is True
    await storage.delete("catalog/current.json")
    assert await storage.exists("catalog/current.json") is False


async def test_get_missing_key_raises_a_typed_error(storage: LocalDiskStorage) -> None:
    with pytest.raises(ObjectNotFound):
        await storage.get("catalog/nope.json")


async def test_delete_is_idempotent(storage: LocalDiskStorage) -> None:
    await storage.delete("catalog/never-existed.json")  # must not raise


async def test_writes_are_atomic_replacements(storage: LocalDiskStorage, tmp_path: Path) -> None:
    """A reader must never see a half-written catalogue, so put() renames into place."""
    await storage.put("catalog/current.json", b'{"v":1}', "application/json")
    await storage.put("catalog/current.json", b'{"v":2}', "application/json")
    assert await storage.get("catalog/current.json") == b'{"v":2}'
    leftovers = [p.name for p in tmp_path.rglob("*") if ".tmp" in p.name]
    assert leftovers == []


async def test_keys_cannot_escape_the_storage_root(storage: LocalDiskStorage) -> None:
    for evil in ("../escape.json", "a/../../escape.json", "/etc/passwd"):
        with pytest.raises(ValueError):
            await storage.put(evil, b"x", "text/plain")


def test_url_for_builds_a_public_url(storage: LocalDiskStorage) -> None:
    assert storage.url_for("artwork/poster/a.jpg") == (
        "http://localhost:8000/media/artwork/poster/a.jpg"
    )


def test_both_backends_satisfy_the_same_protocol(tmp_path: Path) -> None:
    assert isinstance(LocalDiskStorage(root=tmp_path, public_base_url="x"), ObjectStorage)
    assert issubclass(S3CompatibleStorage, ObjectStorage)


def test_swapping_backends_is_one_setting(tmp_path: Path) -> None:
    local = build_storage(
        Settings(
            storage_backend="local",
            storage_local_root=str(tmp_path),
            database_url="postgresql+asyncpg://u:p@localhost/db",
            api_tokens="admin-token:admin,editor-token:editor",
            _env_file=None,
        )
    )
    assert isinstance(local, LocalDiskStorage)

    remote = build_storage(
        Settings(
            storage_backend="s3",
            _env_file=None,
            s3_bucket="peblo-tv",
            s3_endpoint_url="https://accountid.r2.cloudflarestorage.com",
            s3_access_key_id="key",
            s3_secret_access_key="secret",
            database_url="postgresql+asyncpg://u:p@localhost/db",
            api_tokens="admin-token:admin,editor-token:editor",
        )
    )
    assert isinstance(remote, S3CompatibleStorage)


def test_s3_backend_refuses_to_build_without_a_bucket(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="S3_BUCKET"):
        build_storage(
            Settings(
                storage_backend="s3",
                database_url="postgresql+asyncpg://u:p@localhost/db",
                api_tokens="admin-token:admin",
                _env_file=None,
            )
        )


def test_the_default_storage_root_stays_inside_the_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relative root resolves against the repo, so a bare run cannot write outside it."""
    from app.config import REPO_ROOT

    # The suite forces a temp root; clear it so this exercises the shipped default.
    monkeypatch.delenv("STORAGE_LOCAL_ROOT", raising=False)
    storage = build_storage(
        Settings(
            database_url="postgresql+asyncpg://u:p@localhost/db",
            api_tokens="admin-token:admin",
            _env_file=None,
        )
    )
    assert isinstance(storage, LocalDiskStorage)
    assert storage.root.is_relative_to(REPO_ROOT), storage.root


def test_an_absolute_storage_root_is_left_alone(tmp_path: Path) -> None:
    """docker-compose sets an absolute /srv/storage; it must not be re-anchored."""
    storage = build_storage(
        Settings(
            database_url="postgresql+asyncpg://u:p@localhost/db",
            api_tokens="admin-token:admin",
            storage_local_root=str(tmp_path),
            _env_file=None,
        )
    )
    assert isinstance(storage, LocalDiskStorage)
    assert storage.root == tmp_path.resolve()
