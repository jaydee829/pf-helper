# AON Elasticsearch Supplement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AON-only PF2e content (traits, skills, archetypes, narrative rules, and curated extras) from the Archives of Nethys Elasticsearch index into the existing SQLite/FTS5 index, and attach a `source_url` (AON link) to every result.

**Architecture:** A new `AonSource` behind the existing `Source` interface yields the same `Entry` objects from locally-cached AON JSON; `build_index` is generalized to ingest multiple sources into one DB. A new `clean_aon` converts AON's custom markdown dialect to plain text. `source_url` is added across `Entry`/schema/models/retriever: exact AON deep links for AON entries, AON search-by-name links for Foundry entries.

**Tech Stack:** Python 3.14, `uv`, `ruff`, stdlib `sqlite3`+FTS5, stdlib `urllib.request` (AON fetch), `pytest`. Git: feature branch `feat/aon-supplement` → PR → user approves.

## Reference

- Design spec: `docs/superpowers/specs/2026-05-30-aon-es-supplement-design.md` (read first).
- Base design: `docs/superpowers/specs/2026-05-29-pf-helper-mcp-design.md`.
- **AON ES (verified):** `POST https://elasticsearch.aonprd.com/aon/_search` with body `{"size":10000,"query":{"match":{"category":"<cat>"}}}`. Entries are `hits.hits[]._source`. Relevant fields: `name`, `category` (lowercase, e.g. `class-feature`), `id` (unique, e.g. `trait-1`), `trait` (list|null), `primary_source` (str), `level` (sometimes), `markdown` (custom dialect), `url` (relative path e.g. `/Traits.aspx?ID=1`).
- **AON page base (verified 200):** `https://2e.aonprd.com` + `url`; search link `https://2e.aonprd.com/Search.aspx?q=<name>`.

## Working notes

- All steps run from `C:\Users\jayde\Documents\PF_Helper` on Windows; use `uv run` for python/pytest/ruff.
- Branch is already `feat/aon-supplement`. Commit each task on this branch (do NOT create new branches). End every commit message body with a blank line then exactly:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Ruff config: line-length 100, target py314, select E,F,I,UP,B. Run `uv run ruff check . && uv run ruff format .` before each commit.

---

## Task 1: Category enum values + `source_url` on models

**Files:**
- Modify: `pf_helper/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_models.py`)**

```python
def test_new_aon_category_values():
    assert Category.TRAIT == "trait"
    assert Category.RULES == "rules"
    assert Category("class-feature") is Category.CLASS_FEATURE
    assert Category("familiar-ability") is Category.FAMILIAR_ABILITY


def test_entry_has_source_url_default():
    e = Entry(
        id="trait:x-trait-1",
        name="X",
        category="trait",
        traits=(),
        level=None,
        source_book="Core Rulebook",
        text="t",
        raw_json="{}",
    )
    assert e.source_url == ""  # default; sources populate it


def test_models_carry_source_url():
    hit = SearchHit(id="a", name="A", category="trait", excerpt="e", source_url="https://x")
    detail = EntryDetail(id="a", name="A", category="trait", text="t", source_url="https://x")
    assert hit.source_url == "https://x"
    assert detail.source_url == "https://x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `Category` has no `TRAIT`/`CLASS_FEATURE`; `Entry`/`SearchHit`/`EntryDetail` have no `source_url`.

- [ ] **Step 3: Add the new `Category` members**

In `pf_helper/models.py`, inside `class Category(StrEnum)`, after the existing `DEITY = "deity"` line and before the trailing comment, add:

```python
    # AON Elasticsearch supplement categories (not in the Foundry compendium).
    TRAIT = "trait"
    SKILL = "skill"
    ARCHETYPE = "archetype"
    RULES = "rules"
    CLASS_FEATURE = "class-feature"
    HERITAGE = "heritage"
    BLOODLINE = "bloodline"
    MYSTERY = "mystery"
    PATRON = "patron"
    LESSON = "lesson"
    ARCANE_SCHOOL = "arcane-school"
    DOMAIN = "domain"
    IMPLEMENT = "implement"
    IKON = "ikon"
    ANIMAL_COMPANION = "animal-companion"
    FAMILIAR_ABILITY = "familiar-ability"
    RITUAL = "ritual"
    RELIC = "relic"
    CURSE = "curse"
    DISEASE = "disease"
    LANGUAGE = "language"
    PLANE = "plane"
    VEHICLE = "vehicle"
