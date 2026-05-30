"""Content sources. v1: FoundrySource over a cloned foundryvtt/pf2e checkout."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import quote_plus

from pf_helper.ingest.clean import clean_text
from pf_helper.ingest.extract import extract_stats
from pf_helper.models import Entry

# Foundry document `type` -> our Category value. Types not present are skipped.
CATEGORY_MAP: dict[str, str] = {
    "condition": "condition",
    "spell": "spell",
    "feat": "feat",
    "action": "action",
    "hazard": "hazard",
    "npc": "creature",
    "ancestry": "ancestry",
    "heritage": "ancestry",
    "class": "class",
    "background": "background",
    "deity": "deity",
    # equipment-ish item types (verified against the equipment pack)
    "equipment": "equipment",
    "weapon": "equipment",
    "armor": "equipment",
    "shield": "equipment",
    "consumable": "equipment",
    "treasure": "equipment",
    "backpack": "equipment",
    "ammo": "equipment",
    "kit": "equipment",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")


class Source(ABC):
    """A source of rules Entries. The pluggability point for data origins."""

    @abstractmethod
    def iter_entries(self) -> Iterable[Entry]: ...


class FoundrySource(Source):
    """Walks `<root>/pf2e/<pack>/**/*.json` and yields cleaned Entries."""

    def __init__(self, root: str | Path):
        # root is the directory that contains the `pf2e/` packs tree.
        self.packs_root = Path(root) / "pf2e"

    def iter_entries(self) -> Iterator[Entry]:
        for path in sorted(self.packs_root.rglob("*.json")):
            if path.name == "_folders.json":
                continue
            entry = self._load(path)
            if entry is not None:
                yield entry

    def _load(self, path: Path) -> Entry | None:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            return None
        except json.JSONDecodeError:
            return None
        if not isinstance(doc, dict):
            return None  # skip top-level JSON arrays (not Foundry documents)
        doc_type = doc.get("type")
        category = CATEGORY_MAP.get(doc_type)
        if category is None or "name" not in doc or "_id" not in doc:
            return None
        system = doc.get("system", {})
        html = (system.get("description") or {}).get("value", "")
        return Entry(
            # Human-readable slug plus the Foundry _id, which is unique within the
            # compendium. The _id suffix prevents same-name/same-category documents
            # (e.g. creature variants across books) from colliding on the primary
            # key and being silently dropped at build time. Lookups are by name.
            id=f"{category}:{_slug(doc['name'])}-{doc['_id']}",
            name=doc["name"],
            category=category,
            traits=tuple((system.get("traits") or {}).get("value") or []),
            level=_extract_level(system),
            source_book=_extract_source(system),
            text=clean_text(html),
            raw_json=json.dumps(doc, separators=(",", ":")),
            stats=extract_stats(category, system),
            source_url=f"https://2e.aonprd.com/Search.aspx?q={quote_plus(doc['name'])}",
        )


def _extract_level(system: dict) -> int | None:
    level = (system.get("level") or {}).get("value")
    if level is None:
        level = ((system.get("details") or {}).get("level") or {}).get("value")
    return level if isinstance(level, int) else None


def _extract_source(system: dict) -> str | None:
    pub = system.get("publication") or {}
    if pub.get("title"):
        return pub["title"]
    src = system.get("source") or {}
    return src.get("value") or None
