# Pluggable `/ask` LLM Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `/ask` use a configurable LLM provider (LiteLLM) instead of being hard-wired to the Claude Agent SDK, with `claude-sdk` staying the default.

**Architecture:** A `provider` config switch selects which `Answerer` pair `service.ask()` builds — the existing Claude engines or new LiteLLM engines (agentic tool-loop + single-shot RAG) that reuse a shared retriever-tool helper. A small `EngineUnavailable` marker generalizes the fallback loop. `litellm` is an optional, lazily-imported extra. Cache/query-log/embeds are untouched.

**Tech Stack:** Python 3.14, LiteLLM (new optional extra, lazy import), stdlib `json`, pytest (`uv run --no-sync pytest -q`), ruff (`uv run --no-sync ruff check .`).

**Spec:** `docs/superpowers/specs/2026-06-01-pluggable-ask-provider-design.md`

**Conventions:** `from __future__ import annotations`; frozen dataclasses where the codebase uses them; two separate `except` clauses unless an `as` binding lets the tuple keep its parens (ruff py3.14); run tests/lint with `uv run --no-sync`. LiteLLM must be imported **lazily inside methods** so modules import without the extra installed. All LiteLLM calls in tests are mocked — never hit the network.

---

### Task 1: `AnswerConfig` provider fields (+ read `[ask]` from config file)

**Files:**
- Modify: `pf_helper/answer/config.py`
- Test: `tests/test_answer_service.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_answer_service.py`:

```python
import pf_helper.answer.config as cfgmod


def test_answer_config_provider_default(monkeypatch):
    monkeypatch.delenv("PF_HELPER_ASK_PROVIDER", raising=False)
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", dict)
    cfg = cfgmod.AnswerConfig.from_env()
    assert cfg.provider == "claude-sdk"
    assert cfg.litellm_model == "" and cfg.litellm_api_base is None


def test_answer_config_provider_env_wins(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_PROVIDER", "LiteLLM")
    monkeypatch.setenv("PF_HELPER_ASK_LITELLM_MODEL", "openai/gpt-4o")
    monkeypatch.setattr(
        cfgmod.userconfig, "load_file_config",
        lambda: {"ask": {"provider": "claude-sdk", "litellm": {"model": "x"}}},
    )
    cfg = cfgmod.AnswerConfig.from_env()
    assert cfg.provider == "litellm"  # lower-cased, env wins
    assert cfg.litellm_model == "openai/gpt-4o"


def test_answer_config_provider_from_file(monkeypatch):
    monkeypatch.delenv("PF_HELPER_ASK_PROVIDER", raising=False)
    monkeypatch.delenv("PF_HELPER_ASK_LITELLM_MODEL", raising=False)
    monkeypatch.delenv("PF_HELPER_ASK_LITELLM_API_BASE", raising=False)
    monkeypatch.setattr(
        cfgmod.userconfig, "load_file_config",
        lambda: {"ask": {"provider": "litellm", "litellm": {"model": "ollama/llama3.1", "api_base": "http://x/v1"}}},
    )
    cfg = cfgmod.AnswerConfig.from_env()
    assert cfg.provider == "litellm"
    assert cfg.litellm_model == "ollama/llama3.1"
    assert cfg.litellm_api_base == "http://x/v1"
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_answer_service.py -k provider -v` — expect FAIL (no `provider`/`userconfig`).

- [ ] **Step 3: Implement** — rewrite `pf_helper/answer/config.py`:

