"""The publish gate.

Every rule that can block or warn about publishing lives here, expressed over plain
read-only views. Both the seed loader and (in the next step) the DB-backed
``GET /admin/validation-report`` feed the same function, so an editor can never be
told two different stories about the same content.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.reference import TRAILER_SEASON, ArtworkKind, Reference

#: Artwork each surface needs. Shows fill the hero and the browse rows; episodes
#: fill the episode list. A trailer therefore needs only a thumbnail.
SHOW_REQUIRED_ARTWORK: frozenset[str] = frozenset({ArtworkKind.POSTER, ArtworkKind.BANNER})
EPISODE_REQUIRED_ARTWORK: frozenset[str] = frozenset({ArtworkKind.THUMBNAIL})

PUBLISHED = "published"


class Severity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"


class IssueCode(StrEnum):
    SHOW_MISSING_SECTION = "show.missing_section"
    SHOW_UNKNOWN_SECTION = "show.unknown_section"
    SHOW_UNKNOWN_CATEGORY = "show.unknown_category"
    SHOW_MISSING_ARTWORK = "show.missing_artwork"
    SHOW_NO_PUBLISHABLE_EPISODES = "show.no_publishable_episodes"
    CONTENT_GROUP_SPLIT = "content_group.split"
    EPISODE_MISSING_ARTWORK = "episode.missing_artwork"
    EPISODE_MISSING_DURATION = "episode.missing_duration"
    EPISODE_UNKNOWN_LANGUAGE = "episode.unknown_language"
    EPISODE_TITLE_CASING = "episode.title_casing"
    DUPLICATE_VARIANT = "content_group.duplicate_variant"
    VARIANT_TITLE_MISMATCH = "content_group.variant_title_mismatch"


_SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.WARNING: 1}


@dataclass(frozen=True, slots=True)
class Issue:
    code: IssueCode
    severity: Severity
    entity: str
    message: str
    fix_hint: str
    show_slug: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeView:
    #: Stable handle the CMS can deep-link to. The seed loader passes the source
    #: `episode_id`; the API passes the database id, because CMS-created episodes
    #: have no external id at all.
    ref: str
    show_slug: str
    season_number: int
    episode_number: int
    title: str
    duration_seconds: int | None
    language: str
    content_group: str
    status: str
    artwork_kinds: frozenset[str]
    #: kind -> storage key. Empty for the rules engine, populated by the DB projection
    #: so the catalogue builder can turn them into URLs without a second query.
    artwork_keys: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_trailer(self) -> bool:
        return self.season_number == TRAILER_SEASON

    @property
    def is_published(self) -> bool:
        return self.status == PUBLISHED


@dataclass(frozen=True, slots=True)
class ShowView:
    slug: str
    title: str
    synopsis: str
    section: str | None
    categories: tuple[str, ...]
    status: str
    artwork_kinds: frozenset[str]
    artwork_keys: Mapping[str, str] = field(default_factory=dict)
    episodes: list[EpisodeView] = field(default_factory=list)

    @property
    def is_published(self) -> bool:
        return self.status == PUBLISHED


def _looks_untitled(title: str) -> bool:
    """A title an editor pasted without fixing: untrimmed, or entirely lower-case."""
    if title != title.strip():
        return True
    letters = [c for c in title if c.isalpha()]
    return bool(letters) and all(c.islower() for c in letters)


def _severity(published: bool) -> Severity:
    return Severity.BLOCKER if published else Severity.WARNING


def check_show(show: ShowView, reference: Reference) -> list[Issue]:
    """Every issue for one show, including issues about the episodes it carries.

    Public so CRUD can validate a single row on save. Pass the show's real episodes —
    a `ShowView` built with an empty episode list will report
    `SHOW_NO_PUBLISHABLE_EPISODES`, which is correct for a real empty show and
    misleading for a partially-built one.
    """
    return list(_check_show(show, reference))


def check_episode(episode: EpisodeView, reference: Reference) -> list[Issue]:
    """Every issue for one episode. Public so CRUD can validate a single row on save."""
    return list(_check_episode(episode, reference))


def _check_show(show: ShowView, reference: Reference) -> Iterable[Issue]:
    if show.section is None:
        yield Issue(
            code=IssueCode.SHOW_MISSING_SECTION,
            severity=_severity(show.is_published),
            entity=f"show:{show.slug}",
            message=f"“{show.title}” has no section, so there is no row to show it in.",
            fix_hint=f"Pick one of: {', '.join(reference.sections)}.",
            show_slug=show.slug,
        )
    elif not reference.is_section(show.section):
        yield Issue(
            code=IssueCode.SHOW_UNKNOWN_SECTION,
            severity=_severity(show.is_published),
            entity=f"show:{show.slug}",
            message=f"“{show.title}” is in section “{show.section}”, which does not exist.",
            fix_hint=f"Pick one of: {', '.join(reference.sections)}.",
            show_slug=show.slug,
        )

    unknown = [c for c in show.categories if not reference.is_category(c)]
    if unknown:
        yield Issue(
            code=IssueCode.SHOW_UNKNOWN_CATEGORY,
            severity=Severity.WARNING,
            entity=f"show:{show.slug}",
            message=(
                f"“{show.title}” uses {'categories' if len(unknown) > 1 else 'the category'} "
                f"{', '.join(repr(c) for c in unknown)}, which viewers cannot filter by."
            ),
            fix_hint="Remove them or ask an admin to add them to the category list.",
            show_slug=show.slug,
        )

    if show.is_published:
        missing = sorted(SHOW_REQUIRED_ARTWORK - show.artwork_kinds)
        if missing:
            yield Issue(
                code=IssueCode.SHOW_MISSING_ARTWORK,
                severity=Severity.BLOCKER,
                entity=f"show:{show.slug}",
                message=f"“{show.title}” is missing its {' and '.join(missing)} artwork.",
                fix_hint="Upload the missing sizes on the show's edit page.",
                show_slug=show.slug,
            )

        if not any(e.is_published and not e.is_trailer for e in show.episodes):
            yield Issue(
                code=IssueCode.SHOW_NO_PUBLISHABLE_EPISODES,
                severity=Severity.WARNING,
                entity=f"show:{show.slug}",
                message=f"“{show.title}” has no published episodes, so its row will be empty.",
                fix_hint="Publish at least one episode outside Season 0 (trailers).",
                show_slug=show.slug,
            )


def _check_episode(episode: EpisodeView, reference: Reference) -> Iterable[Issue]:
    label = f"{episode.show_slug} S{episode.season_number}E{episode.episode_number}"

    if episode.is_published:
        missing = sorted(EPISODE_REQUIRED_ARTWORK - episode.artwork_kinds)
        if missing:
            yield Issue(
                code=IssueCode.EPISODE_MISSING_ARTWORK,
                severity=Severity.BLOCKER,
                entity=f"episode:{episode.ref}",
                message=f"“{episode.title}” ({label}) has no {' or '.join(missing)} image.",
                fix_hint="Upload a 640×360 thumbnail on the episode's edit page.",
                show_slug=episode.show_slug,
            )

        if episode.duration_seconds is None or episode.duration_seconds <= 0:
            yield Issue(
                code=IssueCode.EPISODE_MISSING_DURATION,
                severity=Severity.BLOCKER,
                entity=f"episode:{episode.ref}",
                message=f"“{episode.title}” ({label}) has no run time.",
                fix_hint="Enter the length in minutes and seconds on the episode's edit page.",
                show_slug=episode.show_slug,
            )

    if not reference.is_language(episode.language):
        yield Issue(
            code=IssueCode.EPISODE_UNKNOWN_LANGUAGE,
            severity=_severity(episode.is_published),
            entity=f"episode:{episode.ref}",
            message=(
                f"“{episode.title}” ({label}) is in “{episode.language}”, which we do not ship."
            ),
            fix_hint=f"Pick one of: {', '.join(reference.languages)}.",
            show_slug=episode.show_slug,
        )

    if _looks_untitled(episode.title):
        yield Issue(
            code=IssueCode.EPISODE_TITLE_CASING,
            severity=Severity.WARNING,
            entity=f"episode:{episode.ref}",
            message=f"“{episode.title}” ({label}) is not capitalised the way viewers expect.",
            fix_hint="Use title case, for example “Rain on the Roof”.",
            show_slug=episode.show_slug,
        )


def _check_content_groups(episodes: Sequence[EpisodeView]) -> Iterable[Issue]:
    """Cross-row rules — these need the whole catalogue, not one entity."""
    groups: dict[str, list[EpisodeView]] = defaultdict(list)
    for episode in episodes:
        groups[episode.content_group].append(episode)

    for group, members in sorted(groups.items()):
        if len(members) < 2:
            continue

        by_language: dict[str, list[EpisodeView]] = defaultdict(list)
        for episode in members:
            by_language[episode.language].append(episode)

        for language, clashing in sorted(by_language.items()):
            if len(clashing) < 2:
                continue
            ids = sorted(e.ref for e in clashing)
            yield Issue(
                code=IssueCode.DUPLICATE_VARIANT,
                severity=Severity.BLOCKER,
                entity=f"content_group:{group}",
                message=(
                    f"{len(ids)} episodes claim to be the {language} version of "
                    f"“{group}”: {', '.join(ids)}. Only one can be."
                ),
                fix_hint="Delete the duplicate, or move it to its own content group.",
                show_slug=members[0].show_slug,
            )

        # A content group is one episode. Publishing collapses it within a single
        # season of a single show, so a group whose members are spread across seasons or
        # shows does not merge — it silently splits into two half-language entries.
        homes = {(e.show_slug, e.season_number) for e in members}
        if len(homes) > 1:
            where = ", ".join(f"{slug} season {number}" for slug, number in sorted(homes))
            yield Issue(
                code=IssueCode.CONTENT_GROUP_SPLIT,
                severity=_severity(any(e.is_published for e in members)),
                entity=f"content_group:{group}",
                message=(
                    f"The language versions of “{group}” are filed in different places "
                    f"({where}), so they will appear as separate episodes."
                ),
                fix_hint="Put every language version in the same show and season.",
                show_slug=sorted(homes)[0][0],
            )

        titles = {e.title for e in members}
        if len(titles) > 1:
            yield Issue(
                code=IssueCode.VARIANT_TITLE_MISMATCH,
                severity=Severity.WARNING,
                entity=f"content_group:{group}",
                message=(
                    f"The language versions of “{group}” have different titles: "
                    f"{', '.join(sorted(repr(t) for t in titles))}."
                ),
                fix_hint="Make every language version use the same episode title.",
                show_slug=members[0].show_slug,
            )


def evaluate(shows: Sequence[ShowView], reference: Reference) -> list[Issue]:
    """Every issue in the catalogue, blockers first, in a stable order."""
    issues: list[Issue] = []
    all_episodes: list[EpisodeView] = []

    for show in shows:
        issues.extend(_check_show(show, reference))
        for episode in show.episodes:
            issues.extend(_check_episode(episode, reference))
            all_episodes.append(episode)

    issues.extend(_check_content_groups(all_episodes))

    return sorted(issues, key=lambda i: (_SEVERITY_ORDER[i.severity], i.code.value, i.entity))


def blockers(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity is Severity.BLOCKER]
