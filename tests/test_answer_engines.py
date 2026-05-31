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


@pytest.mark.asyncio
async def test_agent_returns_text(monkeypatch):
    r = FakeRetriever([], {})
    captured = {}
    _patch_query(monkeypatch, captured, reply="Per the rules, yes.")
    from pf_helper.answer.engines import AgentMcpAnswerer

    answer = await AgentMcpAnswerer(r).answer("can I do X?")
    assert answer.text == "Per the rules, yes."
    assert answer.engine == "agent"
    opts = captured["options"]
    assert "pf2e" in opts.mcp_servers
    assert set(opts.allowed_tools) == {"mcp__pf2e__search", "mcp__pf2e__get_entry"}


@pytest.mark.asyncio
async def test_agent_tool_functions_record_sources(monkeypatch):
    hit = SearchHit(
        id="spell:heal",
        name="Heal",
        category="spell",
        excerpt="heal...",
        source_url="https://2e.aonprd.com/Spells.aspx?ID=1",
    )
    detail = EntryDetail(
        id="spell:heal",
        name="Heal",
        category="spell",
        text="Heal a creature.",
        source_url=hit.source_url,
    )
    r = FakeRetriever([hit], {"Heal": detail})
    from pf_helper.answer.engines import AgentMcpAnswerer

    eng = AgentMcpAnswerer(r)
    search_fn, get_fn, sources = eng._build_tools()  # plain callables + the sources sink
    out = await search_fn({"query": "heal", "category": ""})
    assert "Heal" in out["content"][0]["text"]
    assert ("Heal", hit.source_url) in sources.items()
    out2 = await get_fn({"name": "Heal", "category": "spell"})
    assert "Heal a creature." in out2["content"][0]["text"]
