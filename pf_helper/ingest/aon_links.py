"""Build a name->AON-url index for the Foundry-overlapping categories.

Foundry and AON share no IDs, so exact AON deep links for Foundry entries are
resolved by matching normalized names within a category. AON entries that carry
a `remaster_id` are superseded legacy duplicates and are dropped (prefer
remaster, matching Foundry). A name still mapping to more than one URL after
that is ambiguous and is omitted, so the caller falls back to a search link.
"""

from __future__ import annotations

import json
from pathlib import Path

from pf_helper.ingest.sources import _slug

# Categories to fetch from AON; most map 1:1 to Foundry's category values.
# 'heritage' is the exception: AON keeps heritages in their own category, but
# Foundry maps its heritage document type to the 'ancestry' category.
AON_LINK_CATEGORIES: tuple[str, ...] = (
    "creature",
    "spell",
    "feat",
    "hazard",
    "condition",
    "action",
    "deity",
    "ancestry",
    "class",
    "background",
    "heritage",
)

_AON_BASE = "https://2e.aonprd.com"

# AON 'heritage' entries belong to Foundry's 'ancestry' category (Foundry maps
# its heritage document type to 'ancestry'); all others map to themselves.
_AON_TO_FOUNDRY_CATEGORY: dict[str, str] = {"heritage": "ancestry"}


class AonLinkIndex:
    """Maps (category, normalized name) -> exact AON page URL for unique matches."""

    def __init__(self, mapping: dict[tuple[str, str], str]):
        self._map = mapping

    def url_for(self, category: str, name: str) -> str | None:
        return self._map.get((category, _slug(name)))


def build_link_index(link_dir: str | Path) -> AonLinkIndex:
    """Read cached AON name/url projections and build an AonLinkIndex."""
    link_dir = Path(link_dir)
    candidates: dict[tuple[str, str], set[str]] = {}
    for category in AON_LINK_CATEGORIES:
        path = link_dir / f"{category}.json"
        if not path.exists():
            continue
        try:
            docs = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if not isinstance(docs, list):
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("remaster_id"):
                continue  # drop superseded legacy entries (prefer remaster)
            name = doc.get("name")
            url = doc.get("url")
            if not name or not url:
                continue
            foundry_category = _AON_TO_FOUNDRY_CATEGORY.get(category, category)
            key = (foundry_category, _slug(name))
            candidates.setdefault(key, set()).add(f"{_AON_BASE}/{url.lstrip('/')}")
    mapping = {key: next(iter(urls)) for key, urls in candidates.items() if len(urls) == 1}
    return AonLinkIndex(mapping)
