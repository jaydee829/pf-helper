# PF_Helper — Discord Bot Front-End (Design Spec)

**Date:** 2026-05-30
**Status:** Approved (brainstorming)
**Builds on:** the shipped MCP server + AON supplement on `main`
(`docs/superpowers/specs/2026-05-29-pf-helper-mcp-design.md`,
`docs/superpowers/specs/2026-05-30-aon-es-supplement-design.md`).

## Goal

A Discord bot front-end that lets a tabletop group query PF_Helper's local PF2e
index from Discord. Three slash commands:

- **`/lookup <name> [category]`** and **`/search <query> [category]`** — pure,
  deterministic retrieval over the existing `Retriever` (no LLM, no API cost, no
  subscription usage).
- **`/ask <question>`** — natural-language rules Q&A powered by the **Claude
  Agent SDK** authenticated against the user's **Claude subscription** (no
  metered `ANTHROPIC_API_KEY`), with the **existing `pf-helper` MCP server**
  attached as the agent's retrieval tool.

The bot reuses everything already built: the SQLite/FTS5 index, the `Retriever`
interface, the `source_url` AON links, and the MCP server.

## Non-goals (v1)

- Not a public/multi-tenant SaaS bot. Intended for a private game group; the
  subscription-auth path assumes individual use (see "Auth & billing").
- No separate metered API key required (uses the subscription). A metered key
  remains a future option for heavy/public deployments.
- No name autocomplete on `/lookup` (deferred — nice but adds complexity).
- No LLM for `/lookup` / `/search` (they are deterministic retrieval).
- No per-user rate limiting / usage accounting (deferred).

## Auth & billing (verified)

