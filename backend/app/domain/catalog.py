"""Build the published catalogue.

This is the pure half of the publish job: content rows in, the exact document the
viewer reads out. No database, no storage, no clock — so it can be tested hard and
so publishing twice with unchanged content produces byte-identical bytes.

Three rules from the brief live here:

* Only published shows *and* published episodes appear.
* Episodes sharing a ``content_group`` are language variants of one episode and
  collapse into a single entry carrying a ``languages`` list.
* Season 0 is trailers. It is never rendered as a season, so it comes out on its own
  ``trailers`` field rather than in ``seasons``.

Everything is ordered deterministically: sections in the order the content team listed
them in ``reference.json`` (not alphabetically — "featured" leads for a reason), shows
by title then slug, seasons and episodes by number.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.domain.reference import Reference
from app.domain.rules import EpisodeView, ShowView

#: When a content group has several language variants, one has to supply the title,
#: run time and thumbnail. English is the master unless there isn't one, in which case
#: the lowest language code wins — arbitrary, but stable, which is what matters.
PRIMARY_LANGUAGE = "en"

UrlFor = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class CatalogEpisode:
    ref: str
    content_group: str
    episode_number: int
    title: str
    duration_seconds: int | None
    languages: tuple[str, ...]
    artwork: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CatalogSeason:
    season_number: int
    title: str
    episodes: tuple[CatalogEpisode, ...]


@dataclass(frozen=True, slots=True)
class CatalogShow:
    slug: str
    title: str
    synopsis: str
    categories: tuple[str, ...]
    languages: tuple[str, ...]
    artwork: Mapping[str, str]
    seasons: tuple[CatalogSeason, ...]
    trailers: tuple[CatalogEpisode, ...]


@dataclass(frozen=True, slots=True)
class CatalogSection:
    key: str
    shows: tuple[CatalogShow, ...]


@dataclass(frozen=True, slots=True)
class Catalog:
    sections: tuple[CatalogSection, ...]
    counts: Mapping[str, int]


def _primary(variants: Sequence[EpisodeView]) -> EpisodeView:
    return min(variants, key=lambda e: (e.language != PRIMARY_LANGUAGE, e.language, e.ref))


def _collapse(episodes: Sequence[EpisodeView], url_for: UrlFor) -> list[CatalogEpisode]:
    """One entry per content group, listing the languages it is available in."""
    grouped: dict[str, list[EpisodeView]] = defaultdict(list)
    for episode in episodes:
        grouped[episode.content_group].append(episode)

    collapsed = []
    for content_group, variants in grouped.items():
        lead = _primary(variants)
        collapsed.append(
            CatalogEpisode(
                ref=lead.ref,
                content_group=content_group,
                episode_number=lead.episode_number,
                title=lead.title,
                duration_seconds=lead.duration_seconds,
                languages=tuple(sorted({v.language for v in variants})),
                artwork={kind: url_for(key) for kind, key in sorted(lead.artwork_keys.items())},
            )
        )
    return sorted(collapsed, key=lambda e: (e.episode_number, e.content_group))


def _build_show(show: ShowView, url_for: UrlFor) -> CatalogShow | None:
    live = [e for e in show.episodes if e.is_published]
    regular = [e for e in live if not e.is_trailer]
    if not regular:
        # A show whose only live content is a trailer has nothing to browse.
        return None

    by_season: dict[int, list[EpisodeView]] = defaultdict(list)
    for episode in regular:
        by_season[episode.season_number].append(episode)

    seasons = tuple(
        CatalogSeason(
            season_number=number,
            title=f"Season {number}",
            episodes=tuple(_collapse(by_season[number], url_for)),
        )
        for number in sorted(by_season)
    )

    return CatalogShow(
        slug=show.slug,
        title=show.title,
        synopsis=show.synopsis,
        categories=tuple(show.categories),
        languages=tuple(sorted({e.language for e in live})),
        artwork={kind: url_for(key) for kind, key in sorted(show.artwork_keys.items())},
        seasons=seasons,
        trailers=tuple(_collapse([e for e in live if e.is_trailer], url_for)),
    )


def build_catalog(shows: Sequence[ShowView], reference: Reference, url_for: UrlFor) -> Catalog:
    by_section: dict[str, list[CatalogShow]] = defaultdict(list)
    source_episodes = 0

    for show in shows:
        if not show.is_published or not reference.is_section(show.section):
            continue
        built = _build_show(show, url_for)
        if built is None:
            continue
        assert show.section is not None  # narrowed by is_section above
        by_section[show.section].append(built)
        source_episodes += sum(1 for e in show.episodes if e.is_published)

    sections = tuple(
        CatalogSection(
            key=key,
            shows=tuple(sorted(by_section[key], key=lambda s: (s.title, s.slug))),
        )
        for key in reference.sections
        if by_section.get(key)
    )

    every_show = [show for section in sections for show in section.shows]
    return Catalog(
        sections=sections,
        counts={
            "sections": len(sections),
            "shows": len(every_show),
            "seasons": sum(len(s.seasons) for s in every_show),
            "episodes": sum(len(season.episodes) for s in every_show for season in s.seasons),
            "trailers": sum(len(s.trailers) for s in every_show),
            "source_episodes": source_episodes,
        },
    )


def content_digest(catalog: Catalog) -> str:
    """A fingerprint of the catalogue's *content*, ignoring which run produced it.

    Publishing twice with nothing changed must be recognised as a no-op, so the
    version and the timestamp — the two fields that always differ — are excluded.
    """
    body = to_payload(catalog, version="digest")
    body.pop("version")
    body.pop("generated_at")
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Stable JSON: sorted keys, no incidental whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _episode_payload(episode: CatalogEpisode) -> dict[str, Any]:
    return {
        "ref": episode.ref,
        "content_group": episode.content_group,
        "episode_number": episode.episode_number,
        "title": episode.title,
        "duration_seconds": episode.duration_seconds,
        "languages": list(episode.languages),
        "artwork": dict(episode.artwork),
    }


def to_payload(
    catalog: Catalog, *, version: str, generated_at: str | None = None
) -> dict[str, Any]:
    """The JSON document written to storage and served by ``GET /catalog``.

    ``generated_at`` is passed in rather than read from a clock so the same content
    can produce the same bytes — that is what makes an unchanged re-publish a no-op.
    """
    if not version.strip():
        raise ValueError("a catalogue needs a non-empty version (the publish run id)")

    return {
        "version": version,
        "generated_at": generated_at,
        "counts": dict(catalog.counts),
        "sections": [
            {
                "key": section.key,
                "shows": [
                    {
                        "slug": show.slug,
                        "title": show.title,
                        "synopsis": show.synopsis,
                        "categories": list(show.categories),
                        "languages": list(show.languages),
                        "artwork": dict(show.artwork),
                        "trailers": [_episode_payload(t) for t in show.trailers],
                        "seasons": [
                            {
                                "season_number": season.season_number,
                                "title": season.title,
                                "episodes": [_episode_payload(e) for e in season.episodes],
                            }
                            for season in show.seasons
                        ],
                    }
                    for show in section.shows
                ],
            }
            for section in catalog.sections
        ],
    }
