"""Load ``data/challenge/seed_shows.json`` into Postgres and report what is wrong with it.

Run it with::

    python -m scripts.seed              # upsert everything
    python -m scripts.seed --if-empty   # no-op if content already exists (compose uses this)
    python -m scripts.seed --reset      # wipe content first

Two things it deliberately does **not** do:

* It does not repair bad data. Every problem is reported, not silently fixed.
* It does not force a row past a database constraint. ``ep_9001`` is a second
  Hindi variant of a content group that already has one, which
  ``uq_episodes_content_group_language`` forbids. It is rejected at the door and
  listed in the report, exactly as the API would reject it with a 409.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Artwork, Episode, PublishRun, Season, Show, User
from app.db.session import create_engine, create_session_factory
from app.domain import artwork as keys
from app.domain.reference import ArtworkKind, Reference, load_reference
from app.domain.rules import Issue, Severity
from app.domain.seed import SeedLoad, load_seed
from app.storage import ObjectStorage, build_storage
from scripts import artwork as art

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = REPO_ROOT / "data" / "challenge" / "seed_shows.json"
REPORT_KEY = "reports/seed-latest.json"


@dataclass
class SeedOutcome:
    shows: int = 0
    seasons: int = 0
    episodes: int = 0
    artwork: int = 0
    users: int = 0
    rejected: list[dict[str, str]] = field(default_factory=list)
    #: One real key, so the CLI can print a URL a developer can click straight through.
    example_artwork_key: str | None = None
    example_artwork_url: str | None = None

    def as_dict(self, issues: list[Issue], row_count: int) -> dict[str, Any]:
        return {
            "source_rows": row_count,
            "inserted": {
                "shows": self.shows,
                "seasons": self.seasons,
                "episodes": self.episodes,
                "artwork": self.artwork,
                "users": self.users,
            },
            "rejected": self.rejected,
            "issues": [
                {
                    "code": issue.code.value,
                    "severity": issue.severity.value,
                    "entity": issue.entity,
                    "message": issue.message,
                    "fix_hint": issue.fix_hint,
                }
                for issue in issues
            ],
        }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _seed_users(session: AsyncSession, settings: Settings) -> int:
    """Turn the dev API_TOKENS into real user rows — the API authenticates against these."""
    created = 0
    seen_per_role: dict[str, int] = {}
    for token, role in sorted(settings.token_roles.items()):
        index = seen_per_role.get(role, 0)
        seen_per_role[role] = index + 1
        suffix = "" if index == 0 else f"+{index}"
        email = f"{role}{suffix}@peblo.tv"

        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    email=email,
                    display_name=f"Dev {role.capitalize()}{suffix}",
                    role=role,
                    token_hash=_token_hash(token),
                )
            )
            created += 1
        else:
            existing.role = role
            existing.token_hash = _token_hash(token)
    await session.flush()
    return created


async def _store_artwork(
    session: AsyncSession,
    storage: ObjectStorage,
    reference: Reference,
    *,
    kind: ArtworkKind,
    label: str,
    show: Show,
    episode: Episode | None = None,
) -> tuple[str, bool]:
    # `slug` picks the show's photograph and palette; the seed varies the crop, so each
    # episode thumbnail is a different slice of the same picture rather than a copy.
    composition = f"{show.slug}:{kind.value}"
    if episode is not None:
        composition = f"{composition}:{episode.id}"
    image = art.generate(reference.artwork[kind], seed=composition, label=label, slug=show.slug)

    # The key carries a hash of these exact bytes, so regenerated artwork lands on a new
    # URL rather than hiding behind a browser's cached copy of the old one.
    version = keys.version_of(image.data)
    key = (
        keys.show_key(kind, show_id=show.id, version=version)
        if episode is None
        else keys.episode_key(kind, episode_id=episode.id, version=version)
    )

    owner = Artwork.show_id == show.id if episode is None else Artwork.episode_id == episode.id
    existing = (
        await session.execute(select(Artwork).where(owner, Artwork.kind == kind.value))
    ).scalar_one_or_none()

    await storage.put(key, image.data, image.content_type)
    superseded = (
        existing.storage_key if existing is not None and existing.storage_key != key else None
    )

    if existing is not None:
        existing.storage_key = key
        existing.content_type = image.content_type
        existing.width, existing.height = image.width, image.height
        existing.byte_size = len(image.data)
        existing.checksum_sha256 = image.checksum
        await session.flush()
        if superseded:
            # Repoint first, then delete: a crash leaves a stray file, not a row that
            # points at bytes which are gone.
            await storage.delete(superseded)
        return key, False

    session.add(
        Artwork(
            kind=kind.value,
            show_id=show.id if episode is None else None,
            episode_id=episode.id if episode is not None else None,
            storage_key=key,
            content_type=image.content_type,
            width=image.width,
            height=image.height,
            byte_size=len(image.data),
            checksum_sha256=image.checksum,
        )
    )
    return key, True


async def _reset(session: AsyncSession) -> None:
    await session.execute(delete(PublishRun))
    await session.execute(delete(Artwork))
    await session.execute(delete(Episode))
    await session.execute(delete(Season))
    await session.execute(delete(Show))
    await session.flush()


async def _load(
    session: AsyncSession,
    storage: ObjectStorage,
    reference: Reference,
    seed: SeedLoad,
) -> SeedOutcome:
    outcome = SeedOutcome()
    claimed_variants: set[tuple[str, str]] = set()

    for show_view in seed.shows:
        show = (
            await session.execute(select(Show).where(Show.slug == show_view.slug))
        ).scalar_one_or_none()
        if show is None:
            show = Show(slug=show_view.slug)
            session.add(show)
            outcome.shows += 1
        show.title = show_view.title
        show.synopsis = show_view.synopsis
        show.section = show_view.section
        show.categories = list(show_view.categories)
        show.status = show_view.status
        await session.flush()

        for kind in (ArtworkKind.POSTER, ArtworkKind.BANNER):
            if kind.value not in show_view.artwork_kinds:
                continue
            key, created = await _store_artwork(
                session, storage, reference, kind=kind, label=show_view.title, show=show
            )
            outcome.example_artwork_key = outcome.example_artwork_key or key
            outcome.artwork += int(created)

        seasons: dict[int, Season] = {}
        for number in sorted({e.season_number for e in show_view.episodes}):
            season = (
                await session.execute(
                    select(Season).where(Season.show_id == show.id, Season.season_number == number)
                )
            ).scalar_one_or_none()
            if season is None:
                season = Season(
                    show_id=show.id,
                    season_number=number,
                    title="Trailers" if number == 0 else f"Season {number}",
                )
                session.add(season)
                outcome.seasons += 1
            seasons[number] = season
        await session.flush()

        for view in show_view.episodes:
            variant = (view.content_group, view.language)
            if variant in claimed_variants:
                # The database forbids this and so does the API. Report, do not repair.
                outcome.rejected.append(
                    {
                        "episode_id": view.ref,
                        "reason": "duplicate_content_group_language",
                        "detail": (
                            f"content group '{view.content_group}' already has a "
                            f"'{view.language}' version"
                        ),
                    }
                )
                continue
            claimed_variants.add(variant)

            episode = (
                await session.execute(select(Episode).where(Episode.external_id == view.ref))
            ).scalar_one_or_none()
            if episode is None:
                episode = Episode(external_id=view.ref)
                session.add(episode)
                outcome.episodes += 1
            episode.season_id = seasons[view.season_number].id
            episode.episode_number = view.episode_number
            episode.title = view.title
            episode.duration_seconds = view.duration_seconds
            episode.language = view.language
            episode.content_group = view.content_group
            episode.status = view.status
            await session.flush()

            if ArtworkKind.THUMBNAIL.value in view.artwork_kinds:
                _, created = await _store_artwork(
                    session,
                    storage,
                    reference,
                    kind=ArtworkKind.THUMBNAIL,
                    label=view.title,
                    show=show,
                    episode=episode,
                )
                outcome.artwork += int(created)

    return outcome


def _print_report(seed: SeedLoad, outcome: SeedOutcome) -> None:
    blocking = [i for i in seed.issues if i.severity is Severity.BLOCKER]
    warnings = [i for i in seed.issues if i.severity is Severity.WARNING]

    print(f"\nSeeded from {seed.row_count} rows:")
    print(
        f"  shows={outcome.shows} seasons={outcome.seasons} episodes={outcome.episodes} "
        f"artwork={outcome.artwork} users={outcome.users}"
    )
    if outcome.rejected:
        print(
            f"\n  {len(outcome.rejected)} row(s) rejected — "
            f"uq_episodes_content_group_language would refuse them:"
        )
        for rejected in outcome.rejected:
            print(f"    - {rejected['episode_id']}: {rejected['detail']}")

    print(f"\nValidation: {len(blocking)} blocker(s), {len(warnings)} warning(s)")
    for issue in seed.issues:
        marker = "BLOCK" if issue.severity is Severity.BLOCKER else " warn"
        print(f"  [{marker}] {issue.entity}: {issue.message}")
        print(f"          → {issue.fix_hint}")


async def seed_database(
    settings: Settings, *, reset: bool = False, if_empty: bool = False
) -> tuple[SeedLoad, SeedOutcome | None]:
    """Load the seed file into the configured database.

    Returns the parsed seed (issues included) and what was written — or ``None`` for
    the write half when ``if_empty`` short-circuited because content already exists.
    """
    reference = load_reference(Path(settings.reference_path) if settings.reference_path else None)
    seed = load_seed(SEED_PATH, reference)

    engine = create_engine(settings)
    factory = create_session_factory(engine)
    storage = build_storage(settings, factory)

    try:
        async with factory() as session:
            if reset:
                await _reset(session)
            elif if_empty:
                existing = (await session.execute(select(Show.id).limit(1))).first()
                if existing is not None:
                    return seed, None

            outcome = await _load(session, storage, reference, seed)
            outcome.users = await _seed_users(session, settings)
            await session.commit()

        if outcome.example_artwork_key:
            outcome.example_artwork_url = storage.url_for(outcome.example_artwork_key)

        report = outcome.as_dict(seed.issues, seed.row_count)
        await storage.put(
            REPORT_KEY, json.dumps(report, indent=2, sort_keys=True).encode(), "application/json"
        )
        return seed, outcome
    finally:
        await engine.dispose()


async def run(args: argparse.Namespace, settings: Settings | None = None) -> int:
    seed, outcome = await seed_database(
        settings or get_settings(), reset=args.reset, if_empty=args.if_empty
    )
    if outcome is None:
        print("seed: content already present, nothing to do (--if-empty)")
        return 0

    _print_report(seed, outcome)
    print(f"\nMachine-readable report written to storage key '{REPORT_KEY}'.")
    if outcome.example_artwork_url:
        print(f"Example artwork: {outcome.example_artwork_url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete existing content first")
    parser.add_argument(
        "--if-empty", action="store_true", help="do nothing if any show already exists"
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
