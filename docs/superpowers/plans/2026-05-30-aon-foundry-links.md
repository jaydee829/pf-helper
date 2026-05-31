# Exact AON Deep Links for Foundry Entries — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Foundry-sourced entries an exact Archives of Nethys deep link in `source_url` (instead of the `Search.aspx?q=` search link) by matching names against an AON-built `name→url` index, for the 10 categories whose Foundry/AON category names match 1:1.

**Architecture:** A light AON fetch (`name`/`url`/`remaster_id` only) per link-category is cached to `data/aon_links/`; `build_link_index` turns it into an `AonLinkIndex` that prefers remaster entries and omits still-ambiguous names; the index is injected into `FoundrySource`, which sets the exact url on a unique match or falls back to the search link.

**Tech Stack:** Python 3.14, `uv`, `ruff`, `pytest`, stdlib `urllib`/`json`/`sqlite3`. Git: branch `feat/aon-foundry-links` → PR → user approves.

## Reference

- Spec: `docs/superpowers/specs/2026-05-30-aon-foundry-links-design.md` (read first).
- **AON ES (verified):** `POST https://elasticsearch.aonprd.com/aon/_search`, body `{"size":10000,"query":{"match":{"category":cat}},"_source":["name","url","remaster_id"]}`. Each `_source` has `name`, `url` (relative, e.g. `/Monsters.aspx?ID=2791`), and — on superseded **legacy** entries only — a non-empty `remaster_id`. The 10 link-categories' AON `category` values equal the Foundry category values exactly.
- **Existing code:** `pf_helper/ingest/sources.py` has `FoundrySource` (its `_load` builds each `Entry`; today `source_url=f"https://2e.aonprd.com/Search.aspx?q={quote_plus(doc['name'])}"`) and a module-level `_slug(name)` (lowercases, non-alphanumeric→`-`, trims). `build_index(cfg, sources)` ingests a list of `Source`s. `Config` has `data_dir` + `from_env`. `AonSource` is unchanged by this plan.

## Working notes

- Run from `C:\Users\jayde\Documents\PF_Helper` (Windows). Branch is `feat/aon-foundry-links`; commit on it (do NOT create new branches). Commit footer: blank line then exactly `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Use `uv run --no-sync` for pytest/ruff (avoids a Windows lock if the Claude Desktop `pf-helper` server is running). No dependencies change in this plan.
- Ruff: line-length 100, target py314, select E,F,I,UP,B.

## File structure

```
pf_helper/ingest/aon_links.py   # NEW: AON_LINK_CATEGORIES, AonLinkIndex, build_link_index
pf_helper/ingest/sources.py     # MODIFY: FoundrySource(root, link_index=None); _load uses it
pf_helper/ingest/build.py       # MODIFY: _ensure_aon_link_cache(); main wires the index
pf_helper/config.py             # MODIFY: aon_links_dir property
tests/test_aon_links.py         # NEW
tests/test_sources.py           # MODIFY: FoundrySource with an injected fake index
tests/test_config.py            # NEW (tiny): aon_links_dir   [or fold into an existing config test if present]
data/aon_links/                 # gitignored (covered by data/)
```

---

## Task 1: `AonLinkIndex` + `build_link_index`

**Files:** Create `pf_helper/ingest/aon_links.py`; Test `tests/test_aon_links.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_aon_links.py`:
```python
import json

from pf_helper.ingest.aon_links import build_link_index


def _write(dirpath, category, docs):
    (dirpath / f"{category}.json").write_text(json.dumps(docs), encoding="utf-8")


def test_unique_name_maps_to_exact_url(tmp_path):
    _write(tmp_path, "creature", [{"name": "Goblin Warrior", "url": "/Monsters.aspx?ID=1"}])
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Goblin Warrior") == "https://2e.aonprd.com/Monsters.aspx?ID=1"


def test_remaster_preferred_over_legacy(tmp_path):
    # Legacy 'Arbiter' carries a remaster_id (superseded); the remaster does not.
    _write(tmp_path, "creature", [
        {"name": "Arbiter", "url": "/Monsters.aspx?ID=6", "remaster_id": ["creature-2791"]},
        {"name": "Arbiter", "url": "/Monsters.aspx?ID=2791"},
    ])
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Arbiter") == "https://2e.aonprd.com/Monsters.aspx?ID=2791"


def test_ambiguous_after_remaster_filter_returns_none(tmp_path):
    # Two distinct entries, neither superseded -> ambiguous -> no exact link.
    _write(tmp_path, "creature", [
        {"name": "Python", "url": "/Monsters.aspx?ID=10"},
        {"name": "Python", "url": "/Monsters.aspx?ID=11"},
    ])
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Python") is None


