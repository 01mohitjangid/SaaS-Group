"""Where artwork lives in storage.

The key convention is domain knowledge, not a seed-script detail: step 2's upload
endpoint and the seed loader must agree on it byte for byte, or the same poster is
written twice under two names.

Keys are built from **database ids**, never from slugs or external ids:

* ``external_id`` is NULL for anything an editor creates in the CMS.
* ``slug`` is editable. Renaming show A and giving the freed slug to show B would
  point B's poster at A's bytes — and then collide on ``uq_artwork_storage_key``.

An id is the one handle that is always present and never reused.
"""

from __future__ import annotations

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


def show_key(
    kind: ArtworkKind, *, show_id: uuid.UUID | str, content_type: str = DEFAULT_CONTENT_TYPE
) -> str:
    return f"{ARTWORK_PREFIX}/shows/{show_id}/{kind.value}.{extension_for(content_type)}"


def episode_key(
    kind: ArtworkKind, *, episode_id: uuid.UUID | str, content_type: str = DEFAULT_CONTENT_TYPE
) -> str:
    return f"{ARTWORK_PREFIX}/episodes/{episode_id}/{kind.value}.{extension_for(content_type)}"