```

- [ ] **Step 4: Add `source_url` to `Entry`**

In the `Entry` dataclass, add a defaulted field after `stats`:

```python
    stats: tuple[tuple[str, str], ...] = ()
    # AON page link: exact deep link (AON entries) or search-by-name link
    # (Foundry entries). Defaults empty for older construction sites.
    source_url: str = ""
```

- [ ] **Step 5: Add `source_url` to `SearchHit` and `EntryDetail`**

In `SearchHit`, after `excerpt`:

```python
    source_url: str = Field(default="", description="AON page link for this entry")
```

In `EntryDetail`, after `text`:

```python
    source_url: str = Field(default="", description="AON page link for this entry")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (all model tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/models.py tests/test_models.py
git commit -m "feat: add AON category enum values and source_url to models"
```

---

## Task 2: `source_url` column in schema + db layer

**Files:**
- Modify: `pf_helper/store/schema.sql`, `pf_helper/store/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_db.py`)**

```python
def test_source_url_roundtrips(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry(source_url="https://2e.aonprd.com/Traits.aspx?ID=1")])
    row = db.get_by_name(conn, "Frightened", category="condition")
    assert row["source_url"] == "https://2e.aonprd.com/Traits.aspx?ID=1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_source_url_roundtrips -v`
Expected: FAIL — `Entry` accepts `source_url` (Task 1) but the table has no such column, so `insert_entries` raises or the row lacks the key.

- [ ] **Step 3: Add the column to `schema.sql`**

In `pf_helper/store/schema.sql`, in the `entries` table, add a column after `stats_json`:

```sql
    stats_json  TEXT NOT NULL DEFAULT '[]',  -- JSON array of [label, value] pairs
    source_url  TEXT NOT NULL DEFAULT '',     -- AON page link
    raw_json    TEXT NOT NULL
```

- [ ] **Step 4: Include `source_url` in `insert_entries`**

In `pf_helper/store/db.py`, in `insert_entries`, add `e.source_url` to the row tuple (after the `stats_json` value, before `e.raw_json`) and update the column list + placeholders:

```python
    rows = [
        (
            e.id,
            e.name,
            e.category,
            ",".join(e.traits),
            e.level,
            e.source_book,
            e.text,
            json.dumps([list(pair) for pair in e.stats]),
            e.source_url,
            e.raw_json,
        )
        for e in entries
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO entries "
        "(id, name, category, traits, level, source_book, text, stats_json, source_url, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
```

