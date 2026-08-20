from __future__ import annotations

import pytest

from app.domain.reference import ArtworkKind, Reference, load_reference


def test_reference_exposes_the_allowed_vocabularies(reference: Reference) -> None:
    assert reference.sections == ("featured", "series", "minisodes", "songs")
    assert reference.languages == ("en", "hi")
    assert "adventure" in reference.categories
    assert len(reference.categories) == 15


def test_every_artwork_kind_has_a_spec(reference: Reference) -> None:
    assert set(reference.artwork) == {ArtworkKind.POSTER, ArtworkKind.BANNER, ArtworkKind.THUMBNAIL}

    poster = reference.artwork[ArtworkKind.POSTER]
    assert (poster.target_width, poster.target_height) == (600, 900)
    assert poster.aspect == (2, 3)
    assert poster.max_bytes == 200 * 1024


def test_load_reference_is_cached(reference: Reference) -> None:
    assert load_reference() is load_reference()


@pytest.mark.parametrize(
    ("kind", "width", "height", "size_kb", "expected_codes"),
    [
        (ArtworkKind.POSTER, 600, 900, 100, []),
        (ArtworkKind.BANNER, 1280, 720, 100, []),
        (ArtworkKind.THUMBNAIL, 640, 360, 100, []),
        # tolerated scaling: same aspect, different pixel size
        (ArtworkKind.POSTER, 1200, 1800, 100, []),
        # wrong aspect ratio
        (ArtworkKind.POSTER, 900, 900, 100, ["artwork.aspect"]),
        # too small for the surface it has to fill
        (ArtworkKind.THUMBNAIL, 160, 90, 10, ["artwork.too_small"]),
        # over the 200 KB ceiling
        (ArtworkKind.BANNER, 1280, 720, 400, ["artwork.too_large"]),
        # both wrong at once — the editor sees every problem, not just the first
        (
            ArtworkKind.BANNER,
            100,
            100,
            400,
            ["artwork.aspect", "artwork.too_small", "artwork.too_large"],
        ),
    ],
)
def test_artwork_spec_check(
    reference: Reference,
    kind: ArtworkKind,
    width: int,
    height: int,
    size_kb: int,
    expected_codes: list[str],
) -> None:
    problems = reference.artwork[kind].check(width=width, height=height, size_bytes=size_kb * 1024)
    assert [p.code for p in problems] == expected_codes


def test_artwork_problem_messages_name_the_numbers_an_editor_needs(reference: Reference) -> None:
    (problem,) = reference.artwork[ArtworkKind.POSTER].check(width=900, height=900, size_bytes=1024)
    assert "2:3" in problem.message
    assert "600×900" in problem.message
    assert "900×900" in problem.message
    assert problem.hint


def test_check_refuses_dimensions_that_are_not_a_decoded_image(reference: Reference) -> None:
    """An undecodable upload is the endpoint's error to raise, not a silent 0×0 pass."""
    spec = reference.artwork[ArtworkKind.POSTER]
    for width, height in ((0, 900), (600, 0), (0, 0), (-1, 900)):
        with pytest.raises(ValueError, match="not a decoded image size"):
            spec.check(width=width, height=height, size_bytes=1024)
