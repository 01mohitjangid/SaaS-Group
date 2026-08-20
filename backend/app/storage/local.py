"""Local-disk implementation of :class:`~app.storage.base.ObjectStorage`.

Used for development, tests and ``docker compose up``. Writes go to a temporary
file in the destination directory and are then renamed into place, which is atomic
on POSIX: a concurrent reader sees the old bytes or the new bytes, never a mix.

The file itself is fsynced before the rename, but the *parent directory* is not, so
this guarantees atomic visibility rather than crash durability — if the machine
loses power in the microsecond after the rename, the directory entry can be lost.
That is fine here (a lost publish is simply re-run and recorded as failed) and is
the one place the local backend is weaker than R2, where a completed PUT is durable.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from app.storage.base import ObjectNotFound, StoredObject, validate_key


class LocalDiskStorage:
    def __init__(self, root: Path | str, public_base_url: str) -> None:
        self._root = Path(root).resolve()
        self._public_base_url = public_base_url.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        path = (self._root / validate_key(key)).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError(f"storage key {key!r} resolves outside the storage root")
        return path

    def _put_sync(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Same directory as the destination so the rename stays on one filesystem,
        # which is what makes it atomic.
        descriptor, raw_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(raw_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        await asyncio.to_thread(self._put_sync, key, data)
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    def url_for(self, key: str) -> str:
        """Public URL for artwork. See :meth:`ObjectStorage.url_for` — only the
        ``artwork/`` prefix is actually mounted by the API."""
        return f"{self._public_base_url}/{validate_key(key)}"