(`get_by_name` and `fts_search` use `SELECT *` / `e.*`, so they pick up the new column automatically.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (all db tests, including the new one).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/store/schema.sql pf_helper/store/db.py tests/test_db.py
git commit -m "feat: add source_url column to storage layer"
```

---

## Task 3: Generalize `build_index` to multiple sources

**Files:**
- Modify: `pf_helper/ingest/build.py`
- Modify (call sites): `tests/test_build.py`, `tests/test_retrieval.py`, `tests/test_server.py`
- Test: `tests/test_build.py`

This is a signature refactor: `build_index(cfg, packs_root)` → `build_index(cfg, sources)`. FoundrySource remains the only source for now.

- [ ] **Step 1: Update the build test to the new signature (failing)**

In `tests/test_build.py`, replace the import block and the two existing tests' `build_index(...)` calls. New top of file:

```python
from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.build import build_index
from pf_helper.ingest.sources import FoundrySource
from pf_helper.store import db

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "foundry"
```

Change both `build_index(cfg, packs_root=FIXTURE_PACKS)` calls to:

```python
    counts = build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
```

and in the idempotent test:

```python
    first = build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    second = build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build.py -v`
Expected: FAIL — `build_index` still expects `packs_root`.

- [ ] **Step 3: Rewrite `build_index` to accept sources**

In `pf_helper/ingest/build.py`, replace the imports and `build_index`:

```python
from __future__ import annotations

import subprocess
from collections import Counter
from collections.abc import Iterable

from pf_helper.config import Config
from pf_helper.ingest.sources import FoundrySource, Source
from pf_helper.store import db


def build_index(cfg: Config, sources: Iterable[Source]) -> dict[str, int]:
    """Ingest every source into a fresh DB. Returns per-category counts."""
    if cfg.db_path.exists():
        cfg.db_path.unlink()
    conn = db.connect(cfg.db_path)
    try:
        db.create_schema(conn)
        counts: Counter[str] = Counter()
        batch = []
        for source in sources:
            for entry in source.iter_entries():
                batch.append(entry)
                counts[entry.category] += 1
        db.insert_entries(conn, batch)
    finally:
        conn.close()
    return dict(counts)
```

Also update `main` to pass a source list (AON is wired in Task 8; for now Foundry only):

```python
def main() -> None:
    cfg = Config.from_env()
    print(f"Ensuring Foundry repo at {cfg.foundry_dir} ...")
    _ensure_foundry_repo(cfg)
    print("Building index ...")
    counts = build_index(cfg, [FoundrySource(cfg.foundry_packs_root)])
    total = sum(counts.values())
    print(f"Indexed {total} entries into {cfg.db_path}")
    for cat in sorted(counts):
        print(f"  {cat:12} {counts[cat]}")
```

(Remove the now-unused `from pathlib import Path` import if present and ruff flags it.)

- [ ] **Step 4: Update the other two call sites**

In `tests/test_retrieval.py`, update the import and `_retriever` helper:

```python
from pf_helper.ingest.sources import FoundrySource
...
def _retriever(tmp_path) -> Fts5Retriever:
    cfg = Config(data_dir=tmp_path)
    build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    return Fts5Retriever(cfg.db_path)
```

Also update the two factory tests near the bottom that call `build_index(cfg, packs_root=FIXTURE_PACKS)` to `build_index(cfg, [FoundrySource(FIXTURE_PACKS)])` (add `from pf_helper.ingest.sources import FoundrySource` to those local imports if needed, or rely on the top-level import).

In `tests/test_server.py`, update the import and `_setup`:

```python
from pf_helper.ingest.sources import FoundrySource
...
def _setup(tmp_path):
    cfg = Config(data_dir=tmp_path)
    build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    srv.configure(cfg)
```

- [ ] **Step 5: Run the full suite to verify it passes**

Run: `uv run pytest -q`
Expected: PASS (all existing tests, now on the new signature).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/ingest/build.py tests/test_build.py tests/test_retrieval.py tests/test_server.py
git commit -m "refactor: build_index ingests a list of Sources"
```

---

## Task 4: `FoundrySource` populates `source_url` (AON search link)

**Files:**
- Modify: `pf_helper/ingest/sources.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_sources.py`)**

```python
def test_foundry_entry_has_aon_search_url():
    src = FoundrySource(FIXTURE_ROOT)
    feat = next(e for e in src.iter_entries() if e.name == "Test Feat")
    assert feat.source_url == "https://2e.aonprd.com/Search.aspx?q=Test+Feat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sources.py::test_foundry_entry_has_aon_search_url -v`
Expected: FAIL — `source_url` is `""` (default).

- [ ] **Step 3: Build the search link in `FoundrySource._load`**

