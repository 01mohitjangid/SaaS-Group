"""Uploading artwork: validate hard, explain gently, store behind the abstraction.

Validation happens **here**, on real decoded pixels — not in the browser, and not on
the file name. The CMS shows the same rules next to each slot so an editor is not
surprised, but the browser is never the thing enforcing them.

Replacing a poster with a different file format changes its key (the extension is part
of it), so the previous object is deleted after the row is repointed. Doing it in that
order means a crash leaves an orphaned file, not a database row pointing at nothing.
"""

from __future__ import annotations

import hashlib
import io
import uuid

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Artwork, Episode, Show
from app.domain.artwork import EXTENSIONS, episode_key, show_key, version_of
from app.domain.reference import ArtworkKind, ArtworkProblem, Reference
from app.domain.rules import EPISODE_REQUIRED_ARTWORK, SHOW_REQUIRED_ARTWORK
from app.errors import ApiError, ArtworkRejected, Conflict
from app.storage import ObjectStorage

#: Refused before decoding. The real ceiling is 200 KB per the specs; this only stops
#: someone streaming a 4 GB file into memory to find that out.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

PILLOW_CONTENT_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def _decode(data: bytes, kind: ArtworkKind) -> tuple[int, int, str]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format or ""
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ArtworkRejected(
            kind.value,
            [
                ArtworkProblem(
                    code="artwork.unreadable",
                    message="This file is not an image we can read.",
                    hint="Export it as a JPEG or PNG and upload it again.",
                )
            ],
        ) from exc

    content_type = PILLOW_CONTENT_TYPES.get(image_format, "")
    if content_type not in EXTENSIONS:
        raise ArtworkRejected(
            kind.value,
            [
                ArtworkProblem(
                    code="artwork.wrong_format",
                    message=f"This is a {image_format or 'unknown'} file, which we do not store.",
                    hint="Save it as a JPEG, PNG or WebP and upload it again.",
                )
            ],
        )
    return width, height, content_type


def _check_owner(kind: ArtworkKind, *, for_episode: bool) -> None:
    """Posters and banners describe a show; thumbnails describe an episode."""
    allowed = EPISODE_REQUIRED_ARTWORK if for_episode else SHOW_REQUIRED_ARTWORK
    if kind.value not in allowed:
        surface = "an episode" if for_episode else "a show"
        wanted = "a thumbnail" if for_episode else "a poster or a banner"
        raise Conflict(
            code="artwork_wrong_surface",
            message=f"A {kind.value} does not belong to {surface}.",
            hint=f"Upload {wanted} here instead.",
        )


async def store_artwork(
    session: AsyncSession,
    storage: ObjectStorage,
    reference: Reference,
    *,
    kind: ArtworkKind,
    data: bytes,
    show: Show | None = None,
    episode: Episode | None = None,
) -> Artwork:
    if (show is None) == (episode is None):
        raise ValueError("artwork belongs to exactly one of a show or an episode")

    if len(data) > MAX_UPLOAD_BYTES:
        raise ArtworkRejected(
            kind.value,
            [
                ArtworkProblem(
                    code="artwork.too_large",
                    message=(
                        f"This file is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB, "
                        f"which is far too big."
                    ),
                    hint=f"The limit is {reference.artwork[kind].max_bytes // 1024} KB.",
                )
            ],
        )

    _check_owner(kind, for_episode=episode is not None)
    width, height, content_type = _decode(data, kind)

    problems = reference.artwork[kind].check(width=width, height=height, size_bytes=len(data))
    if problems:
        raise ArtworkRejected(kind.value, problems)

    # Content-addressed: replacing an image writes a new URL, so a browser or CDN that
    # already has the old one cannot keep serving it.
    checksum = hashlib.sha256(data).hexdigest()
    version = version_of(data)

    statement = select(Artwork).where(Artwork.kind == kind.value)
    if show is not None:
        key = show_key(kind, show_id=show.id, version=version, content_type=content_type)
        statement = statement.where(Artwork.show_id == show.id)
    else:
        assert episode is not None  # guaranteed by the exactly-one check above
        key = episode_key(kind, episode_id=episode.id, version=version, content_type=content_type)
        statement = statement.where(Artwork.episode_id == episode.id)

    existing = (await session.execute(statement)).scalar_one_or_none()

    await storage.put(key, data, content_type)
    superseded = existing.storage_key if existing is not None else None

    if existing is None:
        existing = Artwork(
            kind=kind.value,
            show_id=show.id if show is not None else None,
            episode_id=episode.id if episode is not None else None,
        )
        session.add(existing)

    existing.storage_key = key
    existing.content_type = content_type
    existing.width = width
    existing.height = height
    existing.byte_size = len(data)
    existing.checksum_sha256 = checksum
    await session.flush()

    if superseded and superseded != key:
        # Repoint first, then delete: a crash here leaves a stray file, not a dangling row.
        await storage.delete(superseded)

    return existing


async def delete_artwork(
    session: AsyncSession, storage: ObjectStorage, artwork_id: uuid.UUID
) -> str:
    """Remove the record and return the key the caller should delete after committing.

    Same ordering as `store_artwork`: the row goes first. A crash then leaves a stray
    file, which is harmless, rather than a row pointing at bytes that are gone.
    """
    record = (
        await session.execute(select(Artwork).where(Artwork.id == artwork_id))
    ).scalar_one_or_none()
    if record is None:
        raise ApiError(status_code=404, code="not_found", message="That image no longer exists.")
    key = record.storage_key
    await session.delete(record)
    await session.flush()
    return key
