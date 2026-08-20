"""The schema: shows → seasons → episodes, plus artwork records and publish runs.

Design notes that the indexes follow from:

* The catalogue build reads *published* shows grouped by section — hence the
  partial index on ``shows(section) WHERE status = 'published'`` rather than a
  plain index over mostly-draft rows.
* ``(content_group, language)`` is a **database** unique constraint, not just an
  application check: it is the rule that stops two rows claiming to be the same
  episode's Hindi version, and it has to hold under concurrent editors.
* ``categories`` is a Postgres text[] rather than a join table, because the only
  thing done with it is reading it back with the show. It carries **no index**: the
  category filter lives in the viewer, which filters the published document, so no
  query in the app matches on categories. It had a GIN index until that filter moved;
  the index was removed rather than defended, because an index with no query is a
  write cost with a plausible-sounding comment.
* The trigram indexes serve the **CMS**, which must show drafts and therefore cannot
  read the published catalogue. Viewer search filters that catalogue instead, so it
  touches none of this. Search is substring, case-insensitive, over show *and* episode
  titles and over the slug, so the
  title indexes are ``pg_trgm`` GIN on the **raw** column. A btree on
  ``lower(title)`` is never chosen for ``LIKE '%kite%'``, and a trigram index on
  ``lower(title)`` only fires for that exact spelling, not for the ``ILIKE`` an
  ORM emits. ``make bench`` prints the real plans at 20k shows / 220k episodes: a
  selective term uses the index, an unselective one is correctly seq-scanned, and a
  two-character term always is. See docs/ROADMAP.md for the full table.
* ``(season_id, episode_number, language)`` is unique as well: variants share a
  number by design, but two English S1E4s in one season is always an error.
* Only one publish may be in flight at a time, so ``status = 'running'`` carries a
  partial unique index. Atomic writes stop a torn read; this stops two runs
  interleaving and leaving the newest recorded run describing bytes that are not live.
* Artwork is polymorphic over show/episode with a CHECK that exactly one owner is
  set, and a *partial* unique index per owner so a show cannot hold two posters.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey

PUBLICATION_STATUS = ("draft", "published")
ARTWORK_KIND = ("poster", "banner", "thumbnail")
RUN_STATUS = ("running", "succeeded", "failed")
USER_ROLE = ("editor", "admin")


def _enum(name: str, values: tuple[str, ...]) -> Any:
    from sqlalchemy import Enum

    return Enum(*values, name=name, native_enum=True, validate_strings=True)


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(_enum("user_role", USER_ROLE), nullable=False)
    # sha256 of the bearer token. The plaintext token never reaches the database.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class Show(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "shows"

    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    section: Mapped[str | None] = mapped_column(String(40), nullable=True)
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("'{}'::varchar[]")
    )
    status: Mapped[str] = mapped_column(
        _enum("publication_status", PUBLICATION_STATUS), nullable=False, server_default="draft"
    )

    seasons: Mapped[list[Season]] = relationship(
        back_populates="show", cascade="all, delete-orphan", order_by="Season.season_number"
    )
    artwork: Mapped[list[Artwork]] = relationship(
        back_populates="show", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_shows_section_published",
            "section",
            postgresql_where=text("status = 'published'"),
        ),
        Index(
            "ix_shows_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        # The CMS list searches title OR slug. Without an index on *both*, the OR makes
        # the planner abandon the title index too and scan the table. `make bench` prints
        # the plan for the shipped predicate; see docs/ROADMAP.md for the numbers.
        Index(
            "ix_shows_slug_trgm",
            "slug",
            postgresql_using="gin",
            postgresql_ops={"slug": "gin_trgm_ops"},
        ),
    )


class Season(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "seasons"

    show_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    #: 0 is reserved for trailers — the viewer never renders it as a season.
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    show: Mapped[Show] = relationship(back_populates="seasons")
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="season", cascade="all, delete-orphan", order_by="Episode.episode_number"
    )

    __table_args__ = (
        UniqueConstraint("show_id", "season_number", name="uq_seasons_show_id_season_number"),
        CheckConstraint("season_number >= 0", name="season_number_non_negative"),
    )


class Episode(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "episodes"

    season_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False
    )
    #: Stable id from the source system; also makes re-seeding idempotent.
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    content_group: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        _enum("publication_status", PUBLICATION_STATUS), nullable=False, server_default="draft"
    )

    season: Mapped[Season] = relationship(back_populates="episodes")
    artwork: Mapped[list[Artwork]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # The rule from the brief, enforced where concurrent editors cannot dodge it.
        UniqueConstraint("content_group", "language", name="uq_episodes_content_group_language"),
        # Language variants legitimately share (season, number) — that is the whole point
        # of content_group — but two *English* S1E4s in one season is a mistake no rule
        # would otherwise catch.
        UniqueConstraint(
            "season_id",
            "episode_number",
            "language",
            name="uq_episodes_season_id_episode_number_language",
        ),
        Index("ix_episodes_season_id_episode_number", "season_id", "episode_number"),
        # No separate index on content_group: uq_episodes_content_group_language is a
        # btree with content_group as its leading column, so it already serves the
        # variant-collapsing lookup.
        Index(
            "ix_episodes_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0",
            name="duration_seconds_positive",
        ),
        CheckConstraint("episode_number >= 0", name="episode_number_non_negative"),
    )


class Artwork(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "artwork"

    kind: Mapped[str] = mapped_column(_enum("artwork_kind", ARTWORK_KIND), nullable=False)
    show_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shows.id", ondelete="CASCADE"), nullable=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True
    )

    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    show: Mapped[Show | None] = relationship(back_populates="artwork")
    episode: Mapped[Episode | None] = relationship(back_populates="artwork")

    __table_args__ = (
        CheckConstraint(
            "(show_id IS NULL) <> (episode_id IS NULL)", name="artwork_has_exactly_one_owner"
        ),
        # Posters and banners describe a show; thumbnails describe an episode. Without
        # this the rule lives only in Python and a stray write can violate it.
        CheckConstraint(
            "(show_id IS NOT NULL AND kind IN ('poster', 'banner')) "
            "OR (episode_id IS NOT NULL AND kind = 'thumbnail')",
            name="artwork_kind_matches_owner",
        ),
        Index(
            "uq_artwork_show_id_kind",
            "show_id",
            "kind",
            unique=True,
            postgresql_where=text("show_id IS NOT NULL"),
        ),
        Index(
            "uq_artwork_episode_id_kind",
            "episode_id",
            "kind",
            unique=True,
            postgresql_where=text("episode_id IS NOT NULL"),
        ),
    )


class PublishRun(UUIDPrimaryKey, Base):
    """One attempt at building and publishing the catalogue — who, when, what happened."""

    __tablename__ = "publish_runs"

    status: Mapped[str] = mapped_column(
        _enum("publish_run_status", RUN_STATUS), nullable=False, server_default="running"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Denormalised so run history survives the user being deleted.
    created_by_email: Mapped[str] = mapped_column(String(320), nullable=False)

    #: The immutable, versioned catalogue object this run wrote.
    catalog_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Lets an identical re-publish be recognised instead of churning storage.
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Set when this run reused the previous catalogue instead of writing a new one, and
    #: when it re-pointed at an earlier run. Columns rather than keys inside `counts`,
    #: because the CMS needs to label a history row and `counts` is a counts map.
    reused_previous_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rolled_back_to_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publish_runs.id", ondelete="SET NULL"), nullable=True
    )

    created_by: Mapped[User | None] = relationship()

    __table_args__ = (
        # Run history is always "newest first"; a plain btree scans backwards for that.
        Index("ix_publish_runs_started_at", "started_at"),
        # At most one publish in flight. Without this two admins can interleave and
        # the newest 'succeeded' row ends up describing bytes that are not live.
        Index(
            "uq_publish_runs_one_running",
            "status",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )
