import pytest

from pf_helper.answer.engines import ContextRagAnswerer
from pf_helper.models import EntryDetail, SearchHit


class FakeRetriever:
    def __init__(self, hits, details):
        self._hits = hits
        self._details = details
        self.searched = None

    def search(self, query, category, limit):
        self.searched = (query, category, limit)
        return self._hits

    def get(self, name, category):
        return self._details.get(name)


def _patch_query(monkeypatch, captured, reply="ANSWER"):
    """Patch claude_agent_sdk.query (imported into engines) with a fake async gen."""
    from claude_agent_sdk import AssistantMessage, TextBlock

    async def fake_query(prompt, options=None):
        captured["prompt"] = prompt
        captured["options"] = options
        yield AssistantMessage(content=[TextBlock(text=reply)], model="claude-sonnet-4-6")

    monkeypatch.setattr("pf_helper.answer.engines.query", fake_query)


@pytest.mark.asyncio
async def test_rag_uses_retriever_and_returns_sources(monkeypatch):
    hit = SearchHit(
        id="condition:frightened",
        name="Frightened",
        category="condition",
        excerpt="...",
        source_url="https://2e.aonprd.com/Conditions.aspx?ID=1",
    )
    detail = EntryDetail(
        id="condition:frightened",
        name="Frightened",
        category="condition",
        text="You take a status penalty...",
        source_url=hit.source_url,
    )
    r = FakeRetriever([hit], {"Frightened": detail})
    captured = {}
    _patch_query(monkeypatch, captured, reply="Frightened gives a status penalty.")

    answer = await ContextRagAnswerer(r).answer("what is frightened")

    assert r.searched[0] == "what is frightened"
    assert answer.text == "Frightened gives a status penalty."
    assert answer.sources == [("Frightened", "https://2e.aonprd.com/Conditions.aspx?ID=1")]
    assert answer.engine == "rag"
    assert "You take a status penalty" in captured["prompt"]  # full entry text fed as context


@pytest.mark.asyncio
async def test_rag_no_hits_returns_no_match(monkeypatch):
    r = FakeRetriever([], {})
    captured = {}
    _patch_query(monkeypatch, captured)
    answer = await ContextRagAnswerer(r).answer("nonsense")
    assert answer.sources == []
    assert "no matching" in answer.text.lower()
