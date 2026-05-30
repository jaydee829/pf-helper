# PF_Helper MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, pure-retrieval MCP server (Python) that gives Claude fast, accurate access to Pathfinder 2e rules from the FoundryVTT compendium, searchable via SQLite FTS5.

**Architecture:** An offline ingestion pipeline clones the `foundryvtt/pf2e` repo, cleans each entry's Foundry-enriched HTML into plain text, and builds a SQLite + FTS5 index. At query time a FastMCP stdio server exposes two tools (`search`, `get_entry`) over a `Retriever` interface; Claude (Desktop/Code) does all reasoning. No LLM calls inside the server.

**Tech Stack:** Python 3.14, `uv` (env/deps/run), `ruff` (lint+format), `mcp` (FastMCP), stdlib `sqlite3` + FTS5, `beautifulsoup4` (HTML→text), `pytest`. Git workflow: feature branches → PR → user approves.

---

## Reference: spec

Design spec: `docs/superpowers/specs/2026-05-29-pf-helper-mcp-design.md`. Read it before starting.

## Reference: FoundryVTT data shape (verified)

- Source content lives at `packs/pf2e/<pack>/<entry>.json`, **nested** (e.g. `packs/pf2e/spells/focus/aberrant-whispers.json`).
- Each entry is a JSON **object** with top-level `_id`, `name`, `type`, `system`.
- `_folders.json` files are JSON **arrays** of folder metadata — must be skipped.
- Description HTML: `system.description.value`.
- Traits: `system.traits.value` (list of strings).
- Level/rank: `system.level.value` (feats, spells); creatures use `system.details.level.value`.
- Source book: `system.publication.title` (remaster) or `system.source.value` (legacy).
- Enricher forms to clean (verified, by frequency): `@UUID[...]{Label}`, `@Damage[expr[type]]`, `@Check[stat|dc:N]`, `@Template[shape|distance:N]`, `@Embed[...]`, `@Localize[...]`, inline rolls `[[/r 1d4 #comment]]`.

## Reference: category coverage (v1)

v1 ingests Foundry document `type`s that map cleanly to categories. The
`CATEGORY_MAP` (Task 4) covers: condition, spell, feat, action, equipment,
creature, hazard, ancestry, class, background, deity. **Traits, skills,
archetypes, and narrative rules journals are deferred to the AON supplement**
(separate follow-up plan) — they are not clean item documents in Foundry.

## File structure (created by this plan)

```
pyproject.toml                  # uv project + ruff config + entry points
.gitignore
README.md                       # setup docs
pf_helper/
  __init__.py
  config.py                     # Config dataclass + defaults
  models.py                     # Category enum, Entry, SearchHit, EntryDetail
  ingest/
    __init__.py
    clean.py                    # enricher + HTML -> plain text
    extract.py                  # per-category stat extraction (statblock headers)
    sources.py                  # Source ABC, FoundrySource
    build.py                    # clone/pull + build SQLite index
  store/
    __init__.py
    schema.sql
    db.py                       # connect, create schema, insert, query helpers
  retrieval/
    __init__.py
    base.py                     # Retriever ABC
    fts5.py                     # Fts5Retriever
    factory.py                  # build_retriever(config)
  server.py                     # FastMCP server + tools
tests/
  fixtures/
    foundry/pf2e/conditions/frightened.json   # tiny committed sample pack
    foundry/pf2e/spells/spells/rank-1/heal.json
    foundry/pf2e/feats/test-feat.json
    foundry/pf2e/spells/_folders.json          # must be skipped
  test_clean.py
  test_models.py
  test_db.py
  test_extract.py
  test_sources.py
  test_build.py
  test_retrieval.py
  test_server.py
data/                           # gitignored: cloned repo + pf2e.db
```

---

## Task 0: Project scaffolding, repo, first PR

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md` (skeleton), `pf_helper/__init__.py`, all package `__init__.py` files, `tests/__init__.py`.

- [ ] **Step 1: Initialize the uv project**

Run (in `C:\Users\jayde\Documents\PF_Helper`):
```bash
uv init --package --name pf-helper --python 3.14
```
Expected: creates `pyproject.toml` and `src`/package files. If `uv init` creates a `src/` layout or `main.py`/`hello.py`, delete the sample module; we use a flat `pf_helper/` package at repo root (next steps).

- [ ] **Step 2: Add dependencies**

Run:
```bash
uv add "mcp[cli]" beautifulsoup4
uv add --dev ruff pytest
```
Expected: `pyproject.toml` `dependencies` contains `mcp[cli]`, `beautifulsoup4`; dev group contains `ruff`, `pytest`; `uv.lock` created.

- [ ] **Step 3: Configure pyproject — package, entry points, ruff**

Edit `pyproject.toml` so it contains (merge with what `uv init` generated; keep the resolved version pins uv wrote):
```toml
[project]
name = "pf-helper"
version = "0.1.0"
description = "Local MCP server exposing Pathfinder 2e rules to Claude."
requires-python = ">=3.14"
dependencies = [
    "mcp[cli]",
    "beautifulsoup4",
]

[project.scripts]
pf-helper = "pf_helper.server:main"
pf-helper-ingest = "pf_helper.ingest.build:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["pf_helper"]

[dependency-groups]
dev = [
    "ruff",
    "pytest",
]

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Create the package skeleton**

Create these empty files (just the package markers; content comes in later tasks):
`pf_helper/__init__.py`, `pf_helper/ingest/__init__.py`, `pf_helper/store/__init__.py`, `pf_helper/retrieval/__init__.py`, `tests/__init__.py`.

`pf_helper/__init__.py`:
```python
"""PF_Helper: a local MCP server exposing Pathfinder 2e rules to Claude."""

__version__ = "0.1.0"
```

- [ ] **Step 5: Write `.gitignore`**

`.gitignore`:
```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/

# uv
# (keep uv.lock committed)

# Project data (cloned repo + built index)
data/

# OS / editor
.DS_Store
.idea/
.vscode/
```

- [ ] **Step 6: Write README skeleton**

`README.md`:
```markdown
# PF_Helper

A local [MCP](https://modelcontextprotocol.io) server that gives Claude fast,
accurate access to Pathfinder Second Edition rules, sourced from the
[FoundryVTT PF2e](https://github.com/foundryvtt/pf2e) compendium.

Pure retrieval: Claude does the reasoning; this server does fast local search.

## Status

In development. Setup docs land in Task 10.
```

- [ ] **Step 7: Verify the project builds and lints clean**

Run:
```bash
uv sync
uv run ruff check .
uv run pytest -q
```
Expected: `uv sync` resolves; `ruff check` passes; `pytest` reports "no tests ran" (exit 5 is acceptable at this stage).

