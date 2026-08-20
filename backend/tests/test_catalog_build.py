"""The publish job's brain: turning content rows into the file the viewer reads.

This is pure logic — no database, no storage — so it is tested first and hardest.
Language collapsing and deterministic ordering are the two things the brief is most
explicit about, and the two things that are most quietly easy to get wrong.
"""

from __future__ import annotations

import json

import pytest

from app.domain.catalog import build_catalog, to_payload
from app.domain.reference import Reference
from app.domain.rules import EpisodeView, ShowView


def _url(key: str) -> str:
    return f"https://cdn.test/{key}"


def _episode(**overrides: object) -> EpisodeView:
    base: dict[str, object] = {
        "ref": "ep_1",
        "show_slug": "a-show",
        "season_number": 1,
        "episode_number": 1,
        "title": "An Episode",
        "duration_seconds": 500,
        "language": "en",
        "content_group": "a-show-s01e01",
        "status": "published",
        "artwork_kinds": frozenset({"thumbnail"}),
        "artwork_keys": {"thumbnail": "artwork/episodes/1/thumbnail.jpg"},
    }
    base.update(overrides)
    return EpisodeView(**base)  # type: ignore[arg-type]


def _show(episodes: list[EpisodeView] | None = None, **overrides: object) -> ShowView:
    base: dict[str, object] = {
        "slug": "a-show",
        "title": "A Show",
        "synopsis": "Something happens.",
        "section": "series",
        "categories": ("adventure",),
        "status": "published",
        "artwork_kinds": frozenset({"poster", "banner"}),
        "artwork_keys": {
            "poster": "artwork/shows/1/poster.jpg",
            "banner": "artwork/shows/1/banner.jpg",
        },
        "episodes": episodes if episodes is not None else [_episode()],
    }
    base.update(overrides)
    return ShowView(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------ what appears


def test_only_published_shows_appear(reference: Reference) -> None:
    catalog = build_catalog([_show(status="draft")], reference, _url)
    assert catalog.sections == ()
    assert catalog.counts["shows"] == 0


def test_only_published_episodes_appear(reference: Reference) -> None:
    show = _show(
        [
            _episode(ref="ep_live", content_group="cg-1"),
            _episode(ref="ep_draft", content_group="cg-2", status="draft"),
        ]
    )
    (episode,) = build_catalog([show], reference, _url).sections[0].shows[0].seasons[0].episodes
    assert episode.ref == "ep_live"


def test_a_show_with_no_section_never_reaches_the_catalogue(reference: Reference) -> None:
    assert build_catalog([_show(section=None)], reference, _url).sections == ()


def test_a_show_with_an_unknown_section_never_reaches_the_catalogue(
    reference: Reference,
) -> None:
    assert build_catalog([_show(section="carousel")], reference, _url).sections == ()


def test_a_show_whose_only_episodes_are_drafts_is_dropped(reference: Reference) -> None:
    show = _show([_episode(status="draft")])
    assert build_catalog([show], reference, _url).sections == ()


# ------------------------------------------------------------- language collapsing


def test_content_group_variants_collapse_into_one_entry(reference: Reference) -> None:
    """The headline rule: English and Hindi are one episode, not two."""
    show = _show(
        [
            _episode(ref="ep_en", language="en", content_group="cg-1", duration_seconds=510),
            _episode(ref="ep_hi", language="hi", content_group="cg-1", duration_seconds=480),
        ]
    )
    (episode,) = build_catalog([show], reference, _url).sections[0].shows[0].seasons[0].episodes
    assert episode.languages == ("en", "hi")
    assert episode.content_group == "cg-1"


def test_the_english_variant_supplies_the_displayed_fields(reference: Reference) -> None:
    """Dubs differ in length and sometimes in title; one variant has to win, predictably."""
    show = _show(
        [
            _episode(
                ref="ep_hi",
                language="hi",
                content_group="cg-1",
                title="Hindi Title",
                duration_seconds=480,
            ),
            _episode(
                ref="ep_en",
                language="en",
                content_group="cg-1",
                title="English Title",
                duration_seconds=510,
            ),
        ]
    )
    (episode,) = build_catalog([show], reference, _url).sections[0].shows[0].seasons[0].episodes
    assert episode.title == "English Title"
    assert episode.duration_seconds == 510
    assert episode.ref == "ep_en"


def test_without_english_the_lowest_language_code_wins(reference: Reference) -> None:
    show = _show(
        [
            _episode(ref="ep_hi", language="hi", content_group="cg-1", title="Hindi Only"),
        ]
    )
    (episode,) = build_catalog([show], reference, _url).sections[0].shows[0].seasons[0].episodes
    assert episode.title == "Hindi Only"
    assert episode.languages == ("hi",)


def test_a_show_lists_every_language_any_of_its_episodes_has(reference: Reference) -> None:
    show = _show(
        [
            _episode(ref="a", content_group="cg-1", language="en"),
            _episode(ref="b", content_group="cg-1", language="hi"),
            _episode(ref="c", content_group="cg-2", episode_number=2, language="en"),
        ]
    )
    catalog_show = build_catalog([show], reference, _url).sections[0].shows[0]
    assert catalog_show.languages == ("en", "hi")


def test_a_draft_variant_does_not_add_a_language(reference: Reference) -> None:
    """A Hindi dub still in draft must not be advertised as available."""
    show = _show(
        [
            _episode(ref="a", content_group="cg-1", language="en"),
            _episode(ref="b", content_group="cg-1", language="hi", status="draft"),
        ]
    )
    (episode,) = build_catalog([show], reference, _url).sections[0].shows[0].seasons[0].episodes
    assert episode.languages == ("en",)


# -------------------------------------------------------------------- season zero


def test_season_zero_is_trailers_not_a_season(reference: Reference) -> None:
    show = _show(
        [
            _episode(ref="ep_trailer", season_number=0, content_group="cg-0", title="Trailer"),
            _episode(ref="ep_1", season_number=1, content_group="cg-1"),
        ]
    )
    catalog_show = build_catalog([show], reference, _url).sections[0].shows[0]
    assert [s.season_number for s in catalog_show.seasons] == [1]
    assert [t.ref for t in catalog_show.trailers] == ["ep_trailer"]


def test_a_show_with_only_a_trailer_is_not_published(reference: Reference) -> None:
    show = _show([_episode(season_number=0, content_group="cg-0", title="Trailer")])
    assert build_catalog([show], reference, _url).sections == ()


# ----------------------------------------------------------------------- artwork


def test_each_surface_gets_its_own_artwork_url(reference: Reference) -> None:
    catalog_show = build_catalog([_show()], reference, _url).sections[0].shows[0]
    assert catalog_show.artwork == {
        "poster": "https://cdn.test/artwork/shows/1/poster.jpg",
        "banner": "https://cdn.test/artwork/shows/1/banner.jpg",
    }
    episode = catalog_show.seasons[0].episodes[0]
    assert episode.artwork == {"thumbnail": "https://cdn.test/artwork/episodes/1/thumbnail.jpg"}


# ---------------------------------------------------------------------- ordering


def test_sections_follow_reference_order_not_the_alphabet(reference: Reference) -> None:
    shows = [
        _show(slug="s", section="songs", episodes=[_episode(show_slug="s", content_group="a")]),
        _show(slug="f", section="featured", episodes=[_episode(show_slug="f", content_group="b")]),
        _show(slug="e", section="series", episodes=[_episode(show_slug="e", content_group="c")]),
    ]
    catalog = build_catalog(shows, reference, _url)
    assert [s.key for s in catalog.sections] == ["featured", "series", "songs"]


def test_shows_within_a_section_are_ordered_by_title_then_slug(reference: Reference) -> None:
    shows = [
        _show(slug="z", title="Alpha", episodes=[_episode(show_slug="z", content_group="1")]),
        _show(slug="a", title="Alpha", episodes=[_episode(show_slug="a", content_group="2")]),
        _show(slug="m", title="Beta", episodes=[_episode(show_slug="m", content_group="3")]),
    ]
    section = build_catalog(shows, reference, _url).sections[0]
    assert [s.slug for s in section.shows] == ["a", "z", "m"]


def test_episodes_are_ordered_by_number(reference: Reference) -> None:
    show = _show(
        [
            _episode(ref="c", episode_number=3, content_group="c"),
            _episode(ref="a", episode_number=1, content_group="a"),
            _episode(ref="b", episode_number=2, content_group="b"),
        ]
    )
    season = build_catalog([show], reference, _url).sections[0].shows[0].seasons[0]
    assert [e.episode_number for e in season.episodes] == [1, 2, 3]


def test_the_same_content_always_produces_byte_identical_json(reference: Reference) -> None:
    """Publish must be idempotent, which starts with the bytes being stable."""
    shows = [
        _show(slug="b", title="Bee", episodes=[_episode(show_slug="b", content_group="1")]),
        _show(slug="a", title="Ay", episodes=[_episode(show_slug="a", content_group="2")]),
    ]
    first = to_payload(build_catalog(shows, reference, _url), version="v1")
    second = to_payload(build_catalog(list(reversed(shows)), reference, _url), version="v1")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ------------------------------------------------------------------------ counts


def test_counts_describe_what_was_published(reference: Reference) -> None:
    show = _show(
        [
            _episode(ref="a", content_group="cg-1", language="en"),
            _episode(ref="b", content_group="cg-1", language="hi"),
            _episode(ref="c", content_group="cg-2", episode_number=2),
            _episode(ref="t", season_number=0, content_group="cg-0", title="Trailer"),
        ]
    )
    counts = build_catalog([show], reference, _url).counts
    assert counts["sections"] == 1
    assert counts["shows"] == 1
    assert counts["seasons"] == 1
    assert counts["episodes"] == 2  # variants collapsed, trailer counted separately
    assert counts["trailers"] == 1
    assert counts["source_episodes"] == 4


def test_payload_is_json_serialisable_and_carries_its_version(reference: Reference) -> None:
    payload = to_payload(build_catalog([_show()], reference, _url), version="run-123")
    assert payload["version"] == "run-123"
    assert payload["sections"][0]["key"] == "series"
    json.dumps(payload)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_version_is_refused(reference: Reference, blank: str) -> None:
    with pytest.raises(ValueError, match="version"):
        to_payload(build_catalog([_show()], reference, _url), version=blank)


# ------------------------------------------------------------ idempotency fingerprint


def test_the_digest_ignores_the_run_id_and_the_clock(reference: Reference) -> None:
    """Two runs over unchanged content must be recognised as the same catalogue."""
    from app.domain.catalog import content_digest

    catalog = build_catalog([_show()], reference, _url)
    again = build_catalog([_show()], reference, _url)
    assert content_digest(catalog) == content_digest(again)

    first = to_payload(catalog, version="run-1", generated_at="2026-01-01T00:00:00Z")
    second = to_payload(again, version="run-2", generated_at="2026-06-06T12:00:00Z")
    assert first != second  # the documents differ …
    assert content_digest(catalog) == content_digest(again)  # … but the content does not


def test_the_digest_changes_when_content_changes(reference: Reference) -> None:
    from app.domain.catalog import content_digest

    before = content_digest(build_catalog([_show()], reference, _url))
    after = content_digest(build_catalog([_show(title="Renamed")], reference, _url))
    assert before != after


def test_a_new_language_changes_the_digest(reference: Reference) -> None:
    """Shipping the Hindi dub is a real change even though nothing else moved."""
    from app.domain.catalog import content_digest

    english_only = _show([_episode(ref="a", content_group="cg-1", language="en")])
    with_hindi = _show(
        [
            _episode(ref="a", content_group="cg-1", language="en"),
            _episode(ref="b", content_group="cg-1", language="hi"),
        ]
    )
    assert content_digest(build_catalog([english_only], reference, _url)) != content_digest(
        build_catalog([with_hindi], reference, _url)
    )


def test_canonical_bytes_are_stable(reference: Reference) -> None:
    from app.domain.catalog import canonical_bytes

    payload = to_payload(build_catalog([_show()], reference, _url), version="v")
    assert canonical_bytes(payload) == canonical_bytes(dict(reversed(list(payload.items()))))
