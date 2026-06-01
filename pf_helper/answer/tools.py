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
