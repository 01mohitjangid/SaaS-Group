# Peblo TV Mini — four-step roadmap

The brief is one product surface with four layers. Rather than build a thin slice of
everything, each step below is shippable on its own and leaves the repo green.

```
Step 1  Foundation          schema · storage seam · validation rules · seeded data
   ↓
Step 2  Backend API         upload · CRUD · roles · atomic publish · catalog · search
   ↓
Step 3  Two React UIs       internal CMS · Netflix-style viewer
   ↓
Step 4  Pipeline & docs     compose all-up · CI · secrets · alerting · Part E write-up
```

## Step 1 — Foundation  ✅ done

Everything the API layer will stand on, proven against a real Postgres.

| Deliverable | Where |
|---|---|
| Postgres schema + one clean migration | `backend/alembic/versions/0001_initial_schema.py` |
| Storage abstraction (local disk ⇄ Cloudflare R2) | `backend/app/storage/` |
| `reference.json` as typed rules + artwork specs | `backend/app/domain/reference.py` |
| Publish-blocking rules engine (shared by seed *and* the future report endpoint) | `backend/app/domain/rules.py` |
| Seed loader + validation report | `backend/scripts/seed.py` |
| Health endpoints, and `/media/artwork` in local mode | `backend/app/api/health.py`, `backend/app/api/media.py` |
| Data-quality findings | [`DATA_ANALYSIS.md`](DATA_ANALYSIS.md) |

## Step 2 — Backend API  ✅ done

| Deliverable | Where |
|---|---|
| Auth: bearer → `users` row → role, enforced in every route signature | `backend/app/api/deps.py` |
| Artwork upload, validated on real decoded pixels | `backend/app/services/artwork.py` |
| CRUD with editor-readable 409s | `backend/app/api/admin_content.py` |
| Atomic, recorded, idempotent publish + rollback | `backend/app/services/publish.py` |
| The pure catalogue builder (variant collapsing, ordering) | `backend/app/domain/catalog.py` |
| `GET /catalog`, `/catalog/search`, `/catalog/shows/{slug}` | `backend/app/api/catalog.py` |
| CMS episode list and the reference endpoint its pickers read | `backend/app/api/admin_content.py`, `backend/app/api/admin_artwork.py` |
| Validation report and run history | `backend/app/api/admin_publish.py` |
| DB → domain views, one join | `backend/app/db/projections.py` |

Decisions made while building it:

| Decision | Why |
|---|---|
| The catalogue's **English** variant supplies the title, run time and thumbnail | Dubs differ in length and occasionally in title. One variant has to win; picking `en`, then the lowest language code, is arbitrary but stable — and stability is what makes re-publishing idempotent. |
| A show whose only live content is a trailer is **not** published | Season 0 is not a season, so such a show would render as an empty row. |
| `q` matches a category **exactly**, not by substring | Categories are a controlled vocabulary of 15 words. A substring match there produces confusing hits (“sing” matching “singalong”) rather than useful ones. |
| **Viewer search filters the published file; the CMS list queries the database** | We built it the other way first and it drifted: an unpublished rename made a show findable under its new name while showing its old one, and a CMS-published show appeared in search with a 404 detail link. Searching the document you serve makes that unrepresentable. The trigram indexes still earn their place — on the CMS list, which must show drafts and therefore cannot read the catalogue. |
| The `running` publish row is **committed** before any work starts | Flushing it was not enough: a crash rolled the row back, so the attempt vanished from history and the reaper had nothing to find. It also made the partial unique index useless — a competing publish blocked on the open transaction and then succeeded, instead of getting a 409. |
| A content group must live in **one show and one season** | The builder collapses variants within a season, so a group split across seasons silently shipped as two half-language episodes with nothing flagged. The rule previously only looked across shows. |
| Idempotent reuse checks **storage**, not just the database | Otherwise a wiped bucket — or exactly the local-disk→R2 migration Part E §2 describes — makes publish report "reused" while the catalogue is gone. |
| A stuck publish can be **cancelled**, not just waited out | The 15-minute lease is right for a machine and useless for a person with a correction to ship. The 409 now names the stuck run and its age. |
| `slug` carries a trigram index too | The CMS list searches `title OR slug`; indexing one of them indexes neither, because the `OR` forces a scan. See the table in **Measured, not assumed** for the plan on the shipped predicate. |
| Deleting a show or episode deletes its artwork objects too | Otherwise deleted images stay publicly served from the bucket forever. Rows first, then objects: a crash leaves a stray file rather than a row pointing at nothing. |
| Rollback was built, though it is a stretch item | Immutable run objects made it fifteen lines. Skipping it would have wasted the design. |
| A **draft** episode without artwork never blocks publishing | Editors work on drafts all day. Only what is going live has to be clean — a reviewer disagreed and was wrong. |

