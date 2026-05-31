# Fuzzy Answer Cache + Lookup Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/ask` answer cache reuse answers for paraphrased questions via lexical similarity, and make `/lookup` suggest close names + inline search hits on a miss.

**Architecture:** Lexical (keyword-overlap) matching layered on top of the existing exact-match cache (`pf_helper/answer/cache.py`); per-`/ask` `fuzzy`/`fresh` overrides threaded through `ask()`; best-effort JSONL query logging; stdlib-`difflib` "did you mean" in the bot's `/lookup` handler. No new third-party dependencies.

**Tech Stack:** Python 3.14, sqlite3 (stdlib), difflib (stdlib), discord.py, claude-agent-sdk, pytest (`uv run --no-sync pytest -q`), ruff (`uv run --no-sync ruff check .`).

**Spec:** `docs/superpowers/specs/2026-05-31-fuzzy-cache-and-lookup-fallback-design.md`

**Conventions to follow:**
- Run tests/lint with `uv run --no-sync` (Claude Desktop may hold the venv lock).
- `Answer(text, sources, engine)` — footer reads "answered via {engine}".
- `AnswerConfig` is a `@dataclass(frozen=True)`; env vars are `PF_HELPER_ASK_*`.
- `embeds.py` is pure render (no Discord I/O, no network).
- Two separate `except` clauses, not `except (A, B):` (ruff py3.14 rewrites the tuple into a confusing comma form).

---

### Task 1: Answer telemetry fields + AnswerConfig knobs

**Files:**
- Modify: `pf_helper/answer/base.py`
- Modify: `pf_helper/answer/config.py`
- Test: `tests/test_answer_service.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_answer_service.py`, extend the existing `test_answer_defaults` and `test_answer_config_from_env`:

```python
def test_answer_defaults():
    a = Answer(text="hi")
    assert a.sources == []
    assert a.engine == ""
    assert a.match_score is None
    assert a.matched_question is None


def test_answer_config_from_env(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_ENGINE", "B")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE", "0")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE_TTL_DAYS", "7")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE_SIMILARITY", "0.7")
    monkeypatch.setenv("PF_HELPER_ASK_QUERY_LOG", "0")
    cfg = AnswerConfig.from_env()
    assert cfg.engine == "b"  # lower-cased
    assert cfg.cache_enabled is False
    assert cfg.cache_ttl_days == 7
    assert cfg.cache_similarity == 0.7
    assert cfg.query_log_enabled is False
    assert cfg.core.db_path.name == "pf2e.db"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_answer_service.py::test_answer_defaults tests/test_answer_service.py::test_answer_config_from_env -v`
Expected: FAIL (`Answer` has no `match_score`; `AnswerConfig` has no `cache_similarity`).

- [ ] **Step 3: Add the Answer fields**

In `pf_helper/answer/base.py`, add two optional fields to the `Answer` dataclass (after `engine`):

```python
@dataclass
class Answer:
    """An LLM answer plus the AON sources it was grounded in."""

    text: str
    sources: list[tuple[str, str]] = field(default_factory=list)  # (name, source_url)
    engine: str = ""  # "agent" | "rag" | "cache"
    match_score: float | None = None  # fuzzy-cache similarity, when applicable
    matched_question: str | None = None  # the cached (normalized) question matched
```

- [ ] **Step 4: Add the AnswerConfig knobs**

In `pf_helper/answer/config.py`, add two fields (after `cache_max`, before `core`) and read them in `from_env`:

