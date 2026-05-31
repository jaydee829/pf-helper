# Discord Bot Front-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Discord bot for PF_Helper with deterministic `/lookup` + `/search` (local index, no LLM) and an LLM `/ask` powered by the Claude Agent SDK on the user's Claude subscription, plus a shared, front-end-agnostic answering layer with an answer cache.

**Architecture:** A shared `pf_helper/answer/` package (Answerer engines + `ask()` orchestrator + answer cache) makes the subscription LLM call; the Discord bot (`pf_helper/bot/`) is a thin discord.py front-end that reuses the existing `Retriever` for `/lookup`·`/search` and calls `pf_helper.answer.ask` for `/ask`. Engine A gives the agent in-process SDK tools wrapping the `Retriever`; engine B is a single tool-less RAG query; `ask` tries cache → A → B.

**Tech Stack:** Python 3.14, `uv`, `ruff`, `pytest`, stdlib `sqlite3`; `discord.py` and `claude-agent-sdk` (optional `bot` extra). Git: branch `feat/discord-bot` → PR → user approves.

## Reference

- Spec: `docs/superpowers/specs/2026-05-30-discord-bot-design.md` (read first).
- **Claude Agent SDK (verified):** `from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock, tool, create_sdk_mcp_server, ClaudeSDKError, CLINotFoundError`. `query(prompt, options)` is an async generator of messages; `ClaudeAgentOptions(system_prompt=..., max_turns=..., mcp_servers={...}, allowed_tools=[...])`. In-process tools: `@tool(name, desc, {"arg": type})` async fns returning `{"content":[{"type":"text","text":...}]}`, bundled via `create_sdk_mcp_server(name=, tools=[...])` and referenced as `mcp__<server>__<tool>` in `allowed_tools`. Auth uses the logged-in Claude Code subscription (no API key). There is **no typed rate-limit error** — the fallback triggers on any `ClaudeSDKError`; `CLINotFoundError` (a subclass) means "not signed in".
- **discord.py (verified):** `commands.Bot(command_prefix=..., intents=discord.Intents.default())`; slash commands via `@bot.tree.command(name=, description=)` with a typed `interaction: discord.Interaction` first param and optional params as Python defaults; `@app_commands.describe(...)`; `await interaction.response.defer(thinking=True)` then `await interaction.followup.send(embed=...)`; `discord.Embed(title=, url=, description=)` + `.add_field(name=, value=, inline=)`; sync in `setup_hook` via `await bot.tree.sync(guild=discord.Object(id=...))`; `bot.run(token)`.

## Working notes

- Run from `C:\Users\jayde\Documents\PF_Helper` (Windows). Branch is `feat/discord-bot`; commit on it (do NOT create new branches). Commit footer: blank line then exactly `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **`uv run --no-sync` for pytest/ruff** to avoid the Windows file-lock from a running Claude Desktop `pf-helper.exe`. **Exception:** Task 2 runs `uv add` (which must sync) — if it fails with a locked-file error, the Claude Desktop pf-helper server is running and holding the venv exe; fully quit Claude Desktop, run the `uv add`, then resume with `--no-sync`.
- After Task 2 installs `discord.py` + `claude-agent-sdk` into the dev environment, all later tests can import them.
- Ruff: line-length 100, target py314, select E,F,I,UP,B.

## File structure (created by this plan)

```
pf_helper/server.py            # MODIFY: tool docstring nudge (Task 1)
pyproject.toml                 # MODIFY: bot extra + dev deps + entry point (Task 2)
pf_helper/answer/
  __init__.py                  # re-export ask, Answer, AnswerConfig, AnswerError
  base.py                      # Answer dataclass, Answerer ABC, AnswerError (Task 3)
  config.py                    # AnswerConfig.from_env (Task 3)
  cache.py                     # normalize_question, AnswerCache (Task 4)
  engines.py                   # ContextRagAnswerer (Task 5), AgentMcpAnswerer (Task 6)
  service.py                   # ask() orchestrator (Task 7)
pf_helper/bot/
  __init__.py
  config.py                    # BotConfig.from_env (Task 8)
  embeds.py                    # pure embed builders + truncation (Task 8)
  main.py                      # discord client + slash commands + main() (Task 9)
tests/
  test_server_docstrings.py    # Task 1
  test_answer_cache.py         # Task 4
  test_answer_service.py       # Task 7
  test_answer_engines.py       # Tasks 5-6 (mocked SDK / direct tool fns)
  test_bot_embeds.py           # Task 8
README.md                      # MODIFY: Discord bot section (Task 10)
```

---

## Task 1: MCP tool link-citation nudge (companion)

**Files:** Modify `pf_helper/server.py`; Test `tests/test_server_docstrings.py`.

- [ ] **Step 1: Write the failing test**

`tests/test_server_docstrings.py`:
```python
from pf_helper import server


def test_search_docstring_mentions_source_url():
    assert "source_url" in server.search.__doc__
    assert "AON" in server.search.__doc__


def test_get_entry_docstring_mentions_source_url():
    assert "source_url" in server.get_entry.__doc__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_server_docstrings.py -v`
Expected: FAIL — docstrings don't mention `source_url`/`AON` yet.

- [ ] **Step 3: Update the tool docstrings**

In `pf_helper/server.py`, append a sentence to the `search` tool docstring and the `get_entry` tool docstring. For `search`, the docstring currently ends with the missing-index note; add:
```
    Each hit includes a `source_url` (its Archives of Nethys page) — cite it
    when you answer.
```
For `get_entry`, add to its docstring:
```
    The result includes a `source_url` (Archives of Nethys page); cite it when
    you answer.
