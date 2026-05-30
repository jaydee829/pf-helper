"""Core data types shared across ingestion, storage, retrieval, and server."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    """Canonical PF2e content categories exposed to the search tool's enum."""

    SPELL = "spell"
    FEAT = "feat"
    CREATURE = "creature"
    EQUIPMENT = "equipment"
    ANCESTRY = "ancestry"
    CLASS = "class"
    BACKGROUND = "background"
    CONDITION = "condition"
    ACTION = "action"
    HAZARD = "hazard"
    DEITY = "deity"
    # Deferred to AON supplement: trait, skill, archetype, rules.


@dataclass(frozen=True)
class Entry:
    """A fully-cleaned rules entry, ready to index and serve."""

    id: str
    name: str
    category: str
    traits: tuple[str, ...]
    level: int | None
    source_book: str | None
    text: str
    raw_json: str
    # Ordered (label, value) pairs for the statblock header; empty for
    # non-statblock categories (condition, ancestry, ...).
    stats: tuple[tuple[str, str], ...] = ()


class SearchHit(BaseModel):
    """A lean search result row (token-cheap; for scanning)."""

    id: str = Field(description="Stable entry id, e.g. 'spell:heal'")
    name: str
    category: str
    level: int | None = Field(default=None, description="Level or spell rank, if any")
    excerpt: str = Field(description="Short snippet of the entry text")


class EntryDetail(BaseModel):
    """Full entry payload returned when a specific entry is requested."""

    id: str
    name: str
    category: str
    level: int | None = None
    traits: list[str] = Field(default_factory=list)
    source_book: str | None = None
    # Flattened from Entry.stats (a tuple of pairs) to a dict for the response;
    # ordering is not preserved.
    stats: dict[str, str] = Field(
        default_factory=dict,
        description="Category-aware header fields (e.g. creature AC/HP/saves, spell range/area)",
    )
    text: str = Field(description="Full cleaned plain-text rules content")