def test_unknown_name_and_category_return_none(tmp_path):
    _write(tmp_path, "spell", [{"name": "Heal", "url": "/Spells.aspx?ID=1"}])
    idx = build_link_index(tmp_path)
    assert idx.url_for("spell", "Fireball") is None   # unknown name
    assert idx.url_for("feat", "Heal") is None         # category file absent


def test_normalization_matches_varied_casing_and_spacing(tmp_path):
    _write(tmp_path, "spell", [{"name": "Heal", "url": "/Spells.aspx?ID=1"}])
    idx = build_link_index(tmp_path)
    assert idx.url_for("spell", "  heal ") == "https://2e.aonprd.com/Spells.aspx?ID=1"


def test_empty_dir_is_safe(tmp_path):
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Anything") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_aon_links.py -v`
Expected: FAIL — `pf_helper.ingest.aon_links` does not exist.

- [ ] **Step 3: Implement `aon_links.py`**

`pf_helper/ingest/aon_links.py`:
```python
"""Build a name->AON-url index for the Foundry-overlapping categories.

Foundry and AON share no IDs, so exact AON deep links for Foundry entries are
resolved by matching normalized names within a category. AON entries that carry
a `remaster_id` are superseded legacy duplicates and are dropped (prefer
remaster, matching Foundry). A name still mapping to more than one URL after
that is ambiguous and is omitted, so the caller falls back to a search link.
"""

from __future__ import annotations

import json
from pathlib import Path

from pf_helper.ingest.sources import _slug

# Categories whose Foundry category value == AON `category` value (1:1).
AON_LINK_CATEGORIES: tuple[str, ...] = (
    "creature",
    "spell",
    "feat",
    "hazard",
    "condition",
    "action",
    "deity",
    "ancestry",
    "class",
    "background",
)

_AON_BASE = "https://2e.aonprd.com"


class AonLinkIndex:
    """Maps (category, normalized name) -> exact AON page URL for unique matches."""

    def __init__(self, mapping: dict[tuple[str, str], str]):
        self._map = mapping

    def url_for(self, category: str, name: str) -> str | None:
        return self._map.get((category, _slug(name)))


def build_link_index(link_dir: str | Path) -> AonLinkIndex:
    """Read cached AON name/url projections and build an AonLinkIndex."""
    link_dir = Path(link_dir)
    candidates: dict[tuple[str, str], set[str]] = {}
    for category in AON_LINK_CATEGORIES:
        path = link_dir / f"{category}.json"
        if not path.exists():
            continue
        try:
            docs = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(docs, list):
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("remaster_id"):
                continue  # drop superseded legacy entries (prefer remaster)
            name = doc.get("name")
            url = doc.get("url")
            if not name or not url:
                continue
            key = (category, _slug(name))
            candidates.setdefault(key, set()).add(f"{_AON_BASE}/{url.lstrip('/')}")
    # Keep only unambiguous keys (exactly one distinct URL).
    mapping = {key: next(iter(urls)) for key, urls in candidates.items() if len(urls) == 1}
    return AonLinkIndex(mapping)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_aon_links.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/ingest/aon_links.py tests/test_aon_links.py
git commit -m "feat: add AonLinkIndex (name->AON url, remaster-preferred)"
```

---

## Task 2: `FoundrySource` uses the link index

**Files:** Modify `pf_helper/ingest/sources.py`; Test `tests/test_sources.py`.

- [ ] **Step 1: Write the failing test (append to `tests/test_sources.py`)**