```python
"""Configuration for the answering layer (provider + engine choice + cache knobs)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pf_helper import userconfig
from pf_helper.config import Config


@dataclass(frozen=True)
class AnswerConfig:
    provider: str = "claude-sdk"  # "claude-sdk" | "litellm"
    litellm_model: str = ""  # e.g. "gemini/gemini-2.5-pro", "ollama/llama3.1"
    litellm_api_base: str | None = None  # for local/self-hosted endpoints
    engine: str = "auto"  # "auto" (A->B) | "a" | "b"
    cache_enabled: bool = True
    cache_ttl_days: int = 30
    cache_max: int = 500
    cache_similarity: float = 0.5  # Jaccard threshold; 0 disables the fuzzy pass
    query_log_enabled: bool = True
    core: Config = field(default_factory=Config.from_env)

    @classmethod
    def from_env(cls) -> AnswerConfig:
        ask = userconfig.load_file_config().get("ask", {})
        lite = ask.get("litellm", {})
        provider = (os.environ.get("PF_HELPER_ASK_PROVIDER") or ask.get("provider") or "claude-sdk").lower()
        model = os.environ.get("PF_HELPER_ASK_LITELLM_MODEL") or lite.get("model") or ""
        api_base = os.environ.get("PF_HELPER_ASK_LITELLM_API_BASE") or lite.get("api_base") or None
        return cls(
            provider=provider,
            litellm_model=model,
            litellm_api_base=api_base,
            engine=os.environ.get("PF_HELPER_ASK_ENGINE", "auto").lower(),
            cache_enabled=os.environ.get("PF_HELPER_ASK_CACHE", "1") != "0",
            cache_ttl_days=int(os.environ.get("PF_HELPER_ASK_CACHE_TTL_DAYS", "30")),
            cache_max=int(os.environ.get("PF_HELPER_ASK_CACHE_MAX", "500")),
            cache_similarity=float(os.environ.get("PF_HELPER_ASK_CACHE_SIMILARITY", "0.5")),
            query_log_enabled=os.environ.get("PF_HELPER_ASK_QUERY_LOG", "1") != "0",
            core=Config.from_env(),
        )
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_answer_service.py -q` (expect PASS — incl. existing config test) then `uv run --no-sync ruff check pf_helper/answer/config.py tests/test_answer_service.py`.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/answer/config.py tests/test_answer_service.py
git commit -m "feat: AnswerConfig provider + litellm_model/api_base (env > [ask] file)"
```

---

### Task 2: `EngineUnavailable` + shared retriever-tool helper (DRY)

**Files:**
- Modify: `pf_helper/answer/base.py` (add `EngineUnavailable`)
- Create: `pf_helper/answer/tools.py`
- Modify: `pf_helper/answer/engines.py` (use the shared helper)
- Test: `tests/test_answer_tools.py` (new), `tests/test_answer_engines.py` (unchanged — must still pass)

- [ ] **Step 1: Write failing tests** — create `tests/test_answer_tools.py`:

```python
from pf_helper.answer.tools import get_entry_payload, search_payload
from pf_helper.models import EntryDetail, SearchHit


class FakeRetriever:
    def __init__(self, hits, details):
        self._hits, self._details = hits, details

    def search(self, query, category, limit):
        return self._hits

    def get(self, name, category):
        return self._details.get(name)


def test_search_payload_collects_sources():
    hit = SearchHit(id="spell:heal", name="Heal", category="spell", excerpt="h",
                    source_url="https://x/Heal")
    sources = {}
    out = search_payload(FakeRetriever([hit], {}), sources, "heal", "")
    assert out == [{"name": "Heal", "category": "spell", "source_url": "https://x/Heal", "excerpt": "h"}]
    assert sources == {"Heal": "https://x/Heal"}


def test_get_entry_payload_and_miss():
    d = EntryDetail(id="spell:heal", name="Heal", category="spell", text="Heal a creature.",
                    source_url="https://x/Heal")
    sources = {}
    r = FakeRetriever([], {"Heal": d})
    assert get_entry_payload(r, sources, "Heal", "spell")["text"] == "Heal a creature."
    assert sources == {"Heal": "https://x/Heal"}
    assert get_entry_payload(r, sources, "Nope", None) is None
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_answer_tools.py -v` — expect FAIL.

- [ ] **Step 3: Add `EngineUnavailable`** to `pf_helper/answer/base.py` (after `AnswerError`):

```python
class EngineUnavailable(Exception):
    """A transient engine failure (e.g. rate limit) — the caller should try the
    fallback engine. Distinct from AnswerError, which is surfaced to the user."""
```

- [ ] **Step 4: Create `pf_helper/answer/tools.py`** (the shared core both engines use):

```python
"""Shared retriever-tool logic for the agentic engines (search / get_entry).

Returns plain JSON-able payloads and records (name -> source_url) into `sources`.
The Claude engine wraps these in MCP tool-result envelopes; the LiteLLM engine
json.dumps them for tool messages.
"""

from __future__ import annotations

from pf_helper.retrieval.base import Retriever

_SEARCH_LIMIT = 8


def search_payload(
    retriever: Retriever, sources: dict[str, str], query: str, category: str | None
) -> list[dict]:
    hits = retriever.search(query, category=category or None, limit=_SEARCH_LIMIT)
    for h in hits:
        sources[h.name] = h.source_url
    return [
        {"name": h.name, "category": h.category, "source_url": h.source_url, "excerpt": h.excerpt}
        for h in hits
    ]


