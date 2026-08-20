from __future__ import annotations

from app.domain.reference import Reference
from app.domain.rules import EpisodeView, IssueCode, Severity, ShowView, blockers, evaluate


def _episode(**overrides: object) -> EpisodeView:
    base: dict[str, object] = {
        "ref": "ep_0001",
        "show_slug": "a-show",
        "season_number": 1,
        "episode_number": 1,
        "title": "An Episode",
        "duration_seconds": 500,
        "language": "en",
        "content_group": "a-show-s01e01",
        "status": "published",
        "artwork_kinds": frozenset({"thumbnail"}),
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
        "episodes": episodes if episodes is not None else [_episode()],
    }
    base.update(overrides)
    return ShowView(**base)  # type: ignore[arg-type]


def _codes(shows: list[ShowView], reference: Reference) -> list[IssueCode]:
    return [issue.code for issue in evaluate(shows, reference)]


def test_a_clean_show_produces_no_issues(reference: Reference) -> None:
    assert evaluate([_show()], reference) == []


def test_published_episode_without_artwork_blocks_publish(reference: Reference) -> None:
    shows = [_show([_episode(artwork_kinds=frozenset())])]
    (issue,) = evaluate(shows, reference)
    assert issue.code is IssueCode.EPISODE_MISSING_ARTWORK
    assert issue.severity is Severity.BLOCKER
    assert issue.entity == "episode:ep_0001"
    assert "thumbnail" in issue.message


def test_draft_episode_without_artwork_is_not_a_blocker(reference: Reference) -> None:
    """Editors work on drafts all day; only publishing has to be clean."""
    shows = [_show([_episode(status="draft", artwork_kinds=frozenset())])]
    assert blockers(evaluate(shows, reference)) == []


def test_published_episode_without_duration_blocks_publish(reference: Reference) -> None:
    for bad in (None, 0, -5):
        shows = [_show([_episode(duration_seconds=bad)])]
        assert IssueCode.EPISODE_MISSING_DURATION in _codes(shows, reference)


def test_published_show_without_section_blocks_publish(reference: Reference) -> None:
    (issue,) = evaluate([_show(section=None)], reference)
    assert issue.code is IssueCode.SHOW_MISSING_SECTION
    assert issue.severity is Severity.BLOCKER


def test_draft_show_without_section_is_only_a_warning(reference: Reference) -> None:
    shows = [_show(status="draft", section=None, episodes=[_episode(status="draft")])]
    (issue,) = evaluate(shows, reference)
    assert issue.code is IssueCode.SHOW_MISSING_SECTION
    assert issue.severity is Severity.WARNING


def test_duplicate_content_group_and_language_blocks_publish(reference: Reference) -> None:
    shows = [
        _show(
            [
                _episode(ref="ep_a", language="hi"),
                _episode(ref="ep_b", language="hi"),
            ]
        )
    ]
    issues = [i for i in evaluate(shows, reference) if i.code is IssueCode.DUPLICATE_VARIANT]
    assert len(issues) == 1
    assert issues[0].severity is Severity.BLOCKER
    assert "ep_a" in issues[0].message and "ep_b" in issues[0].message


def test_the_same_content_group_in_two_languages_is_fine(reference: Reference) -> None:
    shows = [
        _show(
            [
                _episode(ref="ep_a", language="en"),
                _episode(ref="ep_b", language="hi"),
            ]
        )
    ]
    assert evaluate(shows, reference) == []


def test_unknown_vocabulary_values_are_reported(reference: Reference) -> None:
    shows = [_show(section="carousel", categories=("adventure", "dinosaurs"))]
    codes = _codes(shows, reference)
    assert IssueCode.SHOW_UNKNOWN_SECTION in codes
    assert IssueCode.SHOW_UNKNOWN_CATEGORY in codes

    shows = [_show([_episode(language="fr")])]
    assert IssueCode.EPISODE_UNKNOWN_LANGUAGE in _codes(shows, reference)


def test_published_show_needs_poster_and_banner(reference: Reference) -> None:
    shows = [_show(artwork_kinds=frozenset({"poster"}))]
    (issue,) = evaluate(shows, reference)
    assert issue.code is IssueCode.SHOW_MISSING_ARTWORK
    assert "banner" in issue.message


def test_trailer_only_show_has_no_publishable_episodes(reference: Reference) -> None:
    shows = [_show([_episode(season_number=0, episode_number=1, title="Trailer")])]
    assert IssueCode.SHOW_NO_PUBLISHABLE_EPISODES in _codes(shows, reference)


def test_language_variants_with_different_titles_warn(reference: Reference) -> None:
    shows = [
        _show(
            [
                _episode(ref="ep_a", language="en", title="Rain on the Roof"),
                _episode(ref="ep_b", language="hi", title="The Lost Kite (v2)"),
            ]
        )
    ]
    issues = [i for i in evaluate(shows, reference) if i.code is IssueCode.VARIANT_TITLE_MISMATCH]
    assert len(issues) == 1
    assert issues[0].severity is Severity.WARNING


