from pathlib import Path

from pf_helper.config import Config
from pf_helper.ingest.build import build_index
from pf_helper.ingest.sources import FoundrySource
from pf_helper.store import db

FIXTURE_PACKS = Path(__file__).parent / "fixtures" / "foundry"


def test_build_index_from_local_packs(tmp_path):
    cfg = Config(data_dir=tmp_path)
    counts = build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    assert counts["feat"] >= 1
    assert counts["condition"] >= 1

    conn = db.connect(cfg.db_path)
    row = db.get_by_name(conn, "Frightened", category="condition")
    assert row is not None


def test_build_index_is_idempotent(tmp_path):
    # Rebuilding over an existing db must delete + recreate cleanly.
    cfg = Config(data_dir=tmp_path)
    first = build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    second = build_index(cfg, [FoundrySource(FIXTURE_PACKS)])
    assert first == second
    conn = db.connect(cfg.db_path)
    (total,) = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    assert total == sum(second.values())  # no duplicate rows after rebuild
