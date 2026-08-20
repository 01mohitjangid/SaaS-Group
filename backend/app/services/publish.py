"""The publish job.

**How it is atomic.** Nothing is ever written over the live catalogue. A run writes an
immutable object at ``catalog/runs/<run_id>.json`` and then flips a small pointer at
``catalog/current.json`` to name it. Writing a single object is atomic on local disk
(temp file + rename) and on R2 (one PUT), so a reader following the pointer sees either
the whole old catalogue or the whole new one — never a mix, and never a half-written
file, because the file it is reading was finished before the pointer named it.

**If the process dies mid-publish.** The ``running`` row is **committed before any work
starts** — that is what makes the rest of this true. Before the pointer flip, the old
catalogue is still live and the only debris is an unreferenced run object. After the
flip, the run already succeeded and only the bookkeeping row is stale. Either way there
is no window in which a reader sees something that never existed, and no window in which
a crash is invisible in the run history.

The dead run keeps holding the publish slot, though, and that has to be recoverable two
ways: automatically after ``STALE_RUN_AFTER``, and immediately via ``cancel_run`` — a
person who needs to publish a correction should not have to wait out a lease. Until one
of those happens, a further publish gets a 409 that names the stuck run and its age
rather than telling someone to "wait for it to finish".

**Concurrency.** ``uq_publish_runs_one_running`` is a partial unique index over a
*committed* row, so a second simultaneous publish is refused by Postgres with a 409
rather than queueing behind an open transaction.

**Idempotency.** The run records a digest of the catalogue's content. If a publish
produces the same digest as the last successful one, no new object is written and the
pointer is left alone — the run is recorded as succeeded and marked ``reused``.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import SERVICE_NAME
from app.config import Settings
from app.db.models import PublishRun, User
from app.db.projections import load_show_views
from app.domain.catalog import build_catalog, canonical_bytes, content_digest, to_payload
from app.domain.reference import Reference
from app.domain.rules import Issue, Severity, evaluate
from app.errors import ApiError, Conflict, NotFound
from app.services.catalog_feed import forget_cached_catalog
from app.storage import ObjectNotFound, ObjectStorage

logger = logging.getLogger(SERVICE_NAME)

#: A run still "in flight" after this long lost its process. Generous: a real publish
#: over this catalogue is milliseconds, but a slow storage backend should not be reaped.
STALE_RUN_AFTER = timedelta(minutes=15)
"""How long before an in-flight run is assumed dead.

