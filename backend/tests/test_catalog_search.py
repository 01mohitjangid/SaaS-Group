"""Viewer search, as pure logic over the published document.

Searching the same document the viewer reads is what makes a result and its detail page
agree — index one thing and serve another and they drift the moment an editor saves
without publishing. It also means the viewer never touches the content database at all.

The cost is a scan per request instead of an index lookup; the ceiling that puts on the
catalogue is stated in the README, and measured rather than guessed.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.search import search_document


def _show(slug: str, **overrides: Any) -> dict[str, Any]:
    show: dict[str, Any] = {
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "synopsis": "",
        "categories": ["adventure"],
        "languages": ["en"],
        "artwork": {"poster": "p", "banner": "b"},
        "trailers": [],
        "seasons": [
            {
                "season_number": 1,
                "title": "Season 1",
                "episodes": [
                    {
                        "ref": f"{slug}-1",
                        "content_group": f"{slug}-cg",
                        "episode_number": 1,
                        "title": "The Lost Kite",
                        "duration_seconds": 500,
                        "languages": ["en"],
                        "artwork": {"thumbnail": "t"},
                    }
                ],
            }
        ],
    }
    show.update(overrides)
    return show


def _document(*sections: tuple[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "version": "run-1",
        "counts": {},
        "sections": [{"key": key, "shows": shows} for key, shows in sections],
    }


DOCUMENT = _document(
    (
        "featured",
        [
            _show(
                "motis-many-lives",
                title="Moti's Many Lives",
                categories=["adventure", "india"],
                languages=["en", "hi"],
            )
        ],
    ),
    (
        "songs",
        [
            _show(
                "peblo-songs",
                title="Peblo Songs",
                categories=["music", "singalong"],
                languages=["en", "hi"],
            ),
            _show("peblo-songs-lyrical", title="Peblo Songs — Lyrical", categories=["music"]),
        ],
    ),
)


def test_no_query_returns_everything_in_catalogue_order() -> None:
    page = search_document(DOCUMENT)
    assert [r["slug"] for r in page.results] == [
        "motis-many-lives",
        "peblo-songs",
        "peblo-songs-lyrical",
    ]
    assert page.total == 3


def test_q_matches_a_show_title_case_insensitively() -> None:
    assert [r["slug"] for r in search_document(DOCUMENT, q="MOTI").results] == ["motis-many-lives"]


def test_q_matches_an_episode_title() -> None:
    page = search_document(DOCUMENT, q="lost kite")
    assert len(page.results) == 3  # every show has that episode title in this fixture


def test_q_matches_a_category_exactly_not_by_substring() -> None:
    assert [r["slug"] for r in search_document(DOCUMENT, q="singalong").results] == ["peblo-songs"]
    # "sing" is a prefix of a category but not a category, and no title contains it.
    assert search_document(DOCUMENT, q="sing").results == []


def test_filters_compose() -> None:
    assert len(search_document(DOCUMENT, section="songs").results) == 2
    assert len(search_document(DOCUMENT, category="music").results) == 2
    assert len(search_document(DOCUMENT, language="hi").results) == 2

    both = search_document(DOCUMENT, q="peblo", language="hi", section="songs")
    assert [r["slug"] for r in both.results] == ["peblo-songs"]

    assert search_document(DOCUMENT, q="moti", section="songs").results == []


def test_an_unknown_filter_value_returns_nothing_rather_than_everything() -> None:
    assert search_document(DOCUMENT, section="nowhere").results == []
    assert search_document(DOCUMENT, category="dinosaurs").results == []
    assert search_document(DOCUMENT, language="fr").results == []


@pytest.mark.parametrize("wildcard", ["%", "_", "%%", "*"])
def test_wildcards_are_literal_text_not_wildcards(wildcard: str) -> None:
    assert search_document(DOCUMENT, q=wildcard).results == []


def test_results_carry_only_browse_fields() -> None:
    (result,) = search_document(DOCUMENT, q="moti").results
    assert set(result) == {
        "section",
        "slug",
        "title",
        "synopsis",
        "categories",
        "languages",
        "artwork",
    }


def test_paging_reports_the_full_total() -> None:
    page = search_document(DOCUMENT, limit=1, offset=1)
    assert page.total == 3
    assert [r["slug"] for r in page.results] == ["peblo-songs"]


def test_an_empty_document_searches_cleanly() -> None:
    page = search_document({"sections": []}, q="anything")
    assert page.results == []
    assert page.total == 0


def test_whitespace_only_queries_are_treated_as_no_query() -> None:
    assert search_document(DOCUMENT, q="   ").total == 3
