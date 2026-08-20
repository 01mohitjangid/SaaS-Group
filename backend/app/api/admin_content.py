"""CRUD for shows, seasons and episodes.

Two kinds of validation meet here. Shape errors (a slug with spaces, a negative
duration) are caught by the request models and come back with a field name. Rules that
need the surrounding content — an episode published without artwork, a second Hindi
variant of the same episode — are checked against `app.domain.rules`, the same engine
the validation report and the publish gate use, so an editor is never told two
different stories.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import EditorUser, ReferenceDep, SessionDep, StorageDep
from app.db.models import Artwork, Episode, Season, Show
from app.db.projections import episode_view, show_view
from app.domain.reference import Reference
from app.domain.rules import Severity, check_episode, check_show
from app.errors import ApiError, Conflict, NotFound
from app.schemas.content import (
    ArtworkOut,
    EpisodeCreate,
    EpisodeOut,
    EpisodePage,
    EpisodeUpdate,
    Page,
    ShowCreate,
    ShowDetail,
    ShowOut,
    ShowPage,
    ShowUpdate,
)
from app.storage import ObjectStorage

router = APIRouter(prefix="/admin", tags=["content"])

#: LIKE treats these as wildcards. Un-escaped, a search for "%" returns everything and
#: an editor's search box quietly becomes a query language.
_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def like_pattern(term: str) -> str:
    return f"%{term.strip().translate(_LIKE_ESCAPE)}%"


_SHOW_LOADS = (
    selectinload(Show.artwork),
    selectinload(Show.seasons).selectinload(Season.episodes).selectinload(Episode.artwork),
)


def _artwork_out(records: list[Artwork], storage: ObjectStorage) -> list[ArtworkOut]:
    return [
        ArtworkOut(
            id=a.id,
            kind=a.kind,
            url=storage.url_for(a.storage_key),
            width=a.width,
            height=a.height,
            byte_size=a.byte_size,
        )
        for a in sorted(records, key=lambda a: a.kind)
    ]


def _show_out(show: Show, storage: ObjectStorage) -> ShowOut:
    view = show_view(show)
    return ShowOut(
        id=show.id,
        slug=show.slug,
        title=show.title,
        synopsis=show.synopsis,
        section=show.section,
        categories=list(show.categories),
        status=show.status,
        episode_count=len(view.episodes),
        languages=sorted({e.language for e in view.episodes}),
        artwork=_artwork_out(list(show.artwork), storage),
        updated_at=show.updated_at,
    )


def _episode_out(
    episode: Episode, season: Season, storage: ObjectStorage, show: Show
) -> EpisodeOut:
    return EpisodeOut(
        id=episode.id,
        external_id=episode.external_id,
        show_id=show.id,
        show_slug=show.slug,
        show_title=show.title,
        season_number=season.season_number,
        episode_number=episode.episode_number,
        title=episode.title,
        duration_seconds=episode.duration_seconds,
        language=episode.language,
        content_group=episode.content_group,
        status=episode.status,
        artwork=_artwork_out(list(episode.artwork), storage),
    )


async def _get_show(session: AsyncSession, show_id: uuid.UUID) -> Show:
    show = (
        (await session.execute(select(Show).options(*_SHOW_LOADS).where(Show.id == show_id)))
        .scalars()
        .unique()
        .one_or_none()
    )
    if show is None:
        raise NotFound("show")
    return show


def _reject_if_blocked(show: Show, reference: Reference) -> None:
    """A row may only be saved as `published` if it would actually publish."""
    view = show_view(show)
    blockers = [i for i in check_show(view, reference) if i.severity is Severity.BLOCKER]
    for episode in view.episodes:
        blockers += [i for i in check_episode(episode, reference) if i.severity is Severity.BLOCKER]
    if blockers:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="cannot_publish_yet",
            message=blockers[0].message,
            problems=[
                {"field": None, "message": i.message, "hint": i.fix_hint, "code": i.code.value}
                for i in blockers
            ],
        )


# ------------------------------------------------------------------------- shows


@router.get("/shows", response_model=ShowPage, summary="List shows with search and filters")
async def list_shows(
    session: SessionDep,
    storage: StorageDep,
    _: EditorUser,
    q: Annotated[str | None, Query(max_length=120)] = None,
    section: Annotated[str | None, Query()] = None,
    show_status: Annotated[str | None, Query(alias="status")] = None,
    language: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ShowPage:
    statement = select(Show)
    if q:
        pattern = like_pattern(q)
        # Both columns carry a trigram index. Without one on `slug`, the OR makes the
        # planner abandon the index on `title` too and scan the table.
        statement = statement.where(or_(Show.title.ilike(pattern), Show.slug.ilike(pattern)))
    if section:
        statement = statement.where(Show.section == section)
    if show_status:
        statement = statement.where(Show.status == show_status)
    if language:
        statement = statement.where(
            Show.seasons.any(Season.episodes.any(Episode.language == language))
        )

    total = (
        await session.execute(select(func.count()).select_from(statement.subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                statement.options(*_SHOW_LOADS)
                .order_by(Show.title, Show.slug)
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return ShowPage(
        items=[_show_out(show, storage) for show in rows],
        page=Page(total=int(total), limit=limit, offset=offset),
    )


@router.post(
    "/shows",
    response_model=ShowDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a show",
)
async def create_show(
    payload: ShowCreate,
    session: SessionDep,
    storage: StorageDep,
    reference: ReferenceDep,
    _: EditorUser,
) -> ShowDetail:
    show = Show(
        slug=payload.slug,
        title=payload.title,
        synopsis=payload.synopsis,
        section=payload.section,
        categories=payload.categories,
        status=payload.status,
    )
    session.add(show)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict(
            code="slug_taken",
            message=f"A show with the web address “{payload.slug}” already exists.",
            hint="Pick a different slug, or edit the existing show.",
        ) from exc

    if payload.status == "published":
        _reject_if_blocked(await _get_show(session, show.id), reference)
    await session.commit()
    return await get_show(show.id, session, storage, _)


@router.get("/shows/{show_id}", response_model=ShowDetail, summary="One show with its episodes")
async def get_show(
    show_id: uuid.UUID, session: SessionDep, storage: StorageDep, _: EditorUser
) -> ShowDetail:
    show = await _get_show(session, show_id)
    episodes = [
        _episode_out(episode, season, storage, show)
        for season in sorted(show.seasons, key=lambda s: s.season_number)
        for episode in sorted(season.episodes, key=lambda e: (e.episode_number, e.language))
    ]
    return ShowDetail(**_show_out(show, storage).model_dump(), episodes=episodes)


@router.patch("/shows/{show_id}", response_model=ShowDetail, summary="Edit a show")
async def update_show(
    show_id: uuid.UUID,
    payload: ShowUpdate,
    session: SessionDep,
    storage: StorageDep,
    reference: ReferenceDep,
    _: EditorUser,
) -> ShowDetail:
    show = await _get_show(session, show_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(show, field, value)
    await session.flush()

    if show.status == "published":
        _reject_if_blocked(await _get_show(session, show_id), reference)
    await session.commit()
    return await get_show(show_id, session, storage, _)


def _artwork_keys_under(show: Show) -> list[str]:
    return [a.storage_key for a in show.artwork] + [
        a.storage_key
        for season in show.seasons
        for episode in season.episodes
        for a in episode.artwork
    ]


@router.delete("/shows/{show_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a show")
async def delete_show(
    show_id: uuid.UUID, session: SessionDep, storage: StorageDep, _: EditorUser
) -> None:
    show = await _get_show(session, show_id)
    # Collect the keys before the cascade removes the rows that name them, and delete the
    # objects only after the commit — so a failure leaves orphaned files rather than rows
    # pointing at bytes that are gone. Without this, deleted artwork stays publicly served
    # from the bucket forever.
    keys = _artwork_keys_under(show)
    await session.delete(show)
    await session.commit()
    for key in keys:
        await storage.delete(key)


@router.get(
    "/episodes",
    response_model=EpisodePage,
    summary="List episodes across every show, with search and filters",
)
async def list_episodes(
    session: SessionDep,
    storage: StorageDep,
    _: EditorUser,
    q: Annotated[str | None, Query(max_length=120)] = None,
    show_slug: Annotated[str | None, Query()] = None,
    episode_status: Annotated[str | None, Query(alias="status")] = None,
    language: Annotated[str | None, Query()] = None,
    season_number: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EpisodePage:
    """The CMS's episode list. This is what `ix_episodes_title_trgm` exists for."""
    statement = (
        select(Episode)
        .join(Season, Season.id == Episode.season_id)
        .join(Show, Show.id == Season.show_id)
    )
    if q:
        statement = statement.where(Episode.title.ilike(like_pattern(q)))
    if show_slug:
        statement = statement.where(Show.slug == show_slug)
    if episode_status:
        statement = statement.where(Episode.status == episode_status)
    if language:
        statement = statement.where(Episode.language == language)
    if season_number is not None:
        statement = statement.where(Season.season_number == season_number)

    total = (
        await session.execute(select(func.count()).select_from(statement.subquery()))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                statement.options(
                    selectinload(Episode.artwork),
                    selectinload(Episode.season).selectinload(Season.show),
                )
                .order_by(Show.slug, Season.season_number, Episode.episode_number, Episode.language)
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return EpisodePage(
        items=[_episode_out(e, e.season, storage, e.season.show) for e in rows],
        page=Page(total=int(total), limit=limit, offset=offset),
    )


# ----------------------------------------------------------------------- episodes


async def _season_for(session: AsyncSession, show: Show, number: int) -> Season:
    for season in show.seasons:
        if season.season_number == number:
            return season
    season = Season(
        show_id=show.id,
        season_number=number,
        title="Trailers" if number == 0 else f"Season {number}",
    )
    session.add(season)
    await session.flush()
    return season


@router.post(
    "/shows/{show_id}/episodes",
    response_model=EpisodeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an episode (creating its season if needed)",
)
async def create_episode(
    show_id: uuid.UUID,
    payload: EpisodeCreate,
    session: SessionDep,
    storage: StorageDep,
    reference: ReferenceDep,
    _: EditorUser,
) -> EpisodeOut:
    show = await _get_show(session, show_id)
    season = await _season_for(session, show, payload.season_number)

    episode = Episode(
        season_id=season.id,
        external_id=payload.external_id,
        episode_number=payload.episode_number,
        title=payload.title,
        duration_seconds=payload.duration_seconds,
        language=payload.language,
        content_group=payload.content_group,
        status=payload.status,
    )
    session.add(episode)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise _variant_conflict(payload.content_group, payload.language, exc) from exc

    if payload.status == "published":
        await session.refresh(episode, ["artwork"])
        view = episode_view(episode, season, show)
        blockers = [i for i in check_episode(view, reference) if i.severity is Severity.BLOCKER]
        if blockers:
            await session.rollback()
            raise ApiError(
                status_code=status.HTTP_409_CONFLICT,
                code="cannot_publish_yet",
                message=blockers[0].message,
                problems=[
                    {"field": None, "message": i.message, "hint": i.fix_hint} for i in blockers
                ],
            )

    await session.commit()
    await session.refresh(episode, ["artwork"])
    return _episode_out(episode, season, storage, show)


def _variant_conflict(content_group: str, language: str, exc: IntegrityError) -> Conflict:
    detail = str(exc.orig)
    if "uq_episodes_content_group_language" in detail:
        return Conflict(
            code="duplicate_language_variant",
            message=(
                f"There is already a “{language}” version of “{content_group}”. "
                f"Each episode can have one version per language."
            ),
            hint="Edit the existing version, or give this one its own content group.",
        )
    if "uq_episodes_season_id_episode_number_language" in detail:
        return Conflict(
            code="duplicate_episode_number",
            message=f"This season already has a “{language}” episode with that number.",
            hint="Give it the next free number.",
        )
    if "uq_episodes_external_id" in detail:
        return Conflict(
            code="duplicate_external_id",
            message="Another episode already uses that source id.",
            hint="Leave the source id blank unless you are importing.",
        )
    return Conflict(
        code="conflict",
        message="That change clashes with an episode that already exists.",
        hint="Refresh the page to see the current state.",
    )


@router.patch("/episodes/{episode_id}", response_model=EpisodeOut, summary="Edit an episode")
async def update_episode(
    episode_id: uuid.UUID,
    payload: EpisodeUpdate,
    session: SessionDep,
    storage: StorageDep,
    reference: ReferenceDep,
    _: EditorUser,
) -> EpisodeOut:
    episode = (
        (
            await session.execute(
                select(Episode)
                .options(selectinload(Episode.artwork), selectinload(Episode.season))
                .where(Episode.id == episode_id)
            )
        )
        .scalars()
        .unique()
        .one_or_none()
    )
    if episode is None:
        raise NotFound("episode")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(episode, field, value)

    # Read these *before* flushing: a rollback expires the instance, and touching an
    # expired attribute afterwards triggers lazy IO that fails outside the greenlet —
    # turning what should be a 409 into an unexplained 500.
    attempted_group, attempted_language = episode.content_group, episode.language
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise _variant_conflict(attempted_group, attempted_language, exc) from exc

    season = episode.season
    show = await _get_show(session, season.show_id)
    if episode.status == "published":
        view = episode_view(episode, season, show)
        blockers = [i for i in check_episode(view, reference) if i.severity is Severity.BLOCKER]
        if blockers:
            await session.rollback()
            raise ApiError(
                status_code=status.HTTP_409_CONFLICT,
                code="cannot_publish_yet",
                message=blockers[0].message,
                problems=[
                    {"field": None, "message": i.message, "hint": i.fix_hint} for i in blockers
                ],
            )

    await session.commit()
    await session.refresh(episode, ["artwork"])
    return _episode_out(episode, season, storage, show)


@router.delete(
    "/episodes/{episode_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an episode",
)
async def delete_episode(
    episode_id: uuid.UUID, session: SessionDep, storage: StorageDep, _: EditorUser
) -> None:
    episode = (
        (
            await session.execute(
                select(Episode)
                .options(selectinload(Episode.artwork))
                .where(Episode.id == episode_id)
            )
        )
        .scalars()
        .unique()
        .one_or_none()
    )
    if episode is None:
        raise NotFound("episode")
    keys = [a.storage_key for a in episode.artwork]
    await session.delete(episode)
    await session.commit()
    for key in keys:
        await storage.delete(key)