def get_entry_payload(
    retriever: Retriever, sources: dict[str, str], name: str, category: str | None
) -> dict | None:
    d = retriever.get(name, category=category or None)
    if d is None:
        return None
    sources[d.name] = d.source_url
    return {"name": d.name, "category": d.category, "source_url": d.source_url, "text": d.text}
```

- [ ] **Step 5: Refactor `engines.py`'s `_build_tools`** to use the shared helper while keeping the exact MCP-envelope return shape. In `pf_helper/answer/engines.py`, add `from pf_helper.answer.tools import get_entry_payload, search_payload` and replace the bodies of `do_search`/`do_get` inside `_build_tools`:

```python
        async def do_search(args):
            payload = search_payload(retriever, sources, args["query"], args.get("category"))
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}

        async def do_get(args):
            payload = get_entry_payload(retriever, sources, args["name"], args.get("category"))
            text = json.dumps(payload) if payload is not None else "null"
            return {"content": [{"type": "text", "text": text}]}
```

(Leave everything else in `engines.py` unchanged — `_collect_text`, `ContextRagAnswerer`, the tool registration, system prompts. `json` is already imported.)

- [ ] **Step 6: Run** `uv run --no-sync pytest tests/test_answer_tools.py tests/test_answer_engines.py -q` (expect PASS — the engine tests asserting `out["content"][0]["text"]` still hold) then `uv run --no-sync ruff check pf_helper/answer/`.

- [ ] **Step 7: Commit**

```bash
git add pf_helper/answer/base.py pf_helper/answer/tools.py pf_helper/answer/engines.py tests/test_answer_tools.py
git commit -m "feat: EngineUnavailable + shared retriever-tool helper (DRY engines)"
```

---

### Task 3: LiteLLM engines (RAG + agentic)

**Files:**
- Create: `pf_helper/answer/litellm_engines.py`
- Test: `tests/test_litellm_engines.py`

- [ ] **Step 1: Write failing tests** — create `tests/test_litellm_engines.py`:

```python
import sys
import types

import pytest

from pf_helper.answer.base import AnswerError, EngineUnavailable
from pf_helper.answer.config import AnswerConfig
from pf_helper.models import EntryDetail, SearchHit


class FakeRetriever:
    def __init__(self, hits, details):
        self._hits, self._details = hits, details

    def search(self, query, category, limit):
        return self._hits

    def get(self, name, category):
        return self._details.get(name)


def _cfg(model="openai/gpt-4o"):
    return AnswerConfig(provider="litellm", litellm_model=model)


def _msg(content=None, tool_calls=None):
    m = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m)])


def _tool_call(cid, name, args_json):
    return types.SimpleNamespace(id=cid, function=types.SimpleNamespace(name=name, arguments=args_json))


def _install_fake_litellm(monkeypatch, completion):
    """Install a fake `litellm` module so the lazy import inside the engine finds it."""
    mod = types.ModuleType("litellm")
    mod.completion = completion

    class _Exc(Exception):
        pass

    exc_mod = types.ModuleType("litellm.exceptions")
    exc_mod.AuthenticationError = type("AuthenticationError", (_Exc,), {})
    exc_mod.RateLimitError = type("RateLimitError", (_Exc,), {})
    exc_mod.APIError = type("APIError", (_Exc,), {})
    exc_mod.APIConnectionError = type("APIConnectionError", (_Exc,), {})
    exc_mod.Timeout = type("Timeout", (_Exc,), {})
    mod.exceptions = exc_mod
    monkeypatch.setitem(sys.modules, "litellm", mod)
    monkeypatch.setitem(sys.modules, "litellm.exceptions", exc_mod)
    return mod


