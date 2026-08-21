"""Artwork kept in Postgres.

The third implementation of the same five-method contract, and the reason that contract
exists. Object storage normally means a bucket, but a bucket means a second account and a
payment card; the catalogue's artwork is about 5 MB in total, which sits inside a free
Postgres tier without noticing.

**Atomicity.** ``put`` is a single ``INSERT … ON CONFLICT DO UPDATE``, so it is atomic
per key exactly like a rename on disk or a PUT to R2 — which is what the publish job's
pointer flip depends on.

**The trade-off, stated plainly.** Bytes travel through the API rather than straight from
a bucket edge, so there is no CDN in front of them. At this size that is a few
milliseconds and the artwork keys are content-addressed, so responses can be cached
forever by the browser. It stops being the right answer at the point where the catalogue
outgrows a single published file — the same point at which most of this design changes.
Moving to R2 is one setting; this class is what it replaces, not something it is built on.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.base import ObjectNotFound, StoredObject, validate_key

#: Deliberately not an ORM model. Storage is a layer below the domain, and giving it a
#: mapped class would invite the rest of the app to query artwork bytes directly.
TABLE = "storage_objects"


class PostgresStorage:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], public_base_url: str
    ) -> None:
        self._sessions = session_factory
        self._public_base_url = public_base_url.rstrip("/")

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        validate_key(key)
        async with self._sessions() as session:
            await session.execute(
                text(
                    f"INSERT INTO {TABLE} (key, content_type, byte_size, data) "
                    "VALUES (:key, :content_type, :byte_size, :data) "
                    "ON CONFLICT (key) DO UPDATE SET "
                    "  content_type = EXCLUDED.content_type, "
                    "  byte_size = EXCLUDED.byte_size, "
                    "  data = EXCLUDED.data, "
                    "  updated_at = now()"
                ),
                {
                    "key": key,
                    "content_type": content_type,
                    "byte_size": len(data),
                    "data": data,
                },
            )
            await session.commit()
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        validate_key(key)
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(f"SELECT data FROM {TABLE} WHERE key = :key"),
                    {"key": key},
                )
            ).first()
        if row is None:
            raise ObjectNotFound(key)
        return bytes(row[0])

    async def content_type_of(self, key: str) -> str | None:
        """Used by the media route, so a response does not have to guess from the suffix."""
        validate_key(key)
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(f"SELECT content_type FROM {TABLE} WHERE key = :key"),
                    {"key": key},
                )
            ).first()
        return None if row is None else str(row[0])

    async def delete(self, key: str) -> None:
        validate_key(key)
        async with self._sessions() as session:
            await session.execute(
                text(f"DELETE FROM {TABLE} WHERE key = :key"),
                {"key": key},
            )
            await session.commit()

    async def exists(self, key: str) -> bool:
        validate_key(key)
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text(f"SELECT 1 FROM {TABLE} WHERE key = :key"),
                    {"key": key},
                )
            ).first()
        return row is not None

    def url_for(self, key: str) -> str:
        """Served by the API's own media route — see :mod:`app.api.media`."""
        return f"{self._public_base_url}/{validate_key(key)}"
