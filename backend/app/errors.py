"""Failures, with an explanation the CMS can show verbatim.

These live outside ``app/api`` on purpose: services raise them, and a service that has
to import the web layer to describe a conflict has the dependency arrow backwards.
Rendering them as HTTP is ``app.api.error_handlers``' job.

Every failure reaches the client in one shape::

    {"error": {
        "code": "...",
        "message": "...",
        "problems": [{"field": ..., "message": ..., "hint": ...}]
    }}

``message`` is the one-line summary a toast shows; ``problems`` is what the form renders
inline, next to the field that caused it.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from app.domain.reference import ArtworkProblem


class ApiError(Exception):
    """A failure with an explanation the CMS can show verbatim."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        problems: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.problems = problems or []

    def as_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "problems": self.problems}}


class NotFound(ApiError):
    def __init__(self, what: str) -> None:
        super().__init__(
            status_code=HTTPStatus.NOT_FOUND,
            code="not_found",
            message=f"That {what} does not exist, or was deleted by someone else.",
        )


class Conflict(ApiError):
    def __init__(self, code: str, message: str, hint: str) -> None:
        super().__init__(
            status_code=HTTPStatus.CONFLICT,
            code=code,
            message=message,
            problems=[{"field": None, "message": message, "hint": hint}],
        )


class ArtworkRejected(ApiError):
    def __init__(self, kind: str, problems: list[ArtworkProblem]) -> None:
        super().__init__(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="artwork_rejected",
            message=f"This {kind} cannot be used: {problems[0].message}",
            problems=[
                {"field": kind, "message": p.message, "hint": p.hint, "code": p.code}
                for p in problems
            ],
        )
