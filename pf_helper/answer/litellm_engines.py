"""LLM answering engines over LiteLLM (any provider). Optional `litellm` extra.

`litellm` is imported lazily inside methods so this module imports without the
extra installed. Provider API keys come from the provider's standard env vars.
"""

from __future__ import annotations

import json

from pf_helper.answer.base import (
    Answer,
    Answerer,
    AnswerError,
    EngineUnavailable,
)
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
    except ImportError as exc:  # ModuleNotFoundError or a partial/corrupt install
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
    except (
        lite_exc.RateLimitError,
        lite_exc.APIError,
        lite_exc.APIConnectionError,
        lite_exc.Timeout,
    ) as exc:
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
            f"## {d.name} ({d.category}) — {d.source_url}\n{d.text[:_ENTRY_TEXT_CAP]}"
            for d in details
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
            return search_payload(
                self._retriever, sources, args.get("query", ""), args.get("category")
            )
        if name == "get_entry":
            return get_entry_payload(
                self._retriever, sources, args.get("name", ""), args.get("category")
            )
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
            messages.append(msg)
            for tc in tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                payload = self._run_tool(tc.function.name, args, sources)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "name": tc.function.name,
                     "content": json.dumps(payload)}
                )
        if not text:
            # Exhausted max_turns still calling tools, or an empty final answer —
            # treat as a transient miss so the service falls back to the RAG engine.
            raise EngineUnavailable("LiteLLM agent produced no answer (tool-loop exhausted).")
        return Answer(text=text, sources=list(sources.items()), engine=engine)
