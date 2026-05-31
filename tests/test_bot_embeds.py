import pytest

from pf_helper.answer.base import Answer
from pf_helper.bot.config import BotConfig
from pf_helper.bot.embeds import (
    answer_embed,
    lookup_embed,
    search_embeds,
    split_message,
    truncate,
)
from pf_helper.models import EntryDetail, SearchHit


def test_bot_config_requires_token(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
        BotConfig.from_env()


def test_bot_config_reads_env(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("PF_HELPER_DISCORD_GUILD_ID", "123")
    cfg = BotConfig.from_env()
    assert cfg.token == "tok"
    assert cfg.guild_id == 123


def test_truncate_and_split():
    assert truncate("abcdef", 4).endswith("...") and len(truncate("abcdef", 4)) <= 4 + 3
    chunks = split_message("x" * 4500, limit=2000)
    assert all(len(c) <= 2000 for c in chunks) and "".join(chunks) == "x" * 4500


def test_lookup_embed_links_title_and_shows_stats():
    d = EntryDetail(
        id="creature:goblin",
        name="Goblin",
        category="creature",
        level=1,
        traits=["humanoid"],
        source_book="Monster Core",
        stats={"AC": "16", "HP": "6"},
        text="A goblin.",
        source_url="https://2e.aonprd.com/Monsters.aspx?ID=1",
    )
    e = lookup_embed(d)
    assert e.title == "Goblin"
    assert e.url == "https://2e.aonprd.com/Monsters.aspx?ID=1"
    field_text = " ".join(f"{f.name}:{f.value}" for f in e.fields)
    assert "creature" in field_text and "AC" in field_text


def test_search_embed_lists_hits_with_links():
    hits = [
        SearchHit(
            id="spell:heal",
            name="Heal",
            category="spell",
            excerpt="heal...",
            source_url="https://2e.aonprd.com/Spells.aspx?ID=1",
        )
    ]
    e = search_embeds(hits)
    assert "Heal" in e.description and "Spells.aspx?ID=1" in e.description


def test_answer_embed_has_sources_field():
    ans = Answer(
        text="Yes you can.",
        sources=[("Flanking", "https://2e.aonprd.com/x")],
        engine="agent",
    )
    e = answer_embed(ans)
    assert "Yes you can." in e.description
    src = " ".join(f"{f.name}:{f.value}" for f in e.fields)
    assert "Flanking" in src and "https://2e.aonprd.com/x" in src