- [ ] **Step 8: Initialize git and create the GitHub repo**

Run:
```bash
git init -b main
git add -A
git commit -m "chore: project scaffolding (uv, ruff, package skeleton)"
gh repo create pf-helper --private --source=. --remote=origin --description "Local MCP server exposing Pathfinder 2e rules to Claude"
```
Note: requires `gh auth login` first. If the user prefers a public repo, drop `--private` and use `--public`. Do NOT push to `main` directly after this — the first content goes via PR (next step).

- [ ] **Step 9: Push scaffolding via a PR**

Run:
```bash
git checkout -b chore/scaffolding
git push -u origin chore/scaffolding
gh pr create --base main --head chore/scaffolding --title "chore: project scaffolding + design spec" --body "Scaffolds the uv/ruff project, package skeleton, and includes the approved design spec and implementation plan under docs/superpowers/."
```
Expected: PR opened. **Stop and let the user review + merge.** All subsequent tasks branch off `main` after this PR merges.

---

## Task 1: Data models and Category enum

**Files:**
- Create: `pf_helper/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from pf_helper.models import Category, Entry


def test_category_values_are_lowercase_strings():
    assert Category.SPELL.value == "spell"
    assert Category.CREATURE.value == "creature"
    # StrEnum compares equal to its string value
    assert Category.FEAT == "feat"


def test_category_from_value_roundtrip():
    assert Category("condition") is Category.CONDITION


def test_entry_is_constructible_and_frozen():
    e = Entry(
        id="condition:frightened",
        name="Frightened",
        category="condition",
        traits=("emotion", "fear"),
        level=None,
        source_book="Pathfinder Player Core",
        text="You're gripped by fear...",
        raw_json="{}",
    )
    assert e.name == "Frightened"
    assert e.traits == ("emotion", "fear")
    assert e.stats == ()  # default for categories without a statblock
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.models'`.

- [ ] **Step 3: Write minimal implementation**

`pf_helper/models.py`:
```python
"""Core data types shared across ingestion, storage, retrieval, and server."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    """Canonical PF2e content categories exposed to the search tool's enum."""

    SPELL = "spell"
    FEAT = "feat"
    CREATURE = "creature"
    EQUIPMENT = "equipment"
    ANCESTRY = "ancestry"
    CLASS = "class"
    BACKGROUND = "background"
    CONDITION = "condition"
    ACTION = "action"
    HAZARD = "hazard"
    DEITY = "deity"
    # Deferred to AON supplement: trait, skill, archetype, rules.


@dataclass(frozen=True)
class Entry:
    """A fully-cleaned rules entry, ready to index and serve."""

    id: str
    name: str
    category: str
    traits: tuple[str, ...]
    level: int | None
    source_book: str | None
    text: str
    raw_json: str
    # Ordered (label, value) pairs for the category-aware header. Empty for
    # categories without a statblock (condition, ancestry, ...). Default keeps
    # earlier construction sites and tests valid.
    stats: tuple[tuple[str, str], ...] = ()


class SearchHit(BaseModel):
    """A lean search result row (token-cheap; for scanning)."""

    id: str = Field(description="Stable entry id, e.g. 'spell:heal'")
    name: str
    category: str
    level: int | None = Field(default=None, description="Level or spell rank, if any")
    excerpt: str = Field(description="Short snippet of the entry text")


class EntryDetail(BaseModel):
    """Full entry with a category-aware header for get_entry."""

    id: str
    name: str
    category: str
    level: int | None = None
    traits: list[str] = Field(default_factory=list)
    source_book: str | None = None
    stats: dict[str, str] = Field(
        default_factory=dict,
        description="Category-aware header fields (e.g. creature AC/HP/saves, spell range/area)",
    )
    text: str = Field(description="Full cleaned plain-text rules content")
```

Note: `pydantic` ships transitively with `mcp`; if an import error occurs, run `uv add pydantic`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint and commit**

```bash
git checkout -b feat/models
uv run ruff check . && uv run ruff format .
git add pf_helper/models.py tests/test_models.py
git commit -m "feat: add Category enum and core data models"
```

---

## Task 2: Enricher + HTML cleaning (accuracy-critical)

**Files:**
- Create: `pf_helper/ingest/clean.py`
- Test: `tests/test_clean.py`

- [ ] **Step 1: Write the failing tests (golden cases)**

`tests/test_clean.py`:
```python
from pf_helper.ingest.clean import clean_text


def test_uuid_with_label_keeps_label():
    assert clean_text("Become @UUID[Compendium.pf2e.x.Item.Sickened]{Sickened 2} now") \
        == "Become Sickened 2 now"


def test_uuid_without_label_uses_last_segment():
    assert clean_text("See @UUID[Compendium.pf2e.conditionitems.Item.Confused]") \
        == "See Confused"


def test_damage_renders_dice_and_type():
    assert clean_text("deals @Damage[6d6[force]] damage") == "deals 6d6 force damage"


def test_damage_persistent_multitype():
    assert clean_text("@Damage[2d6[persistent,fire]]") == "2d6 persistent fire"


def test_check_with_dc():
    assert clean_text("attempt a @Check[flat|dc:5]") == "attempt a flat check (DC 5)"


def test_check_without_dc():
    assert clean_text("a @Check[performance] check") == "a performance check check"


def test_template_renders_distance_and_shape():
    assert clean_text("a @Template[burst|distance:15] area") == "a 15-foot burst area"


def test_inline_roll_keeps_dice_drops_comment():
    assert clean_text("lasts [[/r 1d4 #rounds]] rounds") == "lasts 1d4 rounds"


def test_strips_html_tags_and_unescapes_entities():
    assert clean_text("<p>You&apos;re <strong>gripped</strong></p>") == "You're gripped"


def test_paragraphs_become_blank_line_separated():
    assert clean_text("<p>One</p><p>Two</p>") == "One\n\nTwo"


def test_list_items_become_bullet_lines():
    assert clean_text("<ul><li>A</li><li>B</li></ul>") == "- A\n- B"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clean.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.ingest.clean'`.

- [ ] **Step 3: Write the implementation**

