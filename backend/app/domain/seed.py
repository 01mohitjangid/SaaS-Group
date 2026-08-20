"""Read ``seed_shows.json`` — a flat list of episode rows — into the show → season →
episode shape the database and catalogue use, and report what is wrong with it.

The seed is deliberately imperfect. Nothing here silently repairs data: every
problem becomes an ``Issue`` an editor can read, and rows are kept so the CMS can
show them as broken rather than making them disappear.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domain.reference import ArtworkKind, Reference
from app.domain.rules import EpisodeView, Issue, ShowView, evaluate

#: poster/banner describe the show; thumbnail describes the single episode.
SHOW_LEVEL_ARTWORK = frozenset({ArtworkKind.POSTER, ArtworkKind.BANNER})
EPISODE_LEVEL_ARTWORK = frozenset({ArtworkKind.THUMBNAIL})


class SeedRow(BaseModel):
    """One row of ``seed_shows.json``, validated only for shape — not for correctness."""

    model_config = ConfigDict(extra="forbid")

    episode_id: str
    show_title: str
    slug: str
    section: str | None
    categories: list[str]
    synopsis: str
    season_number: int
    episode_number: int
    episode_title: str
    duration_seconds: int | None
    language: str
    content_group: str
    status: str
    artwork_available: list[str]


@dataclass(frozen=True, slots=True)
class SeedLoad:
    shows: list[ShowView]
    issues: list[Issue]
    row_count: int


def parse_rows(raw: Sequence[dict[str, Any]]) -> list[SeedRow]:
    return [SeedRow.model_validate(row) for row in raw]


def build_shows(rows: Sequence[SeedRow]) -> list[ShowView]:
    """Group flat rows by slug, deterministically."""
    grouped: dict[str, list[SeedRow]] = defaultdict(list)
    for row in rows:
        grouped[row.slug].append(row)

    shows: list[ShowView] = []
    for slug in sorted(grouped):
        members = sorted(
            grouped[slug],
            key=lambda r: (r.season_number, r.episode_number, r.language, r.episode_id),
        )
        first = members[0]

        episodes = [
            EpisodeView(
                ref=row.episode_id,
                show_slug=slug,
                season_number=row.season_number,
                episode_number=row.episode_number,
                title=row.episode_title,
                duration_seconds=row.duration_seconds,
                language=row.language,
                content_group=row.content_group,
                status=row.status,
                artwork_kinds=frozenset(row.artwork_available) & EPISODE_LEVEL_ARTWORK,
            )
            for row in members
        ]

        show_artwork: set[str] = set()
        for row in members:
            show_artwork |= set(row.artwork_available) & SHOW_LEVEL_ARTWORK

        shows.append(
            ShowView(
                slug=slug,
                title=first.show_title,
                synopsis=first.synopsis,
                section=first.section,
                categories=tuple(first.categories),
                # A show is live as soon as any one of its episodes is.
                status="published" if any(e.is_published for e in episodes) else "draft",
                artwork_kinds=frozenset(show_artwork),
                episodes=episodes,
            )
        )

    return shows


def load_seed(path: Path, reference: Reference) -> SeedLoad:
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    rows = parse_rows(raw)
    shows = build_shows(rows)
    return SeedLoad(shows=shows, issues=evaluate(shows, reference), row_count=len(rows))
