"""Pure render helpers: build discord.Embed objects (no Discord I/O, no network)."""

from __future__ import annotations

import discord

from pf_helper.answer.base import Answer
from pf_helper.models import EntryDetail, SearchHit

_DESC_LIMIT = 4096
_FIELD_LIMIT = 1024
_MSG_LIMIT = 2000


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def split_message(text: str, limit: int = _MSG_LIMIT) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


def lookup_embed(detail: EntryDetail) -> discord.Embed:
    embed = discord.Embed(
        title=detail.name,
        url=detail.source_url or None,
        description=truncate(detail.text, _DESC_LIMIT - 200),
    )
    embed.add_field(name="Category", value=detail.category, inline=True)
    if detail.level is not None:
        embed.add_field(name="Level", value=str(detail.level), inline=True)
    if detail.traits:
        embed.add_field(
            name="Traits", value=truncate(", ".join(detail.traits), _FIELD_LIMIT), inline=False
        )
    for label, value in detail.stats.items():
        # Stay under Discord's 25-field embed limit, reserving room for the
        # Source/AON fields below (PF2e stats are few, but the dict is unbounded).
        if len(embed.fields) >= 22:
            break
        embed.add_field(name=label, value=truncate(value, _FIELD_LIMIT), inline=True)
    if detail.source_book:
        embed.add_field(name="Source", value=detail.source_book, inline=False)
    if detail.source_url:
        embed.add_field(name="AON", value=f"[Full entry]({detail.source_url})", inline=False)
    return embed


def search_embeds(hits: list[SearchHit]) -> discord.Embed:
    if not hits:
        return discord.Embed(title="No matches", description="Nothing found. Try different terms.")
    lines = [
        f"- [{h.name}]({h.source_url}) · {h.category} — {truncate(h.excerpt, 120)}" for h in hits
    ]
    return discord.Embed(
        title="Search results", description=truncate("\n".join(lines), _DESC_LIMIT)
    )


def lookup_miss_embed(
    name: str, suggestions: list[str], hits: list[SearchHit]
) -> discord.Embed:
    """Embed for a /lookup exact-name miss: 'did you mean' + closest search hits."""
    lines: list[str] = []
    if suggestions:
        lines.append("Did you mean: " + ", ".join(f"**{s}**" for s in suggestions) + "?")
    if hits:
        if lines:
            lines.append("")
        lines.append("Closest matches:")
        lines += [
            f"- [{h.name}]({h.source_url}) · {h.category} — {truncate(h.excerpt, 120)}"
            for h in hits
        ]
    else:
        lines.append("Nothing found. Try `/search`.")
    return discord.Embed(
        title=f"No exact match for '{name}'",
        description=truncate("\n".join(lines), _DESC_LIMIT),
    )


def answer_embed(answer: Answer) -> discord.Embed:
    embed = discord.Embed(description=truncate(answer.text, _DESC_LIMIT - 200))
    if answer.sources:
        links = "\n".join(f"[{name}]({url})" for name, url in answer.sources)
        embed.add_field(
            name="Sources (Archives of Nethys)", value=truncate(links, _FIELD_LIMIT), inline=False
        )
    if answer.engine == "cache" and answer.match_score is not None:
        embed.set_footer(text=f"answered via cache · similar question ({answer.match_score:.2f})")
    elif answer.engine:
        embed.set_footer(text=f"answered via {answer.engine}")
    return embed