@pytest.mark.asyncio
async def test_rag_returns_text_and_sources(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    hit = SearchHit(id="c:frightened", name="Frightened", category="condition", excerpt="...",
                    source_url="https://x/Frightened")
    detail = EntryDetail(id="c:frightened", name="Frightened", category="condition",
                         text="status penalty", source_url=hit.source_url)
    calls = {}

    def fake_completion(model, messages, **kw):
        calls["model"], calls["kw"] = model, kw
        return _msg(content="Frightened is a status penalty.")

    _install_fake_litellm(monkeypatch, fake_completion)
    ans = await LiteLlmRagAnswerer(FakeRetriever([hit], {"Frightened": detail}), _cfg()).answer("x")
    assert ans.text == "Frightened is a status penalty."
    assert ans.sources == [("Frightened", "https://x/Frightened")]
    assert ans.engine == "litellm:openai/gpt-4o"
    assert calls["model"] == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_agent_runs_tool_loop(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer

    hit = SearchHit(id="s:heal", name="Heal", category="spell", excerpt="h",
                    source_url="https://x/Heal")
    r = FakeRetriever([hit], {})
    seq = [
        _msg(tool_calls=[_tool_call("c1", "search", '{"query": "heal"}')]),  # first: ask to search
        _msg(content="Heal restores HP."),  # then: final answer
    ]

    def fake_completion(model, messages, **kw):
        return seq.pop(0)

    _install_fake_litellm(monkeypatch, fake_completion)
    ans = await LiteLlmAgentAnswerer(r, _cfg()).answer("what does heal do?")
    assert ans.text == "Heal restores HP."
    assert ("Heal", "https://x/Heal") in ans.sources  # tool result collected the source
    assert ans.engine == "litellm:openai/gpt-4o"


@pytest.mark.asyncio
async def test_auth_error_maps_to_answererror(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    mod = _install_fake_litellm(monkeypatch, None)

    def boom(model, messages, **kw):
        raise mod.exceptions.AuthenticationError("no key")

    mod.completion = boom
    with pytest.raises(AnswerError) as ei:
        await LiteLlmRagAnswerer(FakeRetriever([], {}), _cfg()).answer("x")
    assert ei.value.reason == "auth"


@pytest.mark.asyncio
async def test_ratelimit_maps_to_engine_unavailable(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    mod = _install_fake_litellm(monkeypatch, None)

    def boom(model, messages, **kw):
        raise mod.exceptions.RateLimitError("slow down")

    mod.completion = boom
    with pytest.raises(EngineUnavailable):
        await LiteLlmRagAnswerer(FakeRetriever([], {}), _cfg()).answer("x")


@pytest.mark.asyncio
async def test_missing_model_raises(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    _install_fake_litellm(monkeypatch, lambda **k: _msg(content="x"))
    with pytest.raises(AnswerError):
        await LiteLlmRagAnswerer(FakeRetriever([], {}), _cfg(model="")).answer("x")
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_litellm_engines.py -v` — expect FAIL (module missing).

- [ ] **Step 3: Create `pf_helper/answer/litellm_engines.py`:**

```python
"""LLM answering engines over LiteLLM (any provider). Optional `litellm` extra.

`litellm` is imported lazily inside methods so this module imports without the
extra installed. Provider API keys come from the provider's standard env vars.
"""

from __future__ import annotations

import json

from pf_helper.answer.base import Answer, AnswerError, Answerer, EngineUnavailable
from pf_helper.answer.config import AnswerConfig
from pf_helper.answer.tools import get_entry_payload, search_payload
from pf_helper.retrieval.base import Retriever

_ENTRY_TEXT_CAP = 1500
_MAX_TURNS = 6

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

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search PF2e rules; returns name/category/excerpt/source_url.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "category": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entry",
            "description": "Get the full PF2e entry by exact name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "category": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
]


def _load_litellm():
    try:
        import litellm
        from litellm import exceptions as lite_exc
    except ModuleNotFoundError as exc:
        raise AnswerError(
            "error", "provider=litellm needs the extra: `uv sync --extra litellm`."
        ) from exc
    return litellm, lite_exc


def _completion_kwargs(cfg: AnswerConfig) -> dict:
    if not cfg.litellm_model:
        raise AnswerError("error", "Set PF_HELPER_ASK_LITELLM_MODEL (or [ask.litellm] model).")
    kw: dict = {"model": cfg.litellm_model}
    if cfg.litellm_api_base:
        kw["api_base"] = cfg.litellm_api_base
    return kw


def _call(litellm, lite_exc, **kwargs):
    """One completion call with provider-error translation."""
    try:
        return litellm.completion(**kwargs)
    except lite_exc.AuthenticationError as exc:
        raise AnswerError("auth", "Set your /ask provider's API key env var.") from exc
    except (lite_exc.RateLimitError, lite_exc.APIError, lite_exc.APIConnectionError, lite_exc.Timeout) as exc:
        raise EngineUnavailable(str(exc)) from exc


class LiteLlmRagAnswerer(Answerer):
    """Fallback: retrieve top-k locally, answer in one LiteLLM call."""

    def __init__(self, retriever: Retriever, cfg: AnswerConfig, limit: int = 6):
        self._retriever, self._cfg, self._limit = retriever, cfg, limit

    async def answer(self, question: str) -> Answer:
        litellm, lite_exc = _load_litellm()
        kw = _completion_kwargs(self._cfg)
        hits = self._retriever.search(question, category=None, limit=self._limit)
        details = [self._retriever.get(h.name, h.category) for h in hits]
        details = [d for d in details if d is not None]
        engine = f"litellm:{self._cfg.litellm_model}"
        if not details:
            return Answer(text="No matching rules entry found.", sources=[], engine=engine)
        context = "\n\n".join(
            f"## {d.name} ({d.category}) — {d.source_url}\n{d.text[:_ENTRY_TEXT_CAP]}" for d in details
        )
        messages = [
            {"role": "system", "content": _SYS_RAG},
            {"role": "user", "content": f"Entries:\n{context}\n\nQuestion: {question}"},
        ]
        resp = _call(litellm, lite_exc, messages=messages, **kw)
        text = (resp.choices[0].message.content or "").strip()
        return Answer(text=text, sources=[(d.name, d.source_url) for d in details], engine=engine)


class LiteLlmAgentAnswerer(Answerer):
    """Primary: the model drives the search/get_entry tools in a bounded loop."""

    def __init__(self, retriever: Retriever, cfg: AnswerConfig, max_turns: int = _MAX_TURNS):
        self._retriever, self._cfg, self._max_turns = retriever, cfg, max_turns

    def _run_tool(self, name: str, args: dict, sources: dict[str, str]) -> object:
        if name == "search":
            return search_payload(self._retriever, sources, args.get("query", ""), args.get("category"))
        if name == "get_entry":
            return get_entry_payload(self._retriever, sources, args.get("name", ""), args.get("category"))
        return None

    async def answer(self, question: str) -> Answer:
        litellm, lite_exc = _load_litellm()
        kw = _completion_kwargs(self._cfg)
        engine = f"litellm:{self._cfg.litellm_model}"
        sources: dict[str, str] = {}
        messages: list = [
            {"role": "system", "content": _SYS_AGENT},
            {"role": "user", "content": question},
        ]
        text = ""
        for _ in range(self._max_turns):
            resp = _call(litellm, lite_exc, messages=messages, tools=_TOOLS, **kw)
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                text = (msg.content or "").strip()
                break
            messages.append(msg)  # the assistant turn that requested the tools
            for tc in tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                payload = self._run_tool(tc.function.name, args, sources)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "name": tc.function.name,
                     "content": json.dumps(payload)}
                )
        return Answer(text=text, sources=list(sources.items()), engine=engine)
```

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_litellm_engines.py -q` (expect PASS) and confirm the module imports without the real extra: `uv run --no-sync python -c "import pf_helper.answer.litellm_engines"`. Then `uv run --no-sync ruff check pf_helper/answer/litellm_engines.py tests/test_litellm_engines.py`.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/answer/litellm_engines.py tests/test_litellm_engines.py
git commit -m "feat: LiteLLM agentic + RAG engines (lazy import, error mapping)"
```

---

### Task 4: Engine-pair selection in `service.ask()` + fallback generalization

**Files:**
- Modify: `pf_helper/answer/service.py`
- Test: `tests/test_answer_service.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_answer_service.py`:

```python
def test_build_engines_claude_sdk(monkeypatch):
    from pf_helper.answer import service
    from pf_helper.answer.engines import AgentMcpAnswerer, ContextRagAnswerer

    a, b = service._build_engines(AnswerConfig(provider="claude-sdk"), retriever=object())
    assert isinstance(a, AgentMcpAnswerer) and isinstance(b, ContextRagAnswerer)


def test_build_engines_litellm(monkeypatch):
    from pf_helper.answer import service
    from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer, LiteLlmRagAnswerer

    a, b = service._build_engines(AnswerConfig(provider="litellm", litellm_model="openai/x"), retriever=object())
    assert isinstance(a, LiteLlmAgentAnswerer) and isinstance(b, LiteLlmRagAnswerer)


@pytest.mark.asyncio
async def test_engine_unavailable_triggers_fallback():
    from pf_helper.answer.base import EngineUnavailable

    a = FakeEngine(exc=EngineUnavailable("rate limited"))
    b = FakeEngine(Answer("B-ans", [("n", "u")], "litellm:x"))
    out = await ask("q", cache=FakeCache(), engine_a=a, engine_b=b)
    assert out.text == "B-ans" and a.calls == 1 and b.calls == 1
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_answer_service.py -k "build_engines or engine_unavailable" -v` — expect FAIL.

- [ ] **Step 3: Implement** — in `pf_helper/answer/service.py`:

3a. Add `EngineUnavailable` to the base import:

```python
from pf_helper.answer.base import Answer, Answerer, AnswerError, EngineUnavailable
```

3b. Add the selection helper (module level, above `ask`):

```python
def _build_engines(cfg: AnswerConfig, retriever) -> tuple[Answerer, Answerer]:
    """Return (primary, fallback) answerers for the configured provider."""
    if cfg.provider == "litellm":
        from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer, LiteLlmRagAnswerer

        return LiteLlmAgentAnswerer(retriever, cfg), LiteLlmRagAnswerer(retriever, cfg)
    from pf_helper.answer.engines import AgentMcpAnswerer, ContextRagAnswerer

    return AgentMcpAnswerer(retriever), ContextRagAnswerer(retriever)
```

3c. Replace the engine-construction block inside `ask()` (the `if engine_a is None or engine_b is None:` block that builds `AgentMcpAnswerer`/`ContextRagAnswerer`) with:

```python
    if engine_a is None or engine_b is None:
        from pf_helper.retrieval.factory import build_retriever

        retriever = retriever or build_retriever(cfg.core)
        built_a, built_b = _build_engines(cfg, retriever)
        engine_a = engine_a or built_a
        engine_b = engine_b or built_b
```

3d. Generalize the loop's exception handling. Replace the per-engine `try/except` body with:

```python
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
        except AnswerError as exc:  # e.g. litellm auth / missing-extra — surface as-is
            _log_query(f"error:{exc.reason}")
            raise
        except (ClaudeSDKError, EngineUnavailable) as exc:
            last_error = exc
            _log.warning("%s failed: %s", type(engine).__name__, exc)
            continue
```

(Leave the cache read, `_log_query` helper, `order` computation, and the final `error:quota` raise unchanged.)

- [ ] **Step 4: Run** `uv run --no-sync pytest tests/test_answer_service.py -q` (expect PASS — all existing + new) then the whole suite `uv run --no-sync pytest -q`. Then `uv run --no-sync ruff check pf_helper/answer/service.py tests/test_answer_service.py`.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/answer/service.py tests/test_answer_service.py
git commit -m "feat: select engine pair by provider + EngineUnavailable fallback"
```

---

### Task 5: `pf-helper setup` provider prompt

**Files:**
- Modify: `pf_helper/setup_flow.py`
- Test: `tests/test_setup_flow.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_setup_flow.py`:

```python
def test_setup_configures_litellm_provider(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")  # skip build prompt
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    written = []
    monkeypatch.setattr(sf.userconfig, "write_file_config", lambda updates: written.append(updates))
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])
    # bot? n | provider? y | provider=litellm | model | api_base "" | desktop? n | cc? n
    sf.run_setup(
        input_fn=_fake_inputs(["n", "y", "litellm", "ollama/llama3.1", "", "n", "n"]),
        getpass_fn=lambda prompt="": "",
    )
    assert {"ask": {"provider": "litellm", "litellm": {"model": "ollama/llama3.1"}}} in written


def test_setup_provider_claude_sdk_writes_provider_only(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    cfg.db_path.write_text("db")
    monkeypatch.setattr(sf.Config, "from_env", classmethod(lambda cls: cfg))
    written = []
    monkeypatch.setattr(sf.userconfig, "write_file_config", lambda updates: written.append(updates))
    monkeypatch.setattr(sf, "server_command", lambda: ["pf", "serve"])
    # bot? n | provider? y | provider=claude-sdk (default, empty) | desktop? n | cc? n
    sf.run_setup(input_fn=_fake_inputs(["n", "y", "", "n", "n"]))
    assert {"ask": {"provider": "claude-sdk"}} in written
```

- [ ] **Step 2: Run** `uv run --no-sync pytest tests/test_setup_flow.py -k provider -v` — expect FAIL.

- [ ] **Step 3: Implement** — in `pf_helper/setup_flow.py`, add a provider step. Insert this block **after** the Discord-bot `if`-block and **before** `cmd = server_command()`:

```python
    if _yn(input_fn, "Configure the /ask LLM provider?", default=False):
        choice = input_fn("Provider [claude-sdk/litellm] (default claude-sdk): ").strip().lower()
        provider = "litellm" if choice == "litellm" else "claude-sdk"
        ask: dict = {"provider": provider}
        if provider == "litellm":
            model = input_fn("Model (e.g. gemini/gemini-2.5-pro, ollama/llama3.1): ").strip()
            litellm: dict = {"model": model}
            api_base = input_fn("API base URL (optional, Enter to skip): ").strip()
            if api_base:
                litellm["api_base"] = api_base
            ask["litellm"] = litellm
            print("  Set the provider's API key env var (e.g. OPENAI_API_KEY / GEMINI_API_KEY).")
        userconfig.write_file_config({"ask": ask})
        print("Saved /ask provider config.")
```

(The `--yes` path returns before this prompt, so it's skipped automatically — no extra guard needed.)

- [ ] **Step 4: Update existing interactive tests, then run.**

**IMPORTANT:** the new prompt sits in the interactive section (after the Discord-bot block, before client registration), so it consumes one `input_fn` answer in the EXISTING interactive setup tests. Each of `test_setup_builds_index_saves_token_registers`, `test_setup_reprompts_on_invalid_guild_id`, and `test_setup_claude_code_failure_is_graceful` needs one extra answer — `"n"` to "Configure the /ask LLM provider?" — inserted **after the Discord-bot answers and before the desktop-registration answer**. Concretely:
- `test_setup_builds_index_saves_token_registers`: `["y","y","","y","y"]` → `["y","y","","n","y","y"]`
- `test_setup_reprompts_on_invalid_guild_id`: `["y","abc","42","n","n"]` → `["y","abc","42","n","n","n"]`
- `test_setup_claude_code_failure_is_graceful`: `["n","n","y"]` → `["n","n","n","y"]`

(`test_setup_yes_builds_only` uses `yes=True` and returns before the interactive section — leave it unchanged.)

Then run `uv run --no-sync pytest tests/test_setup_flow.py -q` (expect PASS).

Then the whole suite `uv run --no-sync pytest -q` and `uv run --no-sync ruff check pf_helper/setup_flow.py tests/test_setup_flow.py`.

- [ ] **Step 5: Commit**

```bash
git add pf_helper/setup_flow.py tests/test_setup_flow.py
git commit -m "feat: pf-helper setup prompts for the /ask provider"
```

---

### Task 6: `litellm` optional extra + docs

**Files:**
- Modify: `pyproject.toml`, `README.md`, `docs/discord-bot-setup.md`

- [ ] **Step 1: Add the optional extra** — in `pyproject.toml` under `[project.optional-dependencies]`, add (leave `bot` as-is):

```toml
litellm = ["litellm>=1.0"]
```

Do NOT run `uv sync --extra litellm` as part of this task (it pulls a large dep and isn't needed for the test suite, which mocks litellm). A bare `uv sync` to refresh the lock is fine if Desktop is closed; otherwise skip — no code imports litellm at module load.

- [ ] **Step 2: Docs** — READ each file first, then:

2a. `README.md` — add an "`/ask` LLM provider" subsection near the bot/install docs:

```markdown
### Choosing the /ask LLM provider

`/ask` defaults to your Claude subscription via the Claude Agent SDK. To use a
different provider, set `provider = "litellm"` (run `pf-helper setup` or edit
`config.toml`) and install the extra: `uv sync --extra bot --extra litellm`.

```toml
[ask]
provider = "litellm"
[ask.litellm]
model = "gemini/gemini-2.5-pro"   # or openai/gpt-4o, ollama/llama3.1, ...
# api_base = "http://localhost:11434/v1"   # local (Ollama/LM Studio)
```

Provider API keys come from that provider's standard env var
(`OPENAI_API_KEY`, `GEMINI_API_KEY`, …) — PF_Helper never stores them. Local
models (Ollama) need no key.
```

2b. `docs/discord-bot-setup.md` — add a short note that `pf-helper setup` now also offers to configure the `/ask` provider, and that non-default providers require `uv sync --extra litellm` + the provider's API-key env var.

- [ ] **Step 3: Full gate** — `uv run --no-sync pytest -q` (all green) and `uv run --no-sync ruff check .` (clean).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock README.md docs/discord-bot-setup.md
git commit -m "feat: litellm optional extra + /ask provider docs"
```

(If `uv.lock` was not regenerated because you skipped `uv sync`, omit it from the add.)

---

### Task 7: Opt-in live LiteLLM integration test

**Files:**
- Modify: `pyproject.toml` (register the `live` pytest marker)
- Test: `tests/test_litellm_live.py` (new)

This test exercises the real `litellm` against a real model to close the mock/reality gap (response shape, tool-call round-trip, real exception types). It is **off by default**: it skips unless `PF_HELPER_TEST_LITELLM_MODEL` is set, the real `litellm` is importable, and an index exists. So `uv run --no-sync pytest -q` stays fully offline/green.

- [ ] **Step 1: Register the marker** — in `pyproject.toml`, add (create the section if absent; if `[tool.pytest.ini_options]` already exists, just add the `markers` key):

```toml
[tool.pytest.ini_options]
markers = ["live: hits a real LLM provider; opt-in, requires PF_HELPER_TEST_LITELLM_MODEL"]
```

- [ ] **Step 2: Write the test** — create `tests/test_litellm_live.py`:

```python
"""Opt-in live LiteLLM smoke test. Skipped unless PF_HELPER_TEST_LITELLM_MODEL is set.

Run it deliberately:  PF_HELPER_TEST_LITELLM_MODEL=ollama/llama3.1  uv run pytest -m live
(local Ollama = free/no key; or set a hosted model + its API-key env var).
"""

import os

import pytest

pytestmark = pytest.mark.live

_MODEL = os.environ.get("PF_HELPER_TEST_LITELLM_MODEL")


@pytest.mark.skipif(not _MODEL, reason="set PF_HELPER_TEST_LITELLM_MODEL to run the live test")
@pytest.mark.asyncio
async def test_live_litellm_rag_and_agent():
    pytest.importorskip("litellm")  # skip if the optional extra isn't installed
    from pf_helper.answer.config import AnswerConfig
    from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer, LiteLlmRagAnswerer
    from pf_helper.retrieval.factory import build_retriever

    cfg = AnswerConfig(
        provider="litellm",
        litellm_model=_MODEL,
        litellm_api_base=os.environ.get("PF_HELPER_TEST_LITELLM_API_BASE"),
    )
    if not cfg.core.db_path.exists():
        pytest.skip("no rules index built (run `pf-helper ingest`)")
    retriever = build_retriever(cfg.core)

    # RAG path: real response parses, non-empty answer, sources from retrieval.
    rag = await LiteLlmRagAnswerer(retriever, cfg).answer("How does flanking work?")
    assert rag.text.strip()
    assert rag.sources

    # Agentic path: the tool-loop round-trips with real litellm objects and the
    # model drives the tools (needs a tool-capable model — that's the point of
    # running this deliberately against your chosen model).
    agent = await LiteLlmAgentAnswerer(retriever, cfg).answer("How does flanking work?")
    assert agent.text.strip()
    assert agent.sources  # >=1 source collected -> a tool was actually called
```

- [ ] **Step 3: Verify it skips by default** — `uv run --no-sync pytest tests/test_litellm_live.py -q` → expect **1 skipped** (env var unset). Confirm `uv run --no-sync pytest -q` still passes with this file present (the live test is skipped, not collected-and-failed). Then `uv run --no-sync ruff check tests/test_litellm_live.py`.

- [ ] **Step 4: (Optional, manual) actually run it** — if you have Ollama running: `PF_HELPER_TEST_LITELLM_MODEL=ollama/llama3.1 uv run pytest -m live -q` (needs `uv sync --extra litellm` and a built index). Not required for the task to be complete — Step 3 is the gate.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_litellm_live.py
git commit -m "test: opt-in live LiteLLM integration smoke test (env-gated)"
```

---

## Final verification (after all tasks)

- [ ] `uv run --no-sync pytest -q` — full suite green.
- [ ] `uv run --no-sync ruff check .` — clean.
- [ ] `uv run --no-sync python -c "import pf_helper.answer.service; import pf_helper.answer.litellm_engines"` — imports clean WITHOUT the `litellm` extra installed (proves lazy import).
- [ ] Default unchanged: with no `PF_HELPER_ASK_PROVIDER`/config, `AnswerConfig.from_env().provider == "claude-sdk"`.
- [ ] The live test (`tests/test_litellm_live.py`) is **skipped** in a plain `pytest -q` run (env var unset) — never fails the gate. `pytest -m live` with `PF_HELPER_TEST_LITELLM_MODEL` set is the deliberate, manual path.
- [ ] Open PR (do not merge); then retrieve + address Gemini review comments per the project workflow.
