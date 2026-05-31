# PF_Helper — Fuzzy Answer Cache + Lookup Fallback (Design Spec)

**Date:** 2026-05-31
**Status:** Approved (brainstorming)
**Builds on:** the merged Discord bot (`pf_helper/answer/`, `pf_helper/bot/`) and
the answer cache on `main`.

## Goal

Two brittleness problems surfaced by the live `/ask` test:

1. **The answer cache only matches near-verbatim questions.** "How does flanking
   work?", "When am I flanking again?", and "What is flanking?" each triggered a
   fresh agent call even though they want the same answer. Only an exact repeat
   hit the cache. We want semantically-equivalent paraphrases to reuse a cached
   answer — saving quota/latency and giving consistent wording.
2. **`/lookup` dead-ends on a near-miss name.** `/lookup Grabbing` returned
   "No exact match for 'Grabbing'. Try `/search`." even though **Grab** and
   **Grapple** exist. We want a close-name suggestion plus inline search results
   on a miss.

Both are the same root cause — exact matching is too brittle — in two places.

## Approach (chosen during brainstorming)

- **Cache:** lexical (keyword-overlap) similarity, **not** embeddings. The PF2e
  domain is keyword-driven (people say "flanking", "grapple"), so shared-keyword
  matching catches realistic paraphrases with zero new dependencies and zero
  quota. Embeddings (a local model or an embeddings API) are deferred.
- **Lookup:** on an exact-name miss, run a search, surface stdlib-`difflib`
  "Did you mean" suggestions (a "very close" guard), and list the closest hits
  inline so the user never retypes.

## Non-goals (v1)

- No embeddings / semantic similarity (deferred — see "Deferred / future").
- No change to the MCP `get_entry` tool or the answering engines' own search
  behavior (Desktop's agent already recovers from a missed `get_entry` by
  searching). Mirroring the lookup fallback there is deferred.
- No offline tuning/eval harness in this spec — it gets its own future spec
  (`2026-05-31-cache-tuning-harness-future.md`). This feature ships the
  **query logging** that harness will consume.
- No fuzzy matching in `/search` (it is already a full-text search).

---

## Component 1 — Lexical similarity in the answer cache

### Tokenization (`pf_helper/answer/cache.py`)

`_content_tokens(question) -> frozenset[str]`:

1. lowercase, split on runs of non-alphanumeric characters
2. drop **stopwords** — both English function words **and** rules-question
   framing words (the main tuning lever)
3. apply a crude stemmer `_stem` (consistency between two questions matters, not
   linguistic correctness)
4. drop empties; return the set

`_STOPWORDS` (initial list, tunable):

```
# function words
a am an and are as at be by can could do does did for from how i if in into is
it me my of on or should that the their them then there this to use what when
where which who why will with would you your
# rules-question framing words
again happen happens mean means rule rules work works explain tell about
```

`_stem(w)` — minimal suffix stripping, applied to the first matching rule only,
with length guards so short tokens are left alone:

```python
def _stem(w: str) -> str:
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w
```

`_jaccard(a, b) = len(a & b) / len(a | b)` (0.0 when the union is empty).

**Worked examples** (with the stopword list above):

```
"how does flanking work"          -> {flank}
"when am i flanking again"        -> {flank}
"what is flanking"                -> {flank}
"what are the rules for flanking" -> {flank}        all = 1.0 -> HIT
"can tiny creatures flank"        -> {tiny, creature, flank}
   jaccard vs {flank} = 1/3 = 0.33  -> MISS (distinct question, answered fresh)
```

These reductions (and the negative case) are **pinned as tests** — the stopword
list and stemmer must keep them holding.

### `AnswerCache` changes

Schema gains a `tokens` column (space-joined sorted content tokens, computed once
at `put`):

```
answers(norm TEXT PRIMARY KEY, text TEXT, sources_json TEXT,
        index_version TEXT, created_at REAL, tokens TEXT NOT NULL)
```

**Migration:** on `__init__`, if an existing `answers` table lacks the `tokens`
column (checked via `PRAGMA table_info(answers)`), `DROP TABLE answers` and
recreate. The cache is disposable, so a one-time clear is acceptable and simpler
than a backfill.

**Constructor:** add `similarity: float = 0.5` (the Jaccard threshold; `0`
disables the fuzzy pass entirely).

**`get(question, *, fuzzy: bool = True) -> Answer | None`:**

1. **Exact fast path** — current behavior: look up by `norm`, apply
   index-version + TTL staleness check, return `Answer(..., engine="cache")` on a
   live hit (delete + miss if stale/expired).
2. If `not fuzzy` or `self.similarity <= 0`: return `None`.
3. Compute `qtokens = _content_tokens(question)`. If empty, return `None` (an
   all-stopwords question must not match everything).