`pf_helper/ingest/clean.py`:
```python
"""Convert Foundry-enriched HTML descriptions into clean plain text.

Order matters: resolve enrichers (which can contain text we keep) *before*
stripping HTML, then normalize whitespace.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# @UUID[...]{Label}  -> Label
_UUID_LABELLED = re.compile(r"@UUID\[[^\]]*\]\{([^}]*)\}")
# @UUID[....Item.Name] -> Name  (last dot-separated segment inside brackets)
_UUID_BARE = re.compile(r"@UUID\[[^\]]*?([^.\]]+)\]")
# @Damage[expr[types]] (ignores any |options) -> "expr types"
_DAMAGE = re.compile(r"@Damage\[([0-9dD+\- ]+)\[([^\]]+)\][^\]]*\]")
# @Check[stat|dc:N|...] -> "stat check (DC N)"  /  @Check[stat] -> "stat check"
_CHECK = re.compile(r"@Check\[([^\]]+)\]")
# @Template[shape|distance:N|...] -> "N-foot shape"
_TEMPLATE = re.compile(r"@Template\[([^\]]+)\]")
# @Embed[...]{Label} -> Label ; @Embed[...] -> ""
_EMBED_LABELLED = re.compile(r"@Embed\[[^\]]*\]\{([^}]*)\}")
_EMBED_BARE = re.compile(r"@Embed\[[^\]]*\]")
# @Localize[...] -> "" (rare; no reliable inline text)
_LOCALIZE = re.compile(r"@Localize\[[^\]]*\]")
# [[/r 1d4 #comment]] or [[/br ...]] -> dice expression only
_INLINE_ROLL = re.compile(r"\[\[/[a-zA-Z]+\s+([0-9dD+\-* ]+?)(?:\s+#[^\]]*)?\]\]")


def _render_damage(m: re.Match[str]) -> str:
    dice = m.group(1).strip()
    types = " ".join(t.strip() for t in m.group(2).split(","))
    return f"{dice} {types}".strip()


def _render_check(m: re.Match[str]) -> str:
    parts = m.group(1).split("|")
    stat = parts[0].strip()
    dc = None
    for p in parts[1:]:
        p = p.strip()
        if p.startswith("dc:"):
            dc = p[3:].strip()
    return f"{stat} check (DC {dc})" if dc else f"{stat} check"


def _render_template(m: re.Match[str]) -> str:
    parts = m.group(1).split("|")
    shape = parts[0].strip()
    distance = None
    for p in parts[1:]:
        p = p.strip()
        if p.startswith("distance:"):
            distance = p[len("distance:"):].strip()
    return f"{distance}-foot {shape}" if distance else shape


def _resolve_enrichers(text: str) -> str:
    text = _UUID_LABELLED.sub(lambda m: m.group(1), text)
    text = _UUID_BARE.sub(lambda m: m.group(1), text)
    text = _DAMAGE.sub(_render_damage, text)
    text = _CHECK.sub(_render_check, text)
    text = _TEMPLATE.sub(_render_template, text)
    text = _EMBED_LABELLED.sub(lambda m: m.group(1), text)
    text = _EMBED_BARE.sub("", text)
    text = _LOCALIZE.sub("", text)
    text = _INLINE_ROLL.sub(lambda m: m.group(1).strip(), text)
    return text


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Convert list items to "- item" lines.
    for li in soup.find_all("li"):
        li.insert_before("- ")
        li.append("\n")
    # Paragraphs and block elements become blank-line separated.
    for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6"]):
        block.append("\n\n")
    text = soup.get_text()
    return text


def _normalize_ws(text: str) -> str:
    # Collapse runs of spaces/tabs, trim each line, collapse 3+ newlines to 2.
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_text(html: str) -> str:
    """Resolve Foundry enrichers, strip HTML, and normalize whitespace."""
    if not html:
        return ""
    return _normalize_ws(_html_to_text(_resolve_enrichers(html)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clean.py -v`
Expected: PASS (11 tests). If `test_list_items_become_bullet_lines` spacing differs, adjust `_html_to_text` list handling until output is exactly `- A\n- B`.

- [ ] **Step 5: Lint and commit**

```bash
git checkout -b feat/clean
uv run ruff check . && uv run ruff format .
git add pf_helper/ingest/clean.py tests/test_clean.py
git commit -m "feat: add Foundry enricher + HTML cleaning"
```

---

## Task 3: SQLite schema and db helpers

**Files:**
- Create: `pf_helper/store/schema.sql`, `pf_helper/store/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:
```python
from pf_helper.models import Entry
from pf_helper.store import db


def _entry(**kw) -> Entry:
    base = dict(
        id="condition:frightened",
        name="Frightened",
        category="condition",
        traits=("emotion",),
        level=None,
        source_book="Player Core",
        text="You're gripped by fear and take a status penalty.",
        raw_json="{}",
    )
    base.update(kw)
    return Entry(**base)


def test_insert_and_fetch_by_name(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry()])
    row = db.get_by_name(conn, "Frightened", category="condition")
    assert row is not None
    assert row["name"] == "Frightened"
    assert row["category"] == "condition"


def test_fts_search_matches_body(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry()])
    hits = db.fts_search(conn, "status penalty", category=None, limit=10)
    assert any(h["name"] == "Frightened" for h in hits)


def test_fts_search_respects_category_filter(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry(), _entry(id="spell:x", name="Fear", category="spell")])
    hits = db.fts_search(conn, "fear", category="spell", limit=10)
    assert all(h["category"] == "spell" for h in hits)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.store.db'`.

- [ ] **Step 3: Write the schema**

`pf_helper/store/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS entries (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    traits      TEXT NOT NULL,   -- comma-separated
    level       INTEGER,
    source_book TEXT,
    text        TEXT NOT NULL,
    stats_json  TEXT NOT NULL DEFAULT '[]',  -- JSON array of [label, value] pairs
    raw_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(category);
CREATE INDEX IF NOT EXISTS idx_entries_name ON entries(name);

-- External-content FTS5 table over the searchable fields.
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    name,
    category UNINDEXED,
    traits,
    text,
    content='entries',
    content_rowid='rowid'
);
```

- [ ] **Step 4: Write db.py**

