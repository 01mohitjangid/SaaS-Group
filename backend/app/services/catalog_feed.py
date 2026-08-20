"""Reading the live catalogue.

Kept apart from the publish job on purpose: this is the only thing the viewer needs,
and it touches no database. Routing it through `services/publish` would have made
`app/api/catalog.py` import SQLAlchemy transitively, which would quietly undermine the
one guarantee that module makes about itself.

Two reads, and no torn state: the pointer names an object that is never rewritten, so
the worst a concurrent publish can do is hand back the previous complete catalogue.
The parsed document is cached in-process against the pointer it came from — a published
run is immutable, so a cache hit cannot be stale, and a publish changes the pointer and
therefore the key.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.errors import ApiError
from app.storage import ObjectNotFound, ObjectStorage

#: One entry. The catalogue is a single document and only the newest one is ever served.
_cache: dict[str, dict[str, Any]] = {}


def _not_published() -> ApiError:
    return ApiError(
        status_code=503,
        code="catalog_not_published",
        message="Nothing has been published yet.",
    )


async def read_live_catalog(storage: ObjectStorage, settings: Settings) -> dict[str, Any]:
    try:
        pointer = json.loads(await storage.get(settings.catalog_pointer_key))
    except ObjectNotFound as exc:
        raise _not_published() from exc
    except ValueError as exc:
        raise ApiError(
            status_code=503,
            code="catalog_pointer_invalid",
            message="The published catalogue could not be read. Publish again.",
        ) from exc

    key = str(pointer.get("key", ""))
    if not key:
        raise ApiError(
            status_code=503,
            code="catalog_pointer_invalid",
            message="The published catalogue could not be read. Publish again.",
        )

    cached = _cache.get(key)
    if cached is not None:
        return cached

    try:
        document: dict[str, Any] = json.loads(await storage.get(key))
    except ObjectNotFound as exc:
        # The pointer names an object that is gone — storage was wiped, or the backend
        # was swapped without moving the objects. Say so rather than serving nothing.
        raise ApiError(
            status_code=503,
            code="catalog_object_missing",
            message="The published catalogue is not in storage. Publish again.",
        ) from exc

    _cache.clear()
    _cache[key] = document
    return document


def forget_cached_catalog() -> None:
    """Drop the cached document. Used by tests, and after a publish in the same process."""
    _cache.clear()
