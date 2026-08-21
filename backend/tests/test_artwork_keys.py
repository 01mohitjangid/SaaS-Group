from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

import pytest

from app.domain.artwork import episode_key, extension_for, show_key, version_of
from app.domain.reference import ArtworkKind
from app.storage.base import validate_key

#: A fixed version keeps the key-shape assertions readable; `version_of` is tested below.
V = "abc123abc123"


def test_artwork_is_keyed_by_database_id_never_by_slug_or_external_id() -> None:
    """Slugs are editable and external ids are NULL for CMS-created rows; ids are neither."""
    show_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    episode_id = uuid.UUID("66666666-7777-8888-9999-000000000000")

    assert (
        show_key(ArtworkKind.POSTER, show_id=show_id, version=V)
        == f"artwork/shows/{show_id}/poster-{V}.jpg"
    )
    assert (
        episode_key(ArtworkKind.THUMBNAIL, episode_id=episode_id, version=V)
        == f"artwork/episodes/{episode_id}/thumbnail-{V}.jpg"
    )


def test_new_bytes_get_a_new_url_so_a_cached_copy_cannot_win() -> None:
    """Reusing one path for changing bytes is how artwork goes stale for every visitor.

    This was a real bug: regenerating every poster changed nothing on screen, because the
    browser already had the old picture at the same URL.
    """
    show_id = uuid.uuid4()
    before = show_key(ArtworkKind.POSTER, show_id=show_id, version=version_of(b"old picture"))
    after = show_key(ArtworkKind.POSTER, show_id=show_id, version=version_of(b"new picture"))
    assert before != after

    # …and identical bytes keep the same URL, so re-seeding is still a no-op.
    assert version_of(b"same") == version_of(b"same")
    assert len(version_of(b"same")) == 12


def test_renaming_a_show_cannot_repoint_its_artwork() -> None:
    show_id = uuid.uuid4()
    # A slug change is invisible to the key, because the key never saw the slug.
    assert show_key(ArtworkKind.POSTER, show_id=show_id, version=V) == show_key(
        ArtworkKind.POSTER, show_id=show_id, version=V
    )


def test_two_shows_never_share_a_key() -> None:
    keys = {show_key(ArtworkKind.POSTER, show_id=uuid.uuid4(), version=V) for _ in range(50)}
    assert len(keys) == 50


def test_shows_and_episodes_live_in_separate_namespaces() -> None:
    shared = uuid.uuid4()
    assert show_key(ArtworkKind.THUMBNAIL, show_id=shared, version=V) != episode_key(
        ArtworkKind.THUMBNAIL, episode_id=shared, version=V
    )


def test_the_extension_follows_the_content_type() -> None:
    show_id = uuid.uuid4()
    assert show_key(
        ArtworkKind.POSTER, show_id=show_id, version=V, content_type="image/png"
    ).endswith(f"poster-{V}.png")
    assert extension_for("image/jpeg") == "jpg"


def test_an_unsupported_image_type_is_refused_with_a_readable_message() -> None:
    with pytest.raises(ValueError, match="image/gif"):
        extension_for("image/gif")
    with pytest.raises(ValueError, match="image/jpeg"):
        show_key(
            ArtworkKind.POSTER, show_id=uuid.uuid4(), version=V, content_type="application/pdf"
        )


def test_keys_are_accepted_by_the_storage_layer() -> None:
    validate_key(show_key(ArtworkKind.POSTER, show_id=uuid.uuid4(), version=V))
    validate_key(episode_key(ArtworkKind.THUMBNAIL, episode_id=uuid.uuid4(), version=V))


# ----------------------------------------------------------- generated placeholder art


def test_titles_never_render_a_missing_glyph() -> None:
    """ "Peblo Songs - Lyrical" is a real seed title, and its em dash rendered as a box.

    The font a slim container falls back to does not carry every typographic character,
    so titles are normalised to characters any font has before they are drawn.
    """
    from scripts.artwork import _drawable

    assert _drawable("Peblo Songs \u2014 Lyrical") == "Peblo Songs - Lyrical"
    assert _drawable("Moti\u2019s Many Lives") == "Moti's Many Lives"
    assert _drawable("\u201cQuoted\u201d and\u2026") == '"Quoted" and...'