`pf_helper/store/db.py`:
```python
"""SQLite + FTS5 storage helpers."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from pf_helper.models import Entry


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    sql = resources.files("pf_helper.store").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def insert_entries(conn: sqlite3.Connection, entries: Iterable[Entry]) -> int:
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
            e.raw_json,
        )
        for e in entries
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO entries "
        "(id, name, category, traits, level, source_book, text, stats_json, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    # Rebuild FTS from content table to stay in sync.
    conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
    conn.commit()
    return len(rows)


def get_by_name(
    conn: sqlite3.Connection, name: str, category: str | None = None
) -> sqlite3.Row | None:
    if category:
        cur = conn.execute(
            "SELECT * FROM entries WHERE name = ? COLLATE NOCASE AND category = ? LIMIT 1",
            (name, category),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM entries WHERE name = ? COLLATE NOCASE LIMIT 1", (name,)
        )
    return cur.fetchone()


def fts_search(
    conn: sqlite3.Connection, query: str, category: str | None, limit: int
) -> list[sqlite3.Row]:
    match = _to_match_query(query)
    sql = (
        "SELECT e.*, bm25(entries_fts) AS score "
        "FROM entries_fts JOIN entries e ON e.rowid = entries_fts.rowid "
        "WHERE entries_fts MATCH ?"
    )
    params: list[object] = [match]
    if category:
        sql += " AND e.category = ?"
        params.append(category)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _to_match_query(query: str) -> str:
    """Make a safe FTS5 MATCH string: quote each term, OR them together."""
    terms = [t for t in query.replace('"', " ").split() if t]
    if not terms:
        return '""'
    return " OR ".join(f'"{t}"' for t in terms)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint and commit**

```bash
git checkout -b feat/store
uv run ruff check . && uv run ruff format .
git add pf_helper/store/schema.sql pf_helper/store/db.py tests/test_db.py
git commit -m "feat: add SQLite + FTS5 storage layer"
```

---

## Task 4: Per-category stat extraction + FoundrySource ingestion

**Files:**
- Create: `pf_helper/ingest/extract.py`, `pf_helper/ingest/sources.py`
- Create fixtures: `tests/fixtures/foundry/pf2e/conditions/frightened.json`, `tests/fixtures/foundry/pf2e/spells/_folders.json`, `tests/fixtures/foundry/pf2e/feats/test-feat.json`, `tests/fixtures/foundry/pf2e/pathfinder-monster-core/test-creature.json`
- Test: `tests/test_extract.py`, `tests/test_sources.py`

Field paths below are verified against the real `foundryvtt/pf2e` repo.

- [ ] **Step 1: Write the failing extractor test**

`tests/test_extract.py`:
```python
from pf_helper.ingest.extract import extract_stats


def test_creature_stats():
    system = {
        "details": {"level": {"value": 6}},
        "attributes": {"ac": {"value": 24}, "hp": {"max": 120}, "speed": {"value": 25}},
        "perception": {"mod": 13},
        "saves": {"fortitude": {"value": 16}, "reflex": {"value": 14}, "will": {"value": 11}},
        "traits": {"size": {"value": "med"}, "value": ["humanoid"]},
    }
    stats = dict(extract_stats("creature", system))
    assert stats["AC"] == "24"
    assert stats["HP"] == "120"
    assert stats["Saves"] == "Fort +16, Ref +14, Will +11"
    assert stats["Perception"] == "+13"
    assert stats["Speed"] == "25 feet"
    assert stats["Size"] == "med"


def test_spell_stats():
    system = {
        "level": {"value": 3},
        "traits": {"traditions": ["arcane", "occult"]},
        "time": {"value": "2"},
        "range": {"value": "30 feet"},
        "area": {"type": "burst", "value": 20, "details": ""},
        "target": {"value": "1 creature"},
        "duration": {"value": "1 minute"},
        "defense": {"save": {"statistic": "will", "basic": False}},
    }
    stats = dict(extract_stats("spell", system))
    assert stats["Rank"] == "3"
    assert stats["Traditions"] == "arcane, occult"
    assert stats["Area"] == "20-foot burst"
    assert stats["Range"] == "30 feet"
    assert stats["Defense"] == "will"


def test_equipment_price_formatting():
    system = {"level": {"value": 1}, "price": {"value": {"gp": 5, "sp": 2}}, "bulk": {"value": 0.1}}
    stats = dict(extract_stats("equipment", system))
    assert stats["Price"] == "5 gp, 2 sp"
    assert stats["Bulk"] == "0.1"


def test_feat_activity_symbol():
    system = {"level": {"value": 2}, "actionType": {"value": "action"}, "actions": {"value": 1}}
    stats = dict(extract_stats("feat", system))
    assert stats["Level"] == "2"
    assert stats["Activity"] == "one action"


def test_action_reaction():
    system = {"actionType": {"value": "reaction"}, "actions": {"value": None}, "category": "defensive"}
    stats = dict(extract_stats("action", system))
    assert stats["Activity"] == "reaction"
    assert stats["Category"] == "defensive"


def test_hazard_stats():
    system = {
        "details": {"level": {"value": 23}},
        "attributes": {"ac": {"value": 45}, "hp": {"value": 300}, "stealth": {"value": 40}},
    }
    stats = dict(extract_stats("hazard", system))
    assert stats["AC"] == "45"
    assert stats["Stealth"] == "40"


def test_category_without_statblock_returns_empty():
    assert extract_stats("condition", {"value": {"isValued": True}}) == ()
    assert extract_stats("ancestry", {}) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.ingest.extract'`.

- [ ] **Step 3: Write extract.py**

