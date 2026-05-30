from pathlib import Path

from pf_helper import server as srv
from pf_helper.config import Config
from pf_helper.ingest.build import build_index
from pf_helper.ingest.sources import FoundrySource
from pf_helper.models import Category

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "foundry"


def _setup(tmp_path):
    cfg = Config(data_dir=tmp_path)
    build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    srv.configure(cfg)


def test_search_tool_returns_hits(tmp_path):
    _setup(tmp_path)
    hits = srv.search("status penalty", category="condition", limit=5)
    assert any(h.name == "Frightened" for h in hits)


def test_search_missing_db_returns_empty_with_hint(tmp_path):
    srv.configure(Config(data_dir=tmp_path))  # no build -> no db file
    hits = srv.search("anything", category=None, limit=5)
    assert hits == []


def test_get_entry_tool_returns_detail(tmp_path):
    _setup(tmp_path)
    detail = srv.get_entry("Frightened", category="condition")
    assert detail is not None
    assert "status penalty" in detail.text


def test_get_entry_unknown_returns_none(tmp_path):
    _setup(tmp_path)
    assert srv.get_entry("Does Not Exist", category=None) is None


def test_get_entry_missing_db_returns_none(tmp_path):
    srv.configure(Config(data_dir=tmp_path))  # no build -> no db file
    assert srv.get_entry("Frightened", category=None) is None


def test_search_accepts_category_enum(tmp_path):
    # Exercises the str(category) translation through an actual Category member,
    # not just the plain-string shortcut.
    _setup(tmp_path)
    hits = srv.search("status penalty", category=Category.CONDITION, limit=5)
    assert any(h.name == "Frightened" for h in hits)
