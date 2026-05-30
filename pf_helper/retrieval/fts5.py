"""SQLite FTS5-backed retriever."""

from __future__ import annotations

import json
from pathlib import Path

from pf_helper.models import EntryDetail, SearchHit
from pf_helper.retrieval.base import MAX_LIMIT, Retriever
from pf_helper.store import db

_EXCERPT_LEN = 240


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _EXCERPT_LEN else text[:_EXCERPT_LEN].rstrip() + "..."


class Fts5Retriever(Retriever):
    def __init__(self, db_path: str | Path):
        self._conn = db.connect(db_path)

    def close(self) -> None:
        self._conn.close()

    def search(self, query: str, category: str | None, limit: int) -> list[SearchHit]:
        limit = max(1, min(limit, MAX_LIMIT))
        rows = db.fts_search(self._conn, query, category, limit)
        return [
            SearchHit(
                id=row["id"],
                name=row["name"],
                category=row["category"],
                level=row["level"],
                excerpt=_excerpt(row["text"]),
            )
            for row in rows
        ]

    def get(self, name: str, category: str | None) -> EntryDetail | None:
        row = db.get_by_name(self._conn, name, category)
        if row is None:
            return None
        traits = [t for t in (row["traits"] or "").split(",") if t]
        stats = {label: value for label, value in json.loads(row["stats_json"] or "[]")}
        return EntryDetail(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            level=row["level"],
            traits=traits,
            source_book=row["source_book"],
            stats=stats,
            text=row["text"],
        )