This is a lease without fencing: a run slower than this would be reaped while still
alive, and could then still flip the pointer. Publishing this catalogue takes
milliseconds, so the window is theoretical — but it is a lease, not a lock, and at a
size where a publish took minutes it would need a fencing token. Meanwhile an admin does
not have to wait it out: `cancel_run` releases the slot immediately.
"""

CONTENT_TYPE = "application/json"


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    run_id: uuid.UUID
    status: str
    catalog_key: str
    checksum: str
    counts: dict[str, int]
    reused: bool
    warnings: list[Issue] = field(default_factory=list)


def _issue_payload(issue: Issue) -> dict[str, Any]:
    return {
        "code": issue.code.value,
        "severity": issue.severity.value,
        "entity": issue.entity,
        "message": issue.message,
        "fix_hint": issue.fix_hint,
        "show_slug": issue.show_slug,
    }


def run_key(settings: Settings, run_id: uuid.UUID) -> str:
    return f"{settings.catalog_run_key_prefix.rstrip('/')}/{run_id}.json"


async def reap_stale_runs(session: AsyncSession) -> int:
    """Fail runs whose process died, so a crash cannot block publishing forever.

    Committed on its own, because the whole point is that other transactions can then
    take the ``running`` slot.
    """
    cutoff = datetime.now(UTC) - STALE_RUN_AFTER
    result = await session.execute(
        update(PublishRun)
        .where(PublishRun.status == "running", PublishRun.started_at < cutoff)
        .values(
            status="failed",
            finished_at=datetime.now(UTC),
            error="The process running this publish stopped before it finished.",
        )
    )
    reaped = int(cast("CursorResult[Any]", result).rowcount or 0)
    await session.commit()
    return reaped


async def _last_successful(session: AsyncSession) -> PublishRun | None:
    return (
        await session.execute(
            select(PublishRun)
            .where(PublishRun.status == "succeeded")
            .order_by(PublishRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _start_run(session: AsyncSession, actor: User) -> PublishRun:
    """Claim the single ``running`` slot, and **commit** it.

    Committing here is load-bearing twice over. It makes a crash visible — a rolled-back
    row would leave no trace of the attempt at all — and it makes the partial unique
    index do its job: a competing publish conflicts with a committed row and is refused
    immediately, instead of blocking on an open transaction and then succeeding once
    this one finishes.
    """
    run = PublishRun(created_by_user_id=actor.id, created_by_email=actor.email, status="running")
    session.add(run)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise await _already_running(session) from exc
    return run


async def _already_running(session: AsyncSession) -> Conflict:
    """Explain *which* run holds the slot, and whether it is still plausibly alive.

    "Wait for that run to finish" is the wrong thing to tell someone about a run whose
    process died — so when the holder looks abandoned, say so and point at the way out.
    """
    holder = (
        await session.execute(select(PublishRun).where(PublishRun.status == "running").limit(1))
    ).scalar_one_or_none()
    if holder is None:  # pragma: no cover - the row disappeared between the two statements
        return Conflict(
            code="publish_already_running",
            message="Someone is publishing right now. Try again in a moment.",
            hint="Refresh the run history.",
        )

    age = datetime.now(UTC) - holder.started_at
    if age >= STALE_RUN_AFTER:  # pragma: no cover - reaped before we ever get here
        return Conflict(
            code="publish_already_running",
            message="A previous publish is still marked as running. Try again.",
            hint="It has been released; publishing again will pick up the slot.",
        )

    minutes_left = max(1, int((STALE_RUN_AFTER - age).total_seconds() // 60) + 1)
    return Conflict(
        code="publish_already_running",
        message=(
            f"{holder.created_by_email} started a publish "
            f"{int(age.total_seconds())}s ago and it has not finished."
        ),
        hint=(
            f"If that run has stopped, cancel it on the publish page — otherwise it is "
            f"released automatically in about {minutes_left} minute(s)."
        ),
    )


async def cancel_run(session: AsyncSession, run_id: uuid.UUID, *, actor: User) -> PublishRun:
    """Release a jammed publish slot without waiting out the lease.

    A crash between the ``running`` commit and the end of the run leaves the slot held
    for up to `STALE_RUN_AFTER`. That is fine for a machine and useless for a person who
    needs to publish a correction now.

    This marks the row failed; it does **not** stop anything. If the run were somehow
    still alive it would carry on and could still flip the pointer — see the note on
    `STALE_RUN_AFTER`. Both outcomes are complete, valid catalogues, so the exposure is
    "possibly the older build wins", not a corrupt read.
    """
    run = (
        await session.execute(select(PublishRun).where(PublishRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise NotFound("publish run")
    if run.status != "running":
        raise Conflict(
            code="run_not_running",
            message="That run has already finished, so there is nothing to cancel.",
            hint="Refresh the run history.",
        )
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.error = f"Cancelled by {actor.email}."
    await session.commit()
    return run


async def _live_catalog_key(storage: ObjectStorage, settings: Settings) -> str | None:
    """Which run object the live pointer names, or ``None`` if nothing is live."""
    try:
        pointer = json.loads(await storage.get(settings.catalog_pointer_key))
    except (ObjectNotFound, ValueError):
        return None
    key = pointer.get("key")
    return str(key) if key else None


async def _record_failure(session: AsyncSession, run: PublishRun, exc: BaseException) -> None:
    """Mark a run failed, without letting the bookkeeping hide what actually went wrong.

    If the database is the thing that broke, this commit fails too — and the original
    exception is the one worth propagating. The row is then left ``running`` and the
    reaper picks it up, which is exactly the case the reaper exists for.
    """
    try:
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = f"{type(exc).__name__}: {exc}"
        await session.commit()
    except Exception:
        logger.exception("could not record publish run %s as failed", run.id)
        # Even the rollback can fail on a dead connection, and none of this is worth
        # replacing the caller's real exception with.
        try:
            await session.rollback()
        except Exception:
            logger.exception("could not roll back after a failed publish run")


async def _write_pointer(
    storage: ObjectStorage, settings: Settings, *, run: PublishRun, key: str, checksum: str
) -> None:
    """The single atomic write that makes the new catalogue live."""
    body = canonical_bytes(
        {
            "run_id": str(run.id),
            "key": key,
            "checksum": checksum,
            "published_at": datetime.now(UTC).isoformat(),
        }
    )
    await storage.put(settings.catalog_pointer_key, body, CONTENT_TYPE)
    # The pointer moved, so anything this process had cached belongs to an older run.
    forget_cached_catalog()


async def publish_catalog(
    session: AsyncSession,
    storage: ObjectStorage,
    reference: Reference,
    settings: Settings,
    *,
    actor: User,
) -> PublishOutcome:
    await reap_stale_runs(session)
    run = await _start_run(session, actor)

    try:
        shows = await load_show_views(session)
        issues = evaluate(shows, reference)
        blockers = [i for i in issues if i.severity is Severity.BLOCKER]

        if blockers:
            run.status = "failed"
            run.finished_at = datetime.now(UTC)
            run.blocker_count = len(blockers)
            run.error = f"{len(blockers)} problem(s) must be fixed before publishing."
            await session.commit()
            raise ApiError(
                status_code=409,
                code="publish_blocked",
                message=(
                    f"{len(blockers)} problem(s) are blocking publishing. Fix them and try again."
                ),
                problems=[_issue_payload(i) for i in blockers],
            )

        catalog = build_catalog(shows, reference, storage.url_for)
        digest = content_digest(catalog)
        previous = await _last_successful(session)

        # "Nothing changed" is only true if the live pointer *still names* the previous
        # run. Existence is not enough: a rollback moves the pointer to an older key
        # while `_last_successful` still returns the newer run, and a bare exists() check
        # would then reuse a run that is not live — permanently, since every unchanged
        # publish after it would do the same. Asking storage what is actually live is the
        # only answer the database cannot fake.
        live_key = await _live_catalog_key(storage, settings)
        reusable = (
            previous is not None
            and previous.checksum_sha256 == digest
            and bool(previous.catalog_key)
            and live_key == previous.catalog_key
        )
        if reusable and previous is not None and previous.catalog_key:
            # Nothing changed. Leave storage and the live pointer completely alone.
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            run.catalog_key = previous.catalog_key
            run.checksum_sha256 = digest
            run.counts = dict(catalog.counts)
            run.error = None
            run.reused_previous_key = previous.catalog_key
            await session.commit()
            return PublishOutcome(
                run_id=run.id,
                status="succeeded",
                catalog_key=previous.catalog_key,
                checksum=digest,
                counts=dict(catalog.counts),
                reused=True,
                warnings=[i for i in issues if i.severity is Severity.WARNING],
            )

        key = run_key(settings, run.id)
        payload = to_payload(
            catalog, version=str(run.id), generated_at=datetime.now(UTC).isoformat()
        )
        await storage.put(key, canonical_bytes(payload), CONTENT_TYPE)
        await _write_pointer(storage, settings, run=run, key=key, checksum=digest)

        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.catalog_key = key
        run.checksum_sha256 = digest
        run.counts = dict(catalog.counts)
        await session.commit()

        return PublishOutcome(
            run_id=run.id,
            status="succeeded",
            catalog_key=key,
            checksum=digest,
            counts=dict(catalog.counts),
            reused=False,
            warnings=[i for i in issues if i.severity is Severity.WARNING],
        )

    except ApiError:
        raise
    except Exception as exc:
        # The pointer was never touched, so the previous catalogue is still live.
        await _record_failure(session, run, exc)
        raise


async def rollback_to(
    session: AsyncSession,
    storage: ObjectStorage,
    settings: Settings,
    *,
    actor: User,
    target_run_id: uuid.UUID,
) -> PublishOutcome:
    """Re-point the live catalogue at an earlier run.

    Cheap precisely because runs are immutable: the old bytes were never overwritten,
    so going back is the same single atomic pointer write as going forward.
    """
    target = (
        await session.execute(select(PublishRun).where(PublishRun.id == target_run_id))
    ).scalar_one_or_none()
    if target is None:
        raise NotFound("publish run")
    if target.status != "succeeded" or not target.catalog_key:
        raise Conflict(
            code="run_not_publishable",
            message="That run never produced a catalogue, so there is nothing to roll back to.",
            hint="Pick a run marked 'succeeded' in the history.",
        )
    if not await storage.exists(target.catalog_key):
        raise Conflict(
            code="run_object_missing",
            message="That run's catalogue file is no longer in storage.",
            hint="Pick a more recent run, or publish again.",
        )

    await reap_stale_runs(session)
    run = await _start_run(session, actor)
    try:
        await _write_pointer(
            storage,
            settings,
            run=run,
            key=target.catalog_key,
            checksum=target.checksum_sha256 or "",
        )
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.catalog_key = target.catalog_key
        run.checksum_sha256 = target.checksum_sha256
        run.counts = {k: v for k, v in target.counts.items() if isinstance(v, int)}
        run.rolled_back_to_run_id = target.id
        await session.commit()
    except Exception as exc:
        # Rollback is the path you reach *because* the live catalogue is already wrong.
        # It must not be the path that leaves the publish slot jammed as well.
        await _record_failure(session, run, exc)
        raise

    return PublishOutcome(
        run_id=run.id,
        status="succeeded",
        catalog_key=target.catalog_key,
        checksum=target.checksum_sha256 or "",
        counts=dict(target.counts),
        reused=True,
    )
