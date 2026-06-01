"""The ask() orchestrator: cache -> engine A -> engine B, with graceful failure."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from pf_helper.answer.base import Answer, Answerer, AnswerError, EngineUnavailable
from pf_helper.answer.cache import AnswerCache, index_version
from pf_helper.answer.config import AnswerConfig
from pf_helper.answer.querylog import log_query

_log = logging.getLogger(__name__)


def _build_engines(cfg: AnswerConfig, retriever) -> tuple[Answerer, Answerer]:
    """Return (primary, fallback) answerers for the configured provider."""
    if cfg.provider == "litellm":
        from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer, LiteLlmRagAnswerer

        return LiteLlmAgentAnswerer(retriever, cfg), LiteLlmRagAnswerer(retriever, cfg)
    from pf_helper.answer.engines import AgentMcpAnswerer, ContextRagAnswerer

    return AgentMcpAnswerer(retriever), ContextRagAnswerer(retriever)


async def ask(
    question: str,
    cfg: AnswerConfig | None = None,
    *,
    retriever=None,
    cache=None,
    engine_a: Answerer | None = None,
    engine_b: Answerer | None = None,
    fuzzy: bool = True,
    fresh: bool = False,
    query_logger: Callable[[dict], None] | None = None,
) -> Answer:
    """Answer a question. Tries cache, then engine A, then engine B.

    fuzzy=False suspends the lexical cache layer (exact cache + agent only);
    fresh=True bypasses the cache read entirely (forces a new agent answer).
    Raises AnswerError(reason='auth') if Claude is not signed in, or
    AnswerError(reason='quota') if every engine failed (e.g. rate-limited).
    Dependencies are injectable for testing; defaults are built from cfg.
    """
    cfg = cfg or AnswerConfig.from_env()

    from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

    if engine_a is None or engine_b is None:
        from pf_helper.retrieval.factory import build_retriever

        retriever = retriever or build_retriever(cfg.core)
        built_a, built_b = _build_engines(cfg, retriever)
        engine_a = engine_a or built_a
        engine_b = engine_b or built_b

    if cache is None and cfg.cache_enabled:
        cache = AnswerCache(
            cfg.core.data_dir / "ask_cache.db",
            cfg.core.db_path,
            cfg.cache_ttl_days,
            cfg.cache_max,
            cfg.cache_similarity,
        )

    if query_logger is None and cfg.query_log_enabled:
        log_path = cfg.core.data_dir / "ask_queries.jsonl"
        query_logger = lambda rec: log_query(log_path, rec)  # noqa: E731

    def _log_query(served_by: str, ans: Answer | None = None) -> None:
        if query_logger is None:
            return
        query_logger(
            {
                "ts": datetime.now(UTC).isoformat(),
                "question": question,
                "served_by": served_by,
                "match_score": ans.match_score if ans else None,
                "matched_question": ans.matched_question if ans else None,
                "threshold": cfg.cache_similarity,
                "fuzzy": fuzzy,
                "fresh": fresh,
                "index_version": index_version(cfg.core.db_path),
            }
        )

    if cache is not None and not fresh:
        hit = cache.get(question, fuzzy=fuzzy)
        if hit is not None:
            _log_query(hit.engine, hit)
            return hit

    order = {"a": [engine_a], "b": [engine_b]}.get(cfg.engine, [engine_a, engine_b])
    last_error: Exception | None = None
    for engine in order:
        try:
            answer = await engine.answer(question)
            if cache is not None and answer.sources:
                cache.put(question, answer)
            _log_query(answer.engine, answer)
            return answer
        except CLINotFoundError as exc:
            _log_query("error:auth")
            raise AnswerError(
                "auth",
                "`/ask` needs Claude sign-in: run `claude setup-token` and set "
                "`CLAUDE_CODE_OAUTH_TOKEN` (or `claude login`).",
            ) from exc
        except AnswerError as exc:  # e.g. litellm auth / missing-extra — surface as-is
            _log_query(f"error:{exc.reason}")
            raise
        except (ClaudeSDKError, EngineUnavailable) as exc:
            last_error = exc
            _log.warning("%s failed: %s", type(engine).__name__, exc)
            continue
    _log_query("error:quota")
    raise AnswerError(
        "quota",
        "Claude is unavailable right now (possibly rate-limited) — try `/lookup` "
        "or `/search`, which work without it.",
    ) from last_error
