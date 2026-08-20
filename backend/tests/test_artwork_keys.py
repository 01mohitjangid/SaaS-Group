from __future__ import annotations

import uuid

import pytest

from app.domain.artwork import episode_key, extension_for, show_key
from app.domain.reference import ArtworkKind
from app.storage.base import validate_key


def test_artwork_is_keyed_by_database_id_never_by_slug_or_external_id() -> None:
    """Slugs are editable and external ids are NULL for CMS-created rows; ids are neither."""
    show_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    episode_id = uuid.UUID("66666666-7777-8888-9999-000000000000")

    assert show_key(ArtworkKind.POSTER, show_id=show_id) == f"artwork/shows/{show_id}/poster.jpg"
    assert show_key(ArtworkKind.BANNER, show_id=show_id) == f"artwork/shows/{show_id}/banner.jpg"
    assert (
        episode_key(ArtworkKind.THUMBNAIL, episode_id=episode_id)
        == f"artwork/episodes/{episode_id}/thumbnail.jpg"
    )


def test_renaming_a_show_cannot_repoint_its_artwork() -> None:
    show_id = uuid.uuid4()
    before = show_key(ArtworkKind.POSTER, show_id=show_id)
    # A slug change is invisible to the key, because the key never saw the slug.
    assert before == show_key(ArtworkKind.POSTER, show_id=show_id)


def test_two_shows_never_share_a_key() -> None:
    keys = {show_key(ArtworkKind.POSTER, show_id=uuid.uuid4()) for _ in range(50)}
    assert len(keys) == 50


def test_shows_and_episodes_live_in_separate_namespaces() -> None:
    shared = uuid.uuid4()
    assert show_key(ArtworkKind.THUMBNAIL, show_id=shared) != episode_key(
        ArtworkKind.THUMBNAIL, episode_id=shared
    )


def test_the_extension_follows_the_content_type() -> None:
    show_id = uuid.uuid4()
    assert show_key(ArtworkKind.POSTER, show_id=show_id, content_type="image/png").endswith(
        "poster.png"
    )
    assert show_key(ArtworkKind.POSTER, show_id=show_id, content_type="image/webp").endswith(
        "poster.webp"
    )
    assert extension_for("image/jpeg") == "jpg"


def test_an_unsupported_image_type_is_refused_with_a_readable_message() -> None:
    with pytest.raises(ValueError, match="image/gif"):
        extension_for("image/gif")
    with pytest.raises(ValueError, match="image/jpeg"):
        show_key(ArtworkKind.POSTER, show_id=uuid.uuid4(), content_type="application/pdf")


def test_keys_are_accepted_by_the_storage_layer() -> None:
    validate_key(show_key(ArtworkKind.POSTER, show_id=uuid.uuid4()))
    validate_key(episode_key(ArtworkKind.THUMBNAIL, episode_id=uuid.uuid4()))
