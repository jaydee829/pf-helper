"""LLM answering engines over the Claude Agent SDK (subscription auth).

A = AgentMcpAnswerer: agent searches via in-process tools wrapping the Retriever.
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


class AgentMcpAnswerer(Answerer):
    """Engine A: the agent searches via in-process tools wrapping the Retriever."""

    def __init__(self, retriever: Retriever, max_turns: int = 6):
        self._retriever = retriever
        self._max_turns = max_turns

    def _build_tools(self):
        """Return (search_callable, get_callable, sources_dict).

        The callables are plain async functions (directly testable); the same
        logic is registered as SDK tools in answer(). `sources` is populated as
        the callables run, so Answer.sources reflects what the agent looked up.
        """
        retriever = self._retriever
        sources: dict[str, str] = {}

        async def do_search(args):
            hits = retriever.search(args["query"], category=args.get("category") or None, limit=8)
            for h in hits:
                sources[h.name] = h.source_url
            payload = [
                {
                    "name": h.name,
                    "category": h.category,
                    "source_url": h.source_url,
                    "excerpt": h.excerpt,
                }
                for h in hits
            ]
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}

        async def do_get(args):
            d = retriever.get(args["name"], category=args.get("category") or None)
            if d is None:
                return {"content": [{"type": "text", "text": "null"}]}
            sources[d.name] = d.source_url
            payload = {
                "name": d.name,
                "category": d.category,
                "source_url": d.source_url,
                "text": d.text,
            }
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}

        return do_search, do_get, sources

    async def answer(self, question: str) -> Answer:
        do_search, do_get, sources = self._build_tools()
        search_tool = tool(
            "search",
            "Search PF2e rules; returns name/category/excerpt/source_url.",
            {"query": str, "category": str},
        )(do_search)
        get_tool = tool(
            "get_entry",
            "Get the full PF2e entry by exact name.",
            {"name": str, "category": str},
        )(do_get)
        server = create_sdk_mcp_server(name="pf2e", tools=[search_tool, get_tool])
        options = ClaudeAgentOptions(
            system_prompt=_SYS_AGENT,
            max_turns=self._max_turns,
            mcp_servers={"pf2e": server},
            allowed_tools=["mcp__pf2e__search", "mcp__pf2e__get_entry"],
        )
        text = await _collect_text(question, options)
        return Answer(text=text, sources=list(sources.items()), engine="agent")
