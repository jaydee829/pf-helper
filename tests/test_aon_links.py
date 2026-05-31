import json

from pf_helper.ingest.aon_links import build_link_index


def _write(dirpath, category, docs):
    (dirpath / f"{category}.json").write_text(json.dumps(docs), encoding="utf-8")


def test_unique_name_maps_to_exact_url(tmp_path):
    _write(tmp_path, "creature", [{"name": "Goblin Warrior", "url": "/Monsters.aspx?ID=1"}])
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Goblin Warrior") == "https://2e.aonprd.com/Monsters.aspx?ID=1"


def test_remaster_preferred_over_legacy(tmp_path):
    _write(
        tmp_path,
        "creature",
        [
            {"name": "Arbiter", "url": "/Monsters.aspx?ID=6", "remaster_id": ["creature-2791"]},
            {"name": "Arbiter", "url": "/Monsters.aspx?ID=2791"},
        ],
    )
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Arbiter") == "https://2e.aonprd.com/Monsters.aspx?ID=2791"


def test_ambiguous_after_remaster_filter_returns_none(tmp_path):
    _write(
        tmp_path,
        "creature",
        [
            {"name": "Python", "url": "/Monsters.aspx?ID=10"},
            {"name": "Python", "url": "/Monsters.aspx?ID=11"},
        ],
    )
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Python") is None


def test_unknown_name_and_category_return_none(tmp_path):
    _write(tmp_path, "spell", [{"name": "Heal", "url": "/Spells.aspx?ID=1"}])
    idx = build_link_index(tmp_path)
    assert idx.url_for("spell", "Fireball") is None
    assert idx.url_for("feat", "Heal") is None


def test_normalization_matches_varied_casing_and_spacing(tmp_path):
    _write(tmp_path, "spell", [{"name": "Heal", "url": "/Spells.aspx?ID=1"}])
    idx = build_link_index(tmp_path)
    assert idx.url_for("spell", "  heal ") == "https://2e.aonprd.com/Spells.aspx?ID=1"


def test_empty_dir_is_safe(tmp_path):
    idx = build_link_index(tmp_path)
    assert idx.url_for("creature", "Anything") is None
