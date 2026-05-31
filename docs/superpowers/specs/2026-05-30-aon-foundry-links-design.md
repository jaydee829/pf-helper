# PF_Helper — Exact AON Deep Links for Foundry Entries (Design Spec)

**Date:** 2026-05-30
**Status:** Approved (brainstorming)
**Builds on:** the shipped Foundry+AON server on `main`
(`docs/superpowers/specs/2026-05-30-aon-es-supplement-design.md`). This is
"Approach B", deferred from that spec.

## Goal

Give Foundry-sourced entries (creatures, spells, feats, …) an **exact** Archives
of Nethys deep link in their `source_url`, instead of today's
`Search.aspx?q=<name>` search link. So `/get_entry`, the Discord bot, and any
MCP client can link straight to a creature's AON page (and its elite/weak
buttons), a spell's page, etc.

The join is by **name**, since Foundry and AON share no IDs. A name→url index is
built from AON for the overlapping categories; a Foundry entry that resolves to a
single AON page gets that exact link, otherwise it keeps the search link.

## Non-goals (v1)

- **Equipment is out of scope.** Foundry's `equipment` category aggregates many
  AON item categories (weapon/armor/shield/consumable/treasure/…); merging those
  is deferred. Equipment keeps the search link.
- No new ingested entries — the link-categories are fetched for their `name→url`
  only, not added to the index (Foundry already provides those entries).
- No fuzzy/semantic name matching — exact normalized-name match only.
- No change to AON-sourced entries (they already carry exact deep links) or to
  the supplement categories (trait/skill/…).

## Scope: categories

The fetched AON categories (`AON_LINK_CATEGORIES`):

```
creature, spell, feat, hazard, condition, action, deity, ancestry, class, background, heritage
```

The first 10 have a Foundry category value identical to the AON `category`
value (1:1). **`heritage` is the one exception:** Foundry maps its `heritage`
document type to the `ancestry` category, but AON keeps heritages in a separate
`heritage` category — so AON `heritage` entries are indexed under the Foundry
`ancestry` category (a small `_AON_TO_FOUNDRY_CATEGORY = {"heritage": "ancestry"}`
mapping; all others are identity).

**Measured coverage (real-data, after the remaster filter below):** exact-link
coverage is **~68% overall** across these Foundry categories, not uniform —
class/deity/background/condition ~95–100%, spell 89%, feat 80%, **creature 55%**,
hazard 44%, action 22%, and **ancestry ~99% once heritages are matched** (66
ancestry + 302 heritage of 372; the heritage match lifts ancestry from ~18%).
The unmatched remainder is mostly content that genuinely isn't a standalone AON
page — adventure-path NPCs and variant statblocks (creatures), deity boon/curse
items and special feats — not a name-formatting problem; those keep the search
link (no regression). Commonly-looked-up entries (remastered Monster Core
creatures, core spells/feats) match, so the practical hit rate exceeds the raw
per-entry percentage. An earlier estimate of ~97–99% was wrong — it measured
AON's internal name-uniqueness, not the Foundry→AON join rate.

## Disambiguation: prefer remaster, then fall back

AON indexes both legacy and remastered versions of many entries, which is the
main source of same-name collisions. AON marks them: a **legacy** entry carries
a `remaster_id` (pointing to its successor); the **remaster** (or
never-remastered) entry does not. Foundry content is remaster.

Build rule for the index:
1. **Drop** any AON entry that has a non-empty `remaster_id` (a superseded legacy
   duplicate) — this prefers remaster content.
2. Normalize each remaining entry's name (`_slug`: lowercase, non-alphanumeric →
   `-`, trimmed) and group by `(category, normalized_name)`.
3. A key with **exactly one** url → store that exact deep link.
4. A key with **more than one** url (still ambiguous after step 1) → omit it, so
   the caller falls back to the search link. (Never guess between collisions.)

## Architecture (Approach A: link index injected into FoundrySource)

```
AON ES (name,url,remaster_id per link-category)
   --_ensure_aon_link_cache-->  data/aon_links/<category>.json   (gitignored)
                                       |
                          build_link_index(...) -> AonLinkIndex
                                       |
build.main: FoundrySource(packs_root, link_index)  --_load-->
        source_url = link_index.url_for(category, name)  or  Search.aspx?q=name
                                       |
                          build_index([FoundrySource(...), AonSource(...)]) -> index
```

The link index is built before ingestion and injected into `FoundrySource`. The
link decision happens once, at entry construction. `FoundrySource` with no index
(e.g., unit tests) keeps today's search-link behavior — the feature is cleanly
optional.

## Components / file structure

