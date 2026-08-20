# Peblo TV Mini

CMS upload → published catalogue → Netflix-style browse.

**Status: step 1 of 4 complete.** The plan and what each step contains is in
[`docs/ROADMAP.md`](docs/ROADMAP.md). Step 1 is the foundation: schema, storage seam,
validation rules and seeded data — all proven against a real Postgres, not sketched.

## Run it

The short way — migrates, seeds and serves in one step:

```bash
docker compose up --build        # API on http://localhost:8000
```

Or locally, which is what you want in order to run the tests:

```bash
cp .env.example .env             # the API reads this; the defaults work as-is
make db                          # Postgres 16 + the database the tests use
cd backend && uv venv --python 3.12 && uv pip install -e ".[dev]" && cd ..

make migrate                     # alembic upgrade head
make seed                        # load the 95 seed rows and print the validation report
make api                         # http://localhost:8000
```

Then:

```bash
curl localhost:8000/healthz
curl localhost:8000/readyz
# `make seed` prints one artwork URL you can open directly
```

Checks — lint, types and tests, the same set CI will run in step 4:

```bash
make check                       # ./scripts/check.sh
```

**Use `make db`, not `docker compose up -d db`.** The schema tests connect to a separate
`peblo_tv_test` database that only `make db` creates. They **skip** rather than fail when
Postgres is unreachable, so a green gate with skips there means the schema is unverified,
not that it passed. `scripts/check.sh` prints the skip list for exactly this reason,
and step 4's GitHub Actions workflow runs the same script.

## What step 1 built

```
seed_shows.json ──► domain/seed.py ──► domain/rules.py ──► validation report
                          │                                      │
                          ▼                                      ▼
                    Postgres (alembic)                    editor-readable issues
                          │
                          ▼
                  storage abstraction  ──►  local disk today, Cloudflare R2 in production
```

* **Schema** — `shows → seasons → episodes`, plus `artwork` and `publish_runs`, in one
  hand-checked migration that upgrades, downgrades and reports no drift against the models.
* **`(content_group, language)` is a database constraint**, not an application check. That
  is what makes the language-variant rule survive two editors saving at once.
* **Storage abstraction** — `ObjectStorage` is five methods. `LocalDiskStorage` writes to a
  temp file and renames, so `put` is atomic; `S3CompatibleStorage` is the same contract
  against R2/MinIO/S3. Swapping is `STORAGE_BACKEND=s3` plus the `S3_*` variables.
* **One rules engine** — the seed report and step 2's `GET /admin/validation-report` call
  the same `evaluate()`, so an editor is never told two different stories.
* **Seeding is idempotent** — running it twice inserts nothing the second time, and
  `backend/tests/test_seed_integration.py` proves it against a real database.
* **The schema is tested, not asserted** — `backend/tests/test_migrations.py` runs the real
  migration against Postgres and proves each constraint rejects what it claims to: a second
  `hi` variant of one content group, a poster attached to an episode, a second poster on one
  show, a second publish run in flight. It also fails on any drift between models and migration.
* **`/media` serves artwork only.** The published catalogue and the validation report live
  in the same storage root and are deliberately not reachable through it.
* **Index claims are reproducible, not asserted** — `make bench` loads 20k shows / 220k
  episodes into a throwaway database and prints the real query plans. The output is in
  [`docs/ROADMAP.md`](docs/ROADMAP.md), including the three cases where an index is
  deliberately *not* used and the one case where the obvious query shape is simply wrong.

## The seed data

It is deliberately imperfect. [`docs/DATA_ANALYSIS.md`](docs/DATA_ANALYSIS.md) has the full
sweep: **2 publish blockers, 3 warnings, and five findings that look like defects but are
not.** The headline is `ep_9001`, a second Hindi version of an episode that already has one.
It is rejected by the database rather than repaired or force-imported.

Running the seed prints the report (abridged here; the real output adds a
`→ <how to fix it>` line under every issue, and a ready-made artwork URL at the end):

```
Seeded from 95 rows:
  shows=8 seasons=10 episodes=94 artwork=109 users=2

  1 row(s) rejected — uq_episodes_content_group_language would refuse them:
    - ep_9001: content group 'motis-many-lives-s01e02' already has a 'hi' version

Validation: 2 blocker(s), 3 warning(s)
  [BLOCK] content_group:motis-many-lives-s01e02: 2 episodes claim to be the hi version
          of “motis-many-lives-s01e02”: ep_0004, ep_9001. Only one can be.
  [BLOCK] episode:ep_0036: “The Midnight Market” (discover-india-with-moti S1E4) has no
          thumbnail image.
  [ warn] content_group:motis-many-lives-s01e02: The language versions have different titles.
  [ warn] episode:ep_0078: “rain on the roof” (number-nest S1E2) is not capitalised …
  [ warn] show:rhyme-rangers: “Rhyme Rangers” has no section, so there is no row to show it in.
```

(95 rows in, 94 episodes out. `users=2` on a first run; re-seeding upserts them and reports 0.)

## Decisions and trade-offs so far

See the table at the end of [`docs/ROADMAP.md`](docs/ROADMAP.md). The two that will matter
most later:

1. **Poster and banner belong to the show; thumbnail belongs to the episode.** This mirrors
   the surfaces in Part C and makes Season 0 trailers correct instead of broken.
2. **The sample `assets/` images were not in the shared Drive folder**, so seeding generates
   placeholder artwork at exact spec (600×900, 1280×720, 640×360, all under 200 KB). The
   upload endpoint in step 2 is what enforces the specs on real uploads — the generator is
   scaffolding, not the validation.

## Not done yet

Everything in steps 2–4: the API surface, both React apps, CI, and the Part E written
answers. Nothing in this repo pretends otherwise — there is no frontend directory and the
gate reports the frontend checks as skipped.