4. Scan only **live** rows (`index_version = current AND created_at > now - ttl`).
   Compute `_jaccard(qtokens, tokens_set)` for each.
5. Pick the best score `>= self.similarity`; tie-break by score, then newest
   `created_at`.
6. On a hit, return `Answer(text, sources, engine="cache", match_score=best,
   matched_question=row_norm)`. Otherwise `None`.

Performance is a non-issue: the cache is capped at `cache_max` (≤500) rows and
`tokens` is precomputed.

**`put`** also writes `tokens = " ".join(sorted(_content_tokens(question)))`.
Size-cap eviction is unchanged.

### `Answer` telemetry fields (`pf_helper/answer/base.py`)

Add two optional fields (defaults keep all existing call sites valid):

```python
match_score: float | None = None       # fuzzy-cache similarity, when applicable
matched_question: str | None = None     # the cached (normalized) question matched
```

### Footer (`pf_helper/bot/embeds.py`)

`answer_embed` footer becomes informative for fuzzy hits:

- exact / engine answers: `answered via cache` / `answered via agent` (unchanged)
- fuzzy cache hit: `answered via cache · similar question (0.83)`

### Per-`/ask` overrides

`ask(question, cfg, *, retriever=..., cache=..., engine_a=..., engine_b=...,
fuzzy: bool = True, fresh: bool = False)`:

- `fresh=True` → skip the cache read entirely (still write the new answer to the
  cache). Forces a brand-new agent answer.
- `fuzzy=False` → call `cache.get(question, fuzzy=False)` (exact cache + engine
  only; a reworded question goes to the agent).
- Both default to today's behavior (`fuzzy=True, fresh=False`).

`AnswerCache` is constructed in `ask()` with `cfg.cache_similarity`.

### Config (`pf_helper/answer/config.py`)

Add to `AnswerConfig` (frozen dataclass) + `from_env`:

```python
cache_similarity: float = 0.5     # PF_HELPER_ASK_CACHE_SIMILARITY
query_log_enabled: bool = True    # PF_HELPER_ASK_QUERY_LOG ("0" disables)
```

The query-log path is derived: `core.data_dir / "ask_queries.jsonl"` (not a
separate env var).

### Bot slash-command options (`pf_helper/bot/main.py`)

`/ask` gains two optional booleans:

```python
@app_commands.describe(
    question="Your rules question",
    fuzzy="Reuse a cached answer to a similar question (default: on)",
    fresh="Ignore the cache and ask Claude fresh (default: off)",
)
async def ask_cmd(interaction, question: str, fuzzy: bool = True, fresh: bool = False):
    ...
    answer = await ask(question, answer_cfg, fuzzy=fuzzy, fresh=fresh)
```

### Query logging (`pf_helper/answer/querylog.py`, new)

`log_query(path, record: dict)` appends one JSON object per line. Called from
`ask()` after the outcome is known (success or `AnswerError`). **Must never raise
into `/ask`** — wrap in `try/except` and log a warning on failure.

Record fields:

```json
{"ts": "2026-05-31T12:00:00Z", "question": "...", "served_by": "cache",
 "match_score": 0.83, "matched_question": "flank", "threshold": 0.5,
 "fuzzy": true, "fresh": false, "index_version": "1717000000-123456"}
```

`served_by` is the answer's `engine` for successes (`cache`/`agent`/`rag`) or
`error:auth` / `error:quota` for `AnswerError`. `match_score`/`matched_question`
are `null` unless it was a fuzzy hit. Logging is gated by `query_log_enabled`.
(Privacy note: these are the operator's own questions on their own bot; the log
lives under the gitignored `data/`.)

---

## Component 2 — `/lookup` fallback

### Flow (`pf_helper/bot/main.py`)

```
/lookup <name> [category]
  detail = r.get(name, category)
  if detail:  -> lookup_embed(detail)            (unchanged)
  else:
     hits = r.search(name, category, limit=6)
     suggestions = _close_names(name, [h.name for h in hits])   # difflib
     -> lookup_miss_embed(name, suggestions, hits)
```

`_close_names(query, names, *, cutoff=_SUGGEST_CUTOFF, n=3) -> list[str]` (pure,
module-level, testable): lowercase `query` and each name, use
`difflib.get_close_matches(qlower, lowered, n=n, cutoff=cutoff)`, map the matches
back to their original-case names (preserving order). `_SUGGEST_CUTOFF = 0.6`
(tunable constant; the "very close" guard).

### Embed (`pf_helper/bot/embeds.py`)

`lookup_miss_embed(name, suggestions: list[str], hits: list[SearchHit]) ->
discord.Embed` (pure):