```python
    cache_max: int = 500
    cache_similarity: float = 0.5  # Jaccard threshold; 0 disables the fuzzy pass
    query_log_enabled: bool = True
    core: Config = field(default_factory=Config.from_env)

    @classmethod
    def from_env(cls) -> AnswerConfig:
        return cls(
            engine=os.environ.get("PF_HELPER_ASK_ENGINE", "auto").lower(),
            cache_enabled=os.environ.get("PF_HELPER_ASK_CACHE", "1") != "0",
            cache_ttl_days=int(os.environ.get("PF_HELPER_ASK_CACHE_TTL_DAYS", "30")),
            cache_max=int(os.environ.get("PF_HELPER_ASK_CACHE_MAX", "500")),
            cache_similarity=float(os.environ.get("PF_HELPER_ASK_CACHE_SIMILARITY", "0.5")),
            query_log_enabled=os.environ.get("PF_HELPER_ASK_QUERY_LOG", "1") != "0",
            core=Config.from_env(),
        )
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_answer_service.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pf_helper/answer/base.py pf_helper/answer/config.py tests/test_answer_service.py
git commit -m "feat: Answer telemetry fields + cache_similarity/query_log config"
```

---

### Task 2: Cache tokenization helpers (lexical similarity primitives)

**Files:**
- Modify: `pf_helper/answer/cache.py`
- Test: `tests/test_answer_cache.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_answer_cache.py`:

```python
from pf_helper.answer.cache import _content_tokens, _jaccard, _stem


def test_stem_is_crude_but_consistent():
    assert _stem("flanking") == "flank"
    assert _stem("flank") == "flank"
    assert _stem("creatures") == _stem("creatures")  # deterministic
    assert _stem("is") == "is"  # short tokens untouched


def test_content_tokens_drop_stopwords_and_framing():
    # function + framing words removed, keyword stemmed
    assert _content_tokens("How does flanking work?") == {"flank"}
    assert _content_tokens("When am I flanking again?") == {"flank"}
    assert _content_tokens("What is flanking?") == {"flank"}
    assert _content_tokens("What are the rules for flanking?") == {"flank"}


def test_content_tokens_keep_salient_nouns():
    assert _content_tokens("can tiny creatures flank") == {"tiny", "creature", "flank"}


def test_jaccard():
    assert _jaccard({"flank"}, {"flank"}) == 1.0
    assert _jaccard({"flank", "tiny", "creature"}, {"flank"}) == 1 / 3
    assert _jaccard(set(), set()) == 0.0
```

Note: `_content_tokens("can tiny creatures flank")` expects `{"tiny", "creature", "flank"}`. The crude `_stem` must map `creatures -> creature`. Implement `_stem` so the `s`-rule is checked before the `es`-rule would mis-fire, OR special-case is unnecessary if the `es` rule yields `creatur` — in that case change this assertion to the stem the implementation actually produces AND keep it consistent (the negative-case math `1/3` is unaffected by which stem). **Pin the exact stem the implementation produces; do not leave it ambiguous.**

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -k "stem or content_tokens or jaccard" -v`
Expected: FAIL (helpers not defined).

- [ ] **Step 3: Implement the helpers**

In `pf_helper/answer/cache.py`, add near the top (after the existing `_WS`/`_EDGE_PUNCT` regexes):

```python
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

# Function words + rules-question framing words. The framing words are the main
# tuning lever: they collapse keyword-dominated paraphrases to the same token.
_STOPWORDS: frozenset[str] = frozenset(
    # function words
    "a am an and are as at be by can could do does did for from how i if in into "
    "is it me my of on or should that the their them then there this to use what "
    "when where which who why will with would you your "
    # rules-question framing words
    "again happen happens mean means rule rules work works explain tell about".split()
)


def _stem(w: str) -> str:
    """Deliberately crude suffix stripping; only needs to be consistent."""
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _content_tokens(question: str) -> frozenset[str]:
    """Salient stemmed content tokens (stopwords + framing words removed)."""
    raw = _TOKEN_SPLIT.split(question.lower())
    return frozenset(_stem(t) for t in raw if t and t not in _STOPWORDS)


def _jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0
```

Note: with this `_stem`, `creatures` -> (no `ing`, no `ed`, ends `s` not `ss`, len>3) -> `creature`. Good — the test assertion `{"tiny", "creature", "flank"}` holds.

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -k "stem or content_tokens or jaccard" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/answer/cache.py tests/test_answer_cache.py
git commit -m "feat: lexical similarity primitives (tokens/stem/jaccard) for cache"
```

