# PF_Helper — Cache Tuning / Eval-Sweep Harness (FUTURE spec stub)

**Date logged:** 2026-05-31
**Status:** Future — NOT planned/scheduled. Placeholder so the idea isn't lost.
**Depends on:** the query logging shipped in
`2026-05-31-fuzzy-cache-and-lookup-fallback-design.md`.

## Idea

An **offline** tool to tune the fuzzy answer cache (the `cache_similarity`
threshold and the `_STOPWORDS` list) with data instead of guesswork.

Two data sources:

1. **Curated eval set** — paraphrase *groups* that SHOULD match (e.g. the
   flanking trio) and *negative pairs* that should NOT (e.g. "can tiny creatures
   flank?" vs "what is flanking?"). Seed by hand from real rules questions;
   optionally LLM-augment offline (one-time quota, not in the hot path).
2. **Real query log** — `data/ask_queries.jsonl` emitted by `/ask`, to see how
   the live threshold/stopwords behave on actual usage.

## Sketch (to be designed properly when picked up)

- A script that, given the eval set, **sweeps** `cache_similarity` values and
  stopword variants and reports **precision/recall** (or F1) per config — i.e.
  how many should-match pairs hit and how many should-not pairs wrongly hit.
- Reuse `pf_helper.answer.cache._content_tokens` / `_jaccard` so the harness
  scores exactly what production uses.
- Output a small table; pick the threshold/stopword set that maximizes recall on
  paraphrases while keeping false matches near zero.
- **MLflow** only if this grows into repeated, tracked experiment runs worth
  comparing over time; otherwise a plain analysis script + a JSON/CSV report is
  enough to start.

## Why deferred

The core fix ships with sensible defaults (threshold `0.5`, a starter stopword
list) and its examples pinned as tests. This harness is a separate, standalone
tool for *principled* tuning once there's real usage data — it doesn't block the
behavior change.