- title: `No exact match for '{name}'`
- if `suggestions`: a line `Did you mean: **Grab**, **Grapple**?`
- if `hits`: list the closest matches (reuse the `search_embeds` line format —
  `- [name](url) · category — excerpt`)
- if no `hits` at all: description falls back to `Nothing found. Try `/search``

```
/lookup Grabbing
  No exact match for 'Grabbing'.
  Did you mean: Grab?
  Closest matches:
  - Grab · action — ...
  - Grapple · action — ...
```

---

## Data flow

```
/ask q, fuzzy, fresh
  └─ ask(q, cfg, fuzzy, fresh)
       fresh? ── yes ─────────────────┐ (skip cache read)
       no → cache.get(q, fuzzy)        │
              exact hit? → return ─────┤
              fuzzy hit (≥thr)? → return
              miss ──────────────────► engine A → (B fallback)
                                         │
       cache.put(q, answer) if sources ◄─┘
       log_query(record)  (success or AnswerError)

/lookup name
  r.get(name) ── hit → lookup_embed
            └─ miss → r.search(name) → _close_names → lookup_miss_embed
```

## Error handling

- Query logging is best-effort: a write failure logs a warning, never breaks
  `/ask` (mirrors the existing "never let one command crash the bot" guard).
- Cache fuzzy pass is pure in-memory math over local rows; no new failure modes.
- Schema migration drops/recreates only when the `tokens` column is absent.
- `fresh`/`fuzzy` defaults preserve existing behavior for callers that omit them
  (e.g. tests calling `ask(q, cfg)`).

## Testing

**Cache (`tests/test_cache.py`, extend):**
- `_content_tokens` — stopwords + framing words dropped; stemming
  (`flanking→flank`, `creatures→creature`).
- the flanking trio → fuzzy hits (score ≥ threshold); "can tiny creatures
  flank?" → miss against a cached "what is flanking?".
- `fuzzy=False` → only the exact match returns; a paraphrase returns `None`.
- `similarity=0` → fuzzy pass disabled.
- stale (`index_version` mismatch) / expired rows excluded from the fuzzy pass.
- `put` populates `tokens`; migration recreates a `tokens`-less table.
- fuzzy hit sets `match_score` + `matched_question`.

**Service (`tests/test_service.py`, extend):**
- `fresh=True` → cache read skipped even when an exact entry exists; engine
  called; answer still written to cache.
- `fuzzy=False` threaded into `cache.get`.
- `log_query` invoked with the right `served_by` for cache / agent / error
  paths (inject a fake logger / temp path).

**Query log (`tests/test_querylog.py`, new):**
- appends valid JSONL; a write error is swallowed (no raise).

**Lookup (`tests/test_bot.py` / `tests/test_embeds.py`, extend):**
- `_close_names("Grabbing", ["Grab", "Grapple", "Trip"])` → `["Grab"]` (Grapple
  below cutoff); empty when nothing is close.
- `lookup_miss_embed` renders suggestions + closest matches; no-hits → fallback
  text.

**Gates:** `uv run --no-sync pytest -q` (full suite green), `uv run --no-sync
ruff check .` clean.

## File structure

```
pf_helper/answer/
  cache.py      # MODIFY: tokens column + migration; _content_tokens/_stem/_jaccard;
                #         get(question, *, fuzzy); similarity threshold; put writes tokens
  base.py       # MODIFY: Answer gains match_score, matched_question (optional)
  config.py     # MODIFY: cache_similarity, query_log_enabled (+ from_env)
  service.py    # MODIFY: ask(..., fuzzy, fresh); construct cache w/ similarity; log_query
  querylog.py   # NEW: log_query(path, record) -> append JSONL, best-effort
pf_helper/bot/
  main.py       # MODIFY: /ask fuzzy+fresh options; /lookup miss fallback; _close_names
  embeds.py     # MODIFY: answer_embed fuzzy footer; lookup_miss_embed (new)
tests/
  test_cache.py, test_service.py, test_embeds.py, test_bot.py  # MODIFY/extend
  test_querylog.py                                             # NEW
```

## Deferred / future

- **Cache tuning / eval-sweep harness** — its own spec
  (`2026-05-31-cache-tuning-harness-future.md`): curated + LLM-generated
  paraphrase groups and negative pairs, sweep `cache_similarity` and stopword
  variants, report precision/recall. Consumes the query log this feature emits.
  MLflow only if it grows into repeated tracked experiment runs; start with a
  plain analysis script.
- **Semantic (embedding) cache** — local sentence-transformers or an embeddings
  API, for paraphrases with no shared keywords. Heavier; not needed yet.
- **`get_entry` "did you mean" parity** in the MCP tool / engines.
