"""Build the SQLite + FTS5 index from one or more content sources.

`build_index` is pure (takes an explicit sources list) for testability.
`main` handles cloning/pulling the Foundry repo and wiring config.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from collections.abc import Iterable

from pf_helper.config import Config
from pf_helper.ingest.sources import FoundrySource, Source
from pf_helper.store import db


def build_index(cfg: Config, sources: Iterable[Source]) -> dict[str, int]:
    """Ingest every source into a fresh DB. Returns per-category counts."""
    if cfg.db_path.exists():
        cfg.db_path.unlink()
    conn = db.connect(cfg.db_path)
    try:
        db.create_schema(conn)
        counts: Counter[str] = Counter()
        batch = []
        for source in sources:
            for entry in source.iter_entries():
                batch.append(entry)
                counts[entry.category] += 1
        db.insert_entries(conn, batch)
    finally:
        conn.close()
    return dict(counts)


def _ensure_foundry_repo(cfg: Config) -> None:
    if (cfg.foundry_dir / ".git").exists():
        subprocess.run(["git", "-C", str(cfg.foundry_dir), "pull", "--ff-only"], check=True)
    else:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", cfg.foundry_repo_url, str(cfg.foundry_dir)],
            check=True,
        )


def main() -> None:
    cfg = Config.from_env()
    print(f"Ensuring Foundry repo at {cfg.foundry_dir} ...")
    _ensure_foundry_repo(cfg)
    print("Building index ...")
    counts = build_index(cfg, [FoundrySource(cfg.foundry_packs_root)])
    total = sum(counts.values())
    print(f"Indexed {total} entries into {cfg.db_path}")
    for cat in sorted(counts):
        print(f"  {cat:12} {counts[cat]}")


if __name__ == "__main__":
    main()
