# Peblo TV Mini

CMS upload → published catalogue → Netflix-style browse.

A take-home for Peblo: three layers and the pipeline that runs them. Built as four steps,
each one green before the next started.

| | |
|---|---|
| **Viewer** | **https://peblo-tv-mini-five.vercel.app** |
| **CMS** | **https://peblo-tv-mini-five.vercel.app/admin** |
| **API** | https://peblo-tv-mini-five.vercel.app/api/healthz |

---

## Try it

Open the **CMS** and sign in with one of these:

```
prod-admin-change-me      admin   — edit content and publish
prod-editor-change-me     editor  — edit content, cannot publish
```

> Demo credentials for review only. Real deployments use `API_TOKENS`, which maps a
> bearer token to a role; the API authenticates against the `users` table, never against
> that setting.

**Worth clicking, in this order:**

1. **Shows → any show.** Three artwork slots state the required shape, size and weight
   *before* you choose a file. Upload a square as the poster — the error names the shape,
   your actual size, and how to fix it.
2. **Publish, signed in as the editor.** The button is disabled with the reason spelled
   out. Roles are enforced in the API, not hidden in the UI.
3. **Publish, signed in as the admin.** The validation report is grouped by show. Publish,
   then publish again — the second says *nothing had changed* and leaves the live file
   untouched.
4. **Back to the viewer.** Your change is live. A grouped episode shows one row with an
   English/हिन्दी toggle, not two rows. Trailers are their own shelf, never a season.

The API sleeps after a few minutes idle on the free tier, so the first request may take a
moment.

---

## Run it locally

Everything, seeded and working, in one command:

```bash
docker compose up --build
```

| | |
|---|---|
| Viewer | http://localhost:5174 |
| CMS | http://localhost:5173 — sign in with `dev-editor-token` or `dev-admin-token` |
| API | http://localhost:8000 |

Or piece by piece, which is what you want for the tests:

```bash
cp .env.example .env             # defaults work as-is
make db                          # Postgres + the database the tests use
cd backend && uv venv --python 3.12 && uv pip install -e ".[dev]" && cd ..

make migrate                     # alembic upgrade head
make seed                        # load the 95 seed rows, print the validation report
make api                         # http://localhost:8000
make ui                          # CMS on 5173, viewer on 5174 (Node 22+)
```

**Checks — the same set CI runs:**

```bash
./scripts/check.sh               # ruff · mypy · pytest · prettier · eslint · tsc
```

Use `make db`, not `docker compose up -d db`: the schema tests need a separate
`peblo_tv_test` database that only `make db` creates. They **skip** rather than fail when
Postgres is unreachable, so a green run with skips means the schema is unverified — the
script says so, and `STRICT_TESTS=1` turns a skipped test into a failure.

```bash
make bench                       # measure the real query plans (see docs/ROADMAP.md)
make artwork                     # re-fetch the show photographs (already committed)
```

---

## How it works

```
CMS ──► API ──► publish job ──► catalog/runs/<id>.json   (immutable)
                                        │
                                        ▼
                               catalog/current.json      (one atomic pointer write)
                                        │
Viewer ◄────────────────────────────────┘
```

The viewer reads the published file and nothing else. Its route handlers take no database
session at all — a test asserts it — so it cannot reach unpublished content by mistake,
and its bundle contains no admin path and no token.

| Endpoint | Who | What |
|---|---|---|
| `GET /catalog` | anyone | The published file, via a pointer to an immutable run |
| `GET /catalog/search` | anyone | `q` over show title, episode title and category; filters compose |
| `GET /catalog/shows/{slug}` | anyone | One show, read from the published file |
| `GET /admin/reference` | editor | Sections, categories, languages, artwork specs |
| `GET /admin/shows`, `/admin/episodes` | editor | Lists with search, filters, pagination |
| `POST/PATCH/DELETE /admin/shows`, `…/episodes` | editor | CRUD, with 409s an editor can act on |
| `POST /admin/artwork` | editor | Three sizes, validated on decoded pixels |
| `GET /admin/validation-report` | editor | Everything blocking publish, grouped by show |
| `POST /admin/catalog/publish` | **admin** | Build → immutable object → atomic pointer flip |
| `POST /admin/catalog/rollback/{run}` | **admin** | Re-point at an earlier run |
| `GET /admin/publish-runs` | editor | Who, when, counts, outcome, rollbacks, reuses |
| `GET /healthz`, `/readyz` | anyone | Liveness, and readiness per dependency |

