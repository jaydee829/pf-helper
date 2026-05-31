"""The ask() orchestrator: cache -> engine A -> engine B, with graceful failure."""

from __future__ import annotations

import logging

from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

from pf_helper.answer.base import Answer, Answerer, AnswerError
from pf_helper.answer.cache import AnswerCache
from pf_helper.answer.config import AnswerConfig

_log = logging.getLogger(__name__)


async def ask(
    question: str,
    cfg: AnswerConfig | None = None,
    *,
    retriever=None,
    cache=None,
    engine_a: Answerer | None = None,
    engine_b: Answerer | None = None,
) -> Answer:
    """Answer a question. Tries cache, then engine A, then engine B.

    Raises AnswerError(reason='auth') if Claude is not signed in, or
    AnswerError(reason='quota') if every engine failed (e.g. rate-limited).
    Dependencies are injectable for testing; defaults are built from cfg.
    """
    cfg = cfg or AnswerConfig.from_env()

    if engine_a is None or engine_b is None:
        from pf_helper.answer.engines import AgentMcpAnswerer, ContextRagAnswerer
        from pf_helper.retrieval.factory import build_retriever

        retriever = retriever or build_retriever(cfg.core)
        engine_a = engine_a or AgentMcpAnswerer(retriever)
        engine_b = engine_b or ContextRagAnswerer(retriever)

    if cache is None and cfg.cache_enabled:
        cache = AnswerCache(
            cfg.core.data_dir / "ask_cache.db",
            cfg.core.db_path,
            cfg.cache_ttl_days,
            cfg.cache_max,
        )

    if cache is not None:
        hit = cache.get(question)
        if hit is not None:
            return hit

    order = {"a": [engine_a], "b": [engine_b]}.get(cfg.engine, [engine_a, engine_b])
    last_error: Exception | None = None
    for engine in order:
        try:
            answer = await engine.answer(question)
            if cache is not None and answer.sources:
                cache.put(question, answer)
            return answer
        except CLINotFoundError as exc:
            raise AnswerError(
                "auth",
                "`/ask` needs Claude sign-in: run `claude setup-token` and set "
                "`CLAUDE_CODE_OAUTH_TOKEN` (or `claude login`).",
            ) from exc
        except ClaudeSDKError as exc:
            last_error = exc
            _log.warning("%s failed: %s", type(engine).__name__, exc)
            continue
    raise AnswerError(
        "quota",
        "Claude is unavailable right now (possibly rate-limited) — try `/lookup` "
        "or `/search`, which work without it.",
    ) from last_error