Original plan, for reference:

1. Auth dependency: bearer token → `users` row → role. `editor` = CRUD, `admin` = CRUD + publish.
2. `POST /admin/artwork` — Pillow reads real dimensions, `ArtworkSpec.check()` already
   returns the editor-readable errors, stored through `ObjectStorage`.
3. CRUD for shows / seasons / episodes, returning 409 with a readable message when
   `(content_group, language)` collides.
4. `POST /admin/catalog/publish` — build → write immutable `catalog/runs/<run_id>.json` →
   flip `catalog/current.json`. Recorded in `publish_runs`; identical content re-uses the
   previous checksum instead of churning storage.
5. `GET /catalog`, `GET /catalog/search`, `GET /admin/validation-report`.
6. Tests: variant collapsing, publish atomicity, role enforcement, search composition.

### Measured, not assumed

`make bench` loads 20k shows / 220k episodes into a throwaway database and prints the
real plans — the predicates the endpoints actually emit, not simplified ones. The
planted terms are seeded, so plans and row counts reproduce exactly; only timings move.

```
query                                  plan                                                                                        rows       exec
--------------------------------------------------------------------------------------------------------------------------------------------------
shows · rare term                      Bitmap Index Scan on ix_shows_title_trgm                                                      40     0.18ms
episodes · rare term                   Bitmap Index Scan on ix_episodes_title_trgm                                                  200     1.28ms
shows · common term (~10% of rows)     Seq Scan on shows                                                                           1854     5.79ms
shows · published + rare term          Bitmap Index Scan on ix_shows_title_trgm                                                       8     0.17ms
shows · published in one section       Bitmap Index Scan on ix_shows_section_published                                             1000     0.39ms
episodes · collapse one content group  Index Scan using uq_episodes_content_group_language on episodes                                2     0.01ms
shows · two-character term             Seq Scan on shows                                                                           1854     6.06ms
cms · show list, title OR slug         Bitmap Index Scan on ix_shows_title_trgm + Bitmap Index Scan on ix_shows_slug_trgm            40     0.39ms
cms · episode list, joined + filtered  Bitmap Index Scan on ix_episodes_title_trgm                                                  200     1.60ms
```

Four things to read out of that, honestly:

* **`title OR slug` is only indexable if both columns are indexed.** With a trigram
  index on `title` alone the CMS list sequentially scanned — an `OR` where one side has
  no index disables the other side too. Both are indexed and the planner uses a
  `BitmapOr`. This is the trap that keeps turning up, and it is why the benchmark
  measures the shipped predicate rather than a tidy one.
* **Indexes help selective terms, not all terms.** A rare word uses the index in
  0.18 ms; a word matching ~10% of rows is correctly seq-scanned. That is the planner
  being right, and it is the real answer to "at what size does search stop working" —
  the ceiling is selectivity, not row count.
* **Two-character terms always seq-scan.** The trigram floor, not tuning.
* **Every index here backs a query someone actually runs.** Two did not and were
  removed rather than defended: the GIN on `categories` (its only consumer moved to the
  viewer, which filters the published document) and an extra btree on `content_group`
  (the unique constraint already leads with it).

