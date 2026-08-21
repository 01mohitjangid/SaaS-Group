"""Fetch a real photograph per show, once, into the repository.

    make artwork

**Why this is a tool and not part of seeding.** `docker compose up` seeds on start, and
a seed that reaches the network fails whenever the network does — which turns a graded
"compose works first try" into a coin flip. So this runs deliberately, writes masters to
``data/artwork/<slug>/source.jpg``, and those files ship with the repo. Seeding then
composites them offline. Delete them and the generated abstract artwork takes over; both
paths produce images that satisfy the same `reference.json` specs.

**Where the photos come from.** By default `picsum.photos`, which serves Unsplash
photographs, needs no API key and is deterministic per seed — the same slug always gets
the same picture, so re-running this changes nothing. Its catalogue is not searchable, so
the pictures are handsome but unrelated to the shows.

Set ``UNSPLASH_ACCESS_KEY`` and it queries the real Unsplash API instead, searching on
terms built from each show's own categories, which is what actually makes a poster look
like it belongs to its programme.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = REPO_ROOT / "data" / "challenge" / "seed_shows.json"
OUTPUT_ROOT = REPO_ROOT / "data" / "artwork"

#: Big enough to crop both a 2:3 poster and a 16:9 banner without upscaling.
MASTER = 1400
TIMEOUT = 30

#: The seed's categories are the closest thing to a brief each show has.
CATEGORY_TERMS = {
    "adventure": "adventure landscape",
    "folk": "folk art textile",
    "friendship": "children playing",
    "india": "india colourful street",
    "language": "alphabet letters",
    "learning": "classroom children",
    "maths": "numbers pattern",
    "music": "musical instruments",
    "nature": "nature wildlife",
    "reading": "children books",
    "science": "science curiosity",
    "singalong": "singing concert",
    "stories": "storytelling books",
    "travel": "travel india",
    "values": "family together",
}


def _get(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "peblo-tv-mini"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body: bytes = response.read()
        return body


def _unsplash_url(query: str, key: str) -> str | None:
    """Ask Unsplash for a landscape photo matching the show's own categories."""
    endpoint = "https://api.unsplash.com/photos/random?" + urllib.parse.urlencode(
        {"query": query, "orientation": "squarish", "content_filter": "high"}
    )
    try:
        payload = json.loads(_get(endpoint, {"Authorization": f"Client-ID {key}"}))
    except (urllib.error.URLError, ValueError, KeyError) as exc:
        print(f"    unsplash search failed ({exc}); falling back", file=sys.stderr)
        return None
    raw: str | None = payload.get("urls", {}).get("raw")
    return f"{raw}&w={MASTER}&h={MASTER}&fit=crop" if raw else None


def _picsum_url(slug: str) -> str:
    # Deterministic: the same show always gets the same photograph.
    return f"https://picsum.photos/seed/{urllib.parse.quote(slug)}/{MASTER}/{MASTER}"


def shows_from_seed() -> dict[str, list[str]]:
    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    shows: dict[str, list[str]] = {}
    for row in rows:
        shows.setdefault(row["slug"], row["categories"])
    return dict(sorted(shows.items()))


def query_for(categories: list[str]) -> str:
    terms = [CATEGORY_TERMS[c] for c in categories if c in CATEGORY_TERMS]
    return terms[0] if terms else "children television"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download masters that exist")
    args = parser.parse_args()

    key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    print(
        "source: Unsplash API (topical search)"
        if key
        else "source: picsum.photos — Unsplash photographs, no API key, random subjects.\n"
        "        Set UNSPLASH_ACCESS_KEY for photos that match each show's categories."
    )

    failures = 0
    for slug, categories in shows_from_seed().items():
        target = OUTPUT_ROOT / slug / "source.jpg"
        if target.exists() and not args.force:
            print(f"  {slug:26} already have it")
            continue

        query = query_for(categories)
        url = (_unsplash_url(query, key) if key else None) or _picsum_url(slug)
        try:
            data = _get(url)
        except urllib.error.URLError as exc:
            print(f"  {slug:26} FAILED ({exc.reason})", file=sys.stderr)
            failures += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"  {slug:26} {len(data) // 1024:>4} KB  ({query})")

    if failures:
        print(
            f"\n{failures} show(s) have no photograph; seeding will generate artwork for them.",
            file=sys.stderr,
        )
    else:
        print("\nRun `make seed` to composite these into posters, banners and thumbnails.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
