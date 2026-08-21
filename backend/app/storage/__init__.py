"""Storage backends and the one factory that chooses between them."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import REPO_ROOT, Settings
from app.storage.base import ObjectNotFound, ObjectStorage, StorageError, StoredObject
from app.storage.local import LocalDiskStorage
from app.storage.postgres import PostgresStorage
from app.storage.s3 import S3CompatibleStorage

__all__ = [
    "LocalDiskStorage",
    "ObjectNotFound",
    "ObjectStorage",
    "PostgresStorage",
    "S3CompatibleStorage",
    "StorageError",
    "StoredObject",
    "build_storage",
]


def build_storage(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession] | None = None
) -> ObjectStorage:
    """The whole 'swap the backend' seam: one branch, driven by ``STORAGE_BACKEND``."""
    if settings.storage_backend == "postgres":
        if session_factory is None:
            raise ValueError("STORAGE_BACKEND=postgres needs a database session factory")
        return PostgresStorage(session_factory, settings.public_media_base_url)

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
