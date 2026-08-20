"""Viewer search, over the published catalogue document.

The viewer reads only what has been published, and search is part of the viewer — so it
filters the same document ``GET /catalog`` serves rather than querying the content
database. That is what keeps a result and its detail page in agreement: index one thing
and serve another, and the two drift the moment an editor saves without publishing.

**Scale.** This is a scan of an in-memory document, so cost is linear in the catalogue.
At the size a single published file makes sense for — thousands of shows — that is
microseconds and the network dominates. The ceiling is the file itself, not this
function: when the catalogue outgrows one document, search should be an index built at
publish time (a `search_documents` table, or a real search engine), not a bigger scan.
The database's trigram indexes exist for the CMS's own list, which is a different
surface with different rules — it must show drafts, so it cannot read the catalogue.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

BROWSE_FIELDS = ("slug", "title", "synopsis", "categories", "languages", "artwork")


@dataclass(frozen=True, slots=True)
class SearchPage:
    results: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


def _walk(document: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for section in document.get("sections", []):
        for show in section.get("shows", []):
            yield section["key"], show


def _episode_titles(show: dict[str, Any]) -> Iterator[str]:
    for season in show.get("seasons", []):
        for episode in season.get("episodes", []):
            yield episode.get("title", "")
    for trailer in show.get("trailers", []):
        yield trailer.get("title", "")


def _matches_query(show: dict[str, Any], needle: str) -> bool:
    """`q` matches a show title, an episode title, or a category.

    Titles match on substring — that is how someone types half a name. Categories match
    exactly, because they are a controlled vocabulary of fifteen words and a substring
    match there produces confusing hits rather than useful ones.
    """
    if needle in show.get("title", "").casefold():
        return True
    if any(category.casefold() == needle for category in show.get("categories", [])):
        return True
    return any(needle in title.casefold() for title in _episode_titles(show))


def search_document(
    document: dict[str, Any],
    *,
    q: str | None = None,
    category: str | None = None,
    language: str | None = None,
    section: str | None = None,
    limit: int = 24,
    offset: int = 0,
) -> SearchPage:
    needle = (q or "").strip().casefold()
    matched: list[dict[str, Any]] = []

    for section_key, show in _walk(document):
        if section and section_key != section:
            continue
        if category and category not in show.get("categories", []):
            continue
        if language and language not in show.get("languages", []):
            continue
        if needle and not _matches_query(show, needle):
            continue
        matched.append({"section": section_key, **{f: show.get(f) for f in BROWSE_FIELDS}})

    return SearchPage(
        results=matched[offset : offset + limit],
        total=len(matched),
        limit=limit,
        offset=offset,
    )