In `pf_helper/ingest/sources.py`, add to the imports:

```python
from urllib.parse import quote_plus
```

In `FoundrySource._load`, add `source_url` to the returned `Entry`:

```python
        return Entry(
            id=f"{category}:{_slug(doc['name'])}-{doc['_id']}",
            name=doc["name"],
            category=category,
            traits=tuple((system.get("traits") or {}).get("value") or []),
            level=_extract_level(system),
            source_book=_extract_source(system),
            text=clean_text(html),
            raw_json=json.dumps(doc, separators=(",", ":")),
            stats=extract_stats(category, system),
            source_url=f"https://2e.aonprd.com/Search.aspx?q={quote_plus(doc['name'])}",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources.py -v`
Expected: PASS (all source tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/ingest/sources.py tests/test_sources.py
git commit -m "feat: FoundrySource sets an AON search-by-name source_url"
```

---

## Task 5: `Fts5Retriever` maps `source_url` into results

**Files:**
- Modify: `pf_helper/retrieval/fts5.py`
- Test: `tests/test_retrieval.py`

- [ ] **Step 1: Write the failing tests (append to `tests/test_retrieval.py`)**

```python
def test_get_includes_source_url(tmp_path):
    r = _retriever(tmp_path)
    detail = r.get("Frightened", category="condition")
    assert detail is not None
    assert detail.source_url == "https://2e.aonprd.com/Search.aspx?q=Frightened"


def test_search_hits_include_source_url(tmp_path):
    r = _retriever(tmp_path)
    hits = r.search("status penalty", category="condition", limit=5)
    hit = next(h for h in hits if h.name == "Frightened")
    assert hit.source_url == "https://2e.aonprd.com/Search.aspx?q=Frightened"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retrieval.py -k source_url -v`
Expected: FAIL — `source_url` is `""` (retriever doesn't read the column).

- [ ] **Step 3: Map the column in `fts5.py`**

In `pf_helper/retrieval/fts5.py`, in `Fts5Retriever.search`, add `source_url=row["source_url"]` to the `SearchHit(...)`:

```python
            SearchHit(
                id=row["id"],
                name=row["name"],
                category=row["category"],
                level=row["level"],
                excerpt=_excerpt(row["text"]),
                source_url=row["source_url"],
            )
```

In `Fts5Retriever.get`, add `source_url=row["source_url"]` to the `EntryDetail(...)`:

```python
        return EntryDetail(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            level=row["level"],
            traits=traits,
            source_book=row["source_book"],
            stats=stats,
            text=row["text"],
            source_url=row["source_url"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: PASS (all retrieval tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/retrieval/fts5.py tests/test_retrieval.py
git commit -m "feat: surface source_url in search hits and entry detail"
```

---

## Task 6: `clean_aon` — AON markdown dialect → plain text

**Files:**
- Create: `pf_helper/ingest/aon_clean.py`
- Test: `tests/test_aon_clean.py`

- [ ] **Step 1: Write the failing golden tests**

`tests/test_aon_clean.py`:

```python
from pf_helper.ingest.aon_clean import clean_aon


def test_resolves_links_to_label():
    assert clean_aon("See [Aberration](/Traits.aspx?ID=1) now") == "See Aberration now"


def test_strips_title_tag_keeps_name():
    md = '<title level="1" right="Trait">[Aberration](/Traits.aspx?ID=1)</title>'
    assert clean_aon(md) == "Aberration"


def test_drops_self_closing_trait_tags():
    md = '<traits>\n<trait label="Uncommon" url="/x" />\n<trait label="Fire" url="/y" /></traits>'
    assert clean_aon(md) == ""  # traits are captured separately on the Entry


def test_row_column_layout_becomes_lines():
    md = '<row gap="medium"><column>A</column><column>B</column></row>'
    assert clean_aon(md) == "A\nB"


def test_keeps_standard_markdown_emphasis():
    md = "**Source** [Core Rulebook](/Sources.aspx?ID=1) pg. 628"
    assert clean_aon(md) == "**Source** Core Rulebook pg. 628"


def test_empty_returns_empty():
    assert clean_aon("") == ""
    assert clean_aon("   ") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_aon_clean.py -v`
Expected: FAIL — `No module named 'pf_helper.ingest.aon_clean'`.

- [ ] **Step 3: Implement `aon_clean.py`**

`pf_helper/ingest/aon_clean.py`:

```python
"""Convert AON's custom markdown dialect (from the Elasticsearch `markdown`
field) into clean plain text.

AON's `markdown` is not standard Markdown: it wraps content in custom tags such
as `<title>`, `<traits>`/`<trait .../>`, and `<row>`/`<column>`, and uses
`[label](url)` links. We resolve links to their label, turn block-closing tags
into line breaks, drop all remaining tags, then normalize whitespace. Standard
Markdown emphasis (`**bold**`, etc.) is left intact -- Claude reads it fine.
"""

from __future__ import annotations

import html
import re

# [label](url) -> label
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Block-level closing tags become a newline so adjacent blocks don't merge.
_BLOCK_CLOSE = re.compile(r"</(?:title|row|column|traits|p|li|h[1-6])>", re.IGNORECASE)
# Any remaining tag (opening, closing, or self-closing) is dropped.
_TAG = re.compile(r"<[^>]+>")


def _normalize_ws(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_aon(markdown: str) -> str:
    """Resolve AON links, strip AON's custom tags, and normalize whitespace."""
    if not markdown:
        return ""
    text = _MD_LINK.sub(lambda m: m.group(1), markdown)
    text = _BLOCK_CLOSE.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    return _normalize_ws(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_aon_clean.py -v`
Expected: PASS (6 tests). If a golden case differs, adjust the implementation until output matches exactly — do not weaken the tests.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/ingest/aon_clean.py tests/test_aon_clean.py
git commit -m "feat: add clean_aon for AON markdown dialect"
```

---

## Task 7: `AonSource` + config + `AON_CATEGORIES` + fixtures

**Files:**
- Modify: `pf_helper/config.py`, `pf_helper/ingest/sources.py`
- Create fixtures: `tests/fixtures/aon/trait.json`, `tests/fixtures/aon/ritual.json`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Add AON config**

In `pf_helper/config.py`, add two fields to the `Config` dataclass (after `retriever`) and a property:

```python
    retriever: str = "fts5"
    aon_es_url: str = "https://elasticsearch.aonprd.com/aon/_search"

    @property
    def aon_dir(self) -> Path:
        return self.data_dir / "aon"
```

- [ ] **Step 2: Create the test fixtures**

`tests/fixtures/aon/trait.json`:

```json
[
  {
    "id": "trait-1",
    "name": "Aberration",
    "category": "trait",
    "type": "Trait",
    "trait": [],
    "primary_source": "Core Rulebook",
    "url": "/Traits.aspx?ID=1",
    "markdown": "<title level=\"1\" right=\"Trait\">[Aberration](/Traits.aspx?ID=1)</title>\n\n**Source** [Core Rulebook](/Sources.aspx?ID=1) pg. 628\n\nAberrations are creatures from beyond the planes."
  }
]
```

`tests/fixtures/aon/ritual.json`:

```json
[
  {
    "id": "ritual-1",
    "name": "Animate Object",
    "category": "ritual",
    "type": "Ritual",
    "trait": ["Transmutation", "Uncommon"],
    "primary_source": "Core Rulebook",
    "level": 2,
    "url": "/Rituals.aspx?ID=1",
    "markdown": "<title level=\"1\" right=\"Ritual 2\">[Animate Object](/Rituals.aspx?ID=1)</title>\n\n<traits>\n<trait label=\"Uncommon\" url=\"/Traits.aspx?ID=159\" />\n<trait label=\"Transmutation\" url=\"/Traits.aspx?ID=155\" /></traits>\n\nYou transform the target into an animated object."
  }
]
```

- [ ] **Step 3: Write the failing test (edit `tests/test_sources.py`)**

Add `AonSource` to the existing sources import at the top of the file (so it
reads `from pf_helper.ingest.sources import AonSource, FoundrySource`), then
append the constant and tests at the end of the file:

```python
AON_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "aon"


def test_aon_source_maps_fields_and_cleans_text():
    src = AonSource(AON_FIXTURE_DIR)
    by_name = {e.name: e for e in src.iter_entries()}
    trait = by_name["Aberration"]
    assert trait.category == "trait"
    assert trait.id == "trait:aberration-trait-1"
    assert trait.source_book == "Core Rulebook"
    assert trait.source_url == "https://2e.aonprd.com/Traits.aspx?ID=1"
    assert "Aberrations are creatures from beyond the planes." in trait.text
    assert "<title" not in trait.text and "[Aberration]" not in trait.text


def test_aon_source_maps_traits_and_level():
    src = AonSource(AON_FIXTURE_DIR)
    ritual = next(e for e in src.iter_entries() if e.name == "Animate Object")
    assert ritual.category == "ritual"
    assert ritual.level == 2
    assert ritual.traits == ("Transmutation", "Uncommon")
    assert ritual.source_url == "https://2e.aonprd.com/Rituals.aspx?ID=1"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_sources.py -k aon -v`
Expected: FAIL — `cannot import name 'AonSource'`.

- [ ] **Step 5: Implement `AonSource` + `AON_CATEGORIES`**

In `pf_helper/ingest/sources.py`, add the import:

```python
from pf_helper.ingest.aon_clean import clean_aon
```

Add the category constant near `CATEGORY_MAP`:

```python
# AON Elasticsearch categories to ingest (those the Foundry compendium lacks).
# Adding one here (plus a matching Category enum value) is all that's needed.
AON_CATEGORIES: tuple[str, ...] = (
    "trait", "skill", "archetype", "rules",
    "class-feature", "heritage", "bloodline", "mystery", "patron", "lesson",
    "arcane-school", "domain", "implement", "ikon",
    "animal-companion", "familiar-ability",
    "ritual", "relic", "curse", "disease",
    "language", "plane", "vehicle",
)
```

Add the `AonSource` class (after `FoundrySource`):

```python
class AonSource(Source):
    """Yields Entries from locally-cached AON Elasticsearch JSON.

    Reads `<aon_dir>/<category>.json` (a JSON array of AON `_source` objects)
    for each category in AON_CATEGORIES. Missing files are skipped.
    """

    def __init__(self, aon_dir: str | Path):
        self.aon_dir = Path(aon_dir)

    def iter_entries(self) -> Iterator[Entry]:
        for category in AON_CATEGORIES:
            path = self.aon_dir / f"{category}.json"
            if not path.exists():
                continue
            try:
                docs = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(docs, list):
                continue
            for doc in docs:
                entry = self._to_entry(doc)
                if entry is not None:
                    yield entry

    def _to_entry(self, doc: dict) -> Entry | None:
        if not isinstance(doc, dict):
            return None
        name = doc.get("name")
        category = doc.get("category")
        aon_id = doc.get("id")
        if not name or not category or not aon_id:
            return None
        traits = doc.get("trait")
        level = doc.get("level")
        url = doc.get("url") or ""
        return Entry(
            id=f"{category}:{_slug(name)}-{aon_id}",
            name=name,
            category=category,
            traits=tuple(traits) if isinstance(traits, list) else (),
            level=level if isinstance(level, int) else None,
            source_book=doc.get("primary_source"),
            text=clean_aon(doc.get("markdown") or ""),
            raw_json=json.dumps(doc, separators=(",", ":")),
            source_url=f"https://2e.aonprd.com{url}" if url else "",
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources.py -v`
Expected: PASS (Foundry + AON source tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/config.py pf_helper/ingest/sources.py tests/fixtures/aon tests/test_sources.py
git commit -m "feat: add AonSource over cached AON JSON + AON_CATEGORIES"
```

---

## Task 8: AON fetch (`_ensure_aon_cache`) + wire both sources into `main`

**Files:**
- Modify: `pf_helper/ingest/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1: Write the failing multi-source build test (edit `tests/test_build.py`)**

Add `AonSource` to the existing sources import at the top (so it reads
`from pf_helper.ingest.sources import AonSource, FoundrySource`), then append the
constant and test at the end of the file:

```python
AON_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "aon"


def test_build_index_combines_foundry_and_aon(tmp_path):
    cfg = Config(data_dir=tmp_path)
    counts = build_index(cfg, [FoundrySource(FIXTURE_PACKS), AonSource(AON_FIXTURE_DIR)])
    assert counts["condition"] >= 1   # from Foundry
    assert counts["trait"] >= 1       # from AON
    assert counts["ritual"] >= 1      # from AON

    conn = db.connect(cfg.db_path)
    row = db.get_by_name(conn, "Aberration", category="trait")
    assert row is not None
    assert row["source_url"] == "https://2e.aonprd.com/Traits.aspx?ID=1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build.py::test_build_index_combines_foundry_and_aon -v`
Expected: FAIL — `cannot import name 'AonSource'` is already resolved (Task 7), so this should actually PASS already for the build part. If it passes, that confirms the multi-source build works; proceed to add the fetch + main wiring below (the real point of this task). If it fails, fix `build_index` per Task 3.

- [ ] **Step 3: Add `_ensure_aon_cache` and wire `main`**

In `pf_helper/ingest/build.py`, add imports at top:

```python
import json
import sys
import urllib.request

from pf_helper.ingest.sources import AON_CATEGORIES, AonSource, FoundrySource, Source
```

(Adjust the existing `from pf_helper.ingest.sources import ...` line to include `AON_CATEGORIES`, `AonSource`, `Source`, `FoundrySource`.)

Add the fetch function:

```python
def _ensure_aon_cache(cfg: Config, refresh: bool = False) -> None:
    """Fetch each AON category from Elasticsearch into data/aon/<category>.json.

    Skips categories already cached unless refresh=True. One bulk query per
    category (size 10000); all target categories are well under that.
    """
    cfg.aon_dir.mkdir(parents=True, exist_ok=True)
    for category in AON_CATEGORIES:
        path = cfg.aon_dir / f"{category}.json"
        if path.exists() and not refresh:
            continue
        body = json.dumps({"size": 10000, "query": {"match": {"category": category}}}).encode()
        req = urllib.request.Request(
            cfg.aon_es_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 (trusted AON URL)
            data = json.loads(resp.read())
        docs = [hit["_source"] for hit in data["hits"]["hits"]]
        path.write_text(json.dumps(docs), encoding="utf-8")
        print(f"  fetched {category:18} {len(docs)}")
```

Replace `main` with the both-sources version:

```python
def main() -> None:
    cfg = Config.from_env()
    refresh = "--refresh" in sys.argv[1:]
    print(f"Ensuring Foundry repo at {cfg.foundry_dir} ...")
    _ensure_foundry_repo(cfg)
    print(f"Ensuring AON cache at {cfg.aon_dir} (refresh={refresh}) ...")
    _ensure_aon_cache(cfg, refresh=refresh)
    print("Building index ...")
    counts = build_index(
        cfg,
        [FoundrySource(cfg.foundry_packs_root), AonSource(cfg.aon_dir)],
    )
    total = sum(counts.values())
    print(f"Indexed {total} entries into {cfg.db_path}")
    for cat in sorted(counts):
        print(f"  {cat:18} {counts[cat]}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS (full suite). `_ensure_aon_cache`/`main` do network I/O and are not unit-tested; only `build_index` over fixtures is.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add pf_helper/ingest/build.py tests/test_build.py
git commit -m "feat: fetch AON ES into local cache and ingest with Foundry"
```

---

## Task 9: Manual end-to-end build with real AON data

**Files:** none (operational verification).

- [ ] **Step 1: Run the real ingest**

Run:
```bash
uv run pf-helper-ingest
```
Expected: pulls/updates the Foundry repo, fetches each AON category (prints per-category fetch counts), writes `data/aon/*.json`, builds `data/pf2e.db`, and prints combined counts that now include `trait`, `skill`, `archetype`, `rules`, `ritual`, etc. (e.g. trait ≈ 900, rules ≈ 3600). Total should be roughly the prior ~24.8k Foundry entries plus several thousand AON entries.

- [ ] **Step 2: Smoke-test AON retrieval + source_url**

Run:
```bash
uv run python -c "from pf_helper.config import Config; from pf_helper.retrieval.factory import build_retriever; r=build_retriever(Config.from_env()); d=r.get('Aberration', category='trait'); print(d.name, '|', d.source_url); print(d.text[:160]); h=r.search('grant an item bonus', category='rules', limit=3); [print(x.category, x.name, x.source_url) for x in h]"
```
Expected: the Aberration trait prints with `source_url` `https://2e.aonprd.com/Traits.aspx?ID=1` and clean text (no `<title>`/`@`/`[..](..)`); the `rules` search returns relevant hits with AON deep-link `source_url`s. Spot-check a creature too: `r.get('Goblin Warrior', category='creature').source_url` should be a `Search.aspx?q=` link.

- [ ] **Step 3: Verify no raw AON markup leaked**

Run:
```bash
uv run python -c "import sqlite3; from pf_helper.config import Config; c=sqlite3.connect(Config.from_env().db_path); print('rows:', c.execute('SELECT COUNT(*) FROM entries').fetchone()[0]); print('raw <title leaks:', c.execute(\"SELECT COUNT(*) FROM entries WHERE text LIKE '%<title%'\").fetchone()[0]); print('unresolved md links:', c.execute(\"SELECT COUNT(*) FROM entries WHERE text LIKE '%](/%'\").fetchone()[0])"
```
Expected: `raw <title leaks: 0` and `unresolved md links: 0`. If non-zero, inspect those entries and extend `clean_aon` (add a golden test first), then rebuild.

- [ ] **Step 4: Commit nothing**

`data/` is gitignored. This task is a gate before the PR.

---

## Task 10: Final PR

- [ ] **Step 1: Full suite + lint**

Run:
```bash
uv run pytest -q
uv run ruff check .
```
Expected: all pass; ruff clean.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin feat/aon-supplement
gh pr create --base main --head feat/aon-supplement --title "feat: AON Elasticsearch supplement (traits, skills, rules, …) + source_url links" --body "<summary of tasks; paste uv run pytest -q result and the real-index combined counts from Task 9 as evidence>"
```

- [ ] **Step 3: Stop for user review**

Do not merge. Report test results and the real-index counts (Foundry + AON categories) in the PR body. The user reviews and merges (never self-merge unless explicitly told).

---

## Notes / deferred (designed-for, not in this plan)

- **Approach B — exact AON deep links for Foundry entries.** Harvest AON's
  name→url map for overlapping categories (creature, spell, feat, …) and attach
  exact AON pages to Foundry entries by normalized-name match, falling back to
  the search link. Its own spec/plan (name-matching, duplicate-name handling).
- **AON per-category stat extraction** (a sibling of `extract.py`).
- **Kingmaker/warfare subsystem categories** — add to `AON_CATEGORIES`.
- **Vector / hybrid retrieval** — unchanged from the base design.
