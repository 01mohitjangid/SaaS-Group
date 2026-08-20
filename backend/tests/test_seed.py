"""The seed file is deliberately imperfect.

These tests pin the exact defects found in `data/challenge/seed_shows.json`, so a
change to the loader that stops surfacing one of them fails loudly.
"""

from __future__ import annotations

from pathlib import Path

from app.domain.reference import Reference
from app.domain.rules import IssueCode, Severity
from app.domain.seed import load_seed


def test_seed_parses_every_row(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    assert load.row_count == 95
    assert len(load.shows) == 8


def test_shows_are_keyed_by_slug_not_title(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    slugs = [s.slug for s in load.shows]
    assert slugs == sorted(slugs), "shows must come back in deterministic slug order"
    assert "peblo-songs" in slugs
    assert "peblo-songs-lyrical" in slugs


def test_poster_and_banner_attach_to_the_show_thumbnail_to_the_episode(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    show = next(s for s in load.shows if s.slug == "motis-many-lives")
    assert show.artwork_kinds == frozenset({"poster", "banner"})
    episode = next(e for e in show.episodes if e.ref == "ep_0001")
    assert episode.artwork_kinds == frozenset({"thumbnail"})


def test_seasons_and_episode_counts(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    show = next(s for s in load.shows if s.slug == "motis-many-lives")
    assert sorted({e.season_number for e in show.episodes}) == [0, 1]
    assert len(show.episodes) == 18


def test_show_status_is_published_when_any_episode_is_published(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    by_slug = {s.slug: s for s in load.shows}
    assert by_slug["number-nest"].status == "published"  # 6 published, 2 draft
    assert by_slug["rhyme-rangers"].status == "draft"  # all 8 rows are draft


# --------------------------------------------------------------- planted defects


def _issues(seed_path: Path, reference: Reference, code: IssueCode) -> list[str]:
    load = load_seed(seed_path, reference)
    return [i.entity for i in load.issues if i.code is code]


def test_defect_duplicate_language_variant_ep_9001(seed_path: Path, reference: Reference) -> None:
    """ep_9001 re-uses (motis-many-lives-s01e02, hi), already taken by ep_0004."""
    load = load_seed(seed_path, reference)
    dupes = [i for i in load.issues if i.code is IssueCode.DUPLICATE_VARIANT]
    assert len(dupes) == 1
    assert dupes[0].severity is Severity.BLOCKER
    assert "ep_0004" in dupes[0].message and "ep_9001" in dupes[0].message


def test_defect_published_episode_with_no_artwork_ep_0036(
    seed_path: Path, reference: Reference
) -> None:
    assert _issues(seed_path, reference, IssueCode.EPISODE_MISSING_ARTWORK) == ["episode:ep_0036"]


def test_defect_rhyme_rangers_has_no_section(seed_path: Path, reference: Reference) -> None:
    entities = _issues(seed_path, reference, IssueCode.SHOW_MISSING_SECTION)
    assert entities == ["show:rhyme-rangers"]

    load = load_seed(seed_path, reference)
    issue = next(i for i in load.issues if i.code is IssueCode.SHOW_MISSING_SECTION)
    # The show is still a draft, so it is a warning today — but it can never be published.
    assert issue.severity is Severity.WARNING


def test_defect_lowercase_episode_title_ep_0078(seed_path: Path, reference: Reference) -> None:
    assert _issues(seed_path, reference, IssueCode.EPISODE_TITLE_CASING) == ["episode:ep_0078"]


def test_defect_variant_title_mismatch_is_reported(seed_path: Path, reference: Reference) -> None:
    entities = _issues(seed_path, reference, IssueCode.VARIANT_TITLE_MISMATCH)
    assert entities == ["content_group:motis-many-lives-s01e02"]


def test_trailers_keep_their_thumbnail_only_artwork_without_complaint(
    seed_path: Path, reference: Reference
) -> None:
    """Season 0 rows only ship a thumbnail; that is correct, not a defect."""
    load = load_seed(seed_path, reference)
    trailer_entities = {"episode:ep_0093", "episode:ep_0094"}
    assert not [i for i in load.issues if i.entity in trailer_entities]


def test_the_whole_seed_has_exactly_two_publish_blockers(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    blocking = sorted(i.entity for i in load.issues if i.severity is Severity.BLOCKER)
    assert blocking == ["content_group:motis-many-lives-s01e02", "episode:ep_0036"]


def test_no_unknown_vocabulary_values_in_the_seed(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    unexpected = {
        IssueCode.SHOW_UNKNOWN_SECTION,
        IssueCode.SHOW_UNKNOWN_CATEGORY,
        IssueCode.EPISODE_UNKNOWN_LANGUAGE,
    }
    assert not [i for i in load.issues if i.code in unexpected]


def test_language_variant_duration_drift_is_accepted_not_flagged(
    seed_path: Path, reference: Reference
) -> None:
    """Hindi dubs legitimately differ in length; the catalogue picks one deterministically."""
    load = load_seed(seed_path, reference)
    show = next(s for s in load.shows if s.slug == "motis-many-lives")
    en = next(e for e in show.episodes if e.ref == "ep_0001")
    hi = next(e for e in show.episodes if e.ref == "ep_0002")
    assert (en.duration_seconds, hi.duration_seconds) == (510, 480)
    assert not [
        i for i in load.issues if "duration" in i.message.lower() and i.severity is Severity.BLOCKER
    ]


# ------------------------------------------------- claims made in docs/DATA_ANALYSIS.md
# Each of these pins a "we checked, and it is clean" statement in the analysis doc, so
# the doc cannot quietly become wrong.


def test_no_duplicate_episode_ids(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    refs = [e.ref for show in load.shows for e in show.episodes]
    assert len(refs) == len(set(refs)) == 95


def test_no_blank_fields_and_no_bad_durations(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    for show in load.shows:
        assert show.slug and show.title and show.synopsis
        for episode in show.episodes:
            assert episode.title.strip()
            assert episode.content_group.strip()
            assert episode.status in {"draft", "published"}
            assert episode.duration_seconds is not None
            assert episode.duration_seconds > 0


def test_no_gaps_in_episode_numbering(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    for show in load.shows:
        by_season: dict[int, set[int]] = {}
        for episode in show.episodes:
            by_season.setdefault(episode.season_number, set()).add(episode.episode_number)
        for numbers in by_season.values():
            assert numbers == set(range(1, max(numbers) + 1)), show.slug


def test_hindi_coverage_is_partial_which_is_why_languages_is_per_entry(
    seed_path: Path, reference: Reference
) -> None:
    """A show-level `languages` field would be a lie: Hindi covers only some episodes."""
    load = load_seed(seed_path, reference)
    groups: dict[str, set[str]] = {}
    for show in load.shows:
        for episode in show.episodes:
            groups.setdefault(episode.content_group, set()).add(episode.language)

    assert len(groups) == 76
    assert len([g for g, langs in groups.items() if len(langs) > 1]) == 18
    assert all(langs <= {"en", "hi"} for langs in groups.values())

    # Per show: how many of its content groups have a Hindi version.
    coverage: dict[str, tuple[int, int]] = {}
    for show in load.shows:
        show_groups: dict[str, set[str]] = {}
        for episode in show.episodes:
            show_groups.setdefault(episode.content_group, set()).add(episode.language)
        with_hindi = len([langs for langs in show_groups.values() if "hi" in langs])
        coverage[show.slug] = (with_hindi, len(show_groups))

    assert coverage == {
        "curious-cubs": (0, 8),
        "discover-india-with-moti": (0, 10),
        "motis-many-lives": (6, 11),
        "number-nest": (0, 8),
        "peblo-songs": (6, 10),
        "peblo-songs-lyrical": (0, 10),
        "rhyme-rangers": (0, 8),
        "tiny-tales-banyan-dadi": (6, 11),
    }
    # Only three shows ship Hindi at all, and none of them ships it for every episode.
    assert [slug for slug, (hi, _) in coverage.items() if hi] == [
        "motis-many-lives",
        "peblo-songs",
        "tiny-tales-banyan-dadi",
    ]
    assert all(hi < total for hi, total in coverage.values() if hi)


def test_sixteen_content_groups_have_language_variants_of_different_lengths(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    durations: dict[str, set[int | None]] = {}
    for show in load.shows:
        for episode in show.episodes:
            durations.setdefault(episode.content_group, set()).add(episode.duration_seconds)
    assert len([g for g, values in durations.items() if len(values) > 1]) == 16


#: The shape table in docs/DATA_ANALYSIS.md, as data.
#: slug -> (rows, section, show status, {language: rows}, seasons)
SHAPE: dict[str, tuple[int, str | None, str, dict[str, int], list[int]]] = {
    "curious-cubs": (8, "series", "published", {"en": 8}, [1]),
    "discover-india-with-moti": (10, "minisodes", "published", {"en": 10}, [1]),
    "motis-many-lives": (18, "featured", "published", {"en": 11, "hi": 7}, [0, 1]),
    "number-nest": (8, "series", "published", {"en": 8}, [1]),
    "peblo-songs": (16, "songs", "published", {"en": 10, "hi": 6}, [1]),
    "peblo-songs-lyrical": (10, "songs", "published", {"en": 10}, [1]),
    "rhyme-rangers": (8, None, "draft", {"en": 8}, [1]),
    "tiny-tales-banyan-dadi": (17, "series", "published", {"en": 11, "hi": 6}, [0, 1]),
}


def test_the_shape_table_in_the_analysis_doc_matches_the_data(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    actual: dict[str, tuple[int, str | None, str, dict[str, int], list[int]]] = {}
    for show in load.shows:
        languages: dict[str, int] = {}
        for episode in show.episodes:
            languages[episode.language] = languages.get(episode.language, 0) + 1
        actual[show.slug] = (
            len(show.episodes),
            show.section,
            show.status,
            dict(sorted(languages.items())),
            sorted({e.season_number for e in show.episodes}),
        )
    assert actual == SHAPE


def test_only_two_shows_have_a_trailer_season(seed_path: Path, reference: Reference) -> None:
    load = load_seed(seed_path, reference)
    with_trailers = sorted(
        show.slug for show in load.shows if any(e.season_number == 0 for e in show.episodes)
    )
    assert with_trailers == ["motis-many-lives", "tiny-tales-banyan-dadi"]


def test_number_nest_has_six_published_and_two_draft_episodes(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    show = next(s for s in load.shows if s.slug == "number-nest")
    published = [e for e in show.episodes if e.status == "published"]
    assert (len(published), len(show.episodes) - len(published)) == (6, 2)


def test_two_different_shows_share_the_songs_section(seed_path: Path, reference: Reference) -> None:
    """A naive search for "peblo songs" will return both — noted, not a defect."""
    load = load_seed(seed_path, reference)
    songs = sorted(show.slug for show in load.shows if show.section == "songs")
    assert songs == ["peblo-songs", "peblo-songs-lyrical"]


def test_the_seed_uses_no_vocabulary_outside_reference_json(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    for show in load.shows:
        assert show.section is None or show.section in reference.sections
        assert all(category in reference.categories for category in show.categories)
        assert all(e.language in reference.languages for e in show.episodes)


def test_ep_0036_is_the_only_row_with_no_artwork_at_all(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    bare = sorted(
        e.ref
        for show in load.shows
        for e in show.episodes
        if not e.artwork_kinds and not show.artwork_kinds
    )
    assert bare == []
    without_thumbnail = sorted(
        e.ref for show in load.shows for e in show.episodes if not e.artwork_kinds
    )
    assert without_thumbnail == ["ep_0036"]


def test_each_trailer_season_holds_exactly_one_trailer_with_only_a_thumbnail(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    trailers = [e for show in load.shows for e in show.episodes if e.season_number == 0]
    assert sorted(e.ref for e in trailers) == ["ep_0093", "ep_0094"]
    assert all(e.artwork_kinds == frozenset({"thumbnail"}) for e in trailers)
    assert all(e.episode_number == 1 and e.title == "Trailer" for e in trailers)
    # Their shows still carry poster and banner, which is why they are not blockers.
    for show in load.shows:
        if any(e.season_number == 0 for e in show.episodes):
            assert show.artwork_kinds == frozenset({"poster", "banner"})


def test_no_content_group_is_shared_between_two_shows(
    seed_path: Path, reference: Reference
) -> None:
    load = load_seed(seed_path, reference)
    owners: dict[str, set[str]] = {}
    for show in load.shows:
        for episode in show.episodes:
            owners.setdefault(episode.content_group, set()).add(show.slug)
    assert [group for group, slugs in owners.items() if len(slugs) > 1] == []
    assert not [i for i in load.issues if i.code is IssueCode.CONTENT_GROUP_SPLIT]
