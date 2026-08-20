"""Measure whether the search indexes are actually used, and at what size.

The README and the schema docstrings make claims about query plans. This is where
those numbers come from, so they can be re-derived rather than believed::

    make bench

It lives in ``tools/`` rather than ``scripts/`` on purpose: ``scripts/`` is what the
container runs, and the first thing this does is ``DROP SCHEMA public CASCADE``. It
refuses to run against a database whose name does not contain ``bench``, and it is
excluded from the image.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORDS = [
    "kite",
    "roof",
    "stone",
    "market",
    "flour",
    "well",
    "map",
    "cart",
    "river",
    "song",
    "lamp",
    "garden",
    "moon",
    "bridge",
    "feather",
    "drum",
    "lantern",
    "harbour",
    "orchard",
    "whistle",
]

#: The two queries the CMS list really emits. `GET /admin/shows?q=` searches title OR
#: slug, which is only indexable if *both* columns carry a trigram index — otherwise the
#: OR drags the whole query into a sequential scan. That is the lesson this file exists
#: to keep honest, and it is measured against the shipped predicate, not a simplified one.
CMS_SHOW_SEARCH = """
SELECT id FROM shows WHERE title ILIKE '%zephyr%' OR slug ILIKE '%zephyr%'
"""

CMS_EPISODE_SEARCH = """
SELECT e.id FROM episodes e
JOIN seasons se ON se.id = e.season_id
JOIN shows sh ON sh.id = se.show_id
WHERE e.title ILIKE '%zephyr%'
"""

QUERIES: tuple[tuple[str, str], ...] = (
    ("shows · rare term", "SELECT id FROM shows WHERE title ILIKE '%zephyr%'"),
    ("episodes · rare term", "SELECT id FROM episodes WHERE title ILIKE '%zephyr%'"),
    ("shows · common term (~10% of rows)", "SELECT id FROM shows WHERE title ILIKE '%kite%'"),
    (
        "shows · published + rare term",
        "SELECT id FROM shows WHERE status = 'published' AND title ILIKE '%zephyr%'",
    ),
    (
        "shows · published in one section",
        "SELECT id FROM shows WHERE status = 'published' AND section = 'series'",
    ),
    ("episodes · collapse one content group", "SELECT id FROM episodes WHERE content_group = :cg"),
    ("shows · two-character term", "SELECT id FROM shows WHERE title ILIKE '%ki%'"),
    ("cms · show list, title OR slug", CMS_SHOW_SEARCH),
    ("cms · episode list, joined + filtered", CMS_EPISODE_SEARCH),
)


def _title(rng: random.Random) -> str:
    return f"The {rng.choice(WORDS).capitalize()} {rng.choice(WORDS).capitalize()}"


def _sql_array(values: list[str]) -> str:
    """A parenthesised literal SQL array, ready to subscript.

    Passing the list as a bind parameter instead would nest it one level too deep:
    ``ARRAY[:w]`` makes a 2-D array and every subscript comes back NULL.
    """
    return "(ARRAY['" + "','".join(values) + "'])"


CATEGORIES = _sql_array(
    [
        "adventure",
        "folk",
        "friendship",
        "india",
        "language",
        "learning",
        "maths",
        "music",
        "nature",
        "reading",
        "science",
        "singalong",
        "stories",
        "travel",
        "values",
    ]
)


def _load(engine: sa.Engine, shows: int, episodes: int) -> str:
    """Load synthetic content and return one content_group that really exists."""
    rng = random.Random(20260820)
    words, n = _sql_array(WORDS), len(WORDS)

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO shows (id, slug, title, synopsis, section, categories, status) "
                # Per-row titles, so the table holds a realistic spread of terms rather
                # than 20k copies of one phrase.
                "SELECT gen_random_uuid(), 'bench-' || i, "
                f"  'The ' || {words}[1 + (i % {n})] || ' ' || {words}[1 + (i / 7 % {n})] "
                "  || ' ' || i, :synopsis, "
                "  (ARRAY['featured','series','minisodes','songs'])[1 + (i % 4)], "
                # 2-3 categories per show, as in the real seed — the axis that governs
                # GIN selectivity.
                f"  ARRAY[{CATEGORIES}[1 + (i % 15)], {CATEGORIES}[1 + ((i + 5) % 15)]] "
                f"    || CASE WHEN i % 2 = 0 THEN ARRAY[{CATEGORIES}[1 + ((i + 9) % 15)]] "
                f"            ELSE ARRAY[]::varchar[] END, "
                "  CASE WHEN i % 5 = 0 THEN 'published' ELSE 'draft' END::publication_status "
                "FROM generate_series(1, :n) AS i"
            ),
            {
                # A realistic row width; a narrow table can be cheaper to seq-scan.
                "synopsis": " ".join(rng.choice(WORDS) for _ in range(60)),
                "n": shows,
            },
        )
        # Seeded, so the published table is re-derivable digit for digit.
        connection.execute(sa.text("SELECT setseed(0.20260820)"))
        # A deliberately rare term, so the table shows both sides of the crossover:
        # a selective search (index) and an unselective one (scan).
        connection.execute(
            sa.text(
                "UPDATE shows SET title = 'The Zephyr Signal ' || ctid "
                "WHERE id IN (SELECT id FROM shows ORDER BY random() LIMIT :n)"
            ),
            {"n": max(1, shows // 500)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO seasons (id, show_id, season_number) "
                "SELECT gen_random_uuid(), id, 1 FROM shows"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO episodes "
                "  (id, season_id, episode_number, title, language, content_group, status) "
                "SELECT gen_random_uuid(), s.id, i, "
                f"  'The ' || {words}[1 + (i % {n})] || ' ' || substr(s.id::text, 1, 8), 'en', "
                "  'bench-cg-' || i || '-' || s.id, 'published' "
                "FROM seasons s CROSS JOIN generate_series(1, :per) AS i"
            ),
            {"per": max(1, episodes // max(1, shows))},
        )
        # Give a slice of the episodes a Hindi sibling, so "collapse one content group"
        # measures a real two-row variant group rather than a point lookup.
        connection.execute(
            sa.text(
                "INSERT INTO episodes "
                "  (id, season_id, episode_number, title, language, content_group, status) "
                "SELECT gen_random_uuid(), e.season_id, e.episode_number, e.title, 'hi', "
                "  e.content_group, 'published' "
                "FROM episodes e WHERE e.episode_number = 1"
            )
        )
        connection.execute(sa.text("SELECT setseed(0.19700101)"))
        connection.execute(
            sa.text(
                "UPDATE episodes SET title = 'The Zephyr Signal ' || ctid "
                "WHERE id IN (SELECT id FROM episodes ORDER BY random() LIMIT :n)"
            ),
            {"n": max(1, episodes // 1000)},
        )
    with engine.begin() as connection:
        connection.execute(sa.text("ANALYZE shows"))
        connection.execute(sa.text("ANALYZE seasons"))
        connection.execute(sa.text("ANALYZE episodes"))
        # Probe a content_group that actually exists, or the timing is an index miss
        # dressed up as a measurement.
        return str(
            connection.execute(sa.text("SELECT content_group FROM episodes LIMIT 1")).scalar_one()
        )


def _explain(engine: sa.Engine, sql: str, params: dict[str, str]) -> tuple[str, float, int]:
    """Return the most specific scan node in the plan, the time, and the row count."""
    with engine.connect() as connection:
        matched = connection.execute(
            sa.text(f"SELECT count(*) FROM ({sql}) AS q"), params
        ).scalar_one()
        rows = connection.execute(sa.text(f"EXPLAIN (ANALYZE, BUFFERS) {sql}"), params).fetchall()
    plan = "\n".join(row[0] for row in rows)

    scans = [
        line.split("(")[0].strip().lstrip("-> ") for line in plan.splitlines() if "Scan" in line
    ]
    # Every index node, deduplicated — a UNION uses one per branch and reporting only
    # the first would undersell it.
    # Primary-key lookups are incidental join plumbing; the interesting nodes are the
    # secondary indexes we are actually testing.
    indexed = list(dict.fromkeys(s for s in scans if "Index" in s and "using pk_" not in s))
    scan = " + ".join(indexed) if indexed else (scans or ["<no scan node>"])[0]
    duration = float(plan.rsplit("Execution Time: ", 1)[-1].split(" ms")[0])
    return scan, duration, int(matched)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shows", type=int, default=20_000)
    parser.add_argument("--episodes", type=int, default=200_000)
    args = parser.parse_args()

    url = os.environ.get("BENCH_DATABASE_URL")
    if not url:
        print("Set BENCH_DATABASE_URL to an empty, throwaway database.", file=sys.stderr)
        return 2
    database = sa.engine.make_url(url).database or ""
    if "bench" not in database:
        # This drops the schema. Refuse anything that is not obviously disposable.
        print(
            f"Refusing to run against {database!r}: the database name must contain 'bench'.",
            file=sys.stderr,
        )
        return 2

    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            # Ask the server what it actually connected to. Parsing the URL is not
            # enough: `.../xbenchx?dbname=peblo_tv` passes a name check and then
            # connects somewhere else entirely.
            actual = connection.execute(sa.text("SELECT current_database()")).scalar_one()
            if "bench" not in str(actual):
                print(
                    f"Refusing to run: connected to {actual!r}, "
                    f"which is not a throwaway 'bench' database.",
                    file=sys.stderr,
                )
                return 2
            connection.execute(sa.text("DROP SCHEMA public CASCADE"))
            connection.execute(sa.text("CREATE SCHEMA public"))
    except sa.exc.OperationalError as exc:
        print(f"Cannot reach {database!r}: {exc.orig}", file=sys.stderr)
        return 2

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    print(f"loading {args.shows} shows / ~{args.episodes} episodes …")
    content_group = _load(engine, args.shows, args.episodes)

    with engine.connect() as connection:
        counts = {
            table: connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("shows", "episodes")
        }
    print(f"loaded: {counts}\n")
    print(f"{'query':<38} {'plan':<88} {'rows':>7} {'exec':>10}")
    print("-" * 146)
    for label, sql in QUERIES:
        scan, duration, matched = _explain(engine, sql, {"cg": content_group})
        print(f"{label:<38} {scan[:88]:<88} {matched:>7} {duration:>8.2f}ms")

    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