---

### Task 3: Cache schema migration, `tokens` on put, similarity arg

**Files:**
- Modify: `pf_helper/answer/cache.py`
- Test: `tests/test_answer_cache.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_answer_cache.py`:

```python
import sqlite3


def test_put_populates_tokens(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("How does flanking work?", Answer("t", [("n", "u")], "agent"))
    row = cache._conn.execute("SELECT tokens FROM answers").fetchone()
    assert row["tokens"] == "flank"


def test_migration_recreates_tokenless_table(tmp_path):
    db = tmp_path / "ask_cache.db"
    index = tmp_path / "pf2e.db"
    index.write_text("v1")
    # simulate an old cache DB without the tokens column
    old = sqlite3.connect(db)
    old.execute(
        "CREATE TABLE answers (norm TEXT PRIMARY KEY, text TEXT NOT NULL, "
        "sources_json TEXT NOT NULL, index_version TEXT NOT NULL, created_at REAL NOT NULL)"
    )
    old.execute(
        "INSERT INTO answers VALUES ('old', 't', '[]', 'v', 0)"
    )
    old.commit()
    old.close()
    cache = AnswerCache(db, index)  # should not raise
    cols = {r[1] for r in cache._conn.execute("PRAGMA table_info(answers)").fetchall()}
    assert "tokens" in cols
    assert cache._conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0  # recreated
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -k "tokens or migration" -v`
Expected: FAIL (no `tokens` column; old-schema DB errors or keeps the row).

- [ ] **Step 3: Update `__init__` (migration + schema + similarity arg)**

In `AnswerCache.__init__`, add the `similarity` parameter and the migration:

```python
    def __init__(
        self,
        path: str | Path,
        index_db_path: str | Path,
        ttl_days: int = 30,
        max_rows: int = 500,
        similarity: float = 0.5,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index_db_path = Path(index_db_path)
        self.ttl_seconds = ttl_days * 86400
        self.max_rows = max_rows
        self.similarity = similarity
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(answers)").fetchall()}
        if cols and "tokens" not in cols:
            self._conn.execute("DROP TABLE answers")  # disposable cache; recreate cleanly
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS answers ("
            "norm TEXT PRIMARY KEY, text TEXT NOT NULL, sources_json TEXT NOT NULL, "
            "index_version TEXT NOT NULL, created_at REAL NOT NULL, "
            "tokens TEXT NOT NULL DEFAULT '')"
        )
        self._conn.commit()
```

- [ ] **Step 4: Write `tokens` in `put`**

Update `put` to compute and store tokens:

```python
    def put(self, question: str, answer: Answer) -> None:
        norm = normalize_question(question)
        tokens = " ".join(sorted(_content_tokens(question)))
        self._conn.execute(
            "INSERT OR REPLACE INTO answers "
            "(norm, text, sources_json, index_version, created_at, tokens) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                norm,
                answer.text,
                json.dumps([list(s) for s in answer.sources]),
                index_version(self.index_db_path),
                time.time(),
                tokens,
            ),
        )
        self._conn.execute(
            "DELETE FROM answers WHERE norm NOT IN "
            "(SELECT norm FROM answers ORDER BY created_at DESC LIMIT ?)",
            (self.max_rows,),
        )
        self._conn.commit()
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -q`
Expected: PASS (existing exact-match tests still green; new tokens/migration tests pass).

- [ ] **Step 6: Commit**

```bash
git add pf_helper/answer/cache.py tests/test_answer_cache.py
git commit -m "feat: cache tokens column + migration + similarity arg"
```

---

### Task 4: Cache fuzzy `get(question, *, fuzzy=True)`

**Files:**
- Modify: `pf_helper/answer/cache.py`
- Test: `tests/test_answer_cache.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_answer_cache.py`:

