from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.build import build_index
from pf_helper.ingest.sources import FoundrySource
from pf_helper.retrieval.fts5 import Fts5Retriever, _excerpt

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "foundry"


def _retriever(tmp_path) -> Fts5Retriever:
    cfg = Config(data_dir=tmp_path)
    build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    return Fts5Retriever(cfg.db_path)


def test_search_returns_hits(tmp_path):
    r = _retriever(tmp_path)
    hits = r.search("status penalty", category=None, limit=10)
    assert any(h.name == "Frightened" for h in hits)
    assert all(hasattr(h, "excerpt") for h in hits)


def test_search_category_filter(tmp_path):
    r = _retriever(tmp_path)
    hits = r.search("sickened", category="feat", limit=10)
    assert hits  # the filter must not vacuously pass on an empty result
    assert all(h.category == "feat" for h in hits)


def test_search_clamps_limit(tmp_path):
    r = _retriever(tmp_path)
    hits = r.search("fear", category=None, limit=999)
    assert len(hits) <= 50


def test_get_returns_detail(tmp_path):
    r = _retriever(tmp_path)
    detail = r.get("Frightened", category="condition")
    assert detail is not None
    assert detail.name == "Frightened"
    assert "status penalty" in detail.text


def test_get_missing_returns_none(tmp_path):
    r = _retriever(tmp_path)
    assert r.get("Nonexistent Thing", category=None) is None


def test_get_includes_category_aware_stats(tmp_path):
    r = _retriever(tmp_path)
    detail = r.get("Test Beast", category="creature")
    assert detail is not None
    assert detail.stats["AC"] == "24"
    assert detail.stats["Saves"] == "Fort +16, Ref +14, Will +11"


def test_excerpt_truncates_long_text():
    out = _excerpt("word " * 200)
    assert len(out) <= _EXCERPT_LEN_PLUS
    assert out.endswith("...")
    assert _excerpt("") == ""  # empty text stays empty (no spurious "...")


_EXCERPT_LEN_PLUS = 243  # 240 chars + "..."


def test_factory_builds_fts5_retriever(tmp_path):
    from pf_helper.config import Config
    from pf_helper.retrieval.factory import build_retriever
    from pf_helper.retrieval.fts5 import Fts5Retriever

    cfg = Config(data_dir=tmp_path)
    build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    r = build_retriever(cfg)
    assert isinstance(r, Fts5Retriever)


def test_factory_rejects_unknown_retriever(tmp_path):
    from dataclasses import replace

    import pytest

    from pf_helper.config import Config
    from pf_helper.retrieval.factory import build_retriever

    cfg = replace(Config(data_dir=tmp_path), retriever="bogus")
    with pytest.raises(ValueError, match="Unknown retriever"):
        build_retriever(cfg)
