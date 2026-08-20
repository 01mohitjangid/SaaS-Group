"""What the viewer reads. No authentication, no database, and no admin data — ever.

Every route here reads the published catalogue and nothing else. That is not a
convention someone has to remember: there is no session dependency in this module, so
the viewer *cannot* reach unpublished content or admin tables even by mistake.

Nothing in this module's own imports reaches SQLAlchemy or ``app.db`` —
``test_layering.py`` asserts it — so the guarantee is structural rather than a habit.

``GET /catalog`` follows a pointer to the immutable object it names, so the home page is
one document whatever the catalogue contains, and it can never show half-edited content.
``GET /catalog/search`` filters that same document, which is what keeps a search result
and its detail page in agreement. The scale ceiling that puts on search is discussed in
``app.domain.search`` and in the README.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import SettingsDep, StorageDep
from app.domain.search import search_document
from app.errors import ApiError, NotFound
from app.services.catalog_feed import read_live_catalog

router = APIRouter(tags=["viewer"])


def _etag(document: dict[str, Any]) -> str:
    """The run id already identifies the bytes exactly — runs are immutable."""
    return '"' + hashlib.sha1(str(document.get("version", "")).encode()).hexdigest() + '"'


@router.get("/catalog", summary="The published catalogue the viewer reads")
async def get_catalog(
    request: Request, response: Response, storage: StorageDep, settings: SettingsDep
) -> Any:
    document = await read_live_catalog(storage, settings)
    etag = _etag(document)
    # A published run never changes, so a client that already has this version can be
    # told so in a few bytes instead of the whole catalogue.
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=60"
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=dict(response.headers))
    return document


async def _live_or_none(storage: StorageDep, settings: SettingsDep) -> dict[str, Any] | None:
    """Search works before the first publish — it just has nothing to find."""
    try:
        return await read_live_catalog(storage, settings)
    except ApiError:
        return None


@router.get("/catalog/search", summary="Search and filter the published catalogue")
async def search_catalog(
    storage: StorageDep,
    settings: SettingsDep,
    q: Annotated[
        str | None,
        Query(max_length=120, description="Matches show title, episode title or category"),
    ] = None,
    category: Annotated[str | None, Query()] = None,
    language: Annotated[str | None, Query()] = None,
    section: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    document = await _live_or_none(storage, settings)
    page = search_document(
        document or {"sections": []},
        q=q,
        category=category,
        language=language,
        section=section,
        limit=limit,
        offset=offset,
    )
    term = (q or "").strip()
    return {
        "query": {
            "q": term or None,
            "category": category,
            "language": language,
            "section": section,
        },
        "catalog_version": (document or {}).get("version"),
        "total": page.total,
        "limit": page.limit,
        "offset": page.offset,
        "results": page.results,
    }


@router.get("/catalog/shows/{slug}", summary="One show, as published")
async def get_catalog_show(slug: str, storage: StorageDep, settings: SettingsDep) -> dict[str, Any]:
    catalog = await read_live_catalog(storage, settings)
    for section in catalog.get("sections", []):
        for show in section.get("shows", []):
            if show.get("slug") == slug:
                return {"section": section["key"], **show}
    raise NotFound("show")
