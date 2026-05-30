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
    # AON Elasticsearch supplement categories (not in the Foundry compendium).
    TRAIT = "trait"
    SKILL = "skill"
    ARCHETYPE = "archetype"
    RULES = "rules"
    CLASS_FEATURE = "class-feature"
    HERITAGE = "heritage"
    BLOODLINE = "bloodline"
    MYSTERY = "mystery"
    PATRON = "patron"
    LESSON = "lesson"
    ARCANE_SCHOOL = "arcane-school"
    DOMAIN = "domain"
    IMPLEMENT = "implement"
    IKON = "ikon"  # AON/PF2e spelling (Exemplar class), not "icon"
    ANIMAL_COMPANION = "animal-companion"
    FAMILIAR_ABILITY = "familiar-ability"
    RITUAL = "ritual"
    RELIC = "relic"
    CURSE = "curse"
    DISEASE = "disease"
    LANGUAGE = "language"
    PLANE = "plane"
    VEHICLE = "vehicle"


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
    # AON page link: exact deep link (AON entries) or search-by-name link
    # (Foundry entries). Defaults empty for older construction sites.
    source_url: str = ""


class SearchHit(BaseModel):
    """A lean search result row (token-cheap; for scanning)."""

    id: str = Field(description="Stable entry id, e.g. 'spell:heal'")
    name: str
    category: str
    level: int | None = Field(default=None, description="Level or spell rank, if any")
    excerpt: str = Field(description="Short snippet of the entry text")
    source_url: str = Field(default="", description="AON page link for this entry")


class EntryDetail(BaseModel):
    """Full entry payload returned when a specific entry is requested."""

    id: str
    name: str
    category: str
    level: int | None = None
    traits: list[str] = Field(default_factory=list)
    source_book: str | None = None
    # Flattened from Entry.stats (a tuple of pairs) to a dict for the response;
    # insertion order is preserved (dict + json both keep order).
    stats: dict[str, str] = Field(
        default_factory=dict,
        description="Category-aware header fields (e.g. creature AC/HP/saves, spell range/area)",
    )
    text: str = Field(description="Full cleaned plain-text rules content")
    source_url: str = Field(default="", description="AON page link for this entry")