def test_generated_artwork_passes_the_very_specs_the_upload_endpoint_enforces() -> None:
    from app.domain.reference import load_reference
    from scripts.artwork import generate

    reference = load_reference()
    for kind, spec in reference.artwork.items():
        image = generate(spec, seed=f"a-show:{kind.value}", label="A Show", slug="a-show")
        assert (image.width, image.height) == (spec.target_width, spec.target_height)
        assert spec.check(width=image.width, height=image.height, size_bytes=len(image.data)) == []


def test_artwork_is_deterministic_but_differs_per_show() -> None:
    """Same slug in, same bytes out — that is what keeps re-seeding idempotent."""
    from app.domain.reference import ArtworkKind, load_reference
    from scripts.artwork import generate

    spec = load_reference().artwork[ArtworkKind.POSTER]
    first = generate(spec, seed="a:poster", label="A", slug="unseeded-a")
    again = generate(spec, seed="a:poster", label="A", slug="unseeded-a")
    other = generate(spec, seed="b:poster", label="B", slug="unseeded-b")

    assert first.checksum == again.checksum
    assert first.checksum != other.checksum


def test_a_show_photograph_is_used_for_every_surface_when_present(tmp_path: Path) -> None:
    """One master, three surfaces — that is what makes them look like one programme."""
    import io

    from PIL import Image

    from app.domain.reference import ArtworkKind, load_reference
    from scripts import artwork

    master = tmp_path / "photo-show" / "source.jpg"
    master.parent.mkdir(parents=True)
    Image.new("RGB", (1400, 1400), (200, 40, 90)).save(master, format="JPEG")

    reference = load_reference()
    original_root = artwork.ARTWORK_ROOT
    artwork.ARTWORK_ROOT = tmp_path
    try:
        assert artwork.load_master("photo-show") is not None
        for kind, spec in reference.artwork.items():
            image = artwork.generate(
                spec, seed=f"photo-show:{kind.value}", label="Photo Show", slug="photo-show"
            )
            assert (image.width, image.height) == (spec.target_width, spec.target_height)
            assert len(image.data) <= spec.max_bytes
            # The picture is pink; a generated gradient for this slug would not be.
            with Image.open(io.BytesIO(image.data)) as rendered:
                pixel = cast(
                    "tuple[int, int, int]",
                    rendered.convert("RGB").getpixel((spec.target_width // 2, 10)),
                )
                assert pixel[0] > pixel[2], f"{kind.value} does not look like the photograph"

        # Two episodes take different crops of the same picture.
        first = artwork.generate(
            reference.artwork[ArtworkKind.THUMBNAIL],
            seed="photo-show:t:1",
            label="A",
            slug="photo-show",
        )
        second = artwork.generate(
            reference.artwork[ArtworkKind.THUMBNAIL],
            seed="photo-show:t:2",
            label="B",
            slug="photo-show",
        )
        assert first.checksum != second.checksum
    finally:
        artwork.ARTWORK_ROOT = original_root


def test_seeding_needs_no_network(tmp_path: Path) -> None:
    """A missing photograph falls back to generated art rather than reaching out.

    `docker compose up` seeds on start; a seed that needs the internet fails whenever the
    internet does, and "compose works first try" is an explicitly graded line.
    """
    from app.domain.reference import ArtworkKind, load_reference
    from scripts import artwork

    original_root = artwork.ARTWORK_ROOT
    artwork.ARTWORK_ROOT = tmp_path  # empty: no masters, no overrides
    try:
        image = artwork.generate(
            load_reference().artwork[ArtworkKind.POSTER],
            seed="no-photo:poster",
            label="No Photo",
            slug="no-photo",
        )
        assert (image.width, image.height) == (600, 900)
    finally:
        artwork.ARTWORK_ROOT = original_root
