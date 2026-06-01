"""FastMCP stdio server exposing PF2e retrieval tools.

Two tools: `search` (lean hits, category enum) and `get_entry` (full detail).
The server performs no LLM calls — Claude reasons over what these return.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from pf_helper.config import Config
from pf_helper.models import Category, EntryDetail, SearchHit
from pf_helper.retrieval.base import Retriever
from pf_helper.retrieval.factory import build_retriever

_log = logging.getLogger(__name__)

mcp = FastMCP("PF_Helper")

_cfg: Config = Config.from_env()
_retriever: Retriever | None = None
# Guards lazy _retriever init. Today's stdio transport runs sync tools on the
# event-loop thread (no concurrency), but a non-stdio transport could dispatch
# from a thread pool; the lock keeps the lazy init a correct singleton either way.
_lock = threading.Lock()


def configure(cfg: Config) -> None:
    """Override config and reset the cached retriever (used by tests and main)."""
    global _cfg, _retriever
    _cfg = cfg
    _retriever = None


def _get_retriever() -> Retriever | None:
    global _retriever
    if _retriever is None:
        with _lock:
            if _retriever is None:
                if not Path(_cfg.db_path).exists():
                    _log.warning(
                        "Index not found at %s -- run `pf-helper-ingest` to build it.",
                        _cfg.db_path,
                    )
                    return None
                _retriever = build_retriever(_cfg)
    return _retriever


@mcp.tool()
def search(query: str, category: Category | None = None, limit: int = 10) -> list[SearchHit]:
    """Search Pathfinder 2e rules. Returns lean ranked hits (name, category,
    level, excerpt, id). Use `category` to scope; call `get_entry` for full text.
    Returns an empty list if the index has not been built yet (run the
    `pf-helper-ingest` command to populate it).
    Each hit includes a `source_url` (its Archives of Nethys / AON page) — cite
    it when you answer."""
    r = _get_retriever()
    if r is None:
        return []
    cat = str(category) if category is not None else None
    return r.search(query, category=cat, limit=limit)


@mcp.tool()
def get_entry(name: str, category: Category | None = None) -> EntryDetail | None:
    """Fetch the full cleaned text of one PF2e entry by exact name (optionally
    scoped by category). Returns None if not found.
    The result includes a `source_url` (its Archives of Nethys / AON page); cite
    it when you answer."""
    r = _get_retriever()
    if r is None:
        return None
    cat = str(category) if category is not None else None
    return r.get(name, category=cat)


def _require_index(cfg: Config) -> None:
    if not Path(cfg.db_path).exists():
        print(
            f"No rules index at {cfg.db_path} — run `pf-helper setup` (or `pf-helper ingest`).",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> None:
    cfg = Config.from_env()
    _require_index(cfg)
    configure(cfg)
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
