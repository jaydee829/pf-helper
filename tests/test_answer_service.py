import pytest
from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

import pf_helper.answer.config as cfgmod
from pf_helper.answer import Answer, AnswerConfig, AnswerError
from pf_helper.answer.service import ask


@pytest.fixture(autouse=True)
def _no_query_log(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_QUERY_LOG", "0")


def test_answer_defaults():
    a = Answer(text="hi")
    assert a.sources == []
    assert a.engine == ""
    assert a.match_score is None
    assert a.matched_question is None


def test_answer_config_from_env(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_ENGINE", "B")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE", "0")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE_TTL_DAYS", "7")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE_SIMILARITY", "0.7")
    monkeypatch.setenv("PF_HELPER_ASK_QUERY_LOG", "0")
    cfg = AnswerConfig.from_env()
    assert cfg.engine == "b"  # lower-cased
    assert cfg.cache_enabled is False
    assert cfg.cache_ttl_days == 7
    assert cfg.cache_similarity == 0.7
    assert cfg.query_log_enabled is False
    assert cfg.core.db_path.name == "pf2e.db"


def test_answer_error_reason():
    e = AnswerError("auth", "sign in")
    assert e.reason == "auth"


class FakeEngine:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = 0

    async def answer(self, question):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


class FakeCache:
    def __init__(self, hit=None):
        self.hit = hit
        self.put_calls = []
        self.got_fuzzy = None

    def get(self, q, *, fuzzy=True):
        self.got_fuzzy = fuzzy
        return self.hit

    def put(self, q, a):
        self.put_calls.append((q, a))


@pytest.mark.asyncio
async def test_cache_hit_skips_engines():
    a = FakeEngine(Answer("A-ans", [("n", "u")], "agent"))
    cache = FakeCache(hit=Answer("cached", [("n", "u")], "cache"))
    out = await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine())
    assert out.text == "cached"
    assert a.calls == 0


@pytest.mark.asyncio
async def test_a_success_is_cached():
    a = FakeEngine(Answer("A-ans", [("Flank", "https://x")], "agent"))
    cache = FakeCache()
    out = await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine())
    assert out.text == "A-ans"
    assert cache.put_calls and cache.put_calls[0][1].text == "A-ans"


@pytest.mark.asyncio
async def test_falls_back_to_b_on_error():
    a = FakeEngine(exc=ClaudeSDKError("rate limit"))
    b = FakeEngine(Answer("B-ans", [("n", "u")], "rag"))
    out = await ask("q", cache=FakeCache(), engine_a=a, engine_b=b)
    assert out.text == "B-ans"
    assert a.calls == 1 and b.calls == 1


@pytest.mark.asyncio
async def test_both_fail_raises_quota():
    a = FakeEngine(exc=ClaudeSDKError("x"))
    b = FakeEngine(exc=ClaudeSDKError("y"))
    with pytest.raises(AnswerError) as ei:
        await ask("q", cache=FakeCache(), engine_a=a, engine_b=b)
    assert ei.value.reason == "quota"


@pytest.mark.asyncio
async def test_auth_error_raises_auth():
    a = FakeEngine(exc=CLINotFoundError("not installed"))
    with pytest.raises(AnswerError) as ei:
        await ask("q", cache=FakeCache(), engine_a=a, engine_b=FakeEngine())
    assert ei.value.reason == "auth"


@pytest.mark.asyncio
async def test_unsourced_answer_not_cached():
    a = FakeEngine(Answer("No matching rules entry found.", [], "agent"))
    cache = FakeCache()
    await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine())
    assert cache.put_calls == []


@pytest.mark.asyncio
async def test_fresh_bypasses_cache_read():
    a = FakeEngine(Answer("fresh-ans", [("n", "u")], "agent"))
    cache = FakeCache(hit=Answer("cached", [("n", "u")], "cache"))
    out = await ask("q", cache=cache, engine_a=a, engine_b=FakeEngine(), fresh=True)
    assert out.text == "fresh-ans"  # cached hit ignored
    assert a.calls == 1
    assert cache.put_calls and cache.put_calls[0][1].text == "fresh-ans"  # still written


@pytest.mark.asyncio
async def test_fuzzy_flag_threaded_to_cache():
    cache = FakeCache(hit=None)
    await ask("q", cache=cache, engine_a=FakeEngine(Answer("x", [("n", "u")], "agent")),
              engine_b=FakeEngine(), fuzzy=False)
    assert cache.got_fuzzy is False


