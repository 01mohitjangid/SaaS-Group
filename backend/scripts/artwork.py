"""Show artwork: a real photograph when we have one, a designed placeholder when we do not.

The challenge ships a handful of sample images but not one per show, and the viewer is
only honest if every published show really has a poster, a banner and thumbnails. This
produces them at exactly the specs in ``reference.json`` — deterministic, so seeding is
reproducible, and inside the 200 KB ceiling by real bytes rather than by assertion.

Three sources, in order:

1. ``data/artwork/<slug>/<kind>.jpg`` — an exact image for one surface, used as-is. This
   is where the challenge's own sample assets would go.
2. ``data/artwork/<slug>/source.jpg`` — the show's photograph, fetched once by
   ``tools/fetch_artwork.py``. One master is cropped to all three surfaces, which is what
   makes a show's poster, banner and thumbnails read as the same programme.
3. Otherwise a generated gradient with one of four abstract motifs.

Nothing here reaches the network: `docker compose up` seeds on start, and a seed that
needs the internet fails whenever the internet does.

This is *not* the upload path — ``ArtworkSpec.check()`` validates real uploads. The
storage key convention both share lives in ``app.domain.artwork``.
"""

from __future__ import annotations

import colorsys
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.domain.reference import ArtworkKind, ArtworkSpec

JPEG_QUALITY = 86
ARTWORK_ROOT = Path(__file__).resolve().parents[2] / "data" / "artwork"

#: Tried in order. The image installs DejaVu; macOS has the first two. Pillow's bundled
#: font is the floor, so this never fails — it just gets less pretty.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

#: Typographic characters a fallback font may not carry. A tofu box in the middle of a
#: title looks like a bug, and "Peblo Songs - Lyrical" is a real title in the seed data.
TYPOGRAPHIC = str.maketrans(
    {
        "\u2014": "-",  # em dash, as in "Peblo Songs — Lyrical"
        "\u2013": "-",  # en dash
        "\u2019": "'",  # right single quote
        "\u2018": "'",  # left single quote
        "\u201c": '"',  # left double quote
        "\u201d": '"',  # right double quote
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",  # non-breaking space
    }
)


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes
    width: int
    height: int
    content_type: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _drawable(text: str) -> str:
    return text.translate(TYPOGRAPHIC)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _digest(seed: str) -> bytes:
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _to_rgb(channels: tuple[float, float, float]) -> tuple[int, int, int]:
    return round(channels[0] * 255), round(channels[1] * 255), round(channels[2] * 255)


def _palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Two gradient stops plus a complementary accent, far enough apart to look chosen."""
    digest = _digest(seed)
    hue = digest[0] / 255
    top = colorsys.hsv_to_rgb(hue, 0.62, 0.88)
    bottom = colorsys.hsv_to_rgb((hue + 0.14) % 1.0, 0.80, 0.22)
    accent = colorsys.hsv_to_rgb((hue + 0.5) % 1.0, 0.62, 0.92)
    return _to_rgb(top), _to_rgb(bottom), _to_rgb(accent)


def _gradient(
    size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    """A one-pixel ramp stretched to size — smooth, and far cheaper than per-pixel."""
    ramp = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        ramp.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return ramp.resize(size, Image.Resampling.BICUBIC)


def _motif(canvas: Image.Image, seed: str, accent: tuple[int, int, int]) -> None:
    """One of four bold abstract motifs, chosen by hash.

    Blurred blobs alone read as "a gradient with nothing on it". Kids' key art is built
    from big confident shapes, so these are drawn crisp at real opacity with a glow
    underneath rather than being blurred away entirely.
    """
    width, height = canvas.size
    digest = _digest(seed + ":motif")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    light, dark = (255, 255, 255), (10, 10, 16)

    choice = digest[0] % 4
    if choice == 0:  # concentric arcs radiating from a corner
        cx = width if digest[1] % 2 else 0
        cy = int(height * 0.28)
        for ring in range(6):
            radius = int(width * (0.32 + ring * 0.24))
            draw.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                outline=(*light, max(70 - ring * 9, 14)),
                width=max(3, width // 46),
            )
    elif choice == 1:  # rolling hills under a low sun
        sun = int(width * 0.20)
        sx, sy = int(width * (0.24 + digest[2] / 255 * 0.5)), int(height * 0.30)
        draw.ellipse([sx - sun, sy - sun, sx + sun, sy + sun], fill=(*accent, 150))
        for hill in range(3):
            span = int(width * (0.85 + hill * 0.4))
            top = int(height * (0.62 + hill * 0.11))
            left = int(width * (-0.25 + digest[3 + hill] / 255 * 0.5))
            draw.ellipse(
                [left, top, left + span, top + span],
                fill=(*dark, 60 + hill * 45) if hill % 2 else (*light, 40),
            )
    elif choice == 2:  # scattered bubbles
        for index in range(9):
            radius = int(width * (0.05 + digest[index] / 255 * 0.17))
            cx = int(width * (digest[(index * 2) % 32] / 255))
            cy = int(height * (digest[(index * 3 + 1) % 32] / 255) * 0.85)
            tint = accent if index % 3 == 0 else light
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*tint, 46))
    else:  # mountain peaks
        base = int(height * 0.78)
        for peak in range(4):
            span = int(width * (0.4 + digest[peak + 4] / 255 * 0.5))
            cx = int(width * (0.1 + peak * 0.28))
            top = base - int(span * (0.7 + digest[peak] / 255 * 0.5))
            draw.polygon(
                [(cx - span // 2, base), (cx, top), (cx + span // 2, base)],
                fill=(*(accent if peak % 2 else light), 55),
            )

    glow = layer.filter(ImageFilter.GaussianBlur(radius=max(width, height) // 22))
    merged = Image.alpha_composite(canvas.convert("RGBA"), glow)
    canvas.paste(Image.alpha_composite(merged, layer).convert("RGB"), (0, 0))


def _scrim(canvas: Image.Image, fraction: float = 0.55) -> None:
    """Darken the bottom so the title stays readable over any part of the picture."""
    width, height = canvas.size
    band = int(height * fraction)
    ramp = Image.new("L", (1, 256))
    for y in range(256):
        ramp.putpixel((0, y), round((y / 255) ** 1.6 * 235))
    canvas.paste(
        Image.new("RGB", (width, band), (8, 8, 11)),
        (0, height - band),
        ramp.resize((width, band), Image.Resampling.BICUBIC),
    )


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Wrap by measuring, not by counting characters.

    A character-count heuristic is tuned to one font's average width and clips the moment
    the font changes — exactly what happens between a dev machine and a slim container.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_title(canvas: Image.Image, label: str, kind: ArtworkKind) -> None:
    width, height = canvas.size
    draw = ImageDraw.Draw(canvas)

    # Sized off the tile, so the title reads at 184px in a row and at 1280px in the hero.
    title_size = max(14, int(width * (0.115 if kind is ArtworkKind.POSTER else 0.075)))
    title_font, mark_font = _font(title_size), _font(max(9, int(width * 0.026)))

    margin = int(width * 0.07)
    lines = _wrap(draw, _drawable(label), title_font, width - margin * 2)[:3]
    line_height = int(title_size * 1.12)

    y = height - margin - line_height * len(lines)
    for line in lines:
        # A soft drop shadow rather than an outline: it survives a bright photograph
        # without looking like a sticker.
        draw.text((margin + 2, y + 2), line, font=title_font, fill=(0, 0, 0))
        draw.text((margin, y), line, font=title_font, fill=(255, 255, 255))
        y += line_height

    draw.text((margin, margin), "PEBLO TV", font=mark_font, fill=(255, 255, 255))


def load_override(kind: ArtworkKind, slug: str) -> bytes | None:
    """An exact image for one surface, used as-is rather than composited."""
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = ARTWORK_ROOT / slug / f"{kind.value}{suffix}"
        if candidate.is_file():
            return candidate.read_bytes()
    return None


def load_master(slug: str) -> Image.Image | None:
    """The show's photograph, fetched once by ``tools/fetch_artwork.py``."""
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = ARTWORK_ROOT / slug / f"source{suffix}"
        if candidate.is_file():
            with Image.open(candidate) as opened:
                return opened.convert("RGB")
    return None


