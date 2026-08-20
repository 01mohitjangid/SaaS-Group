# What is wrong with `seed_shows.json`

95 rows, 8 shows, 76 content groups. The brief says the data is deliberately imperfect
and does not say where. This is what a full sweep found, and what the code does about
each one.

Every claim on this page — the defects **and** the "we checked, this is clean" rows — is
pinned by a test in `backend/tests/test_seed.py`, so the page cannot quietly go stale.
Counts include Season 0 trailers throughout.

## Blockers — publishing must refuse until these are fixed

### 1. `ep_9001` is a second Hindi version of an episode that already has one

```
ep_0003  motis-many-lives S1E2  en  "Rain on the Roof"     cg=motis-many-lives-s01e02
ep_0004  motis-many-lives S1E2  hi  "Rain on the Roof"     cg=motis-many-lives-s01e02
ep_9001  motis-many-lives S1E2  hi  "The Lost Kite (v2)"   cg=motis-many-lives-s01e02  ← duplicate
```

**Why it matters.** `content_group` is the rule that collapses language variants into one
catalogue entry. Two rows claiming `hi` means the catalogue cannot decide which one a
viewer gets — silently picking one would ship whichever row happened to sort first.

**What we do.** `uq_episodes_content_group_language` is a real database constraint, so the
row cannot be stored. The seed loader rejects it and names it; in step 2 the CRUD endpoint
returns 409 with the same message. The note that `ep_9001` also carries the *wrong title*
("The Lost Kite (v2)" is episode 1's title) is reported separately as a warning.

### 2. `ep_0036` is published with no artwork at all

`discover-india-with-moti` S1E4, `status: published`, `artwork_available: []`. It is the
only row in the file with an empty artwork list. An episode with no thumbnail renders as
a grey box in the episode list.

**What we do.** `episode.missing_artwork` blocker, naming the show, the episode and the
required 640×360 size.

## Warnings — publish proceeds, but an editor should see them

### 3. `rhyme-rangers` has `section: null` on all 8 rows

It is the only show with no section, and all 8 of its rows are drafts — so it does not
block publishing *today*. It can never be published as-is, because a published show with
no section has no row to appear in. Reported as a warning now, and the same rule turns it
into a blocker the moment someone publishes the show.

### 4. `ep_0078` has an uncapitalised title

`number-nest` S1E2 is `"rain on the roof"`. Every other title in the file is title case.
Cosmetic, but it is the kind of thing that ships to a TV screen.

### 5. The language versions of `motis-many-lives-s01e02` disagree on the title

Falls out of defect 1 — reported on its own so that fixing the duplicate does not hide it.

## Things that look wrong but are not

| Observation | Verdict |
|---|---|
| 16 of the 18 multi-language content groups have `en` and `hi` durations that differ (e.g. 510s vs 480s) | **Correct.** Dubs are a different length. The catalogue picks one deterministically at publish time. |
| `number-nest` has 6 published and 2 draft episodes | **Correct.** Normal editorial state; the drafts simply do not appear. |
| Season 0 rows `ep_0093` / `ep_0094` carry only a `thumbnail` | **Correct.** Trailers are episodes, and an episode only needs a thumbnail. Poster and banner belong to the show. |
| Hindi exists for only 3 of the 8 shows, and never covers all of one: 6 of `motis-many-lives`' 11 content groups, 6 of `peblo-songs`' 10, 6 of `tiny-tales-banyan-dadi`' 11 | **Correct.** This is precisely why each catalogue entry needs its own `languages` list rather than a show-level one. |
| `peblo-songs` and `peblo-songs-lyrical` are two shows in the same section with near-identical titles | **Correct**, but worth knowing — a naive search will return both for "peblo songs". |
| Categories, sections and languages | All values used are in `reference.json`. No unknown vocabulary in the file. |
| `episode_id` uniqueness, episode-number gaps, missing/blank fields, zero or negative durations | None found. |

## Shape of the data

```
slug                       rows  section     show status    languages (rows)   seasons
motis-many-lives             18  featured    published      en 11 · hi 7       0, 1
tiny-tales-banyan-dadi       17  series      published      en 11 · hi 6       0, 1
peblo-songs                  16  songs       published      en 10 · hi 6       1
peblo-songs-lyrical          10  songs       published      en 10              1
discover-india-with-moti     10  minisodes   published      en 10              1
curious-cubs                  8  series      published      en 8               1
number-nest                   8  series      published      en 8               1
rhyme-rangers                 8  (null)      draft          en 8               1
```

Counts include Season 0 trailers, and include `ep_9001` — the loader keeps every row so
the CMS can show it as broken; only the database insert refuses it. This table is asserted
verbatim in `test_the_shape_table_in_the_analysis_doc_matches_the_data`.

Season 0 exists for `motis-many-lives` and `tiny-tales-banyan-dadi` only — one trailer each.

## One rule with nothing to catch here

`content_group.spans_shows` reports a content group shared by two different shows, because
publishing collapses a group into a single catalogue entry and would silently merge them.
It blocks publishing once any member is published, and warns while they are all drafts.
`(content_group, language)` is unique database-wide, which is what makes that reachable at
all. The seed file does not contain such a case — the rule exists so the CMS cannot create
one.
