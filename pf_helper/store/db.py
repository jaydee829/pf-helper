"""SQLite + FTS5 storage helpers."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from pf_helper.models import Entry


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the server may serve tool calls from a worker
    # thread; the workload is read-mostly so SQLite's internal locking is safe.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    sql = resources.files("pf_helper.store").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def insert_entries(conn: sqlite3.Connection, entries: Iterable[Entry]) -> int:
    rows = [
        (
            e.id,
            e.name,
            e.category,
            ",".join(e.traits),
            e.level,
            e.source_book,
            e.text,
            json.dumps([list(pair) for pair in e.stats]),
            e.source_url,
            e.raw_json,
        )
        for e in entries
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO entries "
        "(id, name, category, traits, level, source_book, text, stats_json, source_url, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    # Sync strategy: this is an external-content FTS5 table with no triggers,
    # so we fully rebuild the index from the content table after writing. That
    # is O(n) and ideal for the intended bulk single-build workflow (Task 5).
    # If incremental writes are ever added, add FTS triggers instead.
    conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
    conn.commit()
    return len(rows)


def get_by_name(
    conn: sqlite3.Connection, name: str, category: str | None = None
) -> sqlite3.Row | None:
    if category:
        cur = conn.execute(
            "SELECT * FROM entries WHERE name = ? COLLATE NOCASE AND category = ? LIMIT 1",
            (name, category),
        )
    else:
        cur = conn.execute("SELECT * FROM entries WHERE name = ? COLLATE NOCASE LIMIT 1", (name,))
    return cur.fetchone()


def fts_search(
    conn: sqlite3.Connection, query: str, category: str | None = None, limit: int = 20
) -> list[sqlite3.Row]:
    match = _to_match_query(query)
    sql = (
        "SELECT e.*, bm25(entries_fts) AS score "
        "FROM entries_fts JOIN entries e ON e.rowid = entries_fts.rowid "
        "WHERE entries_fts MATCH ?"
    )
    params: list[object] = [match]
    if category:
        sql += " AND e.category = ?"
        params.append(category)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def _to_match_query(query: str) -> str:
    """Make a safe FTS5 MATCH string: quote each term, OR them together.

    Quoting each term as a phrase prevents arbitrary user input from being
    parsed as FTS5 syntax (no crashes/injection). Note: inside a quoted phrase
    FTS5 still treats a leading ``^`` as a row-start anchor and a trailing ``*``
    as a prefix operator -- surprising but harmless for rules-text queries.
    """
    terms = [t for t in query.replace('"', " ").split() if t]
    if not terms:
        return '""'
    return " OR ".join(f'"{t}"' for t in terms)