The **Claude Agent SDK for Python** (`/anthropics/claude-agent-sdk-python`)
bundles the Claude Code CLI and, when that CLI is authenticated with a Claude
**Pro/Max** login, runs **on the subscription with no API key** (confirmed by
the SDK's own streaming example: "Authenticates via Claude Code CLI using Claude
Pro subscription (no API key needed)"). For a headless/long-running bot,
authenticate once with a long-lived token (`claude setup-token` →
`CLAUDE_CODE_OAUTH_TOKEN` in the bot's environment).

Implications baked into the design:
- `/ask` still makes network calls to Anthropic (it is not offline) — it just
  isn't a metered API key; usage counts against the **subscription rate limits**
  shared with the user's other Claude usage.
- Because quota is finite, `/ask` degrades gracefully (see "Fallback ladder")
  and the deterministic commands (which never touch the subscription) are the
  primary workhorses.

## Architecture

```
Discord  <-- gateway/REST -->  discord.py client (pf_helper/bot/main.py)
                                   |
        +--------------------------+---------------------------+
        |                          |                           |
   /lookup, /search            /ask                       (bot/embeds.py)
        |                          |                       pure render
   Retriever.get/search      pf_helper.answer.ask(question)   <-- SHARED module
   (local index, no LLM)          |  (cache -> A -> B), front-end-agnostic
                          A: AgentMcpAnswerer  --(Agent SDK, subscription)-->
                                 Claude + pf-helper MCP server (as a tool)
                          B: ContextRagAnswerer (fallback)
                                 Retriever.search -> single tool-less Agent query
```

- The LLM **answering layer lives in a shared, front-end-agnostic package
  `pf_helper/answer/`** (the `Answerer` engines, the `ask` orchestrator, and the
  answer cache). The Discord bot's `/ask` consumes it; any future answering
  front-end (a `pf-helper-ask` CLI, an HTTP endpoint, the deferred standalone
  answering role) reuses the *same* cached, link-guaranteeing logic. Housing it
  here is purely organizational — zero runtime/quota/context difference vs. the
  bot owning it. It does **not** wrap the raw MCP retrieval path (which needs no
  cache); it is the layer that makes the subscription LLM call.
- The bot is an **optional** add-on: its dependencies live in an optional
  dependency group so the core MCP server stays lean. Entry point:
  `pf-helper-bot`.
- `/lookup` and `/search` call `build_retriever(cfg)` (the existing factory) and
  render results — identical data to the MCP tools, no LLM.
- `/ask` calls `pf_helper.answer.ask(...)` (the shared module's two engines +
  automatic fallback).

## Components / file structure

```
pf_helper/answer/              # SHARED, front-end-agnostic LLM answering layer
  __init__.py                  #   re-exports ask(), Answer, AnswerConfig
  config.py     # AnswerConfig.from_env(): engine (auto/a/b), cache on/off/TTL/max;
                # reuses pf_helper.config.Config for the index location
  base.py       # Answerer ABC; Answer dataclass (text + sources: list[(name,url)])
  engines.py    # AgentMcpAnswerer (A); ContextRagAnswerer (B)
  cache.py      # AnswerCache: persistent exact-match (normalized) cache,
                # index-version-stamped + TTL + size cap. get/put.
  service.py    # ask(question, cfg) orchestrator: cache -> A, on RateLimited ->
                # B, else QuotaExhausted. Caches successful sourced answers.
pf_helper/bot/                 # Discord front-end (optional dependency group)
  __init__.py
  config.py     # BotConfig.from_env(): DISCORD_BOT_TOKEN, guild_id?
  embeds.py     # PURE render (no Discord I/O, no network):
                #   lookup_embed(EntryDetail), search_embeds(list[SearchHit]),
                #   answer_embed(Answer); helpers truncate(), split_message()
  main.py       # discord.py client + slash commands + handlers wiring
                # Retriever + pf_helper.answer.ask; def main() entry point.
tests/
  test_answer_cache.py     # AnswerCache: normalization, hit/miss, version + TTL bust
  test_answer_service.py   # ask() cache-first + A->B fallback w/ MOCKED Agent SDK
  test_bot_embeds.py       # pure embed builders + truncation/splitting
```

`pyproject.toml`:
```toml
[project.optional-dependencies]
bot = ["discord.py", "claude-agent-sdk"]

[project.scripts]
pf-helper-bot = "pf_helper.bot.main:main"
```
(Versions pinned by `uv add --optional bot ...` during implementation; current
discord.py and claude-agent-sdk APIs confirmed via Context7 in the plan.)

## Commands & output

All commands are discord.py application (slash) commands. Optional `guild_id`
in config registers commands to one guild for instant availability during dev;
otherwise global registration.

- **`/lookup <name> [category]`** → `Retriever.get(name, category)`.
  - Hit: `lookup_embed` — title = entry name (hyperlinked to `source_url`),
    fields for category, level, traits, source book, and stats (if any), then
    the cleaned text truncated to a Discord-safe length with a "full entry on
    AON" link. `category` is an **optional free-text string** validated against
    the `Category` values — there are ~34 categories (11 Foundry + 23 AON),
    which exceeds Discord's 25-choice slash-command limit, so it cannot be a
    static choice list. An unrecognized category is treated as "no filter" (or
    an ephemeral hint listing valid values).
  - Miss: ephemeral "No exact match for '<name>'. Try `/search`."
- **`/search <query> [category]`** → `Retriever.search(query, category, limit)`
  (limit ~6). One embed listing hits: `name · category · short excerpt` with each
  name hyperlinked to its `source_url`. Empty: "No matches."
- **`/ask <question>`** → `Answerer.ask`. Replies with `answer_embed`: the
  answer text (split across messages if it exceeds Discord's 2000-char limit)
  plus a **Sources** field of AON links. A short footer notes how it was
  answered (e.g. "via search" / "fallback" / "cached").

**AON link guarantee.** Every `/ask` answer carries AON link(s) whenever any
entry was used. This is enforced deterministically by the bot, not left to the
model: the `sources` list is built by the engine from the entries it actually
retrieved (engine A: the `search`/`get_entry` tool-call results; engine B: the
top-k it fed), and `answer_embed` always renders them. The system prompt
additionally tells the agent to cite AON links inline. The only linkless case is
when retrieval returns nothing relevant, where the answer states "no matching
rules entry found" rather than inventing a link.

**Discord limits handled:** message content ≤ 2000 chars; embed description
≤ 4096; total embed ≤ 6000; ≤ 25 fields. `truncate`/`split_message` enforce
these; long entries always include the AON link for the full text. `/ask` uses a
deferred response (it may take seconds) and edits the reply when done.

## `/ask` engines

**A — `AgentMcpAnswerer` (primary).** Runs a Claude Agent SDK query with:
- `ClaudeAgentOptions` configured to attach the **`pf-helper` MCP server** as a
  tool (spawned via the existing `pf-helper` entry point over stdio), with
  `allowed_tools` limited to that server's `search`/`get_entry`.
- A tight system prompt: PF2e rules assistant; use the search/get_entry tools to
  ground every answer; cite the AON links from results; be concise for Discord.
- A small `max_turns` cap to bound tool-call loops (and thus quota use).
- Sources are collected from the tool calls the agent made (entry name +
  `source_url`).

*Implementation note:* attaching the existing MCP server is the DRY choice and
matches the approved design. A lighter alternative the plan may choose is to
register **in-process Agent SDK custom tools** that wrap the same `Retriever`
(no MCP subprocess, no second DB connection). Either satisfies "engine A"; the
plan picks one and documents it. Exact `ClaudeAgentOptions` field names, the
MCP-server attach mechanism, and `max_turns`/system-prompt options are confirmed
via Context7 against the installed `claude-agent-sdk` in the plan.

**B — `ContextRagAnswerer` (fallback).** Calls `Retriever.search(question)`
itself, formats the top-k entries (name, key stats, text, AON link) into a
single prompt, and runs **one tool-less** Agent SDK query ("answer using only
these entries; cite their AON links"). Sources = the entries it fed. Uses less
quota and is more predictable.

## Fallback ladder

`ask(question, cfg)`:
0. **Cache check.** Look up the normalized question in the `AnswerCache`. A
   valid hit (same index version, not expired) returns immediately — zero
   subscription quota, footer "cached".
1. Try **A**. On success, store the answer in the cache and return it.
2. On a **rate-limit / quota** error from the SDK, retry once with **B** (also
   cached on success).
3. If **B** also fails on quota, raise `QuotaExhausted`; the `/ask` handler
   replies: "Claude is rate-limited right now — try `/lookup` or `/search`,
   which work without it." (`/lookup`·`/search` never use the subscription.)
4. Non-quota errors (bad input, transport) → friendly error + logged detail.

Only successful answers that used at least one entry are cached; errors,
quota-exhaustion, and "no matching entry found" results are not cached.

## Answer cache

`AnswerCache` (in `cache.py`) is a persistent exact-match cache for `/ask`,
backed by its own SQLite file `<data_dir>/ask_cache.db` (gitignored, separate
from `pf2e.db` so a re-ingest doesn't wipe it; invalidation is explicit via the
index version). It is **not** semantic — no embeddings (YAGNI for v1).

- **Key normalization:** the stored key is the question lowercased, stripped,
  internal whitespace collapsed, and surrounding punctuation / a trailing `?`
  removed — so "How does flanking work?", "how does flanking work", and
  "  How does Flanking work ??" all collide. (Normalization is a pure,
  unit-tested function.)
- **Row:** `norm_question` (PK), `answer_text`, `sources_json`, `index_version`,
  `created_at`.
- **Index-version invalidation:** `index_version` is a cheap token derived from
  `pf2e.db` (mtime + size). On `get`, a row whose `index_version` differs from
  the current index is a miss (and is deleted), so a content refresh never
  serves a stale ruling.
- **TTL:** entries older than a configurable max age expire on `get` (a freshness
  backstop independent of the index version).
- **Size cap:** a configurable maximum row count; on `put` over the cap, the
  oldest entries are evicted.
- A cache **hit** skips the LLM entirely (zero quota) and is rendered with a
  "cached" footer. Caching is on by default and can be disabled via config.

The error classification (which SDK exception/type means rate-limit vs other) is
confirmed against `claude-agent-sdk` in the plan; the ladder is structured so an
unknown error degrades to the friendly deterministic-command suggestion rather
than crashing.

## Configuration (portable)

Split by layer: `BotConfig.from_env()` owns the Discord-specific vars;
`AnswerConfig.from_env()` (in `pf_helper/answer/`) owns the answering/cache vars
and is reused by any answering front-end. Both reuse `Config` for the index.

| Var | Owner | Required | Purpose |
|---|---|---|---|
| `DISCORD_BOT_TOKEN` | Bot | yes | Discord bot auth |
| `PF_HELPER_DISCORD_GUILD_ID` | Bot | no | register slash commands to one guild instantly (dev); else global |
| `PF_HELPER_DATA_DIR` | Config | no | index location (reuses `Config.from_env`); default repo `data/` |
| `CLAUDE_CODE_OAUTH_TOKEN` | Answer | for `/ask` on a host | subscription auth without interactive login; on a dev PC the logged-in CLI suffices |
| `PF_HELPER_ASK_ENGINE` | Answer | no | `auto` (A→B, default) / `a` / `b` — override for testing/quota control |
| `PF_HELPER_ASK_CACHE` | Answer | no | `1`/`0` — enable the answer cache (default on) |
| `PF_HELPER_ASK_CACHE_TTL_DAYS` | Answer | no | cache entry max age in days (default e.g. 30) |
| `PF_HELPER_ASK_CACHE_MAX` | Answer | no | max cached answers before oldest are evicted (default e.g. 500) |

Same code runs on the user's PC or an always-on host; only env differs. The bot
requires the index to be built first (`pf-helper-ingest`).

## Testing

- `test_bot_embeds.py` — pure `embeds.py` builders against fixture `EntryDetail`/
  `SearchHit` objects: correct fields, the `source_url` hyperlink, truncation,
  and message splitting at the Discord limits. No Discord, no network.
- `test_answer_service.py` — the shared `ask` orchestrator and fallback ladder
  with a **mocked Agent SDK** (a fake that returns a canned answer, or raises a
  rate-limit error to drive A→B, or raises again to drive `QuotaExhausted`).
  Verifies cache-check-first, engine selection, fallback, source extraction, and
  that successful answers are cached. **No real subscription calls.**
- `test_answer_cache.py` — `AnswerCache` against a `tmp_path` db: key
  normalization (the colliding-phrasing cases), hit/miss, index-version
  invalidation (changing the version busts), TTL expiry, and size-cap eviction.
- discord.py wiring in `bot/main.py` is a thin shell over the tested embed
  builders and `pf_helper.answer.ask`, exercised manually (see Deployment), not
  unit-tested (no live gateway in tests).

## Error handling

- **Index missing** → all commands reply: "Rules index not found — run
  `pf-helper-ingest` first."
- **`/ask` with no Claude auth** → "`/ask` needs Claude sign-in; run
  `claude setup-token` and set `CLAUDE_CODE_OAUTH_TOKEN` (or `claude login`)."
- **Quota/rate-limit** → fallback ladder above.
- **Discord length limits** → truncate/split with an AON link to the full entry.
- All exceptions are caught at the handler boundary so one bad command never
  takes the bot down; details are logged, users get a friendly message.

## Deployment

- Install with the extra: `uv sync --extra bot` (or `pip install pf-helper[bot]`).
- Build the index once: `pf-helper-ingest`.
- For `/ask`: authenticate Claude — `claude login` (dev PC) or `claude
  setup-token` and export `CLAUDE_CODE_OAUTH_TOKEN` (host).
- Set `DISCORD_BOT_TOKEN` (+ optional guild id) and run `pf-helper-bot`.
- README gains a "Discord bot" section covering both PC and always-on host.

## Security

- `DISCORD_BOT_TOKEN` and `CLAUDE_CODE_OAUTH_TOKEN` are secrets — env only, never
  committed. `data/` is already gitignored (so `ask_cache.db` and `pf2e.db` stay
  out of git); no token files are written to the repo. The bot reads tokens from
  the environment exclusively.

## Companion change: MCP tool link nudge

Independent of the bot, a tiny change to the shipped MCP server makes AON links
benefit **all** MCP clients (Claude Desktop/Code), not just `/ask`: the
`search` and `get_entry` tool docstrings in `pf_helper/server.py` gain a line
telling the model that each result includes a `source_url` (AON page link) and
to cite it in answers. The `source_url` data is already returned (from the AON
work); this only nudges clients to surface it. It touches `server.py` docstrings
only — no behavior change — and can ship as its own small commit/PR.

## Deferred / future

- `/lookup` name autocomplete (index-backed prefix suggestions).
- **Semantic / fuzzy answer caching** (embedding-based similarity) — v1's cache
  is exact-match-after-normalization only.
- Per-user / per-channel rate limiting and usage accounting.
- A metered `ANTHROPIC_API_KEY` engine option for public/large servers (where
  subscription individual-use limits don't fit).
- Approach B from the AON spec (exact AON deep links for Foundry entries) is
  independent and unaffected.
