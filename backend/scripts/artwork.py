"""Deterministic placeholder artwork — seed scaffolding only.

The challenge ships a handful of sample images but not one per show, and the
viewer UI is only honest if every published show actually has a poster, a banner
and thumbnails. This generates them at exactly the specs in ``reference.json`` —
same slug in, same bytes out — so seeding is reproducible and the 200 KB ceiling
is met by real files rather than by assertion.

This is *not* the upload path: `ArtworkSpec.check()` is what validates real uploads.
The storage key convention both share lives in `app.domain.artwork`.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageDraw

from app.domain.reference import ArtworkSpec

JPEG_QUALITY = 82


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes
    width: int
    height: int
    content_type: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    base = (60 + digest[0] % 120, 60 + digest[1] % 120, 60 + digest[2] % 120)
    accent = tuple(min(255, channel + 70) for channel in base)
    return base, (accent[0], accent[1], accent[2])


def generate(spec: ArtworkSpec, *, seed: str, label: str) -> GeneratedImage:
    width, height = spec.target_width, spec.target_height
    base, accent = _palette(seed)

    image = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(image)

    # A soft diagonal wash so posters and banners are visually distinguishable.
    for step in range(0, width + height, max(8, width // 40)):
        draw.line([(step, 0), (0, step)], fill=accent, width=2)

    band = height // 5
    draw.rectangle([(0, height - band), (width, height)], fill=(15, 15, 20))
    draw.text((width // 20, height - band + band // 3), label[:48], fill=(245, 245, 245))
    draw.text((width // 20, height // 20), spec.kind.value.upper(), fill=(245, 245, 245))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    data = buffer.getvalue()

    if len(data) > spec.max_bytes:  # pragma: no cover - defensive, flat art is far smaller
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=60, optimize=True)
        data = buffer.getvalue()

    return GeneratedImage(data=data, width=width, height=height, content_type="image/jpeg")
