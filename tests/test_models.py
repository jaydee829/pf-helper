from pf_helper.models import Category, Entry, EntryDetail, SearchHit


def test_category_values_are_lowercase_strings():
    assert Category.SPELL.value == "spell"
    assert Category.CREATURE.value == "creature"
    # StrEnum compares equal to its string value
    assert Category.FEAT == "feat"


def test_category_from_value_roundtrip():
    assert Category("condition") is Category.CONDITION


def test_entry_is_constructible_and_frozen():
    e = Entry(
        id="condition:frightened",
        name="Frightened",
        category="condition",
        traits=("emotion", "fear"),
        level=None,
        source_book="Pathfinder Player Core",
        text="You're gripped by fear...",
        raw_json="{}",
    )
    assert e.name == "Frightened"
    assert e.traits == ("emotion", "fear")
    assert e.stats == ()  # default for categories without a statblock


def test_search_hit_constructs_with_defaults():
    hit = SearchHit(id="spell:heal", name="Heal", category="spell", excerpt="Heal a creature...")
    assert hit.level is None  # optional, defaults to None
    assert hit.name == "Heal"


def test_entry_detail_defaults_and_stats_dict():
    detail = EntryDetail(id="creature:goblin", name="Goblin", category="creature", text="A goblin.")
    assert detail.traits == []  # default_factory list
    assert detail.stats == {}  # default_factory dict
    assert detail.source_book is None
    populated = EntryDetail(
        id="creature:goblin",
        name="Goblin",
        category="creature",
        text="A goblin.",
        stats={"AC": "16", "HP": "6"},
    )
    assert populated.stats["AC"] == "16"