```python
class _FakeLinkIndex:
    def __init__(self, mapping):
        self._m = mapping  # {(category, name): url}

    def url_for(self, category, name):
        return self._m.get((category, name))


def test_foundry_uses_exact_link_when_index_matches():
    idx = _FakeLinkIndex({("feat", "Test Feat"): "https://2e.aonprd.com/Feats.aspx?ID=99"})
    src = FoundrySource(FIXTURE_ROOT, link_index=idx)
    feat = next(e for e in src.iter_entries() if e.name == "Test Feat")
    assert feat.source_url == "https://2e.aonprd.com/Feats.aspx?ID=99"


def test_foundry_falls_back_to_search_link_when_index_misses():
    idx = _FakeLinkIndex({})  # knows nothing
    src = FoundrySource(FIXTURE_ROOT, link_index=idx)
    cond = next(e for e in src.iter_entries() if e.name == "Frightened")
    assert cond.source_url == "https://2e.aonprd.com/Search.aspx?q=Frightened"
```
(`FIXTURE_ROOT` and `FoundrySource` are already imported at the top of this file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_sources.py -k link -v`
Expected: FAIL — `FoundrySource.__init__` takes no `link_index` argument.

- [ ] **Step 3: Modify `FoundrySource`**

In `pf_helper/ingest/sources.py`:

Add a `TYPE_CHECKING` import near the top (after the existing imports), so the type hint doesn't create a runtime circular import (`aon_links` imports `_slug` from this module):
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pf_helper.ingest.aon_links import AonLinkIndex
```

Change `FoundrySource.__init__` to accept and store the index:
```python
    def __init__(self, root: str | Path, link_index: "AonLinkIndex | None" = None):
        # root is the directory that contains the `pf2e/` packs tree.
        self.packs_root = Path(root) / "pf2e"
        self._link_index = link_index
```

In `FoundrySource._load`, replace the `source_url=...` keyword in the returned
`Entry(...)` so it prefers the exact link:
```python
        name = doc["name"]
        exact = self._link_index.url_for(category, name) if self._link_index else None
        source_url = exact or f"https://2e.aonprd.com/Search.aspx?q={quote_plus(name)}"
```
and pass `source_url=source_url` to the `Entry(...)` (replacing the previous
inline `source_url=f"https://2e.aonprd.com/Search.aspx?q={quote_plus(doc['name'])}"`).
The rest of the `Entry(...)` construction is unchanged. (`doc["name"]` is already
referenced elsewhere as the entry name; using the local `name` is equivalent.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_sources.py -v`
Expected: PASS — the two new tests plus all existing source tests (the existing
`test_foundry_entry_has_aon_search_url` still passes because `link_index`
defaults to `None`).

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/ingest/sources.py tests/test_sources.py
git commit -m "feat: FoundrySource sets exact AON link via injected link index"
```

---

## Task 3: Config dir + link-cache fetch + build wiring

**Files:** Modify `pf_helper/config.py`, `pf_helper/ingest/build.py`; Test `tests/test_config.py`.

- [ ] **Step 1: Write the failing config test**

`tests/test_config.py`:
```python
from pf_helper.config import Config


def test_aon_links_dir_under_data_dir(tmp_path):
    cfg = Config(data_dir=tmp_path)
    assert cfg.aon_links_dir == tmp_path / "aon_links"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_config.py -v`
Expected: FAIL — `Config` has no `aon_links_dir`.

- [ ] **Step 3: Add the `aon_links_dir` property**

In `pf_helper/config.py`, add to the `Config` dataclass (next to the existing
`aon_dir` property):
```python
    @property
    def aon_links_dir(self) -> Path:
        return self.data_dir / "aon_links"
```

- [ ] **Step 4: Run the config test to verify it passes**

Run: `uv run --no-sync pytest tests/test_config.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Add `_ensure_aon_link_cache` and wire `main` in `build.py`**

In `pf_helper/ingest/build.py`:

Extend the sources import to include the link-index pieces:
```python
from pf_helper.ingest.aon_links import AON_LINK_CATEGORIES, build_link_index
```
(Keep the existing `from pf_helper.ingest.sources import AON_CATEGORIES, AonSource, FoundrySource, Source` line as-is.)

Add the fetch function (after `_ensure_aon_cache`):
```python
def _ensure_aon_link_cache(cfg: Config, refresh: bool = False) -> None:
    """Fetch a light name/url/remaster_id projection per link-category for the
    Foundry->AON exact-link index, into data/aon_links/<category>.json."""
    cfg.aon_links_dir.mkdir(parents=True, exist_ok=True)
    for category in AON_LINK_CATEGORIES:
        path = cfg.aon_links_dir / f"{category}.json"
        if path.exists() and not refresh:
            continue
        body = json.dumps(
            {
                "size": 10000,
                "query": {"match": {"category": category}},
                "_source": ["name", "url", "remaster_id"],
            }
        ).encode()
        req = urllib.request.Request(
            cfg.aon_es_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read())
        docs = [hit["_source"] for hit in data["hits"]["hits"]]
        path.write_text(json.dumps(docs), encoding="utf-8")
        print(f"  link-cached {category:12} {len(docs)}")
```

Update `main` to fetch the link cache, build the index, and inject it into the
Foundry source:
```python
def main() -> None:
    cfg = Config.from_env()
    refresh = "--refresh" in sys.argv[1:]
    print(f"Ensuring Foundry repo at {cfg.foundry_dir} ...")
    _ensure_foundry_repo(cfg)
    print(f"Ensuring AON cache at {cfg.aon_dir} (refresh={refresh}) ...")
    _ensure_aon_cache(cfg, refresh=refresh)
    print(f"Ensuring AON link cache at {cfg.aon_links_dir} (refresh={refresh}) ...")
    _ensure_aon_link_cache(cfg, refresh=refresh)
    link_index = build_link_index(cfg.aon_links_dir)
    print("Building index ...")
    counts = build_index(
        cfg,
        [FoundrySource(cfg.foundry_packs_root, link_index), AonSource(cfg.aon_dir)],
    )
    total = sum(counts.values())
    print(f"Indexed {total} entries into {cfg.db_path}")
    for cat in sorted(counts):
        print(f"  {cat:18} {counts[cat]}")
```
(Keep `build_index` and `_ensure_foundry_repo` otherwise unchanged. `json`,
`sys`, `urllib.request` are already imported in `build.py`.)

- [ ] **Step 6: Run tests + verify import**

Run:
```bash
uv run --no-sync pytest -q
uv run --no-sync python -c "from pf_helper.ingest.build import _ensure_aon_link_cache, main; print('ok')"
```
Expected: full suite passes; prints `ok`. Do NOT run `pf-helper-ingest` (network + rebuild) — that's the next task.

- [ ] **Step 7: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/config.py pf_helper/ingest/build.py tests/test_config.py
git commit -m "feat: fetch AON link cache and inject the link index at ingest"
```

---

## Task 4: Real-data verification (non-destructive)

**Files:** none (operational verification). Uses a temp index so it does not touch
the live `data/pf2e.db` (which the Claude Desktop server may hold open).

- [ ] **Step 1: Build a temp index with the link index and measure coverage**

Write this to `_verify_links.py` (in the repo root), run it, then delete it:
```python
import sqlite3
import tempfile
from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.aon_links import AON_LINK_CATEGORIES, build_link_index
from pf_helper.ingest.build import _ensure_aon_link_cache, build_index
from pf_helper.ingest.sources import AonSource, FoundrySource

REPO = Path(__file__).resolve().parent
EXISTING_PACKS = REPO / "data" / "foundry-pf2e" / "packs"  # reuse, no re-clone

tmp = Path(tempfile.mkdtemp(prefix="pfhelper_links_"))
cfg = Config(data_dir=tmp)
print("Fetching AON link cache (real ES) ...")
_ensure_aon_link_cache(cfg, refresh=False)
idx = build_link_index(cfg.aon_links_dir)
print("Building combined index ...")
build_index(cfg, [FoundrySource(EXISTING_PACKS, idx), AonSource(cfg.aon_dir)])

conn = sqlite3.connect(cfg.db_path)
qmarks = ",".join("?" for _ in AON_LINK_CATEGORIES)
total = conn.execute(
    f"SELECT COUNT(*) FROM entries WHERE category IN ({qmarks})", AON_LINK_CATEGORIES
).fetchone()[0]
exact = conn.execute(
    f"SELECT COUNT(*) FROM entries WHERE category IN ({qmarks}) "
    "AND source_url NOT LIKE '%Search.aspx%'",
    AON_LINK_CATEGORIES,
).fetchone()[0]
print(f"link-category entries: {total}  exact-linked: {exact}  ({exact / total:.1%})")
row = conn.execute(
    "SELECT name, source_url FROM entries WHERE name='Arbiter' AND category='creature'"
).fetchone()
print("Arbiter ->", row)
```
Run: `uv run --no-sync python _verify_links.py`
Expected: prints a high exact-linked percentage (~97–99%) for the link-categories,
and an `Arbiter -> ('Arbiter', 'https://2e.aonprd.com/Monsters.aspx?ID=...')`
exact deep link (a `/Monsters.aspx?ID=` URL, not a `Search.aspx` link). If
`Arbiter` isn't in the Foundry data, pick any creature the output shows; the
point is the URL is an exact `/Monsters.aspx?ID=` page.

- [ ] **Step 2: Spot-check a fallback**

Still in/after the script (or a quick REPL on the temp db), confirm at least one
link-category entry still has a `Search.aspx` URL (the residual ambiguous/no-match
fallback) — i.e. `exact < total`. This confirms the fallback path is exercised on
real data, not that every entry matched.

- [ ] **Step 3: Clean up**

```bash
rm -f _verify_links.py
```
`data/` is gitignored; the temp dir is outside the repo. No commit.

---

## Task 5: Final PR

- [ ] **Step 1: Full suite + lint**

Run:
```bash
uv run --no-sync pytest -q
uv run --no-sync ruff check .
```
Expected: all pass; ruff clean.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin feat/aon-foundry-links
gh pr create --base main --head feat/aon-foundry-links --title "feat: exact AON deep links for Foundry entries (creatures, spells, feats, ...)" --body "<summary; paste uv run pytest -q output and the Task 4 exact-link coverage % + Arbiter sample>"
```

- [ ] **Step 3: Stop for user review**

Do not merge. Report test results and the Task 4 coverage numbers in the PR body.
The user reviews and merges (never self-merge unless explicitly told).

---

## Notes / deferred

- **Equipment** exact links (merge AON weapon/armor/shield/consumable/treasure/…
  into one equipment name→url map) — out of scope here.
- Fuzzy matching for the residual ~1–3% (legacy renames, genuine same-name
  variants) — those keep the search link.
- To activate on the live index after merge: rebuild with `pf-helper-ingest`
  (Claude Desktop closed so it can replace `pf2e.db`), then relaunch Desktop.
```
