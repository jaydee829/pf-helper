# PF_Helper — Pluggable `/ask` LLM Provider (Design Spec)

**Date:** 2026-06-01
**Status:** Approved (brainstorming)
**Builds on:** the merged answer layer (`pf_helper/answer/`), the Discord bot, and
the turnkey CLI/config (`pf-helper setup`, `userconfig.py`) on `main`.

## Goal

Let the Discord bot's `/ask` use a configurable LLM provider instead of being
hard-wired to the Claude Agent SDK — while keeping the Agent SDK (the user's
Claude subscription) as the **default**. A single global config switch selects
the backend; everything else (retrieval, cache, query log, embeds) is unchanged
and provider-agnostic.

## Context & scope decision

The "decouple from Anthropic" brainstorm had two halves; only one is built here:

- **MCP server transport — intentionally NOT in scope.** The server already
  speaks standard MCP over stdio, so any local MCP client (Cursor, Cline, Zed,
  Continue, …) can use it today via `pf-helper print-config`. An HTTP/SSE
  transport would only serve remote/hosted consumers, which neither the
  maintainer nor the bot needs (the bot uses the Retriever **in-process**, not
  over a transport). Deferred until a real issue/PR asks for it.
- **Pluggable `/ask` — this spec.** The only genuinely Anthropic-coupled piece.

Chosen provider layer: **LiteLLM** (one interface to ~100 providers with
normalized tool-calling), so non-Claude providers can also be **agentic** (drive
the `search`/`get_entry` tools), not just single-shot RAG.

## Non-goals

- No per-`/ask` provider override (global config only; revisit later).
- No change to the MCP server, retrieval, cache, query log, or embeds.
- No new providers hand-coded — LiteLLM handles provider specifics.
- Default behavior unchanged: with no config, `/ask` uses the Claude Agent SDK.

---

## Component 1 — Provider configuration (`AnswerConfig`)

Add to `AnswerConfig` (frozen dataclass), read in `from_env` with the standard
precedence **env > `config.toml [ask]` > default** (mirrors how `BotConfig` now
reads `[discord]`):

| field | env | config.toml | default |
|---|---|---|---|
| `provider` | `PF_HELPER_ASK_PROVIDER` | `[ask] provider` | `"claude-sdk"` |
| `litellm_model` | `PF_HELPER_ASK_LITELLM_MODEL` | `[ask.litellm] model` | `""` |
| `litellm_api_base` | `PF_HELPER_ASK_LITELLM_API_BASE` | `[ask.litellm] api_base` | `None` |

`provider` is one of `"claude-sdk"` | `"litellm"`. `litellm_model` uses LiteLLM's
`provider/model` convention (e.g. `gemini/gemini-2.5-pro`, `openai/gpt-4o`,
`ollama/llama3.1`). `api_base` is for local/self-hosted endpoints (e.g. Ollama).

**Provider API keys are environment-only** — PF_Helper never stores them in
config. LiteLLM reads the provider's standard env var (`OPENAI_API_KEY`,
`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, …) from the process environment; there is
no `api_key` config field and `setup` does not prompt for one. `from_env` loads
`userconfig.load_file_config().get("ask", {})`.

`config.toml` example:

```toml
[ask]
provider = "litellm"

[ask.litellm]
model = "gemini/gemini-2.5-pro"
# api_base = "http://localhost:11434/v1"   # e.g. Ollama
# (the provider API key comes from its standard env var, e.g. GEMINI_API_KEY)
```

---

## Component 2 — Engine selection (`service.ask()`)

`ask()`'s control flow is **unchanged**: cache → engine A → engine B fallback →
`AnswerError`. The only change is *which engine pair* is constructed when engines
aren't injected — switch on `cfg.provider`:

```python
if engine_a is None or engine_b is None:
    retriever = retriever or build_retriever(cfg.core)
    if cfg.provider == "litellm":
        from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer, LiteLlmRagAnswerer
        engine_a = engine_a or LiteLlmAgentAnswerer(retriever, cfg)
        engine_b = engine_b or LiteLlmRagAnswerer(retriever, cfg)
    else:  # "claude-sdk" (default)
        from pf_helper.answer.engines import AgentMcpAnswerer, ContextRagAnswerer
        engine_a = engine_a or AgentMcpAnswerer(retriever)
        engine_b = engine_b or ContextRagAnswerer(retriever)