`pf_helper/ingest/extract.py`:
```python
"""Per-category structured stat extraction from Foundry `system` data.

Returns an ordered tuple of (label, value) string pairs for get_entry's
category-aware header. Categories without a statblock return ().
All field paths are verified against the foundryvtt/pf2e repo.
"""

from __future__ import annotations

from collections.abc import Mapping


def _g(node: object, *path: str) -> object:
    cur = node
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _pairs(*items: tuple[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (label, str(value))
        for label, value in items
        if value is not None and value != ""
    )


def _format_price(price: object) -> str | None:
    if not isinstance(price, Mapping):
        return None
    parts = [f"{price[c]} {c}" for c in ("pp", "gp", "sp", "cp") if price.get(c)]
    return ", ".join(parts) if parts else None


_ACTIVITY_WORDS = {1: "one action", 2: "two actions", 3: "three actions"}


def _activity(system: Mapping) -> str | None:
    action_type = _g(system, "actionType", "value")
    count = _g(system, "actions", "value")
    if action_type == "action" and isinstance(count, int):
        return _ACTIVITY_WORDS.get(count, f"{count} actions")
    if action_type in ("reaction", "free", "passive"):
        return action_type
    return action_type if isinstance(action_type, str) else None


def _creature(s: Mapping) -> tuple[tuple[str, str], ...]:
    fort, ref, will = (
        _g(s, "saves", "fortitude", "value"),
        _g(s, "saves", "reflex", "value"),
        _g(s, "saves", "will", "value"),
    )
    saves = None
    if all(isinstance(v, int) for v in (fort, ref, will)):
        saves = f"Fort {fort:+d}, Ref {ref:+d}, Will {will:+d}"
    perception = _g(s, "perception", "mod")
    perception = f"{perception:+d}" if isinstance(perception, int) else None
    speed = _g(s, "attributes", "speed", "value")
    hp = _g(s, "attributes", "hp", "max")
    if hp is None:
        hp = _g(s, "attributes", "hp", "value")
    return _pairs(
        ("Level", _g(s, "details", "level", "value")),
        ("Size", _g(s, "traits", "size", "value")),
        ("AC", _g(s, "attributes", "ac", "value")),
        ("HP", hp),
        ("Perception", perception),
        ("Saves", saves),
        ("Speed", f"{speed} feet" if speed is not None else None),
    )


def _spell(s: Mapping) -> tuple[tuple[str, str], ...]:
    area = _g(s, "area")
    area_str = None
    if isinstance(area, Mapping):
        if area.get("details"):
            area_str = area["details"]
        elif area.get("value") is not None:
            area_str = f"{area['value']}-foot {area.get('type', '')}".strip()
    traditions = _g(s, "traits", "traditions")
    trad_str = ", ".join(traditions) if isinstance(traditions, list) and traditions else None
    return _pairs(
        ("Rank", _g(s, "level", "value")),
        ("Traditions", trad_str),
        ("Cast", _g(s, "time", "value")),
        ("Range", _g(s, "range", "value")),
        ("Area", area_str),
        ("Targets", _g(s, "target", "value")),
        ("Duration", _g(s, "duration", "value")),
        ("Defense", _g(s, "defense", "save", "statistic")),
    )


def _equipment(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Level", _g(s, "level", "value")),
        ("Price", _format_price(_g(s, "price", "value"))),
        ("Bulk", _g(s, "bulk", "value")),
        ("Usage", _g(s, "usage", "value")),
    )


def _feat(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Level", _g(s, "level", "value")),
        ("Activity", _activity(s)),
    )


def _action(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Activity", _activity(s)),
        ("Category", _g(s, "category")),
    )


def _hazard(s: Mapping) -> tuple[tuple[str, str], ...]:
    return _pairs(
        ("Level", _g(s, "details", "level", "value")),
        ("AC", _g(s, "attributes", "ac", "value")),
        ("HP", _g(s, "attributes", "hp", "value")),
        ("Stealth", _g(s, "attributes", "stealth", "value")),
    )


_EXTRACTORS = {
    "creature": _creature,
    "spell": _spell,
    "equipment": _equipment,
    "feat": _feat,
    "action": _action,
    "hazard": _hazard,
}


def extract_stats(category: str, system: Mapping) -> tuple[tuple[str, str], ...]:
    extractor = _EXTRACTORS.get(category)
    return extractor(system) if extractor else ()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extract.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Create test fixtures**

`tests/fixtures/foundry/pf2e/conditions/frightened.json`:
```json
{
  "_id": "TBSHQspnbcqxsmjL",
  "name": "Frightened",
  "type": "condition",
  "system": {
    "description": { "value": "<p>You're gripped by fear and take a status penalty equal to this value to all your checks and DCs.</p>" },
    "publication": { "title": "Pathfinder Player Core" },
    "traits": { "value": [] }
  }
}
```

`tests/fixtures/foundry/pf2e/feats/test-feat.json`:
```json
{
  "_id": "abc123",
  "name": "Test Feat",
  "type": "feat",
  "system": {
    "description": { "value": "<p>Become @UUID[Compendium.pf2e.conditionitems.Item.Sickened]{Sickened 1}.</p>" },
    "level": { "value": 4 },
    "publication": { "title": "Player Core" },
    "traits": { "value": ["general", "skill"] }
  }
}
```

`tests/fixtures/foundry/pf2e/spells/_folders.json`:
```json
[
  { "_id": "x", "name": "Cantrip", "type": "Item" }
]
```

`tests/fixtures/foundry/pf2e/pathfinder-monster-core/test-creature.json`:
```json
{
  "_id": "creat123",
  "name": "Test Beast",
  "type": "npc",
  "system": {
    "description": { "value": "<p>A fearsome test beast.</p>" },
    "details": { "level": { "value": 6 } },
    "attributes": { "ac": { "value": 24 }, "hp": { "max": 120 }, "speed": { "value": 25 } },
    "perception": { "mod": 13 },
    "saves": { "fortitude": { "value": 16 }, "reflex": { "value": 14 }, "will": { "value": 11 } },
    "publication": { "title": "Monster Core" },
    "traits": { "size": { "value": "med" }, "value": ["beast"] }
  }
}
```

- [ ] **Step 6: Write the failing test**

`tests/test_sources.py`:
```python
from pathlib import Path

from pf_helper.ingest.sources import FoundrySource

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "foundry"


def test_iter_entries_yields_known_entries():
    src = FoundrySource(FIXTURE_ROOT)
    by_name = {e.name: e for e in src.iter_entries()}
    assert "Frightened" in by_name
    assert "Test Feat" in by_name


def test_folders_file_is_skipped():
    src = FoundrySource(FIXTURE_ROOT)
    names = [e.name for e in src.iter_entries()]
    assert "Cantrip" not in names  # came from _folders.json


def test_entry_fields_are_mapped_and_cleaned():
    src = FoundrySource(FIXTURE_ROOT)
    feat = next(e for e in src.iter_entries() if e.name == "Test Feat")
    assert feat.category == "feat"
    assert feat.level == 4
    assert feat.source_book == "Player Core"
    assert feat.traits == ("general", "skill")
    assert feat.id == "feat:test-feat"
    assert "Sickened 1" in feat.text  # enricher resolved
    assert "@UUID" not in feat.text


def test_condition_level_is_none():
    src = FoundrySource(FIXTURE_ROOT)
    cond = next(e for e in src.iter_entries() if e.name == "Frightened")
    assert cond.level is None
    assert cond.category == "condition"


def test_creature_stats_are_populated():
    src = FoundrySource(FIXTURE_ROOT)
    beast = next(e for e in src.iter_entries() if e.name == "Test Beast")
    assert beast.category == "creature"
    stats = dict(beast.stats)
    assert stats["AC"] == "24"
    assert stats["Saves"] == "Fort +16, Ref +14, Will +11"
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/test_sources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.ingest.sources'`.

- [ ] **Step 8: Write the implementation**

