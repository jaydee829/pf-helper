"""Opt-in live LiteLLM smoke test. Skipped unless PF_HELPER_TEST_LITELLM_MODEL is set.

Run it deliberately:  PF_HELPER_TEST_LITELLM_MODEL=ollama/llama3.1  uv run pytest -m live
(local Ollama = free/no key; or set a hosted model + its API-key env var).
"""

import os

import pytest

pytestmark = pytest.mark.live

_MODEL = os.environ.get("PF_HELPER_TEST_LITELLM_MODEL")


@pytest.mark.skipif(not _MODEL, reason="set PF_HELPER_TEST_LITELLM_MODEL to run the live test")
@pytest.mark.asyncio
async def test_live_litellm_rag_and_agent():
    pytest.importorskip("litellm")  # skip if the optional extra isn't installed
    from pf_helper.answer.config import AnswerConfig
    from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer, LiteLlmRagAnswerer
    from pf_helper.retrieval.factory import build_retriever

    cfg = AnswerConfig(
        provider="litellm",
        litellm_model=_MODEL,
        litellm_api_base=os.environ.get("PF_HELPER_TEST_LITELLM_API_BASE"),
    )
    if not cfg.core.db_path.exists():
        pytest.skip("no rules index built (run `pf-helper ingest`)")
    retriever = build_retriever(cfg.core)

    rag = await LiteLlmRagAnswerer(retriever, cfg).answer("How does flanking work?")
    assert rag.text.strip()
    assert rag.sources

    agent = await LiteLlmAgentAnswerer(retriever, cfg).answer("How does flanking work?")
    assert agent.text.strip()
    assert agent.sources  # >=1 source collected -> a tool was actually called
