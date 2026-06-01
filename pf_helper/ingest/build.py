"""Build the SQLite + FTS5 index from one or more content sources.

`build_index` is pure (takes an explicit sources list) for testability.
`main` handles cloning/pulling the Foundry repo and wiring config.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from collections import Counter
from collections.abc import Iterable

from pf_helper.config import Config
from pf_helper.ingest.aon_links import AON_LINK_CATEGORIES, build_link_index
from pf_helper.ingest.sources import AON_CATEGORIES, AonSource, FoundrySource, Source
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


def _ensure_aon_cache(cfg: Config, refresh: bool = False) -> None:
    """Fetch each AON category from Elasticsearch into data/aon/<category>.json.

    Skips categories already cached unless refresh=True. One bulk query per
    category (size 10000); all target categories are well under that.
    """
    cfg.aon_dir.mkdir(parents=True, exist_ok=True)
    for category in AON_CATEGORIES:
        path = cfg.aon_dir / f"{category}.json"
        if path.exists() and not refresh:
            continue
        body = json.dumps({"size": 10000, "query": {"match": {"category": category}}}).encode()
        req = urllib.request.Request(
            cfg.aon_es_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.load(resp)
        docs = [hit["_source"] for hit in data["hits"]["hits"]]
        with path.open("w", encoding="utf-8") as f:
            json.dump(docs, f)
        print(f"  fetched {category:18} {len(docs)}")


def _ensure_aon_link_cache(cfg: Config, refresh: bool = False) -> None:
    """Fetch a light name/url/remaster_id projection per link-category for the
    Foundry->AON exact-link index, into data/aon_links/<category>.json."""
    cfg.aon_links_dir.mkdir(parents=True, exist_ok=True)
    for category in AON_LINK_CATEGORIES:
        path = cfg.aon_links_dir / f"{category}.json"
        if path.exists() and not refresh:
            continue
        body = json.dumps(
            {
                "size": 10000,
                "query": {"match": {"category": category}},
                "_source": ["name", "url", "remaster_id"],
            }
        ).encode()
        req = urllib.request.Request(
            cfg.aon_es_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.load(resp)
        docs = [hit["_source"] for hit in data["hits"]["hits"]]
        with path.open("w", encoding="utf-8") as f:
            json.dump(docs, f)
        print(f"  link-cached {category:12} {len(docs)}")


def run_ingest(cfg: Config, refresh: bool = False) -> None:
    """Fetch all content sources and build the SQLite index."""
    print(f"Ensuring Foundry repo at {cfg.foundry_dir} ...")
    _ensure_foundry_repo(cfg)
    print(f"Ensuring AON cache at {cfg.aon_dir} (refresh={refresh}) ...")
    _ensure_aon_cache(cfg, refresh=refresh)
    print(f"Ensuring AON link cache at {cfg.aon_links_dir} (refresh={refresh}) ...")
    _ensure_aon_link_cache(cfg, refresh=refresh)
    link_index = build_link_index(cfg.aon_links_dir)
    print("Building index ...")
    counts = build_index(
        cfg,
        [FoundrySource(cfg.foundry_packs_root, link_index), AonSource(cfg.aon_dir)],
    )
    total = sum(counts.values())
    print(f"Indexed {total} entries into {cfg.db_path}")
    for cat in sorted(counts):
        print(f"  {cat:18} {counts[cat]}")


def ensure_index(cfg: Config) -> None:
    """Build the index if it doesn't exist yet (used by setup and the bot)."""
    if not cfg.db_path.exists():
        run_ingest(cfg)


def main() -> None:
    refresh = "--refresh" in sys.argv[1:]
    run_ingest(Config.from_env(), refresh=refresh)


if __name__ == "__main__":
    main()