The main surface, not the full list — the rest (artwork specs, per-owner artwork, run
cancellation, `whoami`) is at **[/api/docs](https://peblo-tv-mini-five.vercel.app/api/docs)**.

**Stack.** FastAPI · SQLAlchemy 2 · Alembic · Postgres · React 19 · TypeScript · Vite ·
TanStack Query · shadcn-style components on Radix and Tailwind.

**Deployed** as one Vercel project — viewer at `/`, CMS at `/admin`, API as a Python
function at `/api` — against Neon Postgres. One origin, so no CORS at all.

---

## The seed data is deliberately imperfect

A full sweep found **2 publish blockers, 3 warnings, and six findings that look like
defects but are not**. The headline is `ep_9001`, a second Hindi version of an episode
that already has one — rejected by a database constraint rather than repaired or
force-imported.

Every claim in [`docs/DATA_ANALYSIS.md`](docs/DATA_ANALYSIS.md) is pinned by a test, so the
page cannot go stale. Design decisions and the measured query plans are in
[`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## Written reasoning

### 1. Atomic publishing, and what happens if the process dies

Nothing is ever written over the live catalogue. A run writes an immutable object at
`catalog/runs/<run_id>.json`, then flips a small pointer at `catalog/current.json` naming
it. Writing one object is atomic in every backend — a rename on disk, a single PUT to R2,
one `INSERT … ON CONFLICT` in Postgres — so a reader following the pointer gets the whole
old catalogue or the whole new one. The file was finished before the pointer named it, so
a half-written catalogue is not representable.

The `running` row is **committed before any work starts**. That is load-bearing twice: a
flushed-but-uncommitted row rolls back on a crash, leaving no trace of the attempt, and it
makes the partial unique index useless — a competing publish would block on the open
transaction and then succeed rather than being refused.

If the process dies before the flip, the old catalogue is still live and the only debris is
an unreferenced object. If it dies after, the publish already succeeded. Either way the
dead run still holds the slot, so recovery works two ways: automatically after 15 minutes,
and immediately via `POST /admin/publish-runs/{id}/cancel` — someone shipping a correction
should not have to wait out a lease. Until then a further publish gets a 409 naming the
stuck run and its age.

Idempotency is a digest of the catalogue's *content*, version and timestamp excluded. An
unchanged publish writes nothing. It also checks that the live pointer still names the
previous run: existence is not identity, and after a rollback the newest successful run is
not the live one.

### 2. Moving storage from local disk to Cloudflare R2

`STORAGE_BACKEND=s3` plus four `S3_*` variables. Nothing else — `ObjectStorage` is five
methods and `build_storage` has one branch.

**We proved it by doing the same thing to a third backend.** Deploying needed somewhere for
artwork to live and R2 wants a payment card, so the seam grew `PostgresStorage` — artwork in
the same Neon database — and the deployment runs on it. That was one ~90-line class, one
migration, and one branch. No route, service or test outside the storage layer moved.

The trade-off, plainly: bytes travel through the API rather than from a bucket edge, so
there is no CDN. Artwork keys are content-addressed, so those responses are `immutable` and
cached forever by the browser, which is most of what a CDN would have bought. It stops
being right at the size where a single published catalogue file also stops being right.

### 3. Search: how, where it stops working, what is next

`GET /catalog/search` filters the **published document** — the same one `/catalog` serves —
server-side. It is pure logic, unit-tested without a database, and the viewer takes no
database session.

We built it the other way first and it drifted: a show renamed but not yet published became
findable under its *new* name while displaying its *old* one, and a CMS-published show
appeared in search with a detail link that 404'd. Searching the document you serve makes
that class of bug unrepresentable.

Cost is linear in the catalogue, so the ceiling is the published file itself — at the size
one file makes sense for, it is microseconds and the network dominates. Beyond that, search
should be an index built *at publish time* so it cannot drift, then a real search engine.

The database's trigram indexes serve the **CMS**, which must show drafts and so cannot read
the catalogue. `make bench` measures the predicates those endpoints actually emit: a
selective term uses the index in 0.18 ms, a term matching ~10% of rows is correctly
seq-scanned, and `title OR slug` is only indexable because *both* columns are indexed — an
`OR` where one side has no index disables the other side too.

### 4. Why serve a pre-published file at all

Because publishing is an editorial act. The viewer shows what an admin last approved, not
whatever is mid-edit, and the home page is one object read whatever the catalogue contains.
It also makes rollback nearly free: the old run's bytes were never overwritten, so going
back is the same single pointer write as going forward.

Where it bites: staleness becomes something you can forget about — a correction sits
invisible until someone publishes. One file means one blast radius and a full rebuild for a
one-word fix. And it forces search to choose between consistency and indexes; we chose
consistency and wrote down the size at which that stops being right.

### 5. What is left out, and where AI was used

**Left out:** the CI workflow. A publish *dry-run* showing a diff and an audit log of who
changed what are unbuilt; versioned rollback — the third stretch item — is done, because the
immutable-run design made it fifteen lines. No rate limiting and no pagination on `/catalog`;
at 95 rows neither earns its complexity.

**AI:** built with Claude Code driving a maker/checker loop — code is written, then
independent reviewer agents run the checks and audit the diff, and findings are fixed before
moving on. That caught real defects, not typos: `/media` initially served the whole storage
root, exposing the internal validation report; artwork keys were built from the mutable
`slug`, so renaming one show could overwrite another's poster; the trigram indexes were
first written on `lower(title)`, where an ORM's `ILIKE` never uses them; a crashed publish
left no run row at all, quietly making the whole crash-recovery story above false; and a
"fix" to the layering test was in the file but never actually called.

Where the reviewers were wrong I said so — one insisted a draft episode without artwork
should block publishing, which would make the CMS unusable. Every claim in
`docs/DATA_ANALYSIS.md` is pinned by a test for the same reason: an assertion nobody checks
is just a nice sentence.

---

## Time spent

| Part | Roughly |
|---|---|
| Foundation — schema, storage seam, validation rules, seed loader | 4h |
| Backend — upload, CRUD, roles, publish, catalogue, search | 5h |
| CMS + viewer | 5h |
| Artwork, deployment, review loops | 3h |

Review passes are inside those numbers, not on top of them — roughly a third of the total,
and the reason the list of defects above exists.

---

## Not done

The GitHub Actions workflow, and the operability write-up that goes with it — the secrets
paragraph and the one alert worth having. Everything else the brief asks for is built,
running, and covered by `./scripts/check.sh`.
