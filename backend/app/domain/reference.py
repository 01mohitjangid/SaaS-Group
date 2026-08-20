"""``reference.json`` turned into typed, queryable rules.

The allowed sections/categories/languages and the artwork specs are content-team
data, not code. They live in the JSON file so a non-engineer can change them; this
module is the only place that reads it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_REFERENCE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "challenge" / "reference.json"
)

#: Season 0 is reserved for trailers — never rendered as a normal season.
TRAILER_SEASON = 0

#: Aspect ratios are compared with a small tolerance so a 1200×1800 poster still
#: counts as 2:3 — editors legitimately upload higher-resolution masters.
ASPECT_TOLERANCE = 0.02


class ArtworkKind(StrEnum):
    POSTER = "poster"
    BANNER = "banner"
    THUMBNAIL = "thumbnail"


#: Which surface each size fills, used verbatim in the messages editors read.
SURFACE: dict[ArtworkKind, str] = {
    ArtworkKind.POSTER: "browse rows",
    ArtworkKind.BANNER: "the featured hero",
    ArtworkKind.THUMBNAIL: "episode lists",
}


@dataclass(frozen=True, slots=True)
class ArtworkProblem:
    """One rejection reason, written for a content editor rather than an engineer."""

    code: str
    message: str
    hint: str


@dataclass(frozen=True, slots=True)
class ArtworkSpec:
    kind: ArtworkKind
    aspect: tuple[int, int]
    target_width: int
    target_height: int
    max_bytes: int

    @property
    def aspect_label(self) -> str:
        return f"{self.aspect[0]}:{self.aspect[1]}"

    @property
    def target_label(self) -> str:
        return f"{self.target_width}×{self.target_height}"

    @property
    def aspect_ratio(self) -> float:
        return self.aspect[0] / self.aspect[1]

    def check(self, *, width: int, height: int, size_bytes: int) -> list[ArtworkProblem]:
        """Return every problem with this file — not just the first one.

        Callers pass real decoded dimensions. A file that cannot be decoded at all is
        the upload endpoint's error to raise — this refuses to guess about it.
        """
        if width <= 0 or height <= 0:
            raise ValueError(
                f"{width}×{height} is not a decoded image size; "
                f"reject undecodable uploads before calling check()"
            )

        problems: list[ArtworkProblem] = []
        actual = f"{width}×{height}"
        ratio = width / height
        if abs(ratio - self.aspect_ratio) > ASPECT_TOLERANCE * self.aspect_ratio:
            problems.append(
                ArtworkProblem(
                    code="artwork.aspect",
                    message=(
                        f"This {self.kind.value} is {actual}, which is the wrong shape. "
                        f"{self.kind.value.capitalize()}s must be {self.aspect_label} — "
                        f"for example {self.target_label}."
                    ),
                    hint=f"Crop or export the image at {self.target_label} and upload it again.",
                )
            )

        if width < self.target_width or height < self.target_height:
            problems.append(
                ArtworkProblem(
                    code="artwork.too_small",
                    message=(
                        f"This {self.kind.value} is {actual}, which is too small for "
                        f"{SURFACE[self.kind]}. The smallest we accept is {self.target_label}."
                    ),
                    hint=f"Export the original at {self.target_label} or larger.",
                )
            )

        if size_bytes > self.max_bytes:
            problems.append(
                ArtworkProblem(
                    code="artwork.too_large",
                    message=(
                        f"This file is {size_bytes / 1024:.0f} KB. "
                        f"The limit is {self.max_bytes // 1024} KB so it loads quickly on a TV."
                    ),
                    hint="Re-export it as a JPEG at about 80% quality to shrink the file.",
                )
            )

        return problems


@dataclass(frozen=True, slots=True)
class Reference:
    sections: tuple[str, ...]
    categories: tuple[str, ...]
    languages: tuple[str, ...]
    artwork: dict[ArtworkKind, ArtworkSpec]

    def is_section(self, value: str | None) -> bool:
        return value in self.sections

    def is_category(self, value: str) -> bool:
        return value in self.categories

    def is_language(self, value: str) -> bool:
        return value in self.languages


def _parse_aspect(raw: str) -> tuple[int, int]:
    left, _, right = raw.partition(":")
    return int(left), int(right)


def _build(payload: dict[str, Any]) -> Reference:
    specs: dict[ArtworkKind, ArtworkSpec] = {}
    for raw_kind, spec in payload["artwork_specs"].items():
        kind = ArtworkKind(raw_kind)
        width, height = spec["target_px"]
        specs[kind] = ArtworkSpec(
            kind=kind,
            aspect=_parse_aspect(spec["aspect"]),
            target_width=int(width),
            target_height=int(height),
            max_bytes=int(spec["max_kb"]) * 1024,
        )
    return Reference(
        sections=tuple(payload["sections"]),
        categories=tuple(payload["categories"]),
        languages=tuple(payload["languages"]),
        artwork=specs,
    )


@lru_cache(maxsize=4)
def load_reference(path: Path | None = None) -> Reference:
    target = path or DEFAULT_REFERENCE_PATH
    return _build(json.loads(target.read_text(encoding="utf-8")))
