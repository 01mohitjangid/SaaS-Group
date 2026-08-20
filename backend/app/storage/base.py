"""The storage seam.

Everything that writes bytes — uploaded artwork and the published catalogue — goes
through ``ObjectStorage``. Local disk is used in development; Cloudflare R2 in
production. Swapping means constructing a different class, nothing else.

``put`` is required to be **atomic per key**: a concurrent reader sees either the
old object or the new one, never a partial write. That property is what makes the
publish job safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Keys are storage paths, not filesystem paths: forward slashes, no traversal.
_FORBIDDEN = ("..", "\\", "\x00")


class StorageError(RuntimeError):
    """Base class for storage failures."""


class ObjectNotFound(StorageError):
    """The requested key does not exist."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    content_type: str
    etag: str | None = None


def validate_key(key: str) -> str:
    """Reject anything that could escape the bucket or the storage root."""
    if not key or key.startswith("/") or key.endswith("/"):
        raise ValueError(f"storage key {key!r} must be a non-empty relative path")
    if any(token in key for token in _FORBIDDEN):
        raise ValueError(f"storage key {key!r} contains an illegal path segment")
    return key


@runtime_checkable
class ObjectStorage(Protocol):
    """The whole contract. Implementations are ~100 lines each."""

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        """Write ``data`` at ``key``, atomically replacing anything already there."""
        ...

    async def get(self, key: str) -> bytes:
        """Read the object, raising :class:`ObjectNotFound` if it is absent."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the object. Deleting a missing key is not an error."""
        ...

    async def exists(self, key: str) -> bool: ...

    def url_for(self, key: str) -> str:
        """The public URL for an object under ``artwork/``.

        Only artwork is published. The catalogue and the validation report live in the
        same store and are served through the API, not from this URL.
        """
        ...
