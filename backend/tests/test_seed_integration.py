"""Seeding, run for real against Postgres and local disk.

The seed loader is the one piece of step 1 that touches every layer at once — rules,
schema constraints, storage — so it is worth exercising end to end rather than
trusting the parts.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.config import Settings
from app.domain.reference import ArtworkKind, load_reference
from scripts.seed import REPORT_KEY, seed_database
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
def engine() -> Iterator[sa.Engine]:
    migrated = reset_and_migrate()
    try:
        yield migrated
    finally:
        migrated.dispose()


@pytest.fixture
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("seed-storage")
    return Settings(
        database_url=ASYNC_TEST_DATABASE_URL,
        api_tokens="seed-admin:admin,seed-editor:editor",
        storage_backend="local",
        storage_local_root=str(root),
        public_media_base_url="http://localhost:8000/media",
    )


def _counts(engine: sa.Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("shows", "seasons", "episodes", "artwork", "users")
        }


async def test_seeding_writes_the_expected_content(engine: sa.Engine, settings: Settings) -> None:
    seed, outcome = await seed_database(settings, reset=True)
    assert outcome is not None
    assert seed.row_count == 95
    # 95 rows in, 94 episodes out: ep_9001 is a duplicate language variant.
    assert _counts(engine) == {
        "shows": 8,
        "seasons": 10,
        "episodes": 94,
        "artwork": 109,
        "users": 2,
    }


async def test_the_duplicate_variant_is_rejected_and_named(
    engine: sa.Engine, settings: Settings
) -> None:
    _, outcome = await seed_database(settings, reset=True)
    assert outcome is not None
    assert [r["episode_id"] for r in outcome.rejected] == ["ep_9001"]
    assert "already has a 'hi' version" in outcome.rejected[0]["detail"]

    with engine.connect() as connection:
        stored = connection.execute(
            sa.text("SELECT count(*) FROM episodes WHERE external_id = 'ep_9001'")
        ).scalar_one()
    assert stored == 0


async def test_seeding_twice_inserts_nothing_the_second_time(
    engine: sa.Engine, settings: Settings
) -> None:
    await seed_database(settings, reset=True)
    before = _counts(engine)

    _, outcome = await seed_database(settings)
    assert outcome is not None
    assert (outcome.shows, outcome.seasons, outcome.episodes, outcome.artwork, outcome.users) == (
        0,
        0,
        0,
        0,
        0,
    )
    assert _counts(engine) == before


async def test_if_empty_short_circuits_when_content_exists(
    engine: sa.Engine, settings: Settings
) -> None:
    await seed_database(settings, reset=True)
    _, outcome = await seed_database(settings, if_empty=True)
    assert outcome is None


async def test_generated_artwork_meets_the_reference_specs(
    engine: sa.Engine, settings: Settings
) -> None:
    """Every file the seeder writes would pass the upload endpoint's own validation."""
    from PIL import Image

    await seed_database(settings, reset=True)
    reference = load_reference()
    root = Path(settings.storage_local_root)

    files = sorted(root.glob("artwork/**/*.jpg"))
    assert len(files) == 109

    for path in files:
        # Keys are content-addressed: "poster-<hash>.jpg".
        kind = ArtworkKind(path.stem.rsplit("-", 1)[0])
        with Image.open(path) as image:
            width, height = image.size
        problems = reference.artwork[kind].check(
            width=width, height=height, size_bytes=path.stat().st_size
        )
        assert problems == [], f"{path} would be rejected: {problems}"


async def test_a_machine_readable_report_is_written(engine: sa.Engine, settings: Settings) -> None:
    import json

    await seed_database(settings, reset=True)
    report = json.loads((Path(settings.storage_local_root) / REPORT_KEY).read_text())
    assert report["source_rows"] == 95
    assert [r["episode_id"] for r in report["rejected"]] == ["ep_9001"]
    assert {i["severity"] for i in report["issues"]} == {"blocker", "warning"}


async def test_artwork_is_served_but_the_report_is_not(
    engine: sa.Engine, settings: Settings
) -> None:
    """/media exposes artwork only — the validation report is internal."""
    import httpx
    from asgi_lifespan import LifespanManager

    from app.main import create_app

    await seed_database(settings, reset=True)
    with engine.connect() as connection:
        poster_key = connection.execute(
            sa.text("SELECT storage_key FROM artwork WHERE kind = 'poster' LIMIT 1")
        ).scalar_one()

    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            served = await client.get(f"/media/{poster_key}")
            assert served.status_code == 200
            assert served.headers["content-type"] == "image/jpeg"

            assert (await client.get(f"/media/{REPORT_KEY}")).status_code == 404
            assert (await client.get("/media/catalog/current.json")).status_code == 404


async def test_artwork_keys_survive_a_slug_change(engine: sa.Engine, settings: Settings) -> None:
    """Keys are built from ids, so renaming a show cannot repoint its poster."""
    await seed_database(settings, reset=True)
    with engine.begin() as connection:
        before = connection.execute(
            sa.text(
                "SELECT a.storage_key FROM artwork a JOIN shows s ON s.id = a.show_id "
                "WHERE s.slug = 'curious-cubs' AND a.kind = 'poster'"
            )
        ).scalar_one()
        connection.execute(
            sa.text("UPDATE shows SET slug = 'renamed-cubs' WHERE slug = 'curious-cubs'")
        )
        after = connection.execute(
            sa.text(
                "SELECT a.storage_key FROM artwork a JOIN shows s ON s.id = a.show_id "
                "WHERE s.slug = 'renamed-cubs' AND a.kind = 'poster'"
            )
        ).scalar_one()
    assert before == after
    assert "curious-cubs" not in before
