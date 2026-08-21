"""The Postgres storage backend, against a real database.

Artwork lives in Postgres because Cloudflare R2 wants a payment card and the whole
catalogue's artwork is about 5 MB. That only works if this backend honours the same
contract as the other two — especially the atomic ``put`` the publish job depends on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.storage import PostgresStorage, build_storage
from app.storage.base import ObjectNotFound, ObjectStorage
from tests._postgres import (
    ASYNC_TEST_DATABASE_URL,
    SKIP_REASON,
    postgres_available,
    reset_and_migrate,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not postgres_available(), reason=SKIP_REASON),
]


@pytest.fixture(scope="module")
def migrated() -> Iterator[sa.Engine]:
    engine = reset_and_migrate()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
async def storage(migrated: sa.Engine) -> PostgresStorage:
    engine = create_async_engine(ASYNC_TEST_DATABASE_URL)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    return PostgresStorage(factory, "https://api.example.com/media")


async def test_put_then_get_round_trips(storage: PostgresStorage) -> None:
    stored = await storage.put("artwork/shows/1/poster-abc.jpg", b"hello", "image/jpeg")
    assert (stored.size, stored.content_type) == (5, "image/jpeg")
    assert await storage.get("artwork/shows/1/poster-abc.jpg") == b"hello"
    assert await storage.content_type_of("artwork/shows/1/poster-abc.jpg") == "image/jpeg"


async def test_binary_survives_exactly(storage: PostgresStorage) -> None:
    """JPEG bytes are not text; a round trip that mangles them is worse than one that fails."""
    payload = bytes(range(256)) * 40
    await storage.put("artwork/shows/1/banner-bin.jpg", payload, "image/jpeg")
    assert await storage.get("artwork/shows/1/banner-bin.jpg") == payload


async def test_writing_the_same_key_twice_replaces_it_atomically(
    storage: PostgresStorage,
) -> None:
    """`put` is one INSERT … ON CONFLICT, so a reader never sees a half-written object."""
    await storage.put("catalog/current.json", b'{"v":1}', "application/json")
    await storage.put("catalog/current.json", b'{"v":2}', "application/json")
    assert await storage.get("catalog/current.json") == b'{"v":2}'


async def test_concurrent_writes_leave_one_whole_object(storage: PostgresStorage) -> None:
    """The publish pointer is flipped under load; a torn write there is a broken catalogue."""
    payloads = [f'{{"run":{index}}}'.encode() for index in range(12)]
    await asyncio.gather(
        *(storage.put("catalog/current.json", body, "application/json") for body in payloads)
    )
    assert await storage.get("catalog/current.json") in payloads


async def test_exists_and_delete(storage: PostgresStorage) -> None:
    assert await storage.exists("catalog/gone.json") is False
    await storage.put("catalog/gone.json", b"{}", "application/json")
    assert await storage.exists("catalog/gone.json") is True
    await storage.delete("catalog/gone.json")
    assert await storage.exists("catalog/gone.json") is False


async def test_deleting_a_missing_key_is_not_an_error(storage: PostgresStorage) -> None:
    await storage.delete("catalog/never-existed.json")


async def test_a_missing_key_raises_the_shared_error(storage: PostgresStorage) -> None:
    with pytest.raises(ObjectNotFound):
        await storage.get("artwork/shows/1/nope.jpg")
    assert await storage.content_type_of("artwork/shows/1/nope.jpg") is None


@pytest.mark.parametrize("evil", ["../escape.json", "a/../../escape.json", "/etc/passwd"])
async def test_keys_cannot_escape(storage: PostgresStorage, evil: str) -> None:
    with pytest.raises(ValueError):
        await storage.put(evil, b"x", "text/plain")


def test_it_satisfies_the_same_protocol_as_the_others() -> None:
    assert issubclass(PostgresStorage, ObjectStorage)


def test_the_backend_is_one_setting(migrated: sa.Engine) -> None:
    """The point of the seam: a third backend, still one branch."""
    engine = create_async_engine(ASYNC_TEST_DATABASE_URL)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    built = build_storage(
        Settings(
            database_url=ASYNC_TEST_DATABASE_URL,
            storage_backend="postgres",
            api_tokens="admin-token:admin",
            _env_file=None,
        ),
        factory,
    )
    assert isinstance(built, PostgresStorage)


def test_postgres_storage_refuses_to_build_without_a_session_factory() -> None:
    with pytest.raises(ValueError, match="session factory"):
        build_storage(
            Settings(
                database_url="postgresql+asyncpg://u:p@localhost/db",
                storage_backend="postgres",
                api_tokens="admin-token:admin",
                _env_file=None,
            )
        )


def test_urls_point_at_the_apis_own_media_route(storage_url: str = "") -> None:
    engine = create_async_engine("postgresql+asyncpg://u:p@localhost/db")
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine)
    backend = PostgresStorage(factory, "https://api.example.com/media/")
    assert backend.url_for("artwork/shows/1/poster-abc.jpg") == (
        "https://api.example.com/media/artwork/shows/1/poster-abc.jpg"
    )