```
(Insert inside the existing triple-quoted docstrings; do not change tool behavior or signatures.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_server_docstrings.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/server.py tests/test_server_docstrings.py
git commit -m "feat: nudge AON source_url citation in MCP tool docstrings"
```

---

## Task 2: Optional `bot` deps + dev deps + entry point

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1: Add the dependencies**

Run (quit Claude Desktop first if `uv add` reports a locked `pf-helper.exe`):
```bash
uv add --optional bot "discord.py" "claude-agent-sdk"
uv add --dev "discord.py" "claude-agent-sdk"
```
Expected: `pyproject.toml` gains `[project.optional-dependencies] bot = ["discord.py", "claude-agent-sdk"]`, the dev group gains both (so tests can import them), and `uv.lock` updates.

- [ ] **Step 2: Add the entry point**

Edit `pyproject.toml` `[project.scripts]` to add the bot entry point alongside the existing two:
```toml
[project.scripts]
pf-helper = "pf_helper.server:main"
pf-helper-ingest = "pf_helper.ingest.build:main"
pf-helper-bot = "pf_helper.bot.main:main"
```

- [ ] **Step 3: Verify the environment**

Run:
```bash
uv run --no-sync python -c "import discord, claude_agent_sdk; print('ok', discord.__version__)"
uv run --no-sync pytest -q
```
Expected: prints `ok <version>`; full suite still passes (no new tests yet besides Task 1).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add discord.py + claude-agent-sdk (optional bot extra + dev)"
```

---

## Task 3: Answer model, Answerer ABC, AnswerConfig

**Files:** Create `pf_helper/answer/__init__.py`, `pf_helper/answer/base.py`, `pf_helper/answer/config.py`; Test `tests/test_answer_service.py` (config/base portion).

- [ ] **Step 1: Write the failing test**

`tests/test_answer_service.py`:
```python
from pf_helper.answer import Answer, AnswerConfig, AnswerError


def test_answer_defaults():
    a = Answer(text="hi")
    assert a.sources == []
    assert a.engine == ""


def test_answer_config_from_env(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_ENGINE", "B")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE", "0")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE_TTL_DAYS", "7")
    cfg = AnswerConfig.from_env()
    assert cfg.engine == "b"           # lower-cased
    assert cfg.cache_enabled is False
    assert cfg.cache_ttl_days == 7
    assert cfg.core.db_path.name == "pf2e.db"


def test_answer_error_reason():
    e = AnswerError("auth", "sign in")
    assert e.reason == "auth"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_answer_service.py -v`
Expected: FAIL — `pf_helper.answer` does not exist.

- [ ] **Step 3: Write `base.py`**

`pf_helper/answer/base.py`:
```python
"""Core types for the shared answering layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Answer:
    """An LLM answer plus the AON sources it was grounded in."""

    text: str
    sources: list[tuple[str, str]] = field(default_factory=list)  # (name, source_url)
    engine: str = ""  # "agent" | "rag" | "cache"


class AnswerError(Exception):
    """An answering failure with a user-facing reason: 'auth' | 'quota' | 'error'."""

    def __init__(self, reason: str, message: str = ""):
        self.reason = reason
        super().__init__(message or reason)


class Answerer(ABC):
    """Produces an Answer for a question."""

    @abstractmethod
    async def answer(self, question: str) -> Answer: ...
```

- [ ] **Step 4: Write `config.py`**

`pf_helper/answer/config.py`:
```python
"""Configuration for the answering layer (engine choice + cache knobs)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pf_helper.config import Config


@dataclass(frozen=True)
class AnswerConfig:
    engine: str = "auto"  # "auto" (A->B) | "a" | "b"
    cache_enabled: bool = True
    cache_ttl_days: int = 30
    cache_max: int = 500
    core: Config = field(default_factory=Config.from_env)

    @classmethod
    def from_env(cls) -> "AnswerConfig":
        return cls(
            engine=os.environ.get("PF_HELPER_ASK_ENGINE", "auto").lower(),
            cache_enabled=os.environ.get("PF_HELPER_ASK_CACHE", "1") != "0",
            cache_ttl_days=int(os.environ.get("PF_HELPER_ASK_CACHE_TTL_DAYS", "30")),
            cache_max=int(os.environ.get("PF_HELPER_ASK_CACHE_MAX", "500")),
            core=Config.from_env(),
        )
```

- [ ] **Step 5: Write `__init__.py`**

`pf_helper/answer/__init__.py`:
```python
"""Shared, front-end-agnostic LLM answering layer for PF_Helper."""

from pf_helper.answer.base import Answer, AnswerError, Answerer
from pf_helper.answer.config import AnswerConfig

