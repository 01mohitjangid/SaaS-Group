"""Where artwork lives in storage.

The key convention is domain knowledge, not a seed-script detail: step 2's upload
endpoint and the seed loader must agree on it byte for byte, or the same poster is
written twice under two names.

Keys are built from **database ids**, never from slugs or external ids:

* ``external_id`` is NULL for anything an editor creates in the CMS.
* ``slug`` is editable. Renaming show A and giving the freed slug to show B would
  point B's poster at A's bytes — and then collide on ``uq_artwork_storage_key``.

An id is the one handle that is always present and never reused.

Keys are also **content-addressed**: a short hash of the bytes is part of the filename.
Replacing a poster therefore writes a *new* URL, so a browser or a CDN cannot serve the
old picture — reusing one path for changing bytes is how artwork goes stale for everyone
who already visited. The previous object is deleted once the row points at the new one.
"""

from __future__ import annotations

import hashlib
import uuid

from app.domain.reference import ArtworkKind

ARTWORK_PREFIX = "artwork"
DEFAULT_CONTENT_TYPE = "image/jpeg"

#: Content types the artwork pipeline accepts, and the extension each one gets.
EXTENSIONS: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def extension_for(content_type: str) -> str:
    try:
        return EXTENSIONS[content_type]
    except KeyError:
        raise ValueError(
            f"{content_type!r} is not an image type we store; expected one of {sorted(EXTENSIONS)}"
        ) from None


#: Enough of the checksum to make a collision irrelevant, short enough to stay readable.
VERSION_LENGTH = 12


def version_of(data: bytes) -> str:
    """The part of the key that changes when the picture does."""
    return hashlib.sha256(data).hexdigest()[:VERSION_LENGTH]


def show_key(
    kind: ArtworkKind,
    *,
    show_id: uuid.UUID | str,
    version: str,
    content_type: str = DEFAULT_CONTENT_TYPE,
) -> str:
    suffix = extension_for(content_type)
    return f"{ARTWORK_PREFIX}/shows/{show_id}/{kind.value}-{version}.{suffix}"


def episode_key(
    kind: ArtworkKind,
    *,
    episode_id: uuid.UUID | str,
    version: str,
    content_type: str = DEFAULT_CONTENT_TYPE,
) -> str:
    suffix = extension_for(content_type)
    return f"{ARTWORK_PREFIX}/episodes/{episode_id}/{kind.value}-{version}.{suffix}"
