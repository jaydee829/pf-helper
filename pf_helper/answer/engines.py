"""LLM answering engines over the Claude Agent SDK (subscription auth).

B = ContextRagAnswerer: one tool-less query over retrieved entries (cheaper).
(Engine A is added in the next task.) Both ground answers in the local index
and return AON sources.
"""

from __future__ import annotations

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from pf_helper.answer.base import Answer, Answerer
from pf_helper.retrieval.base import Retriever

_ENTRY_TEXT_CAP = 1500  # keep each entry's text bounded in the RAG prompt

_SYS_RAG = (
    "You are a Pathfinder 2e rules assistant. Answer the question using ONLY the "
    "provided entries. Cite each entry's AON link. If the entries do not cover it, "
    "say no matching rules entry was found. Be concise; this is for Discord."
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