__all__ = ["Answer", "AnswerError", "Answerer", "AnswerConfig"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_answer_service.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/answer/__init__.py pf_helper/answer/base.py pf_helper/answer/config.py tests/test_answer_service.py
git commit -m "feat: add answering-layer core types and config"
```

---

## Task 4: Answer cache

**Files:** Create `pf_helper/answer/cache.py`; Test `tests/test_answer_cache.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_answer_cache.py`:
```python
import time

from pf_helper.answer.base import Answer
from pf_helper.answer.cache import AnswerCache, normalize_question


def test_normalize_collides_phrasings():
    a = normalize_question("How does flanking work?")
    b = normalize_question("  how does Flanking work ?? ")
    c = normalize_question("how does flanking work")
    assert a == b == c == "how does flanking work"


def _cache(tmp_path):
    index = tmp_path / "pf2e.db"
    index.write_text("v1")  # stand-in index file for versioning
    return AnswerCache(tmp_path / "ask_cache.db", index, ttl_days=30, max_rows=3), index


def test_put_then_get_hit(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("How does flanking work?", Answer("Flank text", [("Flanking", "https://x")], "agent"))
    hit = cache.get("how does flanking work")  # different phrasing, same norm
    assert hit is not None
    assert hit.text == "Flank text"
    assert hit.sources == [("Flanking", "https://x")]
    assert hit.engine == "cache"


def test_miss_returns_none(tmp_path):
    cache, _ = _cache(tmp_path)
    assert cache.get("never asked") is None


def test_index_version_busts(tmp_path):
    cache, index = _cache(tmp_path)
    cache.put("q", Answer("ans", [("n", "u")]))
    index.write_text("v2-changed-bigger")  # mtime + size change -> new version
    assert cache.get("q") is None


def test_ttl_expiry(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("q", Answer("ans", [("n", "u")]))
    # Force the row's created_at into the past beyond the TTL.
    cache._conn.execute("UPDATE answers SET created_at = ?", (time.time() - 31 * 86400,))
    cache._conn.commit()
    assert cache.get("q") is None


def test_size_cap_evicts_oldest(tmp_path):
    cache, _ = _cache(tmp_path)  # max_rows=3
    for i in range(5):
        cache.put(f"q{i}", Answer(f"a{i}", [("n", "u")]))
        time.sleep(0.01)
    rows = cache._conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    assert rows == 3
    assert cache.get("q0") is None  # oldest evicted
    assert cache.get("q4") is not None  # newest kept
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -v`
Expected: FAIL — `pf_helper.answer.cache` does not exist.

- [ ] **Step 3: Write `cache.py`**

`pf_helper/answer/cache.py`:
```python
"""Persistent exact-match (normalized) cache for /ask answers.

Keyed by the normalized question, stamped with an index-version token so a
re-ingest busts stale rulings, with a TTL and a size cap. Not semantic.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from pf_helper.answer.base import Answer

_WS = re.compile(r"\s+")
_EDGE_PUNCT = re.compile(r"^\W+|\W+$")  # \W is non-word; strips leading/trailing punctuation


def normalize_question(question: str) -> str:
    """Lowercase, collapse whitespace, strip surrounding punctuation (incl. '?')."""
    q = _WS.sub(" ", question.strip().lower())
    return _EDGE_PUNCT.sub("", q)


def index_version(index_db_path: Path) -> str:
    """Cheap version token for the rules index: mtime + size."""
    try:
        st = Path(index_db_path).stat()
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return "missing"


class AnswerCache:
    def __init__(
        self,
        path: str | Path,
        index_db_path: str | Path,
        ttl_days: int = 30,
        max_rows: int = 500,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index_db_path = Path(index_db_path)
        self.ttl_seconds = ttl_days * 86400
        self.max_rows = max_rows
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS answers ("
            "norm TEXT PRIMARY KEY, text TEXT NOT NULL, sources_json TEXT NOT NULL, "
            "index_version TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, question: str) -> Answer | None:
        norm = normalize_question(question)
        row = self._conn.execute("SELECT * FROM answers WHERE norm = ?", (norm,)).fetchone()
        if row is None:
            return None
        stale = row["index_version"] != index_version(self.index_db_path)
        expired = (time.time() - row["created_at"]) > self.ttl_seconds
        if stale or expired:
            self._conn.execute("DELETE FROM answers WHERE norm = ?", (norm,))
            self._conn.commit()
            return None
        sources = [tuple(s) for s in json.loads(row["sources_json"])]
        return Answer(text=row["text"], sources=sources, engine="cache")

    def put(self, question: str, answer: Answer) -> None:
        norm = normalize_question(question)
        self._conn.execute(
            "INSERT OR REPLACE INTO answers (norm, text, sources_json, index_version, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                norm,
                answer.text,
                json.dumps([list(s) for s in answer.sources]),
                index_version(self.index_db_path),
                time.time(),
            ),
        )
        # Evict oldest beyond the cap.
        self._conn.execute(
            "DELETE FROM answers WHERE norm NOT IN "
            "(SELECT norm FROM answers ORDER BY created_at DESC LIMIT ?)",
            (self.max_rows,),
        )
        self._conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/answer/cache.py tests/test_answer_cache.py
git commit -m "feat: add normalized, version-stamped /ask answer cache"
```

---

## Task 5: Engine B — ContextRagAnswerer

**Files:** Create `pf_helper/answer/engines.py`; Test `tests/test_answer_engines.py`.

- [ ] **Step 1: Write the failing test (mocked SDK + fake retriever)**

`tests/test_answer_engines.py`:
```python
import sys

import pytest

from pf_helper.answer.engines import ContextRagAnswerer
from pf_helper.models import EntryDetail, SearchHit


class FakeRetriever:
    def __init__(self, hits, details):
        self._hits = hits
        self._details = details
        self.searched = None

    def search(self, query, category, limit):
        self.searched = (query, category, limit)
        return self._hits

    def get(self, name, category):
        return self._details.get(name)


def _patch_query(monkeypatch, captured, reply="ANSWER"):
    """Patch claude_agent_sdk.query (used inside engines) with a fake async gen."""
    import claude_agent_sdk
    from claude_agent_sdk import AssistantMessage, TextBlock

    async def fake_query(prompt, options=None):
        captured["prompt"] = prompt
        captured["options"] = options
        yield AssistantMessage(content=[TextBlock(text=reply)])

    monkeypatch.setattr("pf_helper.answer.engines.query", fake_query)


@pytest.mark.asyncio
async def test_rag_uses_retriever_and_returns_sources(monkeypatch):
    hit = SearchHit(id="condition:frightened", name="Frightened", category="condition",
                    excerpt="...", source_url="https://2e.aonprd.com/Conditions.aspx?ID=1")
    detail = EntryDetail(id="condition:frightened", name="Frightened", category="condition",
                         text="You take a status penalty...", source_url=hit.source_url)
    r = FakeRetriever([hit], {"Frightened": detail})
    captured = {}
    _patch_query(monkeypatch, captured, reply="Frightened gives a status penalty.")

    answer = await ContextRagAnswerer(r).answer("what is frightened")

    assert r.searched[0] == "what is frightened"
    assert answer.text == "Frightened gives a status penalty."
    assert answer.sources == [("Frightened", "https://2e.aonprd.com/Conditions.aspx?ID=1")]
    assert answer.engine == "rag"
    assert "You take a status penalty" in captured["prompt"]  # full entry text fed as context


@pytest.mark.asyncio
async def test_rag_no_hits_returns_no_match(monkeypatch):
    r = FakeRetriever([], {})
    captured = {}
    _patch_query(monkeypatch, captured)
    answer = await ContextRagAnswerer(r).answer("nonsense")
    assert answer.sources == []
    assert "no matching" in answer.text.lower()
```

Add `pytest-asyncio` if not present: `uv add --dev pytest-asyncio` and enable it (see Step 3 note). The repo's `pyproject.toml` `[tool.pytest.ini_options]` must include `asyncio_mode = "auto"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_answer_engines.py -v`
Expected: FAIL — `pf_helper.answer.engines` does not exist (and possibly an async-mode error until Step 3 config).

- [ ] **Step 3: Enable asyncio test mode**

Run `uv add --dev pytest-asyncio` (quit Claude Desktop if the venv exe is locked). Then in `pyproject.toml` under `[tool.pytest.ini_options]` add:
```toml
asyncio_mode = "auto"
```

- [ ] **Step 4: Write `engines.py` (engine B)**

`pf_helper/answer/engines.py`:
```python
"""LLM answering engines over the Claude Agent SDK (subscription auth).

A = AgentMcpAnswerer: the agent searches via in-process tools (multi-step).
B = ContextRagAnswerer: one tool-less query over retrieved entries (cheaper).
Both ground answers in the local index and return AON sources.
"""

from __future__ import annotations

import json

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from pf_helper.answer.base import Answer, Answerer
from pf_helper.retrieval.base import Retriever

_ENTRY_TEXT_CAP = 1500  # keep each entry's text bounded in the RAG prompt

_SYS_RAG = (
    "You are a Pathfinder 2e rules assistant. Answer the question using ONLY the "
    "provided entries. Cite each entry's AON link. If the entries do not cover it, "
    "say no matching rules entry was found. Be concise; this is for Discord."
)

_SYS_AGENT = (
    "You are a Pathfinder 2e rules assistant. Use the `search` and `get_entry` tools "
    "to ground every answer in the rules index. Cite each referenced entry's AON "
    "link (its source_url). If nothing matches, say so. Be concise; this is for Discord."
)


async def _collect_text(prompt: str, options: ClaudeAgentOptions) -> str:
    parts: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
    return "".join(parts).strip()


class ContextRagAnswerer(Answerer):
    """Engine B: retrieve top-k locally, answer in one tool-less SDK query."""

    def __init__(self, retriever: Retriever, limit: int = 6):
        self._retriever = retriever
        self._limit = limit

    async def answer(self, question: str) -> Answer:
        hits = self._retriever.search(question, category=None, limit=self._limit)
        details = [self._retriever.get(h.name, h.category) for h in hits]
        details = [d for d in details if d is not None]
        if not details:
            return Answer(text="No matching rules entry found.", sources=[], engine="rag")
        context = "\n\n".join(
            f"## {d.name} ({d.category}) — {d.source_url}\n{d.text[:_ENTRY_TEXT_CAP]}"
            for d in details
        )
        prompt = f"Entries:\n{context}\n\nQuestion: {question}"
        text = await _collect_text(prompt, ClaudeAgentOptions(system_prompt=_SYS_RAG, max_turns=1))
        sources = [(d.name, d.source_url) for d in details]
        return Answer(text=text, sources=sources, engine="rag")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_answer_engines.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/answer/engines.py tests/test_answer_engines.py pyproject.toml uv.lock
git commit -m "feat: add ContextRagAnswerer (engine B) for /ask"
```

---

## Task 6: Engine A — AgentMcpAnswerer (in-process tools)

**Files:** Modify `pf_helper/answer/engines.py`; Test `tests/test_answer_engines.py`.

Engine A gives the agent in-process SDK tools that wrap the same `Retriever` (the spec-allowed lighter alternative to spawning the MCP subprocess — no PATH/lock issues, and the tool functions record the sources directly, guaranteeing AON links). The agent loop itself is exercised manually (Task 10); the unit tests verify the tool functions and that `answer` returns the model text.

- [ ] **Step 1: Write the failing tests (append to `tests/test_answer_engines.py`)**

```python
@pytest.mark.asyncio
async def test_agent_returns_text(monkeypatch):
    r = FakeRetriever([], {})
    captured = {}
    _patch_query(monkeypatch, captured, reply="Per the rules, yes.")
    from pf_helper.answer.engines import AgentMcpAnswerer

    answer = await AgentMcpAnswerer(r).answer("can I do X?")
    assert answer.text == "Per the rules, yes."
    assert answer.engine == "agent"
    # options carry the in-process server + allowed tools
    opts = captured["options"]
    assert "pf2e" in opts.mcp_servers
    assert set(opts.allowed_tools) == {"mcp__pf2e__search", "mcp__pf2e__get_entry"}


@pytest.mark.asyncio
async def test_agent_tool_functions_record_sources(monkeypatch):
    hit = SearchHit(id="spell:heal", name="Heal", category="spell", excerpt="heal...",
                    source_url="https://2e.aonprd.com/Spells.aspx?ID=1")
    detail = EntryDetail(id="spell:heal", name="Heal", category="spell", text="Heal a creature.",
                         source_url=hit.source_url)
    r = FakeRetriever([hit], {"Heal": detail})
    from pf_helper.answer.engines import AgentMcpAnswerer

    eng = AgentMcpAnswerer(r)
    search_fn, get_fn, sources = eng._build_tools()  # helper exposes the tool callables + sink
    out = await search_fn({"query": "heal", "category": ""})
    assert "Heal" in out["content"][0]["text"]
    assert ("Heal", hit.source_url) in sources.items()
    out2 = await get_fn({"name": "Heal", "category": "spell"})
    assert "Heal a creature." in out2["content"][0]["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_answer_engines.py -k agent -v`
Expected: FAIL — `AgentMcpAnswerer` does not exist.

- [ ] **Step 3: Add `AgentMcpAnswerer` to `engines.py`**

Append to `pf_helper/answer/engines.py`:
```python
class AgentMcpAnswerer(Answerer):
    """Engine A: the agent searches via in-process tools wrapping the Retriever."""

    def __init__(self, retriever: Retriever, max_turns: int = 6):
        self._retriever = retriever
        self._max_turns = max_turns

    def _build_tools(self):
        """Build the in-process tool callables and a dict that records used sources."""
        retriever = self._retriever
        sources: dict[str, str] = {}  # name -> source_url, populated as tools run

        @tool("search", "Search PF2e rules; returns name/category/excerpt/source_url.",
              {"query": str, "category": str})
        async def search_tool(args):
            hits = retriever.search(args["query"], category=args.get("category") or None, limit=8)
            for h in hits:
                sources[h.name] = h.source_url
            payload = [
                {"name": h.name, "category": h.category,
                 "source_url": h.source_url, "excerpt": h.excerpt}
                for h in hits
            ]
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}

        @tool("get_entry", "Get the full PF2e entry by exact name.",
              {"name": str, "category": str})
        async def get_tool(args):
            d = retriever.get(args["name"], category=args.get("category") or None)
            if d is None:
                return {"content": [{"type": "text", "text": "null"}]}
            sources[d.name] = d.source_url
            payload = {"name": d.name, "category": d.category,
                       "source_url": d.source_url, "text": d.text}
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}

        return search_tool, get_tool, sources

    async def answer(self, question: str) -> Answer:
        search_tool, get_tool, sources = self._build_tools()
        server = create_sdk_mcp_server(name="pf2e", tools=[search_tool, get_tool])
        options = ClaudeAgentOptions(
            system_prompt=_SYS_AGENT,
            max_turns=self._max_turns,
            mcp_servers={"pf2e": server},
            allowed_tools=["mcp__pf2e__search", "mcp__pf2e__get_entry"],
        )
        text = await _collect_text(question, options)
        return Answer(text=text, sources=list(sources.items()), engine="agent")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_answer_engines.py -v`
Expected: PASS (4 tests). Note: `_build_tools` returns the raw async callables; if `@tool` wraps them so they are not directly callable in this SDK version, adjust `_build_tools` to define and return plain `async def` callables and pass `tool(...)`-decorated versions to `create_sdk_mcp_server` separately — keep the plain callables for the unit test and the decorated ones for the server. Verify by running the test.

- [ ] **Step 5: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/answer/engines.py tests/test_answer_engines.py
git commit -m "feat: add AgentMcpAnswerer (engine A) with in-process retriever tools"
```

---

## Task 7: `ask()` orchestrator (cache → A → B)

**Files:** Create `pf_helper/answer/service.py`; update `pf_helper/answer/__init__.py`; Test `tests/test_answer_service.py`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_answer_service.py`)**

```python
import pytest
from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

from pf_helper.answer.base import Answer, AnswerError
from pf_helper.answer.service import ask


class FakeEngine:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    async def answer(self, question):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


class FakeCache:
    def __init__(self, hit=None):
        self.hit = hit
        self.put_calls = []

    def get(self, q):
        return self.hit

    def put(self, q, a):
        self.put_calls.append((q, a))


@pytest.mark.asyncio
async def test_cache_hit_skips_engines():
    a = FakeEngine(Answer("A-ans", [("n", "u")], "agent"))
    cache = FakeCache(hit=Answer("cached", [("n", "u")], "cache"))
    out = await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine())
    assert out.text == "cached"
    assert a.calls == 0


@pytest.mark.asyncio
async def test_a_success_is_cached():
    a = FakeEngine(Answer("A-ans", [("Flank", "https://x")], "agent"))
    cache = FakeCache()
    out = await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine())
    assert out.text == "A-ans"
    assert cache.put_calls and cache.put_calls[0][1].text == "A-ans"


@pytest.mark.asyncio
async def test_falls_back_to_b_on_error():
    a = FakeEngine(exc=ClaudeSDKError("rate limit"))
    b = FakeEngine(Answer("B-ans", [("n", "u")], "rag"))
    out = await ask("q", cache=FakeCache(), engine_a=a, engine_b=b)
    assert out.text == "B-ans"
    assert a.calls == 1 and b.calls == 1


@pytest.mark.asyncio
async def test_both_fail_raises_quota():
    a = FakeEngine(exc=ClaudeSDKError("x"))
    b = FakeEngine(exc=ClaudeSDKError("y"))
    with pytest.raises(AnswerError) as ei:
        await ask("q", cache=FakeCache(), engine_a=a, engine_b=b)
    assert ei.value.reason == "quota"


@pytest.mark.asyncio
async def test_auth_error_raises_auth():
    a = FakeEngine(exc=CLINotFoundError("not installed"))
    with pytest.raises(AnswerError) as ei:
        await ask("q", cache=FakeCache(), engine_a=a, engine_b=FakeEngine())
    assert ei.value.reason == "auth"


@pytest.mark.asyncio
async def test_unsourced_answer_not_cached():
    a = FakeEngine(Answer("No matching rules entry found.", [], "agent"))
    cache = FakeCache()
    await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine())
    assert cache.put_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_answer_service.py -k "cache_hit or falls_back or both_fail or auth_error or unsourced or a_success" -v`
Expected: FAIL — `pf_helper.answer.service` does not exist.

- [ ] **Step 3: Write `service.py`**

`pf_helper/answer/service.py`:
```python
"""The ask() orchestrator: cache -> engine A -> engine B, with graceful failure."""

from __future__ import annotations

import logging

from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

from pf_helper.answer.base import Answer, AnswerError, Answerer
from pf_helper.answer.cache import AnswerCache
from pf_helper.answer.config import AnswerConfig

_log = logging.getLogger(__name__)


async def ask(
    question: str,
    cfg: AnswerConfig | None = None,
    *,
    retriever=None,
    cache=None,
    engine_a: Answerer | None = None,
    engine_b: Answerer | None = None,
) -> Answer:
    """Answer a question. Tries cache, then engine A, then engine B.

    Raises AnswerError(reason='auth') if Claude is not signed in, or
    AnswerError(reason='quota') if every engine failed (e.g. rate-limited).
    Dependencies are injectable for testing; defaults are built from cfg.
    """
    cfg = cfg or AnswerConfig.from_env()

    if engine_a is None or engine_b is None:
        # Imported lazily so the core package doesn't require the SDK unless /ask runs.
        from pf_helper.answer.engines import AgentMcpAnswerer, ContextRagAnswerer
        from pf_helper.retrieval.factory import build_retriever

        retriever = retriever or build_retriever(cfg.core)
        engine_a = engine_a or AgentMcpAnswerer(retriever)
        engine_b = engine_b or ContextRagAnswerer(retriever)

    if cache is None and cfg.cache_enabled:
        cache = AnswerCache(
            cfg.core.data_dir / "ask_cache.db",
            cfg.core.db_path,
            cfg.cache_ttl_days,
            cfg.cache_max,
        )

    if cache is not None:
        hit = cache.get(question)
        if hit is not None:
            return hit

    order = {"a": [engine_a], "b": [engine_b]}.get(cfg.engine, [engine_a, engine_b])
    last_error: Exception | None = None
    for engine in order:
        try:
            answer = await engine.answer(question)
            if cache is not None and answer.sources:
                cache.put(question, answer)
            return answer
        except CLINotFoundError as exc:
            raise AnswerError(
                "auth",
                "`/ask` needs Claude sign-in: run `claude setup-token` and set "
                "`CLAUDE_CODE_OAUTH_TOKEN` (or `claude login`).",
            ) from exc
        except ClaudeSDKError as exc:
            last_error = exc
            _log.warning("%s failed: %s", type(engine).__name__, exc)
            continue
    raise AnswerError(
        "quota",
        "Claude is unavailable right now (possibly rate-limited) — try `/lookup` "
        "or `/search`, which work without it.",
    ) from last_error
```

- [ ] **Step 4: Update `__init__.py` to export `ask`**

`pf_helper/answer/__init__.py` — add `ask` to imports and `__all__`:
```python
from pf_helper.answer.base import Answer, AnswerError, Answerer
from pf_helper.answer.config import AnswerConfig
from pf_helper.answer.service import ask

__all__ = ["Answer", "AnswerError", "Answerer", "AnswerConfig", "ask"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_answer_service.py -v`
Expected: PASS (config tests from Task 3 + the 6 orchestrator tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/answer/service.py pf_helper/answer/__init__.py tests/test_answer_service.py
git commit -m "feat: add ask() orchestrator with cache and A->B fallback"
```

---

## Task 8: Bot config + pure embed builders

**Files:** Create `pf_helper/bot/__init__.py`, `pf_helper/bot/config.py`, `pf_helper/bot/embeds.py`; Test `tests/test_bot_embeds.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_bot_embeds.py`:
```python
import pytest

from pf_helper.answer.base import Answer
from pf_helper.bot.config import BotConfig
from pf_helper.bot.embeds import (
    answer_embed,
    lookup_embed,
    search_embeds,
    split_message,
    truncate,
)
from pf_helper.models import EntryDetail, SearchHit


def test_bot_config_requires_token(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
        BotConfig.from_env()


def test_bot_config_reads_env(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("PF_HELPER_DISCORD_GUILD_ID", "123")
    cfg = BotConfig.from_env()
    assert cfg.token == "tok"
    assert cfg.guild_id == 123


def test_truncate_and_split():
    assert truncate("abcdef", 4).endswith("...") and len(truncate("abcdef", 4)) <= 4 + 3
    chunks = split_message("x" * 4500, limit=2000)
    assert all(len(c) <= 2000 for c in chunks) and "".join(chunks) == "x" * 4500


def test_lookup_embed_links_title_and_shows_stats():
    d = EntryDetail(id="creature:goblin", name="Goblin", category="creature", level=1,
                    traits=["humanoid"], source_book="Monster Core",
                    stats={"AC": "16", "HP": "6"}, text="A goblin.",
                    source_url="https://2e.aonprd.com/Monsters.aspx?ID=1")
    e = lookup_embed(d)
    assert e.title == "Goblin"
    assert e.url == "https://2e.aonprd.com/Monsters.aspx?ID=1"
    field_text = " ".join(f"{f.name}:{f.value}" for f in e.fields)
    assert "creature" in field_text and "AC" in field_text


def test_search_embed_lists_hits_with_links():
    hits = [SearchHit(id="spell:heal", name="Heal", category="spell", excerpt="heal...",
                      source_url="https://2e.aonprd.com/Spells.aspx?ID=1")]
    e = search_embeds(hits)
    assert "Heal" in e.description and "Spells.aspx?ID=1" in e.description


def test_answer_embed_has_sources_field():
    ans = Answer(text="Yes you can.", sources=[("Flanking", "https://2e.aonprd.com/x")], engine="agent")
    e = answer_embed(ans)
    assert "Yes you can." in e.description
    src = " ".join(f"{f.name}:{f.value}" for f in e.fields)
    assert "Flanking" in src and "https://2e.aonprd.com/x" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/test_bot_embeds.py -v`
Expected: FAIL — `pf_helper.bot` modules do not exist.

- [ ] **Step 3: Write `bot/__init__.py` and `bot/config.py`**

`pf_helper/bot/__init__.py`:
```python
"""Discord front-end for PF_Helper (optional `bot` extra)."""
```

`pf_helper/bot/config.py`:
```python
"""Discord-bot configuration from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    token: str
    guild_id: int | None = None

    @classmethod
    def from_env(cls) -> "BotConfig":
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            raise ValueError("DISCORD_BOT_TOKEN is required to run the bot")
        gid = os.environ.get("PF_HELPER_DISCORD_GUILD_ID")
        return cls(token=token, guild_id=int(gid) if gid else None)
```

- [ ] **Step 4: Write `bot/embeds.py`**

`pf_helper/bot/embeds.py`:
```python
"""Pure render helpers: build discord.Embed objects (no Discord I/O, no network)."""

from __future__ import annotations

import discord

from pf_helper.answer.base import Answer
from pf_helper.models import EntryDetail, SearchHit

_DESC_LIMIT = 4096
_FIELD_LIMIT = 1024
_MSG_LIMIT = 2000


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def split_message(text: str, limit: int = _MSG_LIMIT) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


def lookup_embed(detail: EntryDetail) -> discord.Embed:
    embed = discord.Embed(
        title=detail.name,
        url=detail.source_url or None,
        description=truncate(detail.text, _DESC_LIMIT - 200),
    )
    embed.add_field(name="Category", value=detail.category, inline=True)
    if detail.level is not None:
        embed.add_field(name="Level", value=str(detail.level), inline=True)
    if detail.traits:
        embed.add_field(name="Traits", value=truncate(", ".join(detail.traits), _FIELD_LIMIT),
                        inline=False)
    for label, value in detail.stats.items():
        embed.add_field(name=label, value=truncate(value, _FIELD_LIMIT), inline=True)
    if detail.source_book:
        embed.add_field(name="Source", value=detail.source_book, inline=False)
    if detail.source_url:
        embed.add_field(name="AON", value=f"[Full entry]({detail.source_url})", inline=False)
    return embed


def search_embeds(hits: list[SearchHit]) -> discord.Embed:
    if not hits:
        return discord.Embed(title="No matches", description="Nothing found. Try different terms.")
    lines = [
        f"- [{h.name}]({h.source_url}) · {h.category} — {truncate(h.excerpt, 120)}"
        for h in hits
    ]
    return discord.Embed(title="Search results",
                         description=truncate("\n".join(lines), _DESC_LIMIT))


def answer_embed(answer: Answer) -> discord.Embed:
    embed = discord.Embed(description=truncate(answer.text, _DESC_LIMIT - 200))
    if answer.sources:
        links = "\n".join(f"[{name}]({url})" for name, url in answer.sources)
        embed.add_field(name="Sources (Archives of Nethys)",
                        value=truncate(links, _FIELD_LIMIT), inline=False)
    if answer.engine:
        embed.set_footer(text=f"answered via {answer.engine}")
    return embed
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --no-sync pytest tests/test_bot_embeds.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/bot/__init__.py pf_helper/bot/config.py pf_helper/bot/embeds.py tests/test_bot_embeds.py
git commit -m "feat: add bot config and pure embed builders"
```

---

## Task 9: Discord client, slash commands, entry point

**Files:** Create `pf_helper/bot/main.py`. (No unit tests — thin glue over tested builders/`ask`; verified manually in Task 10.)

- [ ] **Step 1: Write `bot/main.py`**

`pf_helper/bot/main.py`:
```python
"""discord.py client wiring /lookup, /search, /ask to the retriever and answerer."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from pf_helper.answer import AnswerError, ask
from pf_helper.answer.config import AnswerConfig
from pf_helper.bot.config import BotConfig
from pf_helper.bot.embeds import answer_embed, lookup_embed, search_embeds, split_message
from pf_helper.retrieval.factory import build_retriever

_log = logging.getLogger(__name__)
_NO_INDEX = "Rules index not found — run `pf-helper-ingest` first."


def build_bot(bot_cfg: BotConfig, answer_cfg: AnswerConfig) -> commands.Bot:
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", intents=intents)

    def retriever_or_none():
        if not answer_cfg.core.db_path.exists():
            return None
        return build_retriever(answer_cfg.core)

    @bot.event
    async def setup_hook():
        if bot_cfg.guild_id:
            guild = discord.Object(id=bot_cfg.guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()

    @bot.tree.command(name="lookup", description="Look up a PF2e rules entry by exact name.")
    @app_commands.describe(name="Exact entry name", category="Optional category filter")
    async def lookup(interaction: discord.Interaction, name: str, category: str | None = None):
        r = retriever_or_none()
        if r is None:
            await interaction.response.send_message(_NO_INDEX, ephemeral=True)
            return
        detail = r.get(name, category=category or None)
        if detail is None:
            await interaction.response.send_message(
                f"No exact match for '{name}'. Try `/search`.", ephemeral=True)
            return
        await interaction.response.send_message(embed=lookup_embed(detail))

    @bot.tree.command(name="search", description="Search PF2e rules.")
    @app_commands.describe(query="Search text", category="Optional category filter")
    async def search(interaction: discord.Interaction, query: str, category: str | None = None):
        r = retriever_or_none()
        if r is None:
            await interaction.response.send_message(_NO_INDEX, ephemeral=True)
            return
        hits = r.search(query, category=category or None, limit=6)
        await interaction.response.send_message(embed=search_embeds(hits))

    @bot.tree.command(name="ask", description="Ask a PF2e rules question (uses Claude).")
    @app_commands.describe(question="Your rules question")
    async def ask_cmd(interaction: discord.Interaction, question: str):
        await interaction.response.defer(thinking=True)
        try:
            answer = await ask(question, answer_cfg)
        except AnswerError as e:
            await interaction.followup.send(str(e))
            return
        except Exception:  # noqa: BLE001 - never let one command crash the bot
            _log.exception("ask failed")
            await interaction.followup.send("Something went wrong answering that.")
            return
        embed = answer_embed(answer)
        chunks = split_message(answer.text)
        if len(chunks) <= 1:
            await interaction.followup.send(embed=embed)
        else:  # very long answers: first chunk as embed, remainder as plain follow-ups
            await interaction.followup.send(embed=answer_embed(answer))
            for extra in chunks[1:]:
                await interaction.followup.send(extra)

    return bot


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot_cfg = BotConfig.from_env()
    answer_cfg = AnswerConfig.from_env()
    bot = build_bot(bot_cfg, answer_cfg)
    bot.run(bot_cfg.token)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports and the entry point resolves**

Run:
```bash
uv run --no-sync python -c "from pf_helper.bot.main import build_bot, main; print('ok')"
uv run --no-sync pytest -q
```
Expected: prints `ok`; full suite passes. (The bot is not started here — `bot.run` needs a real token + gateway.)

- [ ] **Step 3: Lint and commit**

```bash
uv run --no-sync ruff check . && uv run --no-sync ruff format .
git add pf_helper/bot/main.py
git commit -m "feat: add discord.py client with /lookup, /search, /ask"
```

---

## Task 10: README docs + manual end-to-end verification

**Files:** Modify `README.md`.

- [ ] **Step 1: Add a "Discord bot" section to `README.md`**

Append:
```markdown
## Discord bot (optional)

A Discord front-end with `/lookup`, `/search` (instant, local), and `/ask`
(natural-language, powered by the Claude Agent SDK on your Claude subscription —
no API key).

### Install
```bash
uv sync --extra bot
```

### Prerequisites
- Build the index: `uv run pf-helper-ingest`.
- For `/ask`, authenticate Claude (subscription): `claude login` (dev) or, for a
  host, `claude setup-token` and export `CLAUDE_CODE_OAUTH_TOKEN`.
- A Discord bot token (Discord Developer Portal → your app → Bot).

### Configure (env)
| Var | Required | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | yes | bot auth |
| `PF_HELPER_DISCORD_GUILD_ID` | no | register slash commands to one guild instantly |
| `PF_HELPER_ASK_ENGINE` | no | `auto` (default) / `a` / `b` |
| `PF_HELPER_ASK_CACHE` | no | `1`/`0` (default on) |
| `CLAUDE_CODE_OAUTH_TOKEN` | host only | subscription auth without interactive login |

### Run
```bash
uv run pf-helper-bot
```
Invite the bot to your server (OAuth2 → scopes `bot` + `applications.commands`).
Try `/lookup Frightened`, `/search status penalty`, `/ask How does flanking work?`.
```

- [ ] **Step 2: Manual verification**

Run `uv run pf-helper-bot` with a real `DISCORD_BOT_TOKEN` (and Claude signed in)
in a test guild. Confirm:
- `/lookup Frightened` returns an embed with the AON-linked title.
- `/search status penalty` lists hits with AON links.
- `/ask How does flanking work?` returns an answer with a Sources field of AON
  links; a repeat of the same question returns instantly with the "cached"
  footer.
- With Claude signed out, `/ask` replies with the sign-in hint (not a crash).
(No code change — this is the operational gate. `data/` and tokens are not
committed.)

- [ ] **Step 3: Commit**

```bash
uv run --no-sync ruff check .
git add README.md
git commit -m "docs: add Discord bot setup and usage"
```

---

## Task 11: Final PR

- [ ] **Step 1: Full suite + lint**

Run:
```bash
uv run --no-sync pytest -q
uv run --no-sync ruff check .
```
Expected: all pass; ruff clean.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin feat/discord-bot
gh pr create --base main --head feat/discord-bot --title "feat: Discord bot front-end (/lookup, /search, /ask) + shared answering layer" --body "<summary of tasks; paste uv run pytest -q output; note manual /ask verification from Task 10>"
```

- [ ] **Step 3: Stop for user review**

Do not merge. Report test results and the manual `/ask` verification in the PR
body. The user reviews and merges (never self-merge unless explicitly told).

---

## Notes / deferred (designed-for, not in this plan)

- `/lookup` name autocomplete; per-user rate limiting; a metered `ANTHROPIC_API_KEY`
  engine for public/large servers; semantic/fuzzy answer caching.
- A future `pf-helper-ask` CLI or HTTP endpoint reuses `pf_helper.answer.ask`
  unchanged (that is why the answering layer is a shared package).
- Approach B from the AON spec (exact Foundry deep links) is independent.
```
