"""Storage backends and the one factory that chooses between them."""

from __future__ import annotations

from pathlib import Path

from app.config import REPO_ROOT, Settings
from app.storage.base import ObjectNotFound, ObjectStorage, StorageError, StoredObject
from app.storage.local import LocalDiskStorage
from app.storage.s3 import S3CompatibleStorage

__all__ = [
    "LocalDiskStorage",
    "ObjectNotFound",
    "ObjectStorage",
    "S3CompatibleStorage",
    "StorageError",
    "StoredObject",
    "build_storage",
]


def build_storage(settings: Settings) -> ObjectStorage:
    """The whole 'swap to R2' seam: one branch, driven by ``STORAGE_BACKEND``."""
    if settings.storage_backend == "local":
        # A relative root is resolved against the repo, not the working directory, so
        # `make seed` (which runs in backend/) and the tests agree on one location.
        root = Path(settings.storage_local_root)
        return LocalDiskStorage(
            root=root if root.is_absolute() else (REPO_ROOT / root).resolve(),
            public_base_url=settings.public_media_base_url,
        )

    if not settings.s3_bucket:
        raise ValueError("S3_BUCKET must be set when STORAGE_BACKEND=s3")

    return S3CompatibleStorage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key_id=(
            settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
        ),
        secret_access_key=(
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None
        ),
        public_base_url=settings.s3_public_base_url,
    )