```
pf_helper/ingest/
  aon_links.py    # NEW: AON_LINK_CATEGORIES; AonLinkIndex.url_for(category, name);
                  #      build_link_index(link_dir) -> AonLinkIndex; _slug reuse
  sources.py      # MODIFY: FoundrySource(packs_root, link_index=None); _load uses it
  build.py        # MODIFY: _ensure_aon_link_cache(cfg, refresh); main wires the index
pf_helper/config.py   # MODIFY: aon_links_dir property (data/aon_links)
tests/
  test_aon_links.py   # NEW: AonLinkIndex build rules (unique/ambiguous/remaster/miss)
  test_sources.py     # MODIFY: FoundrySource with an injected fake link index
data/aon_links/       # gitignored cache of AON name->url projections
```

### `AonLinkIndex` (in `aon_links.py`)
- `url_for(category: str, name: str) -> str | None` — returns the exact
  `https://2e.aonprd.com<url>` for a unique `(category, slug(name))` match, else
  `None`.
- `build_link_index(link_dir: Path) -> AonLinkIndex` — reads
  `link_dir/<category>.json` (a JSON array of `{name, url, remaster_id?}` objects)
  for each `AON_LINK_CATEGORIES`, applies the build rule above, and returns the
  index. Missing files are skipped (those categories simply get no exact links).

### `FoundrySource` change
`__init__(self, root, link_index: AonLinkIndex | None = None)`. In `_load`:
```python
exact = self._link_index.url_for(category, doc["name"]) if self._link_index else None
source_url = exact or f"https://2e.aonprd.com/Search.aspx?q={quote_plus(doc['name'])}"
```
(`AonSource` is unchanged — it already sets exact deep links from its own `url`.)

### Fetch (`_ensure_aon_link_cache`)
One ES POST per `AON_LINK_CATEGORIES`, body
`{"size":10000,"query":{"match":{"category":cat}},"_source":["name","url","remaster_id"]}`
→ write `data/aon_links/<cat>.json`. Skips already-cached files unless
`refresh=True` (shares the `--refresh` flag with the supplement fetch). Same
fail-loud behavior; a category that errors aborts the run for re-run rather than
writing a partial file.

### `build.main` wiring
```
ensure Foundry repo
ensure AON supplement cache        (existing)
ensure AON link cache              (new)
idx = build_link_index(cfg.aon_links_dir)
build_index([FoundrySource(cfg.foundry_packs_root, idx), AonSource(cfg.aon_dir)])
```

## Testing

- `test_aon_links.py` — `build_link_index` over a `tmp_path` link dir with crafted
  `<category>.json` fixtures:
  - unique name → exact `https://2e.aonprd.com<url>`;
  - a legacy+remaster pair (legacy has `remaster_id`) → resolves to the remaster
    url (not ambiguous);
  - two distinct same-name entries (neither has `remaster_id`) → `url_for` returns
    `None` (ambiguous);
  - unknown name / unknown category → `None`.
- `test_sources.py` — `FoundrySource(FIXTURE_ROOT, link_index=fake)` where the fake
  returns an exact url for the fixture creature/feat → that entry's `source_url`
  is the exact link; a name the fake doesn't know → the `Search.aspx?q=` link.
  (Existing no-index tests stay valid: default `link_index=None` → search link.)
- The live `_ensure_aon_link_cache` fetch is not unit-tested (network); verified
  in the real-data step.

## Real-data verification (operational)

Rebuild via `pf-helper-ingest`, then:
- Confirm a known remastered creature (e.g. `Arbiter`) resolves to an exact
  `/Monsters.aspx?ID=...` link via `get_entry`.
- Measure coverage: % of Foundry entries in the link-categories whose `source_url`
  is now an exact AON page vs. a `Search.aspx?q=` fallback (measured ~68% overall;
  see Scope for the per-category breakdown — ancestry ~99% with the heritage match,
  creature ~55%, etc.).
- Confirm a known same-name collision falls back to the search link.

## Operational notes

- Adds ~10 light ES queries at ingest (name/url/remaster_id only), cached to
  `data/aon_links/`. Negligible vs. the Foundry clone.
- Re-run `pf-helper-ingest` (optionally `--refresh`) to update links when AON or
  the Foundry data changes.

## Deferred / future

- **Equipment** exact links (merge AON weapon/armor/shield/consumable/treasure/…
  into one equipment name→url map).
- Higher creature/feat/hazard/action coverage. Investigation showed the bulk of
  those fallbacks are content that genuinely isn't a standalone AON page
  (adventure-path NPCs and variant statblocks; deity boon/curse items; embedded
  creature actions), not a name-formatting issue — so they are not safely
  recoverable by name manipulation (fuzzy/suffix matching would risk linking to
  the wrong page). Left as search-link fallbacks. Any future improvement here
  needs a more reliable join key than the name.