```python
def test_fuzzy_hits_paraphrases(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("How does flanking work?", Answer("Flank text", [("Flanking", "u")], "agent"))
    for q in ["When am I flanking again?", "What is flanking?", "What are the rules for flanking?"]:
        hit = cache.get(q)
        assert hit is not None, q
        assert hit.text == "Flank text"
        assert hit.engine == "cache"
        assert hit.match_score is not None and hit.match_score >= 0.5
        assert hit.matched_question == "how does flanking work"


def test_fuzzy_misses_distinct_question(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("What is flanking?", Answer("Flank text", [("Flanking", "u")], "agent"))
    assert cache.get("can tiny creatures flank?") is None  # jaccard 1/3 < 0.5


def test_fuzzy_disabled_per_call(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("How does flanking work?", Answer("Flank text", [("Flanking", "u")], "agent"))
    assert cache.get("what is flanking?", fuzzy=False) is None  # exact-only
    assert cache.get("how does flanking work", fuzzy=False) is not None  # exact still hits


def test_similarity_zero_disables_fuzzy(tmp_path):
    index = tmp_path / "pf2e.db"
    index.write_text("v1")
    cache = AnswerCache(tmp_path / "ask_cache.db", index, similarity=0.0)
    cache.put("How does flanking work?", Answer("t", [("n", "u")], "agent"))
    assert cache.get("what is flanking?") is None


def test_fuzzy_skips_stale_rows(tmp_path):
    cache, index = _cache(tmp_path)
    cache.put("How does flanking work?", Answer("t", [("n", "u")], "agent"))
    index.write_text("v2-bigger-changed")  # bust index_version
    assert cache.get("what is flanking?") is None


def test_fuzzy_skips_empty_token_question(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("How does flanking work?", Answer("t", [("n", "u")], "agent"))
    assert cache.get("what is it?") is None  # all stopwords -> no tokens -> no match
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -k fuzzy -v`
Expected: FAIL (`get` has no `fuzzy` kwarg / no fuzzy pass).

- [ ] **Step 3: Implement fuzzy `get`**

Replace `AnswerCache.get` with:

```python
    def get(self, question: str, *, fuzzy: bool = True) -> Answer | None:
        norm = normalize_question(question)
        row = self._conn.execute("SELECT * FROM answers WHERE norm = ?", (norm,)).fetchone()
        if row is not None:
            if self._is_live(row):
                return self._to_answer(row)
            self._conn.execute("DELETE FROM answers WHERE norm = ?", (norm,))
            self._conn.commit()
        if not fuzzy or self.similarity <= 0:
            return None
        qtokens = _content_tokens(question)
        if not qtokens:
            return None
        current = index_version(self.index_db_path)
        cutoff = time.time() - self.ttl_seconds
        best_row = None
        best_score = 0.0
        for r in self._conn.execute(
            "SELECT * FROM answers WHERE index_version = ? AND created_at > ?",
            (current, cutoff),
        ):
            score = _jaccard(qtokens, frozenset(r["tokens"].split()))
            if score >= self.similarity and score > best_score:
                best_row, best_score = r, score
        if best_row is None:
            return None
        ans = self._to_answer(best_row)
        ans.match_score = best_score
        ans.matched_question = best_row["norm"]
        return ans

    def _is_live(self, row: sqlite3.Row) -> bool:
        stale = row["index_version"] != index_version(self.index_db_path)
        expired = (time.time() - row["created_at"]) > self.ttl_seconds
        return not (stale or expired)

    def _to_answer(self, row: sqlite3.Row) -> Answer:
        sources = [tuple(s) for s in json.loads(row["sources_json"])]
        return Answer(text=row["text"], sources=sources, engine="cache")
```

(The exact-hit path returns `engine="cache"` with `match_score=None`, unchanged from today; the fuzzy path adds the score + matched question.)

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_answer_cache.py -q`
Expected: PASS (all old + new cache tests).

- [ ] **Step 5: Commit**

```bash
git add pf_helper/answer/cache.py tests/test_answer_cache.py
git commit -m "feat: lexical fuzzy fallback in AnswerCache.get"
```

---

### Task 5: Query log module

**Files:**
- Create: `pf_helper/answer/querylog.py`
- Test: `tests/test_querylog.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_querylog.py`:

```python
import json

