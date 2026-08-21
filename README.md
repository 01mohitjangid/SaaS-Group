# Peblo TV Mini

CMS upload → published catalogue → Netflix-style browse.

**Status: steps 1–3 of 4 complete.** The plan is in [`docs/ROADMAP.md`](docs/ROADMAP.md).
Step 1 built the foundation (schema, storage seam, validation rules, seeded data), step 2
the whole backend (upload, CRUD, enforced roles, atomic publish, catalogue and search),
and step 3 the two React apps — an internal CMS and a Netflix-style viewer, built with
shadcn-style components on Radix and Tailwind. Step 4 is CI and the operability write-up.

## Run it

The short way — migrates, seeds and serves the whole stack in one step:

```bash
docker compose up --build
```

| | |
|---|---|
| **CMS** | http://localhost:5173 — sign in with `dev-editor-token` or `dev-admin-token` |
| **Viewer** | http://localhost:5174 |
| **API** | http://localhost:8000 |

Or locally, which is what you want in order to run the tests:

```bash
cp .env.example .env             # the API reads this; the defaults work as-is
make db                          # Postgres 16 + the database the tests use
cd backend && uv venv --python 3.12 && uv pip install -e ".[dev]" && cd ..

make migrate                     # alembic upgrade head
make seed                        # load the 95 seed rows and print the validation report
make api                         # http://localhost:8000

make ui                          # both React apps: CMS 5173, viewer 5174 (needs Node 22+)

make artwork                     # optional: re-fetch the show photographs (already committed)
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

## The API

| Endpoint | Who | What |
|---|---|---|
| `GET /catalog` | anyone | The published file, via the pointer to an immutable run object |
| `GET /catalog/search` | anyone | `q` over show title, episode title and category; `section`/`category`/`language` compose. Filters the published file — never the database |
| `GET /catalog/shows/{slug}` | anyone | One show, read from the published file |
| `GET /admin/reference` | editor | Sections, categories, languages, statuses and artwork specs — the CMS's single source for its pickers |
| `GET /admin/shows` | editor | List with search, filters and pagination |
| `GET /admin/shows/{id}` | editor | One show with all of its episodes |
| `GET /admin/episodes` | editor | Episode list across every show — search, status/language/season filters, pagination |
| `POST /admin/shows`, `PATCH /admin/shows/{id}`, `DELETE /admin/shows/{id}` | editor | Show CRUD, with 409s an editor can act on |
| `POST /admin/shows/{id}/episodes` | editor | Add an episode, creating its season if needed |
| `PATCH /admin/episodes/{id}`, `DELETE /admin/episodes/{id}` | editor | Episode CRUD |
| `POST /admin/artwork` | editor | Three sizes, validated on real pixels |
| `GET /admin/artwork/{owner}/{id}` | editor | What is currently uploaded for a show or episode |
| `DELETE /admin/artwork/{id}` | editor | Remove an image (and its object) |
| `GET /admin/artwork/specs` | editor | What each slot requires, so the CMS can show it |
| `GET /admin/validation-report` | editor | Everything blocking publish, grouped by show |
| `POST /admin/catalog/publish` | **admin** | Build → immutable run object → atomic pointer flip |
| `POST /admin/catalog/rollback/{run}` | **admin** | Re-point at an earlier run |
| `GET /admin/publish-runs` | editor | Run history: who, when, counts, outcome, rollbacks and reuses |
| `POST /admin/publish-runs/{run}/cancel` | **admin** | Release a slot held by a run whose process died |
| `GET /healthz`, `/readyz` | anyone | Liveness, and readiness per dependency |

An editor calling `POST /admin/catalog/publish` gets 403 with a sentence, not a 404.
Roles are dependencies in each route's signature, so the check cannot be quietly
deleted, and `backend/tests/test_api_auth.py` enumerates every `/admin` operation **from
the app's own OpenAPI schema** and asserts each one rejects an anonymous caller — so a
route added tomorrow is covered tomorrow, not whenever someone remembers that file.

The viewer routes take no database session at all — `test_no_viewer_route_takes_a_database_session`
enumerates every handler in that module rather than naming them — so they cannot reach
unpublished content even by mistake.

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
  [`docs/ROADMAP.md`](docs/ROADMAP.md) — including the cases where an index is correctly
  *not* used, and the two indexes that were **removed** once nothing queried them.

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
2. **The sample `assets/` images were not in the shared Drive folder.** Each show instead
   has one real photograph in `data/artwork/<slug>/source.jpg`, fetched once by
   `make artwork` and **committed** — seeding then crops it to a poster (600×900), a
   banner (1280×720) and a thumbnail per episode (640×360), washes it in the show's colour
   and lays the title over a scrim. Photographs come from `picsum.photos`, which serves
   Unsplash images without an API key; set `UNSPLASH_ACCESS_KEY` and the fetcher searches
   Unsplash on each show's own categories instead, which is what makes a poster actually
   look like its programme. Delete the files and seeding falls back to generated abstract
   artwork — **nothing in the seed path touches the network**, because a seed that needs
   the internet turns "compose works first try" into a coin flip.

## The two UIs

Both are React + TypeScript + Vite in one pnpm workspace, sharing a typed API client and
a component set (`frontend/shared`). Components follow shadcn/ui — Radix primitives,
Tailwind, and the code owned in-repo rather than pulled from a package — on a Netflix
palette: near-black ground, one saturated red kept for the action that changes what
viewers see, and a grey ramp doing the structural work. TanStack Query handles fetching,
caching and invalidation; a content change invalidates the validation report, so the
publish button's reasons can never be stale.

**Viewer** (`frontend/viewer`) reads the published catalogue and nothing else — the three
route handlers take no database session and the built bundle contains no `/admin` path
and no token. Featured hero uses the banner, browse rows use posters, episode lists use
thumbnails. Season 0 is a separate Trailers shelf, never a season. A grouped episode is
one row with its languages as a choice. Slow images hold their aspect ratio, shimmer,
then fade in; a failed one keeps its frame and shows the title so the row stays navigable.

**CMS** (`frontend/cms`) is built for someone doing this fifty times a week: dense
tables, filters in the URL so a view is shareable, and errors that appear next to the
field that caused them. The three artwork slots state the required shape, size and weight
*before* a file is picked, preview the local file immediately, and show the API's own
sentence when it is rejected — the browser never decides what is acceptable. The publish
button is disabled with every reason listed, and the validation report links to the show
that needs fixing.

## Written reasoning (Part E)

### 1. How publishing is atomic, and what happens if the process dies mid-publish

Nothing is ever written over the live catalogue. A run writes an immutable object at
`catalog/runs/<run_id>.json` and then flips a small pointer at `catalog/current.json`
that names it. Writing one object is atomic on both backends — local disk writes a temp
file and renames, R2 completes a PUT or does not — so a reader following the pointer
gets either the whole old catalogue or the whole new one. The file it reads was finished
before the pointer named it, so a half-written catalogue is not representable.

If the process dies **before** the flip, the old catalogue is still live and the only
debris is an unreferenced object. If it dies **after**, the publish already succeeded and
only the bookkeeping row is stale. Either way the run row survives, because it is
**committed before any work begins** — a flushed-but-uncommitted row would roll back and
the crash would leave no trace at all.

That dead run still holds the publish slot, and recovering from that has to work two
ways: automatically after 15 minutes, and immediately via `POST /admin/publish-runs/{id}/cancel`
— a person shipping a correction should not have to wait out a lease. Until one happens,
a further publish gets a 409 naming the stuck run and its age, not a vague "wait for it
to finish". Concurrency itself is Postgres's job: `uq_publish_runs_one_running` is a
partial unique index over a committed row, so a genuine race is refused rather than
queued. `test_a_hard_crash_leaves_a_visible_running_row_for_the_reaper` kills the worker
with a `BaseException` so no handler runs, and asserts the row survives; the rollback
path has the same failure handling, so the one operation you reach *because* the
catalogue is already wrong cannot also jam the slot.

Idempotency comes from a digest of the catalogue's *content* — version and timestamp
excluded, since those always differ. A publish that produces the same digest as the last
successful one writes nothing and leaves the pointer alone. It also checks storage before
deciding that: the database alone cannot know whether the bytes are still there, and a
DB-only check would report "succeeded, reused" after a wiped bucket while `/catalog`
returned 503 forever.

### 2. Moving the storage abstraction from local disk to Cloudflare R2

`STORAGE_BACKEND=s3` plus the four `S3_*` variables. Nothing else. `ObjectStorage` is
five methods; `LocalDiskStorage` and `S3CompatibleStorage` implement it and `build_storage`
has one branch. R2 speaks the S3 API, so the same class covers R2, MinIO and AWS S3 —
only the endpoint differs.

Two things actually change in production. The API stops serving `/media` (the mount is
only registered for the local backend) and the bucket's own domain serves artwork, so
`S3_PUBLIC_BASE_URL` must be set or `url_for` falls back to signed URLs. And local disk's
atomicity is *visibility*, not durability: the file is fsynced but its parent directory
is not, so a power cut in the microsecond after the rename can lose the directory entry.
R2 has no such gap. That is fine here — a lost publish is re-run and recorded as failed.

### 3. Search: how, where it stops working, and what is next

`GET /catalog/search` filters the **published document** — the same one `/catalog`
serves — server-side. It is pure logic (`app/domain/search.py`), so it is unit-tested
without a database and the viewer takes no database session at all. `q` matches a show
title or an episode title by case-insensitive substring, and a category **exactly**;
categories are a controlled vocabulary of fifteen words, where substring matching
produces confusing hits rather than useful ones.

We tried the other way first and it was wrong. Indexing the database and serving the
file means the two drift the moment an editor saves without publishing: a show renamed
but not yet published became findable under its *new* name while displaying its *old*
one, and a show published in the CMS but not in a run appeared in search with a detail
link that 404'd. Searching the document you serve makes that class of bug unrepresentable.

**Where it stops working:** cost is linear in the catalogue, so the ceiling is the
published file itself, not this function — at the size one file makes sense for
(thousands of shows) it is microseconds and the network dominates. When the catalogue
outgrows one document, search should become an index built *at publish time* — a
`search_documents` table with one `tsvector` per show, refreshed by the publish job so it
can never drift — and after that a real search engine.

**The database's trigram indexes serve the CMS, not the viewer.** `GET /admin/shows` and
`GET /admin/episodes` have to show drafts, so they cannot read the catalogue and must
query rows. `make bench` measures the predicates those endpoints actually emit, not
simplified ones — that distinction matters, because the show list searches `title OR
slug`, and with a trigram index on only one of them the `OR` drags the whole query into
a sequential scan. Both columns are indexed, and the benchmark shows the planner using a
`BitmapOr` across the pair rather than a scan. A term matching ~10% of rows is still correctly
seq-scanned; that is the planner being right, and it is the honest answer to "at what
size does search stop working" — the ceiling is selectivity, not row count.

### 4. Why serve a pre-published file at all, and where that bites

Because publishing is an editorial act. The viewer shows exactly what an admin last
approved, not whatever happens to be in the database mid-edit, and the home page is one
object read whatever the catalogue contains — no joins, no N+1, and it can sit behind a
CDN. It also makes rollback nearly free: the old run's bytes were never overwritten, so
going back is the same single pointer write as going forward.

Where it bites: **staleness is now something you can forget about.** A correction sits
invisible until someone publishes — the CMS shows the last run in its history partly so
that is hard to miss. It bites again on size: one file means one blast radius and a full
rebuild for a one-word fix, so at a catalogue large enough to matter you would shard per
section. And it forces search to choose between consistency and indexes; we chose
consistency (§3) and wrote down the size at which that stops being the right call.

### 5. What is left out, and where AI was used

**Left out on purpose:** the CI workflow and the operability write-up (step 4, not
skipped — not yet reached). A publish *dry-run* showing a diff, and an audit log of who
changed what, are still unbuilt; versioned rollback, the third stretch item, is done
because the immutable-run design made it fifteen lines. There is no rate limiting and no
pagination on `/catalog` — at 95 rows neither earns its complexity yet. The CMS has no
drag-to-reorder, which is why the episode-number constraint being non-deferrable is
acceptable.

**AI:** this repo was built with Claude Code driving a maker/checker loop — the code is
written, then independent reviewer agents run the checks and audit the diff, and the
findings are fixed before moving on. That caught real defects, not typos: `/media`
initially served the whole storage root (exposing the internal validation report),
artwork keys were built from the mutable `slug` (so renaming one show could overwrite
another's poster), the trigram indexes were first written on `lower(title)` where an
ORM's `ILIKE` never uses them, and a "fix" to the layering test was in the file but never
actually called. It also caught that a crashed publish left *no* run row at all, because
the `running` row was flushed but never committed — which quietly made the whole
crash-recovery story in §1 false until it was fixed. Where the reviewers were wrong I said
so and moved on — one insisted a draft episode without artwork should block publishing,
which would make the CMS unusable.
Every claim in `docs/DATA_ANALYSIS.md` is pinned by a test for the same reason: an
assertion nobody checks is just a nice sentence.
