import sys
import types

import pytest

from pf_helper.answer.base import AnswerError, EngineUnavailable
from pf_helper.answer.config import AnswerConfig
from pf_helper.models import EntryDetail, SearchHit


class FakeRetriever:
    def __init__(self, hits, details):
        self._hits, self._details = hits, details

    def search(self, query, category, limit):
        return self._hits

    def get(self, name, category):
        return self._details.get(name)


def _cfg(model="openai/gpt-4o"):
    return AnswerConfig(provider="litellm", litellm_model=model)


def _msg(content=None, tool_calls=None):
    m = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m)])


def _tool_call(cid, name, args_json):
    return types.SimpleNamespace(id=cid, function=types.SimpleNamespace(name=name, arguments=args_json))  # noqa: E501


def _install_fake_litellm(monkeypatch, completion):
    mod = types.ModuleType("litellm")
    mod.completion = completion

    class _Exc(Exception):
        pass

    exc_mod = types.ModuleType("litellm.exceptions")
    exc_mod.AuthenticationError = type("AuthenticationError", (_Exc,), {})
    exc_mod.RateLimitError = type("RateLimitError", (_Exc,), {})
    exc_mod.APIError = type("APIError", (_Exc,), {})
    exc_mod.APIConnectionError = type("APIConnectionError", (_Exc,), {})
    exc_mod.Timeout = type("Timeout", (_Exc,), {})
    mod.exceptions = exc_mod
    monkeypatch.setitem(sys.modules, "litellm", mod)
    monkeypatch.setitem(sys.modules, "litellm.exceptions", exc_mod)
    return mod


@pytest.mark.asyncio
async def test_rag_returns_text_and_sources(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    hit = SearchHit(id="c:frightened", name="Frightened", category="condition", excerpt="...",
                    source_url="https://x/Frightened")
    detail = EntryDetail(id="c:frightened", name="Frightened", category="condition",
                         text="status penalty", source_url=hit.source_url)
    calls = {}

    def fake_completion(model, messages, **kw):
        calls["model"], calls["kw"] = model, kw
        return _msg(content="Frightened is a status penalty.")

    _install_fake_litellm(monkeypatch, fake_completion)
    ans = await LiteLlmRagAnswerer(FakeRetriever([hit], {"Frightened": detail}), _cfg()).answer("x")
    assert ans.text == "Frightened is a status penalty."
    assert ans.sources == [("Frightened", "https://x/Frightened")]
    assert ans.engine == "litellm:openai/gpt-4o"
    assert calls["model"] == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_agent_runs_tool_loop(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmAgentAnswerer

    hit = SearchHit(id="s:heal", name="Heal", category="spell", excerpt="h",
                    source_url="https://x/Heal")
    r = FakeRetriever([hit], {})
    seq = [
        _msg(tool_calls=[_tool_call("c1", "search", '{"query": "heal"}')]),
        _msg(content="Heal restores HP."),
    ]

    def fake_completion(model, messages, **kw):
        return seq.pop(0)

    _install_fake_litellm(monkeypatch, fake_completion)
    ans = await LiteLlmAgentAnswerer(r, _cfg()).answer("what does heal do?")
    assert ans.text == "Heal restores HP."
    assert ("Heal", "https://x/Heal") in ans.sources
    assert ans.engine == "litellm:openai/gpt-4o"


@pytest.mark.asyncio
async def test_auth_error_maps_to_answererror(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    mod = _install_fake_litellm(monkeypatch, None)

    def boom(model, messages, **kw):
        raise mod.exceptions.AuthenticationError("no key")

    mod.completion = boom
    with pytest.raises(AnswerError) as ei:
        await LiteLlmRagAnswerer(FakeRetriever([SearchHit(id="s:h", name="H", category="spell",
            excerpt="e", source_url="u")], {"H": EntryDetail(id="s:h", name="H", category="spell",
            text="t", source_url="u")}), _cfg()).answer("x")
    assert ei.value.reason == "auth"


@pytest.mark.asyncio
async def test_ratelimit_maps_to_engine_unavailable(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    mod = _install_fake_litellm(monkeypatch, None)

    def boom(model, messages, **kw):
        raise mod.exceptions.RateLimitError("slow down")

    mod.completion = boom
    with pytest.raises(EngineUnavailable):
        await LiteLlmRagAnswerer(FakeRetriever([SearchHit(id="s:h", name="H", category="spell",
            excerpt="e", source_url="u")], {"H": EntryDetail(id="s:h", name="H", category="spell",
            text="t", source_url="u")}), _cfg()).answer("x")


@pytest.mark.asyncio
async def test_missing_model_raises(monkeypatch):
    from pf_helper.answer.litellm_engines import LiteLlmRagAnswerer

    _install_fake_litellm(monkeypatch, lambda **k: _msg(content="x"))
    with pytest.raises(AnswerError):
        await LiteLlmRagAnswerer(FakeRetriever([], {}), _cfg(model="")).answer("x")
