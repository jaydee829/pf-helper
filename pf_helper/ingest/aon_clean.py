"""Convert AON's custom markdown dialect (from the Elasticsearch `markdown`
field) into clean plain text.

AON's `markdown` is not standard Markdown: it wraps content in custom tags such
as `<title>`, `<traits>`/`<trait .../>`, and `<row>`/`<column>`, and uses
`[label](url)` links. We resolve links to their label, turn block-closing tags
into line breaks, drop all remaining tags, then normalize whitespace. Standard
Markdown emphasis (`**bold**`, etc.) is left intact -- Claude reads it fine.
"""

from __future__ import annotations

import html
import re

# [label](url) -> label
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# <actions string="Single Action" /> -> [Single Action] (preserve the action cost).
_ACTIONS = re.compile(r'<actions\s+string="([^"]*)"[^>]*>', re.IGNORECASE)
# <br> / <br /> -> newline (AON uses it as a field separator).
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
# Block-level closing tags become a newline so adjacent blocks/cells don't merge.
_BLOCK_CLOSE = re.compile(
    r"</(?:title|row|column|traits|p|li|h[1-6]|td|th|tr|thead|tbody|tfoot|table|ul|ol|aside)>",
    re.IGNORECASE,
)
# Any remaining tag (opening, closing, or self-closing) is dropped. Requiring a
# leading letter (or "/letter") means a literal "<" in prose (e.g. "damage < 5")
# is left alone rather than mistaken for a tag.
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def _normalize_ws(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_aon(markdown: str) -> str:
    """Resolve AON links, strip AON's custom tags, and normalize whitespace."""
    if not markdown:
        return ""
    text = _MD_LINK.sub(lambda m: m.group(1), markdown)
    text = _ACTIONS.sub(lambda m: f"[{m.group(1)}]", text)
    text = _BR.sub("\n", text)
    text = _BLOCK_CLOSE.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    return _normalize_ws(text)
