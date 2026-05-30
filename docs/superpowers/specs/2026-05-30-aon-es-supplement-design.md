# PF_Helper — AON Elasticsearch Supplement (Design Spec)

**Date:** 2026-05-30
**Status:** Approved (brainstorming)
**Builds on:** `docs/superpowers/specs/2026-05-29-pf-helper-mcp-design.md` (the base MCP server, now shipped on `main`).

## Goal

Add Pathfinder 2e content that the FoundryVTT compendium does **not** ship as
clean item documents — traits, skills, archetypes, narrative rules, and a
curated set of other AON-only categories — by pulling it from the **Archives of
Nethys (AON) Elasticsearch** index. The new content flows into the **same**
SQLite + FTS5 index and is served by the **same** `search` / `get_entry` MCP
tools. Additionally, every result (Foundry- or AON-sourced) gains a `source_url`
so Claude can link the user to the AON page.

This is a pure-retrieval extension: no LLM calls, no network at query time.

## Non-goals (v1)

- No AON content for categories Foundry already covers well (spell, feat,
  creature, equipment, condition, action, hazard, ancestry, class, background,
  deity). AON only *fills gaps*.
- No per-category structured stat extraction for AON entries (the cleaned text
  carries the statblock). See "Stats" below.
- No exact AON deep links for Foundry-sourced entries (see "Deferred:
  Approach B").
- No HTML scraping; the ES index is the only AON data source.

## Scope: categories

A constant `AON_CATEGORIES` (easily edited; adding a category later is just a
string here + a `Category` enum value + a re-ingest — no per-category code):

- **Core gaps:** `trait`, `skill`, `archetype`, `rules`
- **Class/ancestry options:** `class-feature`, `heritage`, `bloodline`,
  `mystery`, `patron`, `lesson`, `arcane-school`, `domain`, `implement`, `ikon`
- **Companions/familiars:** `animal-companion`, `familiar-ability`
- **Magic & afflictions:** `ritual`, `relic`, `curse`, `disease`
- **World/lore:** `language`, `plane`, `vehicle`

**Excluded** (site-meta or creature-internal, not standalone rules):
`source`, `category-page`, `sidebar`, `article`, `deity-category`,
`class-sample`, `class-kit`, `creature-family`, `creature-ability`,
`creature-adjustment`, `item-bonus`. **Left out by default** (Kingmaker/warfare
subsystems; add to `AON_CATEGORIES` if those games are in play):
`kingdom-structure`, `kingdom-event`, `campsite-meal`, `siege-weapon`, `tactic`,
`warfare-tactic`.

All target categories have well under 10,000 entries, so a single query per
category retrieves the whole category (no pagination).

## Architecture

A second `Source` implementation behind the **existing** `Source` interface
(`pf_helper/ingest/sources.py`), producing the same `Entry` objects:

```
AON ES  --fetch-->  data/aon/<category>.json (cached, gitignored)
                          |
                    AonSource.iter_entries()  -> Entry (cleaned text, source_url)
                          |
build_index(cfg, sources=[FoundrySource(...), AonSource(...)])  -> one SQLite/FTS5 DB
                          |
            search / get_entry  (unchanged except Category enum + source_url)
```

- **Eager + unified.** Both sources are ingested into one index at build time.
  Query time stays pure local FTS5 (sub-millisecond), source-independent. No
  query-time source preference is needed: the gap categories don't overlap
  Foundry, so there is no same-entry competition; bm25 ranks any cross-source
  term matches by relevance.
- **Local cache.** AON responses are cached to `data/aon/<category>.json`
  (gitignored, like the Foundry clone). Rebuilds and tests do not re-hit AON.
- **HTTP via stdlib `urllib.request`** — a handful of bulk POSTs; no new
  dependency.

## Data source: AON Elasticsearch

- **Endpoint:** `POST https://elasticsearch.aonprd.com/aon/_search`
- **Per-category query:** `{"size": 10000, "query": {"match": {"category": "<cat>"}}}`
- **Entries** are `hits.hits[].​_source` objects. Verified relevant fields:
  - `name` — display name
  - `category` — lowercase slug (`trait`, `rules`, `class-feature`, …)
  - `id` — unique, category-prefixed (`trait-1`, `rules-1829`, `ritual-1`)
  - `trait` — list of trait names (may be absent/null)
  - `primary_source` — source book (string); `source` is a list (use
    `primary_source`)
  - `level` — present for some categories; absent for most gap categories
  - `markdown` — AON's custom markup (the body to clean; see below)
  - `url` — relative AON page path (`/Traits.aspx?ID=1`)

## Field mapping: AON `_source` → `Entry`

| Entry field   | From AON `_source` |
|---------------|--------------------|
| `id`          | `f"{category}:{slug(name)}-{id}"` (e.g. `trait:aberration-trait-1`) |
| `name`        | `name` |
| `category`    | `category` (new `Category` enum value, hyphens preserved) |
| `traits`      | `tuple(trait or ())` |
| `level`       | `level` if an int, else `None` |
| `source_book` | `primary_source` |
| `text`        | `clean_aon(markdown)` |
| `source_url`  | `f"https://2e.aonprd.com{url}"` (exact deep link) |
| `raw_json`    | compact JSON of the full `_source` |
| `stats`       | `()` (empty; see Stats) |

IDs are unique (AON `id` is unique) and these categories don't overlap Foundry,
so no primary-key collisions.

## Content cleaning: `clean_aon(markdown)`

AON's `markdown` field is a custom dialect, not standard Markdown. A new module
`pf_helper/ingest/aon_clean.py` converts it to clean plain text (kept separate
from the Foundry enricher cleaner in `clean.py`, which handles a different
dialect). It must:

- Resolve link syntax `[Label](/Some.aspx?ID=N)` → `Label`.
- Strip AON custom tags while keeping their inner text:
  `<title level=".." right=".." pfs="..">…</title>`,
  `<traits>…</traits>` / `<trait label=".." url=".." />`,
  `<row>` / `<column>` layout tags, and any other `<tag …>`/`</tag>` wrappers.
- Normalize whitespace (collapse runs, trim lines, blank-line-separate
  paragraphs) — same normalization contract as `clean.py`.

Correctness is pinned by **golden tests** against real AON samples (mirroring
`test_clean.py`): a trait, a `rules` entry (with a table/row layout), and a
ritual are the representative cases. The flat `text` field is intentionally not
used (run-together, lossy on tables, encoding artifacts).

## `source_url` on results (Approach A)

Every entry carries a `source_url`; both tools return it so Claude can offer
"view on AON" / "make it elite" links.

- **AON-sourced entries:** exact deep link `https://2e.aonprd.com{url}`.
- **Foundry-sourced entries:** AON **search-by-name** link
  `https://2e.aonprd.com/Search.aspx?q={url-quoted name}` — deterministic,
  always resolves, one click from the formatted AON page (and its elite/weak
  buttons). `FoundrySource` constructs this from the entry name.

Changes required:
- `Entry` gains `source_url: str`.
- `entries` schema gains a `source_url TEXT` column.
- `SearchHit` and `EntryDetail` gain `source_url: str`.
- `Fts5Retriever` reads the column into both models.

The `2e.aonprd.com` page base and the `Search.aspx?q=` form are verified to
resolve (HTTP 200).

## Build / fetch / ingest changes

- **`build_index` generalized to multiple sources.** Signature becomes
  `build_index(cfg, sources: Iterable[Source]) -> dict[str, int]`. It drops the
  DB once, then inserts every source's entries (`INSERT OR REPLACE`), and
  returns combined per-category counts. Existing Foundry-only tests are updated
  to pass a single-element source list (`[FoundrySource(packs_root)]`).
- **`AonSource(root_or_dir)`** reads the cached `data/aon/<category>.json`
  files and yields `Entry`s. Pure/offline/testable, like `FoundrySource`.
- **`_ensure_aon_cache(cfg)`** POSTs each category in `AON_CATEGORIES` to the ES
  endpoint and writes `data/aon/<category>.json`, skipping categories already
  cached. A `--refresh` flag (or equivalent) forces re-fetch.
- **`main` (`pf-helper-ingest`)**: ensure Foundry repo → ensure AON cache →
  `build_index` from both. Re-run to refresh. Prints combined per-category
  counts.
- **Config** gains AON settings: ES base URL and `aon_dir` (`data/aon`) as
  properties. `AON_CATEGORIES` is a module-level constant in `sources.py`,
  alongside `AonSource` and the existing `CATEGORY_MAP`.

## Category enum & tools

`Category` (in `models.py`) gains the new values (e.g. `TRAIT = "trait"`,
`SKILL = "skill"`, `ARCHETYPE = "archetype"`, `RULES = "rules"`,
`CLASS_FEATURE = "class-feature"`, … one per `AON_CATEGORIES` entry). The
`search` tool's `category` parameter is the `Category` enum, so the new values
become valid filters automatically. No other server changes.

## Stats

AON gap categories are narrative; v1 stores `stats = ()` and relies on the
cleaned `text` (which includes the statblock prose for rituals, etc.). Adding
per-category AON stat extraction later is straightforward (a sibling of
`extract.py`) but is YAGNI now.

## Testing

- `tests/test_aon_clean.py` — golden cases for `clean_aon` (trait, rules-table,
  ritual; link resolution; tag stripping; whitespace).
- `tests/fixtures/aon/<category>.json` — tiny committed AON samples
  (a couple categories) for `AonSource`.
- `tests/test_sources.py` — add `AonSource` cases (field mapping, id scheme,
  cleaned text, `source_url` exact link; Foundry `source_url` search link).
- `tests/test_build.py` — multi-source build produces AON + Foundry counts.
- `tests/test_db.py` / `test_retrieval.py` / `test_server.py` — `source_url`
  column round-trips into `SearchHit` / `EntryDetail`.
- Live ES fetch (`_ensure_aon_cache`) is **not** unit-tested (network); only the
  pure parse/build path is.

## File structure (added/changed)

```
pf_helper/
  models.py            # + Category values; + Entry.source_url; + SearchHit/EntryDetail.source_url
  config.py            # + aon_dir, aon ES url; AON_CATEGORIES constant (here or sources.py)
  ingest/
    aon_clean.py       # NEW: clean_aon(markdown) -> text
    sources.py         # + AonSource(Source); FoundrySource sets source_url (search link)
    build.py           # build_index(sources=...); _ensure_aon_cache(); main wires both
  store/
    schema.sql         # + source_url column
    db.py              # insert/select include source_url
  retrieval/fts5.py    # map source_url into SearchHit/EntryDetail
tests/
  test_aon_clean.py    # NEW
  fixtures/aon/*.json  # NEW tiny samples
  (updates to test_sources/test_build/test_db/test_retrieval/test_server)
data/aon/              # gitignored cache of AON ES responses
```

## Operational notes

- **Politeness/ToS:** one bulk query per category (≈20 total), cached locally;
  no per-query traffic. `--refresh` re-fetches deliberately. This matches AON's
  intended ES usage pattern and keeps load minimal.
- **Refresh cadence:** re-run `pf-helper-ingest` (optionally `--refresh`) to pull
  updated AON content, same as updating the Foundry data.

## Deferred / future enhancements

- **Approach B — exact AON deep links for Foundry entries.** Harvest AON's
  name→url map for Foundry-overlapping categories (creature, spell, feat, …) and
  attach the exact AON page to Foundry entries by normalized-name match, falling
  back to the search link when there is no unique match. Adds a name-matching
  step (with duplicate-name / remaster-rename handling). Its own spec.
- **AON per-category stat extraction** (statblock headers for rituals, etc.).
- **Kingmaker/warfare subsystem categories** — add to `AON_CATEGORIES`.
- **Vector / hybrid retrieval** — already deferred in the base design, unchanged
  here.