from pf_helper.answer.querylog import log_query


def test_log_query_appends_jsonl(tmp_path):
    path = tmp_path / "ask_queries.jsonl"
    log_query(path, {"served_by": "agent", "question": "q1"})
    log_query(path, {"served_by": "cache", "question": "q2"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["served_by"] == "agent"
    assert json.loads(lines[1])["question"] == "q2"


def test_log_query_swallows_errors(tmp_path):
    # a directory where a file is expected -> open() fails; must not raise
    bad = tmp_path / "subdir"
    bad.mkdir()
    log_query(bad, {"served_by": "agent"})  # should not raise
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_querylog.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `querylog.py`**

Create `pf_helper/answer/querylog.py`:

```python
"""Best-effort append-only JSONL log of /ask queries, for offline cache tuning.

Never raises into the request path: a logging failure is swallowed (warned).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def log_query(path: str | Path, record: dict) -> None:
    """Append one JSON record as a line. Failures are logged, never raised."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        _log.warning("query log write failed: %s", exc)
    except (TypeError, ValueError) as exc:  # non-serializable record
        _log.warning("query log serialize failed: %s", exc)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_querylog.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/answer/querylog.py tests/test_querylog.py
git commit -m "feat: best-effort JSONL query log"
```

---

### Task 6: `ask()` — fuzzy/fresh overrides + query logging

**Files:**
- Modify: `pf_helper/answer/service.py`
- Test: `tests/test_answer_service.py`

- [ ] **Step 1: Update the test fakes + add an autouse log-disable, write failing tests**

In `tests/test_answer_service.py`:

1. Add an autouse fixture (so existing tests don't write logs to the real data dir) at the top of the file:

```python
@pytest.fixture(autouse=True)
def _no_query_log(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_QUERY_LOG", "0")
```

2. Update `FakeCache` so `get` accepts the `fuzzy` kwarg and records it:

```python
class FakeCache:
    def __init__(self, hit=None):
        self.hit = hit
        self.put_calls = []
        self.got_fuzzy = None

    def get(self, q, *, fuzzy=True):
        self.got_fuzzy = fuzzy
        return self.hit

    def put(self, q, a):
        self.put_calls.append((q, a))
```

3. Add new tests:

```python
@pytest.mark.asyncio
async def test_fresh_bypasses_cache_read():
    a = FakeEngine(Answer("fresh-ans", [("n", "u")], "agent"))
    cache = FakeCache(hit=Answer("cached", [("n", "u")], "cache"))
    out = await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine(), fresh=True)
    assert out.text == "fresh-ans"  # cached hit ignored
    assert a.calls == 1
    assert cache.put_calls and cache.put_calls[0][1].text == "fresh-ans"  # still written


@pytest.mark.asyncio
async def test_fuzzy_flag_threaded_to_cache():
    cache = FakeCache(hit=None)
    await ask("q", cache=cache, engine_a=FakeEngine(Answer("x", [("n", "u")], "agent")),
              engine_b=FakeEngine(), fuzzy=False)
    assert cache.got_fuzzy is False


@pytest.mark.asyncio
async def test_query_logger_records_served_by():
    recs = []
    a = FakeEngine(Answer("A-ans", [("n", "u")], "agent"))
    await ask("q", cache=FakeCache(), engine_a=a, engine_b=FakeEngine(), query_logger=recs.append)
    assert recs and recs[0]["served_by"] == "agent"
    assert recs[0]["fuzzy"] is True and recs[0]["fresh"] is False


@pytest.mark.asyncio
async def test_query_logger_records_cache_and_auth():
    recs = []
    cache = FakeCache(hit=Answer("cached", [("n", "u")], "cache"))
    await ask("q", cache=cache, engine_a=FakeEngine(), engine_b=FakeEngine(),
              query_logger=recs.append)
    assert recs[-1]["served_by"] == "cache"
    recs.clear()
    a = FakeEngine(exc=CLINotFoundError("nope"))
    with pytest.raises(AnswerError):
        await ask("q", cache=FakeCache(), engine_a=a, engine_b=FakeEngine(),
                  query_logger=recs.append)
    assert recs[-1]["served_by"] == "error:auth"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_answer_service.py -k "fresh or fuzzy_flag or query_logger" -v`
Expected: FAIL (`ask` has no `fuzzy`/`fresh`/`query_logger` params).

- [ ] **Step 3: Implement the new `ask()`**

Rewrite `pf_helper/answer/service.py`:

```python
"""The ask() orchestrator: cache -> engine A -> engine B, with graceful failure."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from pf_helper.answer.base import Answer, Answerer, AnswerError
from pf_helper.answer.cache import AnswerCache, index_version
from pf_helper.answer.config import AnswerConfig
from pf_helper.answer.querylog import log_query

_log = logging.getLogger(__name__)


async def ask(
    question: str,
    cfg: AnswerConfig | None = None,
    *,
    retriever=None,
    cache=None,
    engine_a: Answerer | None = None,
    engine_b: Answerer | None = None,
    fuzzy: bool = True,
    fresh: bool = False,
    query_logger: Callable[[dict], None] | None = None,
) -> Answer:
    """Answer a question. Tries cache, then engine A, then engine B.

    fuzzy=False suspends the lexical cache layer (exact cache + agent only);
    fresh=True bypasses the cache read entirely (forces a new agent answer).
    Raises AnswerError(reason='auth') if Claude is not signed in, or
    AnswerError(reason='quota') if every engine failed (e.g. rate-limited).
    Dependencies are injectable for testing; defaults are built from cfg.
    """
    cfg = cfg or AnswerConfig.from_env()

    from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

    if engine_a is None or engine_b is None:
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
            cfg.cache_similarity,
        )

    if query_logger is None and cfg.query_log_enabled:
        log_path = cfg.core.data_dir / "ask_queries.jsonl"
        query_logger = lambda rec: log_query(log_path, rec)  # noqa: E731

    def _log_query(served_by: str, ans: Answer | None = None) -> None:
        if query_logger is None:
            return
        query_logger(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "question": question,
                "served_by": served_by,
                "match_score": ans.match_score if ans else None,
                "matched_question": ans.matched_question if ans else None,
                "threshold": cfg.cache_similarity,
                "fuzzy": fuzzy,
                "fresh": fresh,
                "index_version": index_version(cfg.core.db_path),
            }
        )

    if cache is not None and not fresh:
        hit = cache.get(question, fuzzy=fuzzy)
        if hit is not None:
            _log_query(hit.engine, hit)
            return hit

    order = {"a": [engine_a], "b": [engine_b]}.get(cfg.engine, [engine_a, engine_b])
    last_error: Exception | None = None
    for engine in order:
        try:
            answer = await engine.answer(question)
            if cache is not None and answer.sources:
                cache.put(question, answer)
            _log_query(answer.engine, answer)
            return answer
        except CLINotFoundError as exc:
            _log_query("error:auth")
            raise AnswerError(
                "auth",
                "`/ask` needs Claude sign-in: run `claude setup-token` and set "
                "`CLAUDE_CODE_OAUTH_TOKEN` (or `claude login`).",
            ) from exc
        except ClaudeSDKError as exc:
            last_error = exc
            _log.warning("%s failed: %s", type(engine).__name__, exc)
            continue
    _log_query("error:quota")
    raise AnswerError(
        "quota",
        "Claude is unavailable right now (possibly rate-limited) — try `/lookup` "
        "or `/search`, which work without it.",
    ) from last_error
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_answer_service.py -q`
Expected: PASS (all old + new service tests).

- [ ] **Step 5: Commit**

```bash
git add pf_helper/answer/service.py tests/test_answer_service.py
git commit -m "feat: ask() fuzzy/fresh overrides + query logging"
```

---

### Task 7: Embeds — fuzzy footer + lookup-miss embed

**Files:**
- Modify: `pf_helper/bot/embeds.py`
- Test: `tests/test_bot_embeds.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_bot_embeds.py` (extend the import line to include `lookup_miss_embed`):

```python
from pf_helper.bot.embeds import (
    answer_embed,
    lookup_embed,
    lookup_miss_embed,
    search_embeds,
    split_message,
    truncate,
)


def test_answer_embed_fuzzy_footer():
    ans = Answer(text="x", sources=[("n", "u")], engine="cache", match_score=0.83,
                 matched_question="flank")
    e = answer_embed(ans)
    assert "cache" in e.footer.text and "0.83" in e.footer.text


def test_answer_embed_plain_footer_unchanged():
    e = answer_embed(Answer(text="x", sources=[("n", "u")], engine="agent"))
    assert e.footer.text == "answered via agent"


def test_lookup_miss_embed_suggestions_and_hits():
    hits = [
        SearchHit(id="action:grab", name="Grab", category="action", excerpt="grab...",
                  source_url="https://2e.aonprd.com/Grab"),
        SearchHit(id="action:grapple", name="Grapple", category="action", excerpt="grapple...",
                  source_url="https://2e.aonprd.com/Grapple"),
    ]
    e = lookup_miss_embed("Grabbing", ["Grab"], hits)
    assert "Grabbing" in e.title
    assert "Grab" in e.description
    assert "Grapple" in e.description  # listed even if not a "did you mean"


def test_lookup_miss_embed_no_hits():
    e = lookup_miss_embed("Zxqwv", [], [])
    assert "/search" in e.description
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_bot_embeds.py -k "fuzzy or lookup_miss or plain_footer" -v`
Expected: FAIL (`lookup_miss_embed` missing; footer not fuzzy-aware).

- [ ] **Step 3: Update `answer_embed` footer + add `lookup_miss_embed`**

In `pf_helper/bot/embeds.py`, change the footer block of `answer_embed`:

```python
    if answer.engine == "cache" and answer.match_score is not None:
        embed.set_footer(text=f"answered via cache · similar question ({answer.match_score:.2f})")
    elif answer.engine:
        embed.set_footer(text=f"answered via {answer.engine}")
    return embed
```

Add a new builder (after `search_embeds`):

```python
def lookup_miss_embed(
    name: str, suggestions: list[str], hits: list[SearchHit]
) -> discord.Embed:
    """Embed for a /lookup exact-name miss: 'did you mean' + closest search hits."""
    lines: list[str] = []
    if suggestions:
        lines.append("Did you mean: " + ", ".join(f"**{s}**" for s in suggestions) + "?")
    if hits:
        if lines:
            lines.append("")
        lines.append("Closest matches:")
        lines += [
            f"- [{h.name}]({h.source_url}) · {h.category} — {truncate(h.excerpt, 120)}"
            for h in hits
        ]
    else:
        lines.append("Nothing found. Try `/search`.")
    return discord.Embed(
        title=f"No exact match for '{name}'",
        description=truncate("\n".join(lines), _DESC_LIMIT),
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_bot_embeds.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/bot/embeds.py tests/test_bot_embeds.py
git commit -m "feat: fuzzy-cache footer + lookup-miss embed"
```

---

### Task 8: Bot wiring — `_close_names`, `/ask` options, `/lookup` fallback

**Files:**
- Modify: `pf_helper/bot/main.py`
- Test: `tests/test_bot_embeds.py` (pure `_close_names` helper)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_bot_embeds.py`:

```python
from pf_helper.bot.main import _close_names


def test_close_names_picks_very_close_only():
    names = ["Grab", "Grapple", "Trip"]
    assert _close_names("Grabbing", names) == ["Grab"]  # Grapple/Trip below cutoff


def test_close_names_empty_when_nothing_close():
    assert _close_names("Zxqwv", ["Grab", "Trip"]) == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run --no-sync pytest tests/test_bot_embeds.py -k close_names -v`
Expected: FAIL (`_close_names` not defined).

If `Grabbing -> Grab` lands just under the chosen cutoff in practice, set `_SUGGEST_CUTOFF` so the pinned test holds (the spec allows ~0.6); `difflib.SequenceMatcher("grabbing","grab").ratio() == 0.667`, so `0.6` passes and `Grapple` (~0.4) / `Trip` stay out. Keep `0.6`.

- [ ] **Step 3: Implement bot changes**

In `pf_helper/bot/main.py`:

1. Add imports + constant near the top:

```python
import difflib
...
from pf_helper.bot.embeds import answer_embed, lookup_embed, lookup_miss_embed, search_embeds

_SUGGEST_CUTOFF = 0.6  # difflib ratio for a "did you mean" suggestion (very close only)
```

2. Add the pure helper (module level, before `build_bot`):

```python
def _close_names(
    query: str, names: list[str], *, cutoff: float = _SUGGEST_CUTOFF, n: int = 3
) -> list[str]:
    """Names that are a very close match to query (case-insensitive), original-cased."""
    lowered = [nm.lower() for nm in names]
    matches = difflib.get_close_matches(query.lower(), lowered, n=n, cutoff=cutoff)
    return [names[lowered.index(m)] for m in matches]
```

3. Replace the `lookup` miss branch:

```python
        detail = r.get(name, category=_category_filter(category))
        if detail is None:
            hits = r.search(name, category=_category_filter(category), limit=6)
            suggestions = _close_names(name, [h.name for h in hits])
            await interaction.response.send_message(
                embed=lookup_miss_embed(name, suggestions, hits), ephemeral=True
            )
            return
        await interaction.response.send_message(embed=lookup_embed(detail))
```

4. Add `fuzzy`/`fresh` options to `/ask`:

```python
    @bot.tree.command(name="ask", description="Ask a PF2e rules question (uses Claude).")
    @app_commands.describe(
        question="Your rules question",
        fuzzy="Reuse a cached answer to a similar question (default: on)",
        fresh="Ignore the cache and ask Claude fresh (default: off)",
    )
    async def ask_cmd(
        interaction: discord.Interaction,
        question: str,
        fuzzy: bool = True,
        fresh: bool = False,
    ):
        await interaction.response.defer(thinking=True)
        try:
            answer = await ask(question, answer_cfg, fuzzy=fuzzy, fresh=fresh)
        except AnswerError as e:
            await interaction.followup.send(str(e))
            return
        except Exception:  # noqa: BLE001 - never let one command crash the bot
            _log.exception("ask failed")
            await interaction.followup.send("Something went wrong answering that.")
            return
        await interaction.followup.send(embed=answer_embed(answer))
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run --no-sync pytest tests/test_bot_embeds.py -q`
Expected: PASS.

- [ ] **Step 5: Full gate**

Run: `uv run --no-sync pytest -q` (expect all green) and `uv run --no-sync ruff check .` (clean).

- [ ] **Step 6: Commit**

```bash
git add pf_helper/bot/main.py tests/test_bot_embeds.py
git commit -m "feat: /lookup did-you-mean fallback + /ask fuzzy/fresh options"
```

---

## Final verification (after all tasks)

- [ ] `uv run --no-sync pytest -q` — full suite green.
- [ ] `uv run --no-sync ruff check .` — clean.
- [ ] Sanity: `/ask` "How does flanking work?" then "What is flanking?" → second served via cache (footer shows "similar question"); `/ask ... fresh:true` re-asks the agent; `/lookup Grabbing` → suggests Grab + lists hits.
- [ ] Open PR (do not merge); then retrieve + address Gemini review comments per the project workflow.
