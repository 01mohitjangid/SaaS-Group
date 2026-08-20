"""Publishing, the validation report and run history.

Publishing is `admin` only; the report and the history are readable by any editor,
because an editor's whole job here is fixing what the report lists.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import AdminUser, EditorUser, ReferenceDep, SessionDep, SettingsDep, StorageDep
from app.db.models import PublishRun
from app.db.projections import load_show_views
from app.domain.rules import Issue, Severity, evaluate
from app.schemas.publish import (
    IssueOut,
    PublishResult,
    PublishRunOut,
    ShowIssueGroup,
    ValidationReport,
)
from app.services.publish import cancel_run, publish_catalog, rollback_to

router = APIRouter(prefix="/admin", tags=["admin"])


def _issue_out(issue: Issue) -> IssueOut:
    return IssueOut(
        code=issue.code.value,
        severity=issue.severity.value,
        entity=issue.entity,
        message=issue.message,
        fix_hint=issue.fix_hint,
        show_slug=issue.show_slug,
    )


def _run_out(run: PublishRun) -> PublishRunOut:
    return PublishRunOut(
        id=run.id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_by_email=run.created_by_email,
        catalog_key=run.catalog_key,
        checksum_sha256=run.checksum_sha256,
        counts={k: int(v) for k, v in run.counts.items() if isinstance(v, int | float)},
        blocker_count=run.blocker_count,
        error=run.error,
        # A reuse and a rollback both look like an ordinary success without these.
        rolled_back_to=str(run.rolled_back_to_run_id) if run.rolled_back_to_run_id else None,
        reused=run.reused_previous_key is not None,
    )


@router.get(
    "/validation-report",
    response_model=ValidationReport,
    summary="Everything currently blocking publish, grouped by show",
)
async def validation_report(
    session: SessionDep, reference: ReferenceDep, _: EditorUser
) -> ValidationReport:
    shows = await load_show_views(session)
    titles = {show.slug: show.title for show in shows}
    issues = evaluate(shows, reference)

    grouped: dict[str | None, list[Issue]] = defaultdict(list)
    for issue in issues:
        grouped[issue.show_slug].append(issue)

    groups = [
        ShowIssueGroup(
            show_slug=slug,
            show_title=titles.get(slug or ""),
            blockers=[_issue_out(i) for i in items if i.severity is Severity.BLOCKER],
            warnings=[_issue_out(i) for i in items if i.severity is Severity.WARNING],
        )
        # None sorts first: issues that belong to no single show are everyone's problem.
        for slug, items in sorted(grouped.items(), key=lambda kv: (kv[0] is not None, kv[0] or ""))
    ]

    blockers = sum(len(g.blockers) for g in groups)
    return ValidationReport(
        can_publish=blockers == 0,
        blocker_count=blockers,
        warning_count=sum(len(g.warnings) for g in groups),
        groups=groups,
    )


@router.post(
    "/catalog/publish",
    response_model=PublishResult,
    status_code=status.HTTP_201_CREATED,
    summary="Build the catalogue and make it live (admin only)",
)
async def publish(
    session: SessionDep,
    storage: StorageDep,
    reference: ReferenceDep,
    settings: SettingsDep,
    actor: AdminUser,
) -> PublishResult:
    outcome = await publish_catalog(session, storage, reference, settings, actor=actor)
    run = await session.get(PublishRun, outcome.run_id)
    assert run is not None
    return PublishResult(
        run=_run_out(run),
        reused=outcome.reused,
        warnings=[_issue_out(i) for i in outcome.warnings],
    )


@router.post(
    "/catalog/rollback/{run_id}",
    response_model=PublishResult,
    summary="Point the live catalogue back at an earlier run (admin only)",
)
async def rollback(
    run_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    actor: AdminUser,
) -> PublishResult:
    outcome = await rollback_to(session, storage, settings, actor=actor, target_run_id=run_id)
    run = await session.get(PublishRun, outcome.run_id)
    assert run is not None
    out = _run_out(run)
    return PublishResult(run=out, reused=out.reused, warnings=[])


@router.post(
    "/publish-runs/{run_id}/cancel",
    response_model=PublishRunOut,
    summary="Release a publish slot held by a run that stopped (admin only)",
)
async def cancel_publish_run(
    run_id: uuid.UUID, session: SessionDep, actor: AdminUser
) -> PublishRunOut:
    return _run_out(await cancel_run(session, run_id, actor=actor))


@router.get("/publish-runs", response_model=list[PublishRunOut], summary="Run history")
async def publish_runs(
    session: SessionDep,
    _: EditorUser,
    limit: int = Query(20, ge=1, le=100),
) -> list[PublishRunOut]:
    # Deliberately read-only: reaping happens when a publish is attempted, not when
    # someone looks at the history. A stale `running` row is shown as it is.
    rows = (
        await session.execute(
            select(PublishRun).order_by(PublishRun.started_at.desc()).limit(limit)
        )
    ).scalars()
    return [_run_out(run) for run in rows]
