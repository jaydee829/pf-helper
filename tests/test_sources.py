from pathlib import Path

from pf_helper.ingest.sources import AonSource, FoundrySource

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


def test_foundry_entry_has_aon_search_url():
    src = FoundrySource(FIXTURE_ROOT)
    feat = next(e for e in src.iter_entries() if e.name == "Test Feat")
    assert feat.source_url == "https://2e.aonprd.com/Search.aspx?q=Test+Feat"


AON_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "aon"


def test_aon_source_maps_fields_and_cleans_text():
    src = AonSource(AON_FIXTURE_DIR)
    by_name = {e.name: e for e in src.iter_entries()}
    trait = by_name["Aberration"]
    assert trait.category == "trait"
    assert trait.id == "trait:aberration-trait-1"
    assert trait.source_book == "Core Rulebook"
    assert trait.source_url == "https://2e.aonprd.com/Traits.aspx?ID=1"
    assert "Aberrations are creatures from beyond the planes." in trait.text
    assert "<title" not in trait.text and "[Aberration]" not in trait.text


def test_aon_source_maps_traits_and_level():
    src = AonSource(AON_FIXTURE_DIR)
    ritual = next(e for e in src.iter_entries() if e.name == "Animate Object")
    assert ritual.category == "ritual"
    assert ritual.level == 2
    assert ritual.traits == ("Transmutation", "Uncommon")
    assert ritual.source_url == "https://2e.aonprd.com/Rituals.aspx?ID=1"


def test_aon_source_skips_corrupt_cache_file(tmp_path):
    # Invalid UTF-8 in one category file must be skipped, not crash the build.
    (tmp_path / "trait.json").write_bytes(b"\xff\xfe not valid utf-8")
    (tmp_path / "ritual.json").write_text(
        '[{"id":"ritual-9","name":"Test Ritual","category":"ritual",'
        '"url":"/Rituals.aspx?ID=9","markdown":"A test ritual."}]',
        encoding="utf-8",
    )
    names = [e.name for e in AonSource(tmp_path).iter_entries()]
    assert names == ["Test Ritual"]  # corrupt trait.json skipped, ritual still read


def test_aon_source_url_tolerates_missing_leading_slash(tmp_path):
    (tmp_path / "trait.json").write_text(
        '[{"id":"trait-9","name":"Oddurl","category":"trait",'
        '"url":"Traits.aspx?ID=9","markdown":"x"}]',
        encoding="utf-8",
    )
    entry = next(iter(AonSource(tmp_path).iter_entries()))
    assert entry.source_url == "https://2e.aonprd.com/Traits.aspx?ID=9"


class _FakeLinkIndex:
    def __init__(self, mapping):
        self._m = mapping  # {(category, name): url}

    def url_for(self, category, name):
        return self._m.get((category, name))


def test_foundry_uses_exact_link_when_index_matches():
    idx = _FakeLinkIndex({("feat", "Test Feat"): "https://2e.aonprd.com/Feats.aspx?ID=99"})
    src = FoundrySource(FIXTURE_ROOT, link_index=idx)
    feat = next(e for e in src.iter_entries() if e.name == "Test Feat")
    assert feat.source_url == "https://2e.aonprd.com/Feats.aspx?ID=99"


def test_foundry_falls_back_to_search_link_when_index_misses():
    idx = _FakeLinkIndex({})  # knows nothing
    src = FoundrySource(FIXTURE_ROOT, link_index=idx)
    cond = next(e for e in src.iter_entries() if e.name == "Frightened")
    assert cond.source_url == "https://2e.aonprd.com/Search.aspx?q=Frightened"
