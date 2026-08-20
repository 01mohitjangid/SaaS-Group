"""The migration and the constraints it creates, exercised against a real Postgres.

Everything else in this suite is pure Python. These tests are the only thing that
can catch schema drift or a constraint that was written but never enforced, so they
run the real ``alembic upgrade`` against a scratch database.

They are marked ``integration`` and skip when no Postgres is reachable, which keeps
the gate honest rather than green-by-omission: a skip here means the schema is
unverified, not that it passed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic import command
from tests._postgres import SKIP_REASON, alembic_config, postgres_available, reset_and_migrate

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not postgres_available(), reason=SKIP_REASON),
]


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[sa.Engine]:
    engine = reset_and_migrate()
    try:
        yield engine
    finally:
        engine.dispose()


def test_migration_leaves_no_drift_against_the_models(migrated_engine: sa.Engine) -> None:
    """`alembic check` raises if the models and the migration disagree."""
    command.check(alembic_config())


def test_downgrade_removes_everything_including_the_enum_types(
    migrated_engine: sa.Engine,
) -> None:
    config = alembic_config()
    command.downgrade(config, "base")
    with migrated_engine.connect() as connection:
        tables = set(sa.inspect(connection).get_table_names())
        enums = {
            row[0]
            for row in connection.execute(
                sa.text("SELECT typname FROM pg_type WHERE typtype = 'e'")
            )
        }
    assert tables == {"alembic_version"}
    assert not enums & {"publication_status", "artwork_kind", "publish_run_status", "user_role"}
    command.upgrade(config, "head")


def _make_show(connection: sa.Connection, slug: str) -> uuid.UUID:
    show_id = uuid.uuid4()
    connection.execute(
        sa.text(
            "INSERT INTO shows (id, slug, title, synopsis, section, categories, status) "
            "VALUES (:id, :slug, :title, '', 'series', '{}', 'published')"
        ),
        {"id": show_id, "slug": slug, "title": slug},
    )
    return show_id


def _make_episode(connection: sa.Connection, show_id: uuid.UUID, **overrides: object) -> uuid.UUID:
    existing = connection.execute(
        sa.text("SELECT id FROM seasons WHERE show_id = :show_id AND season_number = 1"),
        {"show_id": show_id},
    ).scalar_one_or_none()
    if existing is None:
        season_id = uuid.uuid4()
        connection.execute(
            sa.text("INSERT INTO seasons (id, show_id, season_number) VALUES (:id, :show_id, 1)"),
            {"id": season_id, "show_id": show_id},
        )
    else:
        season_id = existing
    episode_id = uuid.uuid4()
    values: dict[str, object] = {
        "id": episode_id,
        "season_id": season_id,
        "episode_number": 1,
        "title": "An Episode",
        "language": "en",
        "content_group": f"{show_id}-s01e01",
    }
    values.update(overrides)
    connection.execute(
        sa.text(
            "INSERT INTO episodes (id, season_id, episode_number, title, language, content_group) "
            "VALUES (:id, :season_id, :episode_number, :title, :language, :content_group)"
        ),
        values,
    )
    return episode_id


def test_a_content_group_cannot_have_two_versions_of_one_language(
    migrated_engine: sa.Engine,
) -> None:
    """The rule from the brief, and the reason seeding rejects ep_9001."""
    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"dupe-{uuid.uuid4().hex[:8]}")
        _make_episode(connection, show_id, content_group="cg-1", language="hi")
        with pytest.raises(IntegrityError, match="uq_episodes_content_group_language"):
            _make_episode(connection, show_id, content_group="cg-1", language="hi")


def test_the_same_content_group_in_two_languages_is_allowed(migrated_engine: sa.Engine) -> None:
    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"langs-{uuid.uuid4().hex[:8]}")
        _make_episode(connection, show_id, content_group="cg-2", language="en")
        _make_episode(connection, show_id, content_group="cg-2", language="hi")


def _insert_artwork(connection: sa.Connection, **values: object) -> None:
    payload: dict[str, object] = {
        "id": uuid.uuid4(),
        "show_id": None,
        "episode_id": None,
        "kind": "poster",
        "storage_key": f"artwork/{uuid.uuid4().hex}.jpg",
        "content_type": "image/jpeg",
        "width": 600,
        "height": 900,
        "byte_size": 1000,
        "checksum_sha256": "0" * 64,
    }
    payload.update(values)
    connection.execute(
        sa.text(
            "INSERT INTO artwork (id, show_id, episode_id, kind, storage_key, content_type,"
            " width, height, byte_size, checksum_sha256) VALUES (:id, :show_id, :episode_id,"
            " :kind, :storage_key, :content_type, :width, :height, :byte_size, :checksum_sha256)"
        ),
        payload,
    )


def test_artwork_must_have_exactly_one_owner(migrated_engine: sa.Engine) -> None:
    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"art-{uuid.uuid4().hex[:8]}")
        episode_id = _make_episode(connection, show_id)
        with pytest.raises(IntegrityError, match="artwork_has_exactly_one_owner"):
            _insert_artwork(connection, show_id=show_id, episode_id=episode_id)

    with (
        migrated_engine.begin() as connection,
        pytest.raises(IntegrityError, match="artwork_has_exactly_one_owner"),
    ):
        _insert_artwork(connection)


def test_posters_belong_to_shows_and_thumbnails_to_episodes(migrated_engine: sa.Engine) -> None:
    """The surface rule the roadmap commits to, enforced in the database not just Python."""
    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"kind-{uuid.uuid4().hex[:8]}")
        episode_id = _make_episode(connection, show_id)
        _insert_artwork(connection, show_id=show_id, kind="poster")
        _insert_artwork(connection, show_id=show_id, kind="banner")
        _insert_artwork(connection, episode_id=episode_id, kind="thumbnail")

    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"kind2-{uuid.uuid4().hex[:8]}")
        with pytest.raises(IntegrityError, match="artwork_kind_matches_owner"):
            _insert_artwork(connection, show_id=show_id, kind="thumbnail")

    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"kind3-{uuid.uuid4().hex[:8]}")
        episode_id = _make_episode(connection, show_id)
        with pytest.raises(IntegrityError, match="artwork_kind_matches_owner"):
            _insert_artwork(connection, episode_id=episode_id, kind="poster")


def test_a_show_cannot_hold_two_posters(migrated_engine: sa.Engine) -> None:
    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"twoposters-{uuid.uuid4().hex[:8]}")
        _insert_artwork(connection, show_id=show_id, kind="poster")
        with pytest.raises(IntegrityError, match="uq_artwork_show_id_kind"):
            _insert_artwork(connection, show_id=show_id, kind="poster")


def test_trigram_indexes_exist_for_substring_search(migrated_engine: sa.Engine) -> None:
    with migrated_engine.connect() as connection:
        definitions = {
            row[0]: row[1]
            for row in connection.execute(
                sa.text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename IN ('shows', 'episodes')"
                )
            )
        }
    for name in ("ix_shows_title_trgm", "ix_episodes_title_trgm"):
        assert "gin" in definitions[name].lower()
        # On the raw column, so it serves ILIKE as well as LIKE. An index on
        # lower(title) only fires for that exact spelling.
        assert "(title gin_trgm_ops)" in definitions[name]
    # The redundant plain index on content_group must stay gone.
    assert "ix_episodes_content_group" not in definitions


def test_only_one_publish_run_can_be_in_flight(migrated_engine: sa.Engine) -> None:
    """Atomic writes stop a torn read; this stops two publishes interleaving."""
    with migrated_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM publish_runs"))
        connection.execute(
            sa.text(
                "INSERT INTO publish_runs (id, status, created_by_email) "
                "VALUES (:id, 'running', 'admin@peblo.tv')"
            ),
            {"id": uuid.uuid4()},
        )
        with pytest.raises(IntegrityError, match="uq_publish_runs_one_running"):
            connection.execute(
                sa.text(
                    "INSERT INTO publish_runs (id, status, created_by_email) "
                    "VALUES (:id, 'running', 'admin@peblo.tv')"
                ),
                {"id": uuid.uuid4()},
            )

    # Finished runs are unconstrained — history can hold as many as it likes.
    with migrated_engine.begin() as connection:
        for _ in range(3):
            connection.execute(
                sa.text(
                    "INSERT INTO publish_runs (id, status, created_by_email) "
                    "VALUES (:id, 'succeeded', 'admin@peblo.tv')"
                ),
                {"id": uuid.uuid4()},
            )
        connection.execute(sa.text("DELETE FROM publish_runs"))


def test_language_variants_share_an_episode_number_but_a_language_cannot(
    migrated_engine: sa.Engine,
) -> None:
    """Two Hindi versions of S1E1 is the content_group rule; two English ones is this."""
    with migrated_engine.begin() as connection:
        show_id = _make_show(connection, f"numbering-{uuid.uuid4().hex[:8]}")
        _make_episode(connection, show_id, content_group="cg-en", language="en")
        _make_episode(connection, show_id, content_group="cg-hi", language="hi")
        with pytest.raises(IntegrityError, match="uq_episodes_season_id_episode_number_language"):
            _make_episode(connection, show_id, content_group="cg-other", language="en")
