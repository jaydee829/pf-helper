# PF_Helper — MCP Rules-Retrieval Server — Design Spec

**Date:** 2026-05-29
**Status:** Approved design, pending spec review

## 1. Purpose

PF_Helper is a local **MCP server** that gives Claude fast, accurate access to
Pathfinder Second Edition (PF2e) rules content. The user asks Claude a rules
question in Claude Desktop or Claude Code; Claude calls PF_Helper's retrieval
tools to fetch the relevant rules text; Claude reasons over that text and
answers.

The server itself performs **no LLM calls** — it is a pure retrieval layer.
Claude is the reasoning engine, supplied via the user's existing Claude
subscription. This makes responses fast (no extra LLM round-trip inside the
server) and free beyond that subscription.

### Goals
- Runs entirely on the user's local machine.
- Fast: query latency dominated by a local SQLite lookup (milliseconds).
- Accurate: clean, complete rules text so Claude answers correctly.
- Works from both **Claude Desktop** and **Claude Code**.

### Non-goals (v1)
- The server does not call Claude or Gemini itself (see Deferred §9).
- No semantic/vector search in v1 (interface is ready for it — §9).
- No Docker/HTTP service in v1 (designed-for, deferred — §9).

## 2. Architecture overview

```
You ── ask ──▶ Claude (Desktop / Code)
                   │  MCP tool call (stdio)
                   ▼
            PF_Helper MCP server
                   │
            Retriever (FTS5)
                   │
            SQLite + FTS5 index  ◀── built offline by ingestion
```

**Transport:** stdio. The Claude client launches the server as a subprocess
on demand and manages its lifecycle. No daemon, no network port.

**Two phases:**
- **Ingestion (occasional, offline):** clone/pull the FoundryVTT PF2e repo →
  clean each entry → build the SQLite + FTS5 index at `data/pf2e.db`.
- **Query (every request):** Claude → MCP tool → `Fts5Retriever` → SQLite →
  results → Claude answers.

## 3. Stack & tooling

- **Language:** Python 3.14.
- **Env / deps / run:** `uv` (locked dependencies, `uv run`). No raw pip/venv.
- **Lint + format:** `ruff`.
- **MCP server:** official `mcp` Python SDK (FastMCP).
- **Index / storage:** SQLite + FTS5 via stdlib `sqlite3` (verified available,
  SQLite 3.50.4). No external services, no vector DB, no model downloads in v1.
- **Ingestion deps:** `git` (clone Foundry repo), stdlib JSON; `httpx` later
  for the AON supplement.
- **Tests:** `pytest`.
- **Library-doc rule:** when generating setup/API code for `mcp`, `uv`, `ruff`,
  `httpx`, etc., fetch current docs via Context7 first.

## 4. Components

Each component sits behind a clean interface so it can be understood, tested,
and replaced independently.

### 4.1 Data model — `pf_helper/models.py`
- `Entry`: `id, name, category, traits (list), level, source_book, text
  (cleaned plain text), raw_json`.
- `Result`: `id, name, category, traits, excerpt, score`.

### 4.2 Ingestion — `pf_helper/ingest/`
- `sources.py`
  - `Source` (ABC): `iter_entries() -> Iterable[Entry]`. The pluggability
    point for data origins.
  - `FoundrySource`: walks the cloned `foundryvtt/pf2e` repo's
    `packs/**/*.json` source files and normalizes each to an `Entry`.
    Covers all categories: spells, feats, creatures, equipment, ancestries,
    classes, backgrounds, conditions, traits, skills, actions, hazards,
    archetypes, rules.
  - `AonSource` *(deferred, same interface)*: AON Elasticsearch to fill gaps.
- `clean.py` — **accuracy-critical, thoroughly tested.** Converts Foundry's
  enriched text to clean plain text:
  - `@UUID[...]{Label}` → `Label`
  - `@Damage[...]`, `@Check[...]`, `@Template[...]` → readable text
  - inline rolls `[[/r ...]]` → readable text
  - strip HTML tags → plain text
- `build.py` — orchestrates: ensure repo present (clone/pull) → iterate the
  configured `Source` → clean → write to SQLite. Idempotent (drop + recreate).
  Malformed entries are skipped with a logged warning and a final count;
  the build never half-completes.

### 4.3 Storage — `pf_helper/store/`
- `schema.sql`:
  - `entries(id, name, category, traits, level, source_book, text, raw_json)`.
  - `entries_fts` — FTS5 virtual table over `name + category + traits + text`,
    BM25-ranked, kept in sync with `entries`.
- `db.py` — open/connect helpers, schema creation, insert/upsert.

### 4.4 Retrieval — `pf_helper/retrieval/`  *(hooks for future vector/hybrid)*
- `base.py`
  - `Retriever` (ABC):
    - `search(query, category=None, limit=10) -> list[Result]`
    - `get(name, category=None) -> Entry | None`
- `fts5.py`
  - `Fts5Retriever`: BM25 full-text search + optional category filter +
    exact-name fast path.
- `factory.py`
  - `build_retriever(config) -> Retriever`. Selects implementation by config
    (`fts5` default). A future `VectorRetriever` / `HybridRetriever` slots in
    here with **no changes to the server layer**.

### 4.5 MCP server — `pf_helper/server.py`
FastMCP server exposing **two** tools:

