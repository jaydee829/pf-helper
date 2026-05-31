import pytest
from claude_agent_sdk import ClaudeSDKError, CLINotFoundError

from pf_helper.answer import Answer, AnswerConfig, AnswerError
from pf_helper.answer.service import ask


def test_answer_defaults():
    a = Answer(text="hi")
    assert a.sources == []
    assert a.engine == ""


def test_answer_config_from_env(monkeypatch):
    monkeypatch.setenv("PF_HELPER_ASK_ENGINE", "B")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE", "0")
    monkeypatch.setenv("PF_HELPER_ASK_CACHE_TTL_DAYS", "7")
    cfg = AnswerConfig.from_env()
    assert cfg.engine == "b"  # lower-cased
    assert cfg.cache_enabled is False
    assert cfg.cache_ttl_days == 7
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

    def get(self, q):
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
