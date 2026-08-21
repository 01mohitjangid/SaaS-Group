"""Serving stored artwork.

With ``STORAGE_BACKEND=s3`` and a public bucket domain, artwork is served by the bucket
and none of this is registered. Otherwise the API serves it itself so
``PUBLIC_MEDIA_BASE_URL`` resolves — from local disk in development, from Postgres in the
deployment.

Only the ``artwork/`` subtree is exposed. The same store holds the published catalogue
runs and the internal validation report; those are not public files, and serving the
whole store would have handed them to anyone who asked.

Artwork keys are content-addressed, so a URL's bytes can never change. That makes these
responses immutable and cacheable forever — which is most of what a CDN would have
bought us anyway.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from app.domain.artwork import ARTWORK_PREFIX, EXTENSIONS
from app.errors import NotFound
from app.storage import LocalDiskStorage, ObjectNotFound, ObjectStorage, PostgresStorage

MEDIA_MOUNT = "/media"

#: A published run object never changes and neither does a content-addressed image.
IMMUTABLE = "public, max-age=31536000, immutable"

_BY_SUFFIX = {suffix: content_type for content_type, suffix in EXTENSIONS.items()}

router = APIRouter(tags=["media"])


@router.get(f"{MEDIA_MOUNT}/{{key:path}}", summary="Serve stored artwork")
async def serve_media(key: str, request: Request) -> Response:
    storage: ObjectStorage = request.app.state.storage

    # Refuse anything outside artwork/ before touching storage: the catalogue and the
    # validation report live in the same store and are not public.
    if not key.startswith(f"{ARTWORK_PREFIX}/") or ".." in key:
        raise NotFound("image")

    try:
        data = await storage.get(key)
    except (ObjectNotFound, ValueError) as exc:
        raise NotFound("image") from exc

    content_type = _BY_SUFFIX.get(key.rsplit(".", 1)[-1].lower(), "application/octet-stream")
    if isinstance(storage, PostgresStorage):
        content_type = await storage.content_type_of(key) or content_type

    # The key already contains a hash of these bytes, so it is its own ETag.
    etag = f'"{key.rsplit("/", 1)[-1]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": IMMUTABLE})

    return Response(
        content=data,
        media_type=content_type,
        headers={"ETag": etag, "Cache-Control": IMMUTABLE},
    )


def mount_media(app: FastAPI, storage: ObjectStorage) -> None:
    """Serve artwork from whichever backend holds it.

    Local disk gets a real static mount because letting the ASGI server stream from the
    filesystem is strictly better than reading files into memory. Everything else goes
    through the route above.
    """
    if isinstance(storage, LocalDiskStorage):
        artwork_root = storage.root / ARTWORK_PREFIX
        artwork_root.mkdir(parents=True, exist_ok=True)
        app.mount(
            f"{MEDIA_MOUNT}/{ARTWORK_PREFIX}",
            StaticFiles(directory=artwork_root),
            name="media-artwork",
        )
        return

    app.include_router(router)