def test_lowercase_title_warns(reference: Reference) -> None:
    shows = [_show([_episode(title="rain on the roof")])]
    codes = _codes(shows, reference)
    assert IssueCode.EPISODE_TITLE_CASING in codes
    assert all(
        i.severity is Severity.WARNING
        for i in evaluate(shows, reference)
        if i.code is IssueCode.EPISODE_TITLE_CASING
    )


def test_issues_are_ordered_deterministically(reference: Reference) -> None:
    shows = [
        _show(
            section=None,
            artwork_kinds=frozenset(),
            episodes=[
                _episode(ref="ep_z", title="lower case", duration_seconds=None),
                _episode(ref="ep_a", artwork_kinds=frozenset(), language="fr"),
            ],
        )
    ]
    first = evaluate(shows, reference)
    second = evaluate(shows, reference)
    assert first == second
    severities = [i.severity for i in first]
    assert severities == sorted(severities, key=lambda s: 0 if s is Severity.BLOCKER else 1)


def test_blockers_property_is_the_publish_gate(reference: Reference) -> None:
    shows = [_show([_episode(title="lower case")])]
    assert blockers(evaluate(shows, reference)) == []

    shows = [_show([_episode(artwork_kinds=frozenset())])]
    assert len(blockers(evaluate(shows, reference))) == 1


def test_a_content_group_used_by_two_shows_blocks_publish(reference: Reference) -> None:
    """Publishing collapses a group into one entry, so a shared group would merge shows."""
    shared = "shared-group-s01e01"
    shows = [
        _show(slug="show-a", episodes=[_episode(show_slug="show-a", content_group=shared)]),
        _show(
            slug="show-b",
            episodes=[
                _episode(ref="ep_b", show_slug="show-b", language="hi", content_group=shared)
            ],
        ),
    ]
    issues = [i for i in evaluate(shows, reference) if i.code is IssueCode.CONTENT_GROUP_SPLIT]
    assert len(issues) == 1
    assert issues[0].severity is Severity.BLOCKER
    assert "show-a" in issues[0].message and "show-b" in issues[0].message


def test_single_entity_checks_return_lists_not_generators(reference: Reference) -> None:
    """CRUD will call these per row and test the result for truthiness."""
    from app.domain.rules import check_episode, check_show

    clean = check_show(_show(), reference)
    assert isinstance(clean, list)
    assert not clean

    broken = check_episode(_episode(artwork_kinds=frozenset()), reference)
    assert isinstance(broken, list)
    assert [i.code for i in broken] == [IssueCode.EPISODE_MISSING_ARTWORK]


def test_a_shared_content_group_only_warns_while_everything_is_a_draft(
    reference: Reference,
) -> None:
    """Nothing can merge at publish time if nothing is published."""
    shared = "shared-group-s01e01"
    shows = [
        _show(
            slug="show-a",
            status="draft",
            episodes=[_episode(show_slug="show-a", status="draft", content_group=shared)],
        ),
        _show(
            slug="show-b",
            status="draft",
            episodes=[
                _episode(
                    ref="ep_b",
                    show_slug="show-b",
                    status="draft",
                    language="hi",
                    content_group=shared,
                )
            ],
        ),
    ]
    issues = [i for i in evaluate(shows, reference) if i.code is IssueCode.CONTENT_GROUP_SPLIT]
    assert len(issues) == 1
    assert issues[0].severity is Severity.WARNING
    assert not blockers(evaluate(shows, reference))


def test_language_versions_in_different_seasons_are_reported(reference: Reference) -> None:
    """The catalogue collapses within one season, so a split group becomes two entries.

    This was silent: the rule only looked across shows, and the builder groups per
    season, so an English S1E1 with its Hindi sibling filed under S2 shipped as two
    single-language episodes with nothing flagged.
    """
    shared = "a-show-s01e01"
    shows = [
        _show(
            episodes=[
                _episode(ref="ep_en", season_number=1, content_group=shared),
                _episode(ref="ep_hi", season_number=2, language="hi", content_group=shared),
            ]
        )
    ]
    issues = [i for i in evaluate(shows, reference) if i.code is IssueCode.CONTENT_GROUP_SPLIT]
    assert len(issues) == 1
    assert issues[0].severity is Severity.BLOCKER
    assert "season 1" in issues[0].message and "season 2" in issues[0].message


def test_a_trailer_sharing_a_content_group_with_an_episode_is_reported(
    reference: Reference,
) -> None:
    shows = [
        _show(
            episodes=[
                _episode(ref="ep_1", season_number=1, content_group="cg"),
                _episode(ref="ep_t", season_number=0, language="hi", content_group="cg"),
            ]
        )
    ]
    assert IssueCode.CONTENT_GROUP_SPLIT in _codes(shows, reference)


def test_language_versions_in_the_same_season_are_fine(reference: Reference) -> None:
    shows = [
        _show(
            episodes=[
                _episode(ref="ep_en", content_group="cg"),
                _episode(ref="ep_hi", language="hi", content_group="cg"),
            ]
        )
    ]
    assert not [i for i in evaluate(shows, reference) if i.code is IssueCode.CONTENT_GROUP_SPLIT]