def _crop_to(master: Image.Image, size: tuple[int, int], offset: float) -> Image.Image:
    """Crop to the target aspect, sliding the window by ``offset`` (0 to 1).

    Episodes each take a different slice of the show's photograph, so an episode list
    looks varied without needing one download per episode.
    """
    target_ratio = size[0] / size[1]
    width, height = master.size
    offset = min(max(offset, 0.0), 1.0)
    if width / height > target_ratio:
        box_width = int(height * target_ratio)
        left = int((width - box_width) * offset)
        box = (left, 0, left + box_width, height)
    else:
        box_height = int(width / target_ratio)
        top = int((height - box_height) * offset)
        box = (0, top, width, top + box_height)
    return master.resize(size, Image.Resampling.LANCZOS, box=box)


def _tint(canvas: Image.Image, colour: tuple[int, int, int], alpha: int) -> None:
    """A wash of the show's colour, so photographs stay distinguishable in a grid."""
    wash = Image.new("RGBA", canvas.size, (*colour, alpha))
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), wash).convert("RGB"), (0, 0))


def _encode(image: Image.Image, spec: ArtworkSpec) -> GeneratedImage:
    data = b""
    for quality in (JPEG_QUALITY, 70, 55, 40):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
        data = buffer.getvalue()
        if len(data) <= spec.max_bytes:
            break
    return GeneratedImage(
        data=data, width=image.width, height=image.height, content_type="image/jpeg"
    )


def generate(
    spec: ArtworkSpec, *, seed: str, label: str, slug: str | None = None
) -> GeneratedImage:
    """``slug`` chooses the picture and the colour; ``seed`` chooses the composition."""
    override = load_override(spec.kind, slug) if slug else None
    if override is not None:
        with Image.open(io.BytesIO(override)) as opened:
            return _encode(
                opened.convert("RGB").resize(
                    (spec.target_width, spec.target_height), Image.Resampling.LANCZOS
                ),
                spec,
            )

    size = (spec.target_width, spec.target_height)
    top, bottom, accent = _palette(slug or seed)
    master = load_master(slug) if slug else None

    if master is not None:
        # A photograph treated the way streaming key art is: cropped to the surface, a
        # colour wash so the show stays recognisable in a grid, then a scrim so the title
        # survives whatever the picture happens to be doing.
        canvas = _crop_to(master, size, _digest(seed)[0] / 255)
        _tint(canvas, bottom, 52)
    else:
        canvas = _gradient(size, top, bottom)
        _motif(canvas, seed, accent)

    _scrim(canvas, 0.5 if spec.kind is ArtworkKind.POSTER else 0.6)
    _draw_title(canvas, label, spec.kind)
    return _encode(canvas, spec)
