"""Serving stored artwork in local development.

With ``STORAGE_BACKEND=s3`` the bucket's own domain serves artwork and none of this
is registered. With the local backend the API serves it itself, so
``PUBLIC_MEDIA_BASE_URL`` resolves and the viewer UI can render real images.

Only the ``artwork/`` subtree is exposed. The storage root also holds the published
catalogue runs and the internal validation report; those are not public files, and
mounting the root would have handed them to anyone who asked.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.domain.artwork import ARTWORK_PREFIX
from app.storage import LocalDiskStorage, ObjectStorage

MEDIA_MOUNT = "/media"


def mount_local_media(app: FastAPI, storage: ObjectStorage) -> None:
    """Mount ``/media/artwork`` when the backend keeps bytes on this machine."""
    if not isinstance(storage, LocalDiskStorage):
        return

    artwork_root = storage.root / ARTWORK_PREFIX
    artwork_root.mkdir(parents=True, exist_ok=True)
    app.mount(
        f"{MEDIA_MOUNT}/{ARTWORK_PREFIX}",
        StaticFiles(directory=artwork_root),
        name="media-artwork",
    )
