"""Fixtures for the API integration tests: a real database, a real storage root, a client."""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from PIL import Image

from app.config import Settings
from app.domain.reference import ArtworkKind, load_reference
from app.main import create_app
from tests._postgres import ASYNC_TEST_DATABASE_URL, reset_and_migrate

ADMIN_TOKEN = "test-admin-token"
EDITOR_TOKEN = "test-editor-token"


def image_bytes(
    kind: ArtworkKind,
    *,
    width: int | None = None,
    height: int | None = None,
    quality: int = 70,
    noisy: bool = False,
) -> bytes:
    """A real JPEG at (by default) exactly the size the reference specs demand.

    ``noisy`` fills it with random pixels, which JPEG cannot compress — the only way to
    build a genuinely oversized file, since a flat colour stays tiny at any dimension.
    """
    spec = load_reference().artwork[kind]
    size = (width or spec.target_width, height or spec.target_height)
    if noisy:
        pixels = os.urandom(size[0] * size[1] * 3)
        image = Image.frombytes("RGB", size, pixels)
    else:
        image = Image.new("RGB", size, (40, 90, 140))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def migrated() -> Iterator[sa.Engine]:
    engine = reset_and_migrate()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def api_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("api-storage")
    return Settings(
        database_url=ASYNC_TEST_DATABASE_URL,
        api_tokens=f"{ADMIN_TOKEN}:admin,{EDITOR_TOKEN}:editor",
        storage_backend="local",
        storage_local_root=str(root),
        public_media_base_url="http://testserver/media",
        _env_file=None,
    )


@pytest.fixture
def clean_database(migrated: sa.Engine) -> sa.Engine:
    """Every test starts from an empty catalogue with exactly two known principals."""
    with migrated.begin() as connection:
        for table in ("publish_runs", "artwork", "episodes", "seasons", "shows", "users"):
            connection.execute(sa.text(f"DELETE FROM {table}"))
        for email, role, token in (
            ("admin@peblo.tv", "admin", ADMIN_TOKEN),
            ("editor@peblo.tv", "editor", EDITOR_TOKEN),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, display_name, role, token_hash) "
                    "VALUES (:id, :email, :name, :role, :hash)"
                ),
                {
                    "id": uuid.uuid4(),
                    "email": email,
                    "name": role.capitalize(),
                    "role": role,
                    "hash": _token_hash(token),
                },
            )
    return migrated


@pytest.fixture
def api_app(clean_database: sa.Engine, api_settings: Settings) -> FastAPI:
    return create_app(api_settings)


@pytest.fixture
async def client(api_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    app = api_app
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


def as_admin(**headers: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}", **headers}


def as_editor(**headers: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {EDITOR_TOKEN}", **headers}


async def make_show(
    client: httpx.AsyncClient,
    *,
    slug: str = "motis-many-lives",
    title: str = "Moti's Many Lives",
    section: str | None = "featured",
    categories: list[str] | None = None,
    with_artwork: bool = True,
) -> str:
    response = await client.post(
        "/admin/shows",
        json={
            "slug": slug,
            "title": title,
            "synopsis": "Moti the dog is reborn across India.",
            "section": section,
            "categories": categories if categories is not None else ["adventure", "india"],
        },
        headers=as_editor(),
    )
    assert response.status_code == 201, response.text
    show_id: str = response.json()["id"]

    if with_artwork:
        for kind in (ArtworkKind.POSTER, ArtworkKind.BANNER):
            uploaded = await client.post(
                "/admin/artwork",
                data={"kind": kind.value, "show_id": show_id},
                files={"file": (f"{kind.value}.jpg", image_bytes(kind), "image/jpeg")},
                headers=as_editor(),
            )
            assert uploaded.status_code == 201, uploaded.text
    return show_id


async def make_episode(
    client: httpx.AsyncClient,
    show_id: str,
    *,
    season: int = 1,
    number: int = 1,
    title: str = "The Lost Kite",
    language: str = "en",
    content_group: str = "motis-many-lives-s01e01",
    duration: int | None = 510,
    with_artwork: bool = True,
    publish: bool = True,
) -> str:
    response = await client.post(
        f"/admin/shows/{show_id}/episodes",
        json={
            "season_number": season,
            "episode_number": number,
            "title": title,
            "duration_seconds": duration,
            "language": language,
            "content_group": content_group,
            "status": "draft",
        },
        headers=as_editor(),
    )
    assert response.status_code == 201, response.text
    episode_id: str = response.json()["id"]

    if with_artwork:
        uploaded = await client.post(
            "/admin/artwork",
            data={"kind": "thumbnail", "episode_id": episode_id},
            files={"file": ("t.jpg", image_bytes(ArtworkKind.THUMBNAIL), "image/jpeg")},
            headers=as_editor(),
        )
        assert uploaded.status_code == 201, uploaded.text

    if publish:
        published = await client.patch(
            f"/admin/episodes/{episode_id}", json={"status": "published"}, headers=as_editor()
        )
        assert published.status_code == 200, published.text
    return episode_id


async def publish_show(client: httpx.AsyncClient, show_id: str) -> None:
    response = await client.patch(
        f"/admin/shows/{show_id}", json={"status": "published"}, headers=as_editor()
    )
    assert response.status_code == 200, response.text
