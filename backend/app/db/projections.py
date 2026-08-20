"""Turn database rows into the plain views the domain layer works on.

This is the seam the roadmap called for. Both the validation report and the publish
job need the same picture of the content, and neither should learn what the ORM looks
like — so the join is written **once**, here, and everything downstream is pure.

The eager loads matter: without them the catalogue build issues one query per season,
per episode and per artwork row, which at 8 shows is invisible and at 800 is not.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Artwork, Episode, Season, Show
from app.domain.rules import EpisodeView, ShowView


def _artwork_keys(records: Sequence[Artwork]) -> dict[str, str]:
    return {record.kind: record.storage_key for record in sorted(records, key=lambda a: a.kind)}


def episode_view(episode: Episode, season: Season, show: Show) -> EpisodeView:
    keys = _artwork_keys(episode.artwork)
    return EpisodeView(
        # The database id, because it is the handle the CMS deep-links on and the only
        # one every episode has — `external_id` is NULL for anything created in the UI.
        ref=str(episode.id),
        show_slug=show.slug,
        season_number=season.season_number,
        episode_number=episode.episode_number,
        title=episode.title,
        duration_seconds=episode.duration_seconds,
        language=episode.language,
        content_group=episode.content_group,
        status=episode.status,
        artwork_kinds=frozenset(keys),
        artwork_keys=keys,
    )


def show_view(show: Show) -> ShowView:
    keys = _artwork_keys(show.artwork)
    episodes = [
        episode_view(episode, season, show)
        for season in show.seasons
        for episode in season.episodes
    ]
    return ShowView(
        slug=show.slug,
        title=show.title,
        synopsis=show.synopsis,
        section=show.section,
        categories=tuple(show.categories),
        status=show.status,
        artwork_kinds=frozenset(keys),
        artwork_keys=keys,
        episodes=sorted(
            episodes, key=lambda e: (e.season_number, e.episode_number, e.language, e.ref)
        ),
    )


def _loaded_shows() -> Sequence[object]:
    """Every relationship the views read, in one round trip each."""
    return (
        selectinload(Show.artwork),
        selectinload(Show.seasons).selectinload(Season.episodes).selectinload(Episode.artwork),
    )


async def load_show_views(
    session: AsyncSession, *, slugs: Sequence[str] | None = None
) -> list[ShowView]:
    """Every show, in slug order, with its seasons, episodes and artwork attached."""
    statement = select(Show).options(*_loaded_shows()).order_by(Show.slug)  # type: ignore[arg-type]
    if slugs is not None:
        statement = statement.where(Show.slug.in_(slugs))
    result = await session.execute(statement)
    return [show_view(show) for show in result.scalars().unique().all()]


async def load_show_view(session: AsyncSession, show_id: uuid.UUID) -> ShowView | None:
    result = await session.execute(
        select(Show).options(*_loaded_shows()).where(Show.id == show_id)  # type: ignore[arg-type]
    )
    show = result.scalars().unique().one_or_none()
    return None if show is None else show_view(show)
