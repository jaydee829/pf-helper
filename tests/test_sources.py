from pathlib import Path

from pf_helper.ingest.sources import FoundrySource

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "foundry"


def test_iter_entries_yields_known_entries():
    src = FoundrySource(FIXTURE_ROOT)
    by_name = {e.name: e for e in src.iter_entries()}
    assert "Frightened" in by_name
    assert "Test Feat" in by_name


def test_folders_file_is_skipped():
    src = FoundrySource(FIXTURE_ROOT)
    names = [e.name for e in src.iter_entries()]
    assert "Cantrip" not in names  # came from _folders.json


def test_entry_fields_are_mapped_and_cleaned():
    src = FoundrySource(FIXTURE_ROOT)
    feat = next(e for e in src.iter_entries() if e.name == "Test Feat")
    assert feat.category == "feat"
    assert feat.level == 4
    assert feat.source_book == "Player Core"
    assert feat.traits == ("general", "skill")
    assert feat.id == "feat:test-feat-abc123"  # slug + Foundry _id for uniqueness
    assert "Sickened 1" in feat.text  # enricher resolved
    assert "@UUID" not in feat.text


def test_condition_level_is_none():
    src = FoundrySource(FIXTURE_ROOT)
    cond = next(e for e in src.iter_entries() if e.name == "Frightened")
    assert cond.level is None
    assert cond.category == "condition"


def test_creature_stats_are_populated():
    src = FoundrySource(FIXTURE_ROOT)
    beast = next(e for e in src.iter_entries() if e.name == "Test Beast")
    assert beast.category == "creature"
    stats = dict(beast.stats)
    assert stats["AC"] == "24"
    assert stats["Saves"] == "Fort +16, Ref +14, Will +11"