`pf_helper/ingest/sources.py`:
```python
"""Content sources. v1: FoundrySource over a cloned foundryvtt/pf2e checkout."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from pathlib import Path

from pf_helper.ingest.clean import clean_text
from pf_helper.ingest.extract import extract_stats
from pf_helper.models import Entry

# Foundry document `type` -> our Category value. Types not present are skipped.
CATEGORY_MAP: dict[str, str] = {
    "condition": "condition",
    "spell": "spell",
    "feat": "feat",
    "action": "action",
    "hazard": "hazard",
    "npc": "creature",
    "ancestry": "ancestry",
    "heritage": "ancestry",
    "class": "class",
    "background": "background",
    "deity": "deity",
    # equipment-ish item types (verified against the equipment pack)
    "equipment": "equipment",
    "weapon": "equipment",
    "armor": "equipment",
    "shield": "equipment",
    "consumable": "equipment",
    "treasure": "equipment",
    "backpack": "equipment",
    "ammo": "equipment",
    "kit": "equipment",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")


class Source(ABC):
    """A source of rules Entries. The pluggability point for data origins."""

    @abstractmethod
    def iter_entries(self) -> Iterable[Entry]:
        ...


class FoundrySource(Source):
    """Walks `<root>/pf2e/<pack>/**/*.json` and yields cleaned Entries."""

    def __init__(self, root: str | Path):
        # root is the directory that contains the `pf2e/` packs tree.
        self.packs_root = Path(root) / "pf2e"

    def iter_entries(self) -> Iterator[Entry]:
        for path in sorted(self.packs_root.rglob("*.json")):
            if path.name == "_folders.json":
                continue
            entry = self._load(path)
            if entry is not None:
                yield entry

    def _load(self, path: Path) -> Entry | None:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(doc, dict):
            return None  # _folders.json arrays and other non-documents
        doc_type = doc.get("type")
        category = CATEGORY_MAP.get(doc_type)
        if category is None or "name" not in doc:
            return None
        system = doc.get("system", {})
        html = (system.get("description") or {}).get("value", "")
        return Entry(
            id=f"{category}:{_slug(doc['name'])}",
            name=doc["name"],
            category=category,
            traits=tuple((system.get("traits") or {}).get("value", []) or ()),
            level=_extract_level(system),
            source_book=_extract_source(system),
            text=clean_text(html),
            raw_json=json.dumps(doc, separators=(",", ":")),
            stats=extract_stats(category, system),
        )


def _extract_level(system: dict) -> int | None:
    level = (system.get("level") or {}).get("value")
    if level is None:
        level = ((system.get("details") or {}).get("level") or {}).get("value")
    return level if isinstance(level, int) else None


def _extract_source(system: dict) -> str | None:
    pub = system.get("publication") or {}
    if pub.get("title"):
        return pub["title"]
    src = system.get("source") or {}
    return src.get("value") or None
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources.py tests/test_extract.py -v`
Expected: PASS (5 source tests + 7 extract tests).

- [ ] **Step 10: Lint and commit**

```bash
git checkout -b feat/foundry-source
uv run ruff check . && uv run ruff format .
git add pf_helper/ingest/extract.py pf_helper/ingest/sources.py tests/fixtures tests/test_extract.py tests/test_sources.py
git commit -m "feat: add per-category stat extraction and FoundrySource ingestion"
```

---

## Task 5: Build orchestration (clone/pull + index)

**Files:**
- Create: `pf_helper/config.py`, `pf_helper/ingest/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1: Write config**

`pf_helper/config.py`:
```python
"""Runtime configuration with sensible local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Config:
    data_dir: Path = _DEFAULT_DATA
    foundry_repo_url: str = "https://github.com/foundryvtt/pf2e"
    retriever: str = "fts5"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pf2e.db"

    @property
    def foundry_dir(self) -> Path:
        return self.data_dir / "foundry-pf2e"

    @property
    def foundry_packs_root(self) -> Path:
        # FoundrySource expects the dir containing `pf2e/`.
        return self.foundry_dir / "packs"

    @classmethod
    def from_env(cls) -> "Config":
        data = os.environ.get("PF_HELPER_DATA_DIR")
        return cls(data_dir=Path(data)) if data else cls()
```

- [ ] **Step 2: Write the failing test**

`tests/test_build.py`:
```python
from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.build import build_index
from pf_helper.store import db

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "foundry"


def test_build_index_from_local_packs(tmp_path):
    cfg = Config(data_dir=tmp_path)
    counts = build_index(cfg, packs_root=FIXTURE_PACKS)
    assert counts["feat"] >= 1
    assert counts["condition"] >= 1

    conn = db.connect(cfg.db_path)
    row = db.get_by_name(conn, "Frightened", category="condition")
    assert row is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_build.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.ingest.build'`.

- [ ] **Step 4: Write build.py**

`pf_helper/ingest/build.py`:
```python
"""Build the SQLite + FTS5 index from a content source.

`build_index` is pure (takes an explicit packs_root) for testability.
`main` handles cloning/pulling the Foundry repo and wiring config.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.sources import FoundrySource
from pf_helper.store import db


def build_index(cfg: Config, packs_root: Path) -> dict[str, int]:
    """Ingest from packs_root into a fresh DB. Returns per-category counts."""
    if cfg.db_path.exists():
        cfg.db_path.unlink()
    conn = db.connect(cfg.db_path)
    db.create_schema(conn)

    source = FoundrySource(packs_root)
    counts: Counter[str] = Counter()
    batch = []
    for entry in source.iter_entries():
        batch.append(entry)
        counts[entry.category] += 1
    db.insert_entries(conn, batch)
    conn.close()
    return dict(counts)


def _ensure_foundry_repo(cfg: Config) -> None:
    if cfg.foundry_dir.exists():
        subprocess.run(["git", "-C", str(cfg.foundry_dir), "pull", "--ff-only"], check=True)
    else:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", cfg.foundry_repo_url, str(cfg.foundry_dir)],
            check=True,
        )


