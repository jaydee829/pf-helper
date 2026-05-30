from pf_helper.ingest.extract import extract_stats


def test_creature_stats():
    system = {
        "details": {"level": {"value": 6}},
        "attributes": {"ac": {"value": 24}, "hp": {"max": 120}, "speed": {"value": 25}},
        "perception": {"mod": 13},
        "saves": {"fortitude": {"value": 16}, "reflex": {"value": 14}, "will": {"value": 11}},
        "traits": {"size": {"value": "med"}, "value": ["humanoid"]},
    }
    stats = dict(extract_stats("creature", system))
    assert stats["AC"] == "24"
    assert stats["HP"] == "120"
    assert stats["Saves"] == "Fort +16, Ref +14, Will +11"
    assert stats["Perception"] == "+13"
    assert stats["Speed"] == "25 feet"
    assert stats["Size"] == "med"


def test_spell_stats():
    system = {
        "level": {"value": 3},
        "traits": {"traditions": ["arcane", "occult"]},
        "time": {"value": "2"},
        "range": {"value": "30 feet"},
        "area": {"type": "burst", "value": 20, "details": ""},
        "target": {"value": "1 creature"},
        "duration": {"value": "1 minute"},
        "defense": {"save": {"statistic": "will", "basic": False}},
    }
    stats = dict(extract_stats("spell", system))
    assert stats["Rank"] == "3"
    assert stats["Traditions"] == "arcane, occult"
    assert stats["Area"] == "20-foot burst"
    assert stats["Range"] == "30 feet"
    assert stats["Defense"] == "will"


def test_equipment_price_formatting():
    system = {"level": {"value": 1}, "price": {"value": {"gp": 5, "sp": 2}}, "bulk": {"value": 0.1}}
    stats = dict(extract_stats("equipment", system))
    assert stats["Price"] == "5 gp, 2 sp"
    assert stats["Bulk"] == "0.1"


def test_feat_activity_symbol():
    system = {"level": {"value": 2}, "actionType": {"value": "action"}, "actions": {"value": 1}}
    stats = dict(extract_stats("feat", system))
    assert stats["Level"] == "2"
    assert stats["Activity"] == "one action"


def test_action_reaction():
    system = {
        "actionType": {"value": "reaction"},
        "actions": {"value": None},
        "category": "defensive",
    }
    stats = dict(extract_stats("action", system))
    assert stats["Activity"] == "reaction"
    assert stats["Category"] == "defensive"


def test_hazard_stats():
    system = {
        "details": {"level": {"value": 23}},
        "attributes": {"ac": {"value": 45}, "hp": {"value": 300}, "stealth": {"value": 40}},
    }
    stats = dict(extract_stats("hazard", system))
    assert stats["AC"] == "45"
    assert stats["Stealth"] == "40"


def test_category_without_statblock_returns_empty():
    assert extract_stats("condition", {"value": {"isValued": True}}) == ()
    assert extract_stats("ancestry", {}) == ()


def test_zero_values_are_not_dropped():
    # Regression: the _pairs filter drops None/"" but must keep a real 0.
    spell = dict(extract_stats("spell", {"level": {"value": 0}}))  # cantrip
    assert spell["Rank"] == "0"
    equip = dict(extract_stats("equipment", {"level": {"value": 0}, "bulk": {"value": 0}}))
    assert equip["Bulk"] == "0"
    assert equip["Level"] == "0"


def test_spell_area_details_string_takes_precedence():
    system = {"level": {"value": 1}, "area": {"type": "emanation", "value": 30, "details": "cone"}}
    assert dict(extract_stats("spell", system))["Area"] == "cone"
