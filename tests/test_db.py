from pf_helper.models import Entry
from pf_helper.store import db


def _entry(**kw) -> Entry:
    base = dict(
        id="condition:frightened",
        name="Frightened",
        category="condition",
        traits=("emotion",),
        level=None,
        source_book="Player Core",
        text="You're gripped by fear and take a status penalty.",
        raw_json="{}",
    )
    base.update(kw)
    return Entry(**base)


def test_insert_and_fetch_by_name(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry()])
    row = db.get_by_name(conn, "Frightened", category="condition")
    assert row is not None
    assert row["name"] == "Frightened"
    assert row["category"] == "condition"


def test_fts_search_matches_body(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry()])
    hits = db.fts_search(conn, "status penalty", category=None, limit=10)
    assert any(h["name"] == "Frightened" for h in hits)


def test_fts_search_respects_category_filter(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry(), _entry(id="spell:x", name="Fear", category="spell")])
    hits = db.fts_search(conn, "fear", category="spell", limit=10)
    assert all(h["category"] == "spell" for h in hits)


def test_get_by_name_returns_none_for_missing(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    assert db.get_by_name(conn, "NotAReal Entry") is None


def test_get_by_name_is_case_insensitive(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.create_schema(conn)
    db.insert_entries(conn, [_entry()])
    assert db.get_by_name(conn, "frightened") is not None  # COLLATE NOCASE


def test_to_match_query_edge_cases():
    assert db._to_match_query("") == '""'
    assert db._to_match_query('"') == '""'  # quote-only stripped to empty
    assert db._to_match_query("fire damage") == '"fire" OR "damage"'
    assert db._to_match_query('fire"damage') == '"fire" OR "damage"'  # embedded quote split
