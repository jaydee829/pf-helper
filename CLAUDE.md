# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This is a **greenfield project** — no code, build system, or tests exist yet. The only content is `background/Inspiration.md`, a design discussion. When you scaffold the project, update this file with real build/lint/test commands.

## What this project is

**PF_Helper** is a Pathfinder Second Edition (PF2e) assistant. The goal is to ingest PF2e rules content (spells, feats, creatures, equipment, ancestries, classes, backgrounds, conditions, traits, skills, actions, hazards, archetypes, rules) and make it **accessible to an LLM** for answering rules questions.

The source of truth for PF2e content is the **Archives of Nethys (AON, aonprd.com)**, the official PF2e SRD.

## Intended architecture

`background/Inspiration.md` records the chosen direction. Read it before designing data ingestion. Summary of the plan:

**Data acquisition** — three options, in recommended order:
1. **FoundryVTT PF2e compendium** (`foundryvtt/pf2e` on GitHub) — preferred starting point. Content ships as structured JSON in `packs/` (LevelDB `.db` files); the repo includes scripts to unpack them. No scraping, no ToS/rate-limit concerns.
2. **AON Elasticsearch** (`https://elasticsearch.aonprd.com`, confirm endpoint via DevTools → Network → XHR) — query the `aon` index per `category` with `size: 10000` to pull all entries as JSON. Use to fill gaps from option 1.
3. **HTML scraper** (`httpx` + `BeautifulSoup`, async, polite rate limiting) — only if rendered narrative HTML is needed. AON pages are `.aspx` with query-string IDs.

**LLM access** — two patterns:
- **RAG**: chunk each entry (name + category + full text), embed (sentence-transformers or Anthropic embeddings), store in a vector DB (ChromaDB / Qdrant / pgvector), retrieve top-k at query time.
- **Direct tool access**: flatten JSON to per-entry markdown and expose a search tool to the LLM. Simpler; works well given PF2e's bounded domain.

The inspiration doc recommends: **start with the FoundryVTT compendium, supplement with ES queries, build a simple ChromaDB RAG pipeline in Python (~200–300 lines).** This implies a Python project — but no language choice is committed in code yet, so confirm before scaffolding.

## Working notes

- Library/framework work (elasticsearch client, ChromaDB, httpx, sentence-transformers, etc.): per the user's global rules, fetch current docs via Context7 before generating setup or API code.
