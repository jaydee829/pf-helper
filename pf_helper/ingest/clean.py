"""Convert Foundry-enriched HTML descriptions into clean plain text.

Order matters: resolve enrichers (which can contain text we keep) *before*
stripping HTML, then normalize whitespace.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# @UUID[...]{Label}  -> Label
_UUID_LABELLED = re.compile(r"@UUID\[[^\]]*\]\{([^}]*)\}")
# @UUID[Compendium.pack.id.Item.Name] -> Name  (last dot-separated segment inside brackets)
_UUID_BARE = re.compile(r"@UUID\[[^\]]*?([^.\]]+)\]")
# @Damage[expr[types]] (ignores any |options) -> "expr types". The formula
# part is [^\[]+ rather than a dice-only class: real data has parenthesized and
# expression formulas like (1d10+14), floor(@item.level/2)d6, (@item.level).
_DAMAGE_TYPED = re.compile(r"@Damage\[([^\[]+)\[([^\]]+)\][^\]]*\]")
# Typeless @Damage with a label: @Damage[formula|opts]{Label} -> Label.
_DAMAGE_LABELLED = re.compile(r"@Damage\[[^\[\]]*\]\{([^}]*)\}")
# Typeless @Damage, no label: @Damage[formula|opts] -> formula (drop |options).
_DAMAGE_BARE = re.compile(r"@Damage\[([^\[\]]*)\]")
# @Check[stat|dc:N|...] -> "stat check (DC N)"  /  @Check[stat] -> "stat check"
_CHECK = re.compile(r"@Check\[([^\]]+)\]")
# @Template[shape|distance:N|...] -> "N-foot shape"
_TEMPLATE = re.compile(r"@Template\[([^\]]+)\]")
# @Embed[...]{Label} -> Label ; @Embed[...] -> ""
_EMBED_LABELLED = re.compile(r"@Embed\[[^\]]*\]\{([^}]*)\}")
_EMBED_BARE = re.compile(r"@Embed\[[^\]]*\]")
# @Localize[...] -> "" (rare; no reliable inline text)
_LOCALIZE = re.compile(r"@Localize\[[^\]]*\]")
# [[/r 1d4 #comment]] or [[/br ...]] -> dice expression only
_INLINE_ROLL = re.compile(r"\[\[/[a-zA-Z]+\s+([0-9dD+\-* ]+?)(?:\s+#[^\]]*)?\]\]")


def _render_damage(m: re.Match[str]) -> str:
    dice = m.group(1).strip()
    types = " ".join(t.strip() for t in m.group(2).split(","))
    return f"{dice} {types}".strip()


def _render_damage_bare(m: re.Match[str]) -> str:
    # Typeless damage: keep the formula, drop any |options suffix.
    return m.group(1).split("|")[0].strip()


def _render_check(m: re.Match[str]) -> str:
    parts = m.group(1).split("|")
    stat = parts[0].strip()
    dc = None
    for p in parts[1:]:
        p = p.strip()
        if p.startswith("dc:"):
            dc = p[3:].strip()
    return f"{stat} check (DC {dc})" if dc else f"{stat} check"


def _render_template(m: re.Match[str]) -> str:
    parts = m.group(1).split("|")
    shape = parts[0].strip()
    distance = None
    for p in parts[1:]:
        p = p.strip()
        if p.startswith("distance:"):
            distance = p[len("distance:") :].strip()
    return f"{distance}-foot {shape}" if distance else shape


def _resolve_enrichers(text: str) -> str:
    text = _UUID_LABELLED.sub(lambda m: m.group(1), text)
    text = _UUID_BARE.sub(lambda m: m.group(1), text)
    text = _DAMAGE_TYPED.sub(_render_damage, text)
    text = _DAMAGE_LABELLED.sub(lambda m: m.group(1), text)
    text = _DAMAGE_BARE.sub(_render_damage_bare, text)
    text = _CHECK.sub(_render_check, text)
    text = _TEMPLATE.sub(_render_template, text)
    text = _EMBED_LABELLED.sub(lambda m: m.group(1), text)
    text = _EMBED_BARE.sub("", text)
    text = _LOCALIZE.sub("", text)
    text = _INLINE_ROLL.sub(lambda m: m.group(1).strip(), text)
    return text


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Convert list items to "- item" lines.
    for li in soup.find_all("li"):
        li.insert_before("- ")
        li.append("\n")
    # Paragraphs and block elements become blank-line separated.
    for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6"]):
        block.append("\n\n")
    text = soup.get_text()
    return text


def _normalize_ws(text: str) -> str:
    # Collapse runs of spaces/tabs, trim each line, collapse 3+ newlines to 2.
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_text(html: str) -> str:
    """Resolve Foundry enrichers, strip HTML, and normalize whitespace."""
    if not html:
        return ""
    return _normalize_ws(_html_to_text(_resolve_enrichers(html)))
