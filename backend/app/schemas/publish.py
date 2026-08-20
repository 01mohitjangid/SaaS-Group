from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class IssueOut(BaseModel):
    code: str
    severity: str
    entity: str
    message: str
    fix_hint: str
    show_slug: str | None


class ValidationReport(BaseModel):
    """Grouped so an editor can work through it show by show without an engineer."""

    can_publish: bool
    blocker_count: int
    warning_count: int
    groups: list[ShowIssueGroup]


class ShowIssueGroup(BaseModel):
    show_slug: str | None
    show_title: str | None
    blockers: list[IssueOut]
    warnings: list[IssueOut]


class PublishRunOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    created_by_email: str
    catalog_key: str | None
    checksum_sha256: str | None
    counts: dict[str, int]
    blocker_count: int
    error: str | None
    rolled_back_to: str | None = None
    reused: bool = False


class PublishResult(BaseModel):
    run: PublishRunOut
    reused: bool
    warnings: list[IssueOut]


ValidationReport.model_rebuild()