```

The cache (exact + fuzzy), query log, and `engine` ordering knob
(`auto`/`a`/`b`) all keep working unchanged — they operate on the `Answer`
regardless of who produced it.

### Transient-failure handling (small generalization)

Today the fallback loop catches `ClaudeSDKError` to mean "this engine failed, try
the next." Generalize it so a transient LiteLLM failure does the same. Introduce
a new plain exception class `EngineUnavailable(Exception)` in `answer/base.py`
(distinct from `AnswerError`), and have the loop catch
`(ClaudeSDKError, EngineUnavailable)` for the fallback path. An engine raising
`AnswerError("auth")` is NOT caught by that clause, so it propagates straight out
of `ask()` — exactly the existing auth behavior. The Claude engines
keep raising `ClaudeSDKError`/`CLINotFoundError` (unchanged); the LiteLLM engines
translate (Component 3). Net behavior is identical to today: primary fails →
fallback → `AnswerError("quota")` if both fail; auth failure → `AnswerError("auth")`.

---

## Component 3 — LiteLLM engines (`pf_helper/answer/litellm_engines.py`, new)

`litellm` is **lazy-imported inside this module** (like the Claude SDK is in
`engines.py`), so it's only required when `provider="litellm"`. It lives in a new
optional extra (`[project.optional-dependencies] litellm = ["litellm>=..."]`);
install via `uv sync --extra litellm`.

Both engines implement the existing `Answerer` interface and set
`engine=f"litellm:{model}"` (the embed footer shows it).

**`LiteLlmRagAnswerer`** (fallback, single-shot): retrieve top-k locally (reuse
the same retrieval + context-building as `ContextRagAnswerer`), then one
`litellm.completion(model, messages, api_base=?, api_key=?)` call; return the
text + the retrieved entries' AON sources.

**`LiteLlmAgentAnswerer`** (primary, agentic): a bounded ReAct tool-loop —
- tools = OpenAI-function-schema definitions for `search(query, category?)` and
  `get_entry(name, category?)` (the same two tools the Claude engine exposes).
- loop up to `max_turns`: `litellm.completion(model, messages, tools=tools, …)`;
  if the assistant message has `tool_calls`, execute each against the **Retriever**
  (reusing the search/get_entry → JSON logic and the `sources` collection from
  `engines.py`'s `_build_tools`; factor that into a shared helper so it isn't
  duplicated), append the tool results as `role:"tool"` messages, and continue;
  otherwise the assistant text is the final answer.
- return `Answer(text, sources=list(sources.items()), engine=f"litellm:{model}")`.

Both pass `api_base` to `litellm.completion` only when set in cfg. Provider API
keys are **not** passed from config — LiteLLM reads them from the standard
provider env vars.

### Error translation

Catch LiteLLM's exception types (lazy-imported from `litellm.exceptions`):
- `AuthenticationError` → `raise AnswerError("auth", "set your /ask provider API
  key …")` (propagates straight out of `ask`, like the Claude auth path).
- `RateLimitError` / `APIConnectionError` / `APIError` / `Timeout` → `raise
  EngineUnavailable(...)` so the service falls back, then surfaces `quota`.

---

## Component 4 — `pf-helper setup` provider prompt

Extend `setup_flow.run_setup` with an interactive provider step (after the
Discord-bot step, before client registration):

```
Configure the /ask LLM provider? [y/N]
  -> Provider [claude-sdk/litellm] (default claude-sdk):
     if litellm:
        Model (e.g. gemini/gemini-2.5-pro, openai/gpt-4o, ollama/llama3.1):
        API base URL (optional, Enter to skip):
        (reminder printed: set the provider's API key env var, e.g. GEMINI_API_KEY)
     write_file_config({"ask": {"provider": ..., "litellm": {model, api_base?}}})
```

`setup` does **not** prompt for or store a provider API key — it prints a
reminder to set the relevant env var. Empty optional answers are omitted (the
existing `_dumps` skips `None`). Factored into testable pure helpers behind the
`input_fn` injection `run_setup` already uses. `--yes` skips this prompt.

---

## Dependencies

Add an optional extra only:

```toml
[project.optional-dependencies]
litellm = ["litellm>=1.0"]
```

No core dependency change. `litellm` is imported lazily, so `import
pf_helper.answer.service` / running with `provider="claude-sdk"` never needs it.

## File structure

```
pf_helper/answer/
  config.py            # MODIFY: provider + litellm_model/api_base/api_key; read [ask] from config file
  base.py              # MODIFY: add EngineUnavailable exception
  service.py           # MODIFY: build engine pair by cfg.provider; loop catches EngineUnavailable
  engines.py           # MODIFY: extract the shared search/get_entry tool-exec helper (DRY)
  litellm_engines.py   # NEW: LiteLlmAgentAnswerer + LiteLlmRagAnswerer (lazy litellm import)
pf_helper/setup_flow.py  # MODIFY: optional /ask provider prompt
pyproject.toml           # MODIFY: add `litellm` optional extra
tests/
  test_answer_config.py    # NEW or extend test_answer_service.py: provider/litellm config precedence
  test_litellm_engines.py  # NEW: RAG + agentic loop with an injected fake `completion`; error mapping
  test_answer_service.py   # MODIFY: engine-pair selection by provider; EngineUnavailable fallback
  test_setup_flow.py       # MODIFY: provider prompt writes [ask] config
docs/...                   # MODIFY: provider config + examples (Ollama/OpenAI/Gemini) + which env key
```

## Error handling

- Auth failure (any provider) → `AnswerError("auth")` with a provider-appropriate
  message; the bot renders it as today.
- Transient/rate-limit → fallback engine, then `AnswerError("quota")`.
- Missing `litellm` extra while `provider="litellm"` → the lazy import raises
  `ModuleNotFoundError`; catch it at engine construction and surface a clear
  `AnswerError`/log message: "provider=litellm needs `uv sync --extra litellm`."
- Provider API keys are env-only and never written to config or logs.

## Testing

- **Config:** `provider`/`litellm_*` precedence (env > `[ask]` file > default);
  default stays `claude-sdk`.
- **Engine selection:** `provider="litellm"` builds the LiteLLM pair,
  `"claude-sdk"` builds the existing pair (inject a fake retriever; assert types).
- **`LiteLlmRagAnswerer`:** with an injected fake `completion` returning a message
  → returns its text + the retrieved sources.
- **`LiteLlmAgentAnswerer`:** fake `completion` returns a `tool_calls` response
  first (for `search`) then a final text message → assert the retriever was
  called, sources collected, loop terminates, final text returned; `max_turns`
  cap respected.
- **Error mapping:** fake `completion` raising `AuthenticationError` →
  `AnswerError("auth")`; raising `RateLimitError` → `EngineUnavailable` →
  service falls back then `quota`.
- **Setup:** provider prompt (litellm path) writes
  `{"ask": {"provider": "litellm", "litellm": {"model": ...}}}`; empty optionals
  omitted; `--yes` skips.
- All LiteLLM calls are mocked — **no network**. Gates: `uv run --no-sync pytest
  -q` green, `uv run --no-sync ruff check .` clean.

## Deferred / future

- MCP server **HTTP/SSE transport** + cross-client registration recipes (revisit
  on a real issue/PR).
- **Per-`/ask` provider/model override** (slash-command params).
- A curated short-list of provider presets in `setup` (vs free-text model).