- `search(query, category=None, limit=10)` → ranked list of lean `Result`
  rows (name, category, one key stat — e.g. level/rank, short excerpt, id).
  `category` is a **JSON-schema enum** of the canonical PF2e categories
  (spell, feat, creature, equipment, ancestry, class, background, condition,
  trait, skill, action, hazard, archetype, rules). Because the enum ships in
  the tool schema, Claude knows the valid categories up front — **no discovery
  round-trip** — and the result rows stay token-cheap so Claude can scan many
  hits and refine.
- `get_entry(name, category=None)` → full cleaned text of one entry, with a
  **category-aware structured header** of the fields that matter for that type
  (creature → level/AC/HP/saves; spell → rank/traditions/range/area/targets;
  equipment → level/price/bulk/usage; etc.), followed by the body text.

**No `list_categories` tool.** Category discovery is handled by the enum in
the `search` schema. The canonical category set is validated against the built
DB at server start. (If a passive list is ever wanted, expose it as a read-only
MCP *resource*, not a tool — but it is not needed for v1.)

Tools return clear, structured "no results" / "run ingestion first" messages
instead of raising, so an MCP session never crashes.

### 4.6 Config — `pf_helper/config.py`
- DB path (default `data/pf2e.db`), retriever type (default `fts5`), Foundry
  repo path/URL. Future: embedding model name (deferred).

## 5. Data flow detail

**Setup:**
```
uv run python -m pf_helper.ingest
  → clone/pull foundryvtt/pf2e into data/foundry-pf2e
  → FoundrySource.iter_entries()
  → clean.py per entry
  → write entries + entries_fts to data/pf2e.db
  → print counts (by category, skipped)
```

**Query (inside a Claude session):**
```
Claude calls search("flat-footed", category="condition")
  → Fts5Retriever.search(...)
  → SQLite FTS5 BM25
  → top-k lean Result list
Claude (optionally) calls get_entry("Off-Guard", "condition")
  → category-aware header + full text → final answer
```

## 6. Error handling

- **Ingestion:** skip malformed entries (logged + counted); never leave a
  partially-built DB (build into a temp DB / transaction, swap on success).
- **Missing DB at query time:** tools return an actionable message
  ("index not found — run `uv run python -m pf_helper.ingest`").
- **No results:** tools return an explicit empty result with a hint, not an
  error.
- **Input validation:** clamp `limit`, validate `category` against known set.

## 7. Testing (TDD)

- `test_clean.py` — golden cases for each enricher type (`@UUID`, `@Damage`,
  `@Check`, inline rolls) and HTML stripping.
- `test_retrieval.py` — `Fts5Retriever` ranking, category filter, exact-name
  fast path, `get()` hit/miss — against a small committed JSON fixture set
  (no full Foundry clone needed in CI).
- `test_ingest.py` — `Entry` normalization from sample Foundry JSON; malformed
  entry skipped with count.
- MCP tool layer kept thin over tested functions.
- `ruff` clean; `pytest` green required before any PR is opened.

## 8. Project layout

```
pf_helper/
  __init__.py
  config.py
  models.py
  ingest/
    __init__.py
    sources.py      # Source ABC, FoundrySource, (AonSource later)
    clean.py        # Foundry enricher / HTML cleaning
    build.py        # orchestrates ingest -> SQLite
  store/
    __init__.py
    schema.sql
    db.py
  retrieval/
    __init__.py
    base.py         # Retriever ABC, Result
    fts5.py         # Fts5Retriever
    factory.py      # build_retriever(config)
  server.py         # FastMCP server + tools
tests/
  fixtures/         # small committed JSON entries
  test_clean.py
  test_retrieval.py
  test_ingest.py
data/               # gitignored: cloned repo + built pf2e.db
docs/
  superpowers/specs/2026-05-29-pf-helper-mcp-design.md
pyproject.toml      # uv + ruff config
README.md           # setup docs (see §10)
.gitignore
```

## 9. Explicitly deferred (YAGNI — but designed-for)

- **Vector / hybrid retrieval** — add `VectorRetriever` / `HybridRetriever`
  behind the existing `Retriever` interface; optional `sentence-transformers`
  + an embeddings column. The factory already dispatches by config.
- **Standalone LLM answering (Server role "B")** — an `answer/` module calling
  Claude or Gemini for non-MCP callers (scripts, bots). Retrieval layer is
  reused unchanged.
- **AON Elasticsearch supplement** — `AonSource` behind the existing `Source`
  interface to fill any Foundry gaps.
- **Docker / HTTP transport** — a streamable-HTTP entrypoint + Dockerfile for
  an always-on/networked service. Additive: server logic is transport-agnostic
  behind FastMCP.

## 10. Setup docs (README must cover)

1. Install `uv`.
2. `uv sync` to create the environment.
3. `uv run python -m pf_helper.ingest` to build the index (notes on first-run
   clone size + time).
4. Register the server with **Claude Desktop** (`claude_desktop_config.json`
   snippet) and **Claude Code** (`claude mcp add` / `.mcp.json` snippet).
5. Verify (ask Claude a sample rules question; how to confirm the tools loaded).
6. Re-ingesting to update content.
7. Troubleshooting (Python version, index-not-found, client not detecting
   the server).

## 11. Development workflow

- `uv` for env/deps/run; `ruff` for lint+format.
- New GitHub repo; all work on feature branches.
- Every change goes through a **PR to `main`**, which the **user reviews and
  approves** — no direct commits to `main`, no self-merge.
- The first PR ("project scaffolding") includes this spec, `pyproject.toml`,
  `ruff` config, `.gitignore`, README skeleton, and the package skeleton.