The viewer touches none of this — it reads the published file. These indexes exist for
the CMS, which must show drafts and therefore cannot read the catalogue. The one
un-indexed CMS shape is `GET /admin/shows?language=`, which scans; at CMS scale that is
a few milliseconds and not worth an index.

### Carried into step 3

* **Search below three characters** scans rather than using an index. Viewer search
  filters the published document, so this only affects the CMS list; it is a few
  milliseconds at CMS scale and not worth an index.
* **`GET /admin/shows?language=`** is the one un-indexed CMS shape (it walks seasons and
  episodes). Same reasoning: cheap enough at this size, and stated rather than hidden.
* **Artwork URLs are not content-addressed**, so replacing an image reuses its URL when
  the format is unchanged and a CDN can serve stale bytes. Either version the key or send
  a short `max-age` before putting a CDN in front of `/media`.
* **The publish lease has no fencing.** A run reaped after 15 minutes could in principle
  still be alive and still flip the pointer. Both outcomes are complete catalogues, so the
  exposure is "possibly the older build wins", not a corrupt read — but at a size where a
  publish took minutes this would need a fencing token.

## Step 3 — Two React UIs

* **CMS** (`frontend/cms`) — list with search/filters/pagination, edit form with three
  labelled artwork slots and live previews, publish page with the validation report and
  run history, all four states (loading / empty / error / permission-denied). TanStack Query.
* **Viewer** (`frontend/viewer`) — reads `GET /catalog` only, never an admin endpoint.
  Hero uses the banner, rows use posters, episode lists use thumbnails. Season 0 is
  rendered as "Trailers", never as a season.

## Step 4 — Pipeline & operability

`docker compose up` brings up db + api + both UIs seeded; GitHub Actions running
`scripts/check.sh` plus image builds and an explained deploy step; `.env.example`
completed; the Part E written answers in the README.

## Deliberate decisions so far

| Decision | Why |
|---|---|
| Poster + banner belong to the **show**; thumbnail belongs to the **episode** | Matches the surfaces in Part C. It also makes the Season 0 trailers correct rather than broken: they ship only a thumbnail, which is all an episode needs. |
| A show is `published` if **any** episode is | The seed has no show-level status. Anything stricter would hide `number-nest`, which has 6 published and 2 draft episodes. |
| `ep_9001` is **rejected**, not repaired or force-imported | `(content_group, language)` is a database constraint. Bending it to import a known-bad row would prove the constraint is decorative. It is reported instead. |
| Trigram indexes sit on the **raw** `title` column | A btree on `lower(title)` is never chosen for `LIKE '%kite%'`, and a trigram index on `lower(title)` only fires for that exact spelling — not for the `ILIKE` an ORM emits. `make bench` reproduces the plans; see **Measured, not assumed** above. |
| Artwork keys are built from **database ids**, never slugs or external ids | A slug is editable and an external id is NULL for CMS-created rows. Keying on either lets one show's upload overwrite another's bytes. |
| `status = 'running'` on `publish_runs` carries a partial unique index | Atomic writes stop a torn read but not two admins interleaving. One publish in flight at a time, enforced by Postgres. |
| `/media` exposes only the `artwork/` subtree | The same storage root holds the published catalogue and the validation report. Mounting the root would have published both. |
| `API_TOKENS` is optional | It is bootstrap only — `scripts/seed.py` turns it into `users` rows, and the API authenticates against that table. A production API should not need to hold tokens it never reads. |
| Static bearer tokens in `API_TOKENS`, materialised as `users` rows | Keeps role enforcement real and testable without standing up an IdP for a take-home. |
| Language-variant duration drift is accepted, not flagged | Hindi dubs are genuinely a different length. The catalogue will pick one deterministically at publish time. |
| Sample `assets/` images were not in the shared Drive folder | Placeholder artwork is generated at exact spec instead (`backend/scripts/artwork.py`), so every show really has files. The upload endpoint in step 2 is what enforces the specs on real uploads. |