@pytest.mark.asyncio
async def test_query_logger_records_served_by():
    recs = []
    a = FakeEngine(Answer("A-ans", [("n", "u")], "agent"))
    await ask("q", cache=FakeCache(), engine_a=a, engine_b=FakeEngine(), query_logger=recs.append)
    assert recs and recs[0]["served_by"] == "agent"
    assert recs[0]["fuzzy"] is True and recs[0]["fresh"] is False


@pytest.mark.asyncio
async def test_query_logger_records_cache_and_auth():
    recs = []
    cache = FakeCache(hit=Answer("cached", [("n", "u")], "cache"))
    await ask("q", cache=cache, engine_a=FakeEngine(), engine_b=FakeEngine(),
              query_logger=recs.append)
    assert recs[-1]["served_by"] == "cache"
    recs.clear()
    a = FakeEngine(exc=CLINotFoundError("nope"))
    with pytest.raises(AnswerError):
        await ask("q", cache=FakeCache(), engine_a=a, engine_b=FakeEngine(),
                  query_logger=recs.append)
    assert recs[-1]["served_by"] == "error:auth"


@pytest.mark.asyncio
async def test_engine_fallback_logs_once_not_per_engine():
    # engine A fails with ClaudeSDKError (continue, no log), B succeeds -> exactly one log
    recs = []
    a = FakeEngine(exc=ClaudeSDKError("rate limit"))
    b = FakeEngine(Answer("B-ans", [("n", "u")], "rag"))
    out = await ask("q", cache=FakeCache(), engine_a=a, engine_b=b, query_logger=recs.append)
    assert out.text == "B-ans"
    assert len(recs) == 1 and recs[0]["served_by"] == "rag"


def test_answer_config_provider_default(monkeypatch):
    monkeypatch.delenv("PF_HELPER_ASK_PROVIDER", raising=False)
    monkeypatch.setattr(cfgmod.userconfig, "load_file_config", dict)
    cfg = cfgmod.AnswerConfig.from_env()
    assert cfg.provider == "claude-sdk"
    assert cfg.litellm_model == "" and cfg.litellm_api_base is None


def test_answer_config_provider_env_wins(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_PROVIDER", "LiteLLM")
    monkeypatch.setenv("PF_HELPER_ASK_LITELLM_MODEL", "openai/gpt-4o")
    monkeypatch.setattr(
        cfgmod.userconfig, "load_file_config",
        lambda: {"ask": {"provider": "claude-sdk", "litellm": {"model": "x"}}},
    )
    cfg = cfgmod.AnswerConfig.from_env()
    assert cfg.provider == "litellm"  # lower-cased, env wins
    assert cfg.litellm_model == "openai/gpt-4o"


def test_answer_config_provider_from_file(monkeypatch):
    monkeypatch.delenv("PF_HELPER_ASK_PROVIDER", raising=False)
    monkeypatch.delenv("PF_HELPER_ASK_LITELLM_MODEL", raising=False)
    monkeypatch.delenv("PF_HELPER_ASK_LITELLM_API_BASE", raising=False)
    monkeypatch.setattr(
        cfgmod.userconfig, "load_file_config",
        lambda: {"ask": {"provider": "litellm", "litellm": {"model": "ollama/llama3.1", "api_base": "http://x/v1"}}},
    )
    cfg = cfgmod.AnswerConfig.from_env()
    assert cfg.provider == "litellm"
    assert cfg.litellm_model == "ollama/llama3.1"
    assert cfg.litellm_api_base == "http://x/v1"


def test_build_engines_claude_sdk():
    from pf_helper.answer import service
    from pf_helper.answer.engines import AgentMcpAnswerer, ContextRagAnswerer

    a, b = service._build_engines(AnswerConfig(provider="claude-sdk"), retriever=object())
    assert isinstance(a, AgentMcpAnswerer) and isinstance(b, ContextRagAnswerer)


def test_build_engines_litellm():
    from pf_helper.answer import service
    from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer, LiteLlmRagAnswerer

    a, b = service._build_engines(
        AnswerConfig(provider="litellm", litellm_model="openai/x"), retriever=object()
    )
    assert isinstance(a, LiteLlmAgentAnswerer) and isinstance(b, LiteLlmRagAnswerer)


@pytest.mark.asyncio
async def test_engine_unavailable_triggers_fallback():
    from pf_helper.answer.base import EngineUnavailable

    a = FakeEngine(exc=EngineUnavailable("rate limited"))
    b = FakeEngine(Answer("B-ans", [("n", "u")], "litellm:x"))
    out = await ask("q", cache=FakeCache(), engine_a=a, engine_b=b)
    assert out.text == "B-ans" and a.calls == 1 and b.calls == 1