def main() -> None:
    cfg = Config.from_env()
    print(f"Ensuring Foundry repo at {cfg.foundry_dir} ...")
    _ensure_foundry_repo(cfg)
    print("Building index ...")
    counts = build_index(cfg, packs_root=cfg.foundry_packs_root)
    total = sum(counts.values())
    print(f"Indexed {total} entries into {cfg.db_path}")
    for cat in sorted(counts):
        print(f"  {cat:12} {counts[cat]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_build.py -v`
Expected: PASS (1 test).

- [ ] **Step 6: Lint and commit**

```bash
git checkout -b feat/build
uv run ruff check . && uv run ruff format .
git add pf_helper/config.py pf_helper/ingest/build.py tests/test_build.py
git commit -m "feat: add index build orchestration with Foundry clone/pull"
```

---

## Task 6: Retriever interface and Fts5Retriever

**Files:**
- Create: `pf_helper/retrieval/base.py`, `pf_helper/retrieval/fts5.py`
- Test: `tests/test_retrieval.py`

- [ ] **Step 1: Write the failing test**

`tests/test_retrieval.py`:
```python
from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.build import build_index
from pf_helper.retrieval.fts5 import Fts5Retriever

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "foundry"


def _retriever(tmp_path) -> Fts5Retriever:
    cfg = Config(data_dir=tmp_path)
    build_index(cfg, packs_root=FIXTURE_PACKS)
    return Fts5Retriever(cfg.db_path)


def test_search_returns_hits(tmp_path):
    r = _retriever(tmp_path)
    hits = r.search("status penalty", category=None, limit=10)
    assert any(h.name == "Frightened" for h in hits)
    assert all(hasattr(h, "excerpt") for h in hits)


def test_search_category_filter(tmp_path):
    r = _retriever(tmp_path)
    hits = r.search("sickened", category="feat", limit=10)
    assert all(h.category == "feat" for h in hits)


def test_search_clamps_limit(tmp_path):
    r = _retriever(tmp_path)
    hits = r.search("fear", category=None, limit=999)
    assert len(hits) <= 50


def test_get_returns_detail(tmp_path):
    r = _retriever(tmp_path)
    detail = r.get("Frightened", category="condition")
    assert detail is not None
    assert detail.name == "Frightened"
    assert "status penalty" in detail.text


def test_get_missing_returns_none(tmp_path):
    r = _retriever(tmp_path)
    assert r.get("Nonexistent Thing", category=None) is None


def test_get_includes_category_aware_stats(tmp_path):
    r = _retriever(tmp_path)
    detail = r.get("Test Beast", category="creature")
    assert detail is not None
    assert detail.stats["AC"] == "24"
    assert detail.stats["Saves"] == "Fort +16, Ref +14, Will +11"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.retrieval.fts5'`.

- [ ] **Step 3: Write base.py**

`pf_helper/retrieval/base.py`:
```python
"""Retriever interface. Implementations: Fts5Retriever (v1); Vector/Hybrid later."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pf_helper.models import EntryDetail, SearchHit

MAX_LIMIT = 50


class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, category: str | None, limit: int) -> list[SearchHit]:
        ...

    @abstractmethod
    def get(self, name: str, category: str | None) -> EntryDetail | None:
        ...
```

- [ ] **Step 4: Write fts5.py**

`pf_helper/retrieval/fts5.py`:
```python
"""SQLite FTS5-backed retriever."""

from __future__ import annotations

import json
from pathlib import Path

from pf_helper.models import EntryDetail, SearchHit
from pf_helper.retrieval.base import MAX_LIMIT, Retriever
from pf_helper.store import db

_EXCERPT_LEN = 240


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _EXCERPT_LEN else text[:_EXCERPT_LEN].rstrip() + "..."


class Fts5Retriever(Retriever):
    def __init__(self, db_path: str | Path):
        self._conn = db.connect(db_path)

    def search(self, query: str, category: str | None, limit: int) -> list[SearchHit]:
        limit = max(1, min(limit, MAX_LIMIT))
        rows = db.fts_search(self._conn, query, category, limit)
        return [
            SearchHit(
                id=row["id"],
                name=row["name"],
                category=row["category"],
                level=row["level"],
                excerpt=_excerpt(row["text"]),
            )
            for row in rows
        ]

    def get(self, name: str, category: str | None) -> EntryDetail | None:
        row = db.get_by_name(self._conn, name, category)
        if row is None:
            return None
        traits = [t for t in (row["traits"] or "").split(",") if t]
        stats = {label: value for label, value in json.loads(row["stats_json"] or "[]")}
        return EntryDetail(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            level=row["level"],
            traits=traits,
            source_book=row["source_book"],
            stats=stats,
            text=row["text"],
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Lint and commit**

```bash
git checkout -b feat/retrieval
uv run ruff check . && uv run ruff format .
git add pf_helper/retrieval/base.py pf_helper/retrieval/fts5.py tests/test_retrieval.py
git commit -m "feat: add Retriever interface and Fts5Retriever"
```

---

## Task 7: Retriever factory

**Files:**
- Create: `pf_helper/retrieval/factory.py`
- Test: add to `tests/test_retrieval.py`

- [ ] **Step 1: Write the failing test (append to tests/test_retrieval.py)**

```python
def test_factory_builds_fts5_retriever(tmp_path):
    from pf_helper.config import Config
    from pf_helper.retrieval.factory import build_retriever
    from pf_helper.retrieval.fts5 import Fts5Retriever

    cfg = Config(data_dir=tmp_path)
    build_index(cfg, packs_root=FIXTURE_PACKS)
    r = build_retriever(cfg)
    assert isinstance(r, Fts5Retriever)


def test_factory_rejects_unknown_retriever(tmp_path):
    from dataclasses import replace

    import pytest

    from pf_helper.config import Config
    from pf_helper.retrieval.factory import build_retriever

    cfg = replace(Config(data_dir=tmp_path), retriever="bogus")
    with pytest.raises(ValueError, match="Unknown retriever"):
        build_retriever(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retrieval.py -k factory -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pf_helper.retrieval.factory'`.

- [ ] **Step 3: Write factory.py**

`pf_helper/retrieval/factory.py`:
```python
"""Selects a Retriever implementation from config. Future vector/hybrid slot here."""

from __future__ import annotations

from pf_helper.config import Config
from pf_helper.retrieval.base import Retriever
from pf_helper.retrieval.fts5 import Fts5Retriever


def build_retriever(cfg: Config) -> Retriever:
    if cfg.retriever == "fts5":
        return Fts5Retriever(cfg.db_path)
    raise ValueError(f"Unknown retriever: {cfg.retriever!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retrieval.py -k factory -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint and commit**

```bash
git checkout -b feat/factory
uv run ruff check . && uv run ruff format .
git add pf_helper/retrieval/factory.py tests/test_retrieval.py
git commit -m "feat: add retriever factory"
```

---

## Task 8: MCP server and tools

**Files:**
- Create: `pf_helper/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

`tests/test_server.py`:
```python
from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.build import build_index
from pf_helper import server as srv

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "foundry"


def _setup(tmp_path):
    cfg = Config(data_dir=tmp_path)
    build_index(cfg, packs_root=FIXTURE_PACKS)
    srv.configure(cfg)


def test_search_tool_returns_hits(tmp_path):
    _setup(tmp_path)
    hits = srv.search("status penalty", category="condition", limit=5)
    assert any(h.name == "Frightened" for h in hits)


def test_search_missing_db_returns_empty_with_hint(tmp_path):
    srv.configure(Config(data_dir=tmp_path))  # no build -> no db file
    hits = srv.search("anything", category=None, limit=5)
    assert hits == []


def test_get_entry_tool_returns_detail(tmp_path):
    _setup(tmp_path)
    detail = srv.get_entry("Frightened", category="condition")
    assert detail is not None
    assert "status penalty" in detail.text


def test_get_entry_unknown_returns_none(tmp_path):
    _setup(tmp_path)
    assert srv.get_entry("Does Not Exist", category=None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `server` has no `configure`/`search`/`get_entry`.

- [ ] **Step 3: Write server.py**

`pf_helper/server.py`:
```python
"""FastMCP stdio server exposing PF2e retrieval tools.

Two tools: `search` (lean hits, category enum) and `get_entry` (full detail).
The server performs no LLM calls — Claude reasons over what these return.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from pf_helper.config import Config
from pf_helper.models import Category, EntryDetail, SearchHit
from pf_helper.retrieval.base import Retriever
from pf_helper.retrieval.factory import build_retriever

mcp = FastMCP("PF_Helper")

_cfg: Config = Config.from_env()
_retriever: Retriever | None = None


def configure(cfg: Config) -> None:
    """Override config and reset the cached retriever (used by tests and main)."""
    global _cfg, _retriever
    _cfg = cfg
    _retriever = None


def _get_retriever() -> Retriever | None:
    global _retriever
    if _retriever is None:
        if not Path(_cfg.db_path).exists():
            return None
        _retriever = build_retriever(_cfg)
    return _retriever


@mcp.tool()
def search(query: str, category: Category | None = None, limit: int = 10) -> list[SearchHit]:
    """Search Pathfinder 2e rules. Returns lean ranked hits (name, category,
    level, excerpt, id). Use `category` to scope; call `get_entry` for full text.
    If the index is missing, returns an empty list."""
    r = _get_retriever()
    if r is None:
        return []
    cat = category.value if category is not None else None
    return r.search(query, category=cat, limit=limit)


@mcp.tool()
def get_entry(name: str, category: Category | None = None) -> EntryDetail | None:
    """Fetch the full cleaned text of one PF2e entry by exact name (optionally
    scoped by category). Returns None if not found."""
    r = _get_retriever()
    if r is None:
        return None
    cat = category.value if category is not None else None
    return r.get(name, category=cat)


def main() -> None:
    configure(Config.from_env())
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Full suite + lint**

Run:
```bash
uv run pytest -q
uv run ruff check .
```
Expected: all tests pass; ruff clean.

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/server
uv run ruff format .
git add pf_helper/server.py tests/test_server.py
git commit -m "feat: add FastMCP server with search and get_entry tools"
```

---

## Task 9: Manual end-to-end index build (real data)

**Files:** none (operational verification).

- [ ] **Step 1: Build the real index**

Run:
```bash
uv run pf-helper-ingest
```
Expected: clones `foundryvtt/pf2e` into `data/foundry-pf2e` (first run downloads the repo — note it is large), prints per-category counts, writes `data/pf2e.db`. Confirm counts are non-trivial (spells in the hundreds, feats in the thousands).

- [ ] **Step 2: Smoke-test retrieval from a REPL**

Run:
```bash
uv run python -c "from pf_helper.config import Config; from pf_helper.retrieval.factory import build_retriever; r=build_retriever(Config.from_env()); [print(h.category, h.name) for h in r.search('flat-footed off-guard', category=None, limit=5)]"
```
Expected: prints several relevant hits (e.g. the Off-Guard condition). If empty, revisit `_to_match_query` / category mapping.

- [ ] **Step 3: Commit nothing**

`data/` is gitignored. No commit. This task is a gate before wiring clients.

---

## Task 10: Setup docs + client wiring

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write full README setup docs**

Replace `README.md` body with complete instructions:

```markdown
# PF_Helper

A local MCP server that gives Claude fast, accurate access to Pathfinder
Second Edition rules, sourced from the FoundryVTT PF2e compendium. Pure
retrieval — Claude reasons; this server searches.

## Requirements
- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- git
- Claude Desktop and/or Claude Code

## Install
```bash
uv sync
```

## Build the rules index (first run)
```bash
uv run pf-helper-ingest
```
This clones the FoundryVTT PF2e repo into `data/foundry-pf2e` (large; first
run takes a few minutes) and builds `data/pf2e.db`. Re-run anytime to update.

## Register with Claude Desktop
Edit `claude_desktop_config.json`
(Windows: `%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "pf-helper": {
      "command": "uv",
      "args": ["run", "pf-helper"],
      "cwd": "C:\\Users\\jayde\\Documents\\PF_Helper"
    }
  }
}
```
Restart Claude Desktop. The `pf-helper` tools should appear.

## Register with Claude Code
```bash
claude mcp add pf-helper -- uv run pf-helper
```
Run this from the project directory (so `uv` resolves this project), or add a
`.mcp.json` with the same command. Verify with `claude mcp list`.

## Verify
Ask Claude: "Using pf-helper, what does the frightened condition do?" Claude
should call `search`/`get_entry` and answer from the indexed text.

## Updating content
Re-run `uv run pf-helper-ingest` to pull the latest Foundry data and rebuild.

## Troubleshooting
- **"index not found" / empty results:** run `uv run pf-helper-ingest`.
- **Client doesn't list the server:** confirm `cwd` is the project root and
  `uv run pf-helper` works in a terminal.
- **Wrong Python:** `uv run python --version` should be 3.14+.
```

- [ ] **Step 2: Verify the documented commands work**

Run:
```bash
uv run pf-helper --help 2>&1 | head -5 || true
claude mcp list 2>&1 | head -5 || true
```
Expected: `uv run pf-helper` starts (it will block waiting on stdio — Ctrl-C to exit; that confirms it launches). `claude mcp list` shows `pf-helper` if added.

- [ ] **Step 3: Commit**

```bash
git checkout -b docs/setup
uv run ruff check .
git add README.md
git commit -m "docs: add full setup and client-wiring instructions"
```

---

## Task 11: Final PR

- [ ] **Step 1: Open the feature PR(s)**

Push each feature branch and open PRs against `main` for the user to review and
approve (per workflow — no self-merge). Suggested grouping if batching: one PR
"feat: PF_Helper retrieval MCP server (Tasks 1-8)" plus "docs: setup (Task 10)".

```bash
git push -u origin <branch>
gh pr create --base main --head <branch> --title "<title>" --body "<summary of tasks, test evidence: uv run pytest output>"
```

- [ ] **Step 2: Stop for user review**

Do not merge. Report test results (`uv run pytest -q`) and the real-index
counts from Task 9 in the PR body as evidence.

---

## Notes / deferred (designed-for, not in this plan)

- **AON Elasticsearch supplement** — `AonSource(Source)` to add trait, skill,
  archetype, and narrative rules entries not present as Foundry item docs.
  Separate spec + plan.
- **Vector / hybrid retrieval** — `VectorRetriever` / `HybridRetriever` behind
  the `Retriever` interface; extend `build_retriever`. Add an embeddings column.
- **Standalone LLM answering (server role B)** — `answer/` module calling
  Claude/Gemini for non-MCP callers.
- **Docker / HTTP transport** — `mcp.run(transport="streamable-http")` entry +
  Dockerfile for an always-on/networked service.

Category-aware `get_entry` headers ARE in v1 (Task 4 `extract.py`): creature
AC/HP/saves/perception/speed, spell rank/traditions/range/area/defense,
equipment level/price/bulk/usage, feat & action activity, hazard AC/HP/stealth.
Categories without a statblock (condition, ancestry, background, class, deity)
return an empty `stats` map and rely on the cleaned narrative `text`.
