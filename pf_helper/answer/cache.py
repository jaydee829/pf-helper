"""Persistent exact-match (normalized) cache for /ask answers.

Keyed by the normalized question, stamped with an index-version token so a
re-ingest busts stale rulings, with a TTL and a size cap. Not semantic.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from pf_helper.answer.base import Answer

_WS = re.compile(r"\s+")
_EDGE_PUNCT = re.compile(r"^\W+|\W+$")  # \W is non-word; strips leading/trailing punctuation
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

# Function words + rules-question framing words. The framing words are the main
# tuning lever: they collapse keyword-dominated paraphrases to the same token.
_STOPWORDS: frozenset[str] = frozenset(
    (
        # function words
        "a am an and are as at be by can could do does did for from how i if in into "
        "is it me my of on or should that the their them then there this to use what "
        "when where which who why will with would you your "
        # rules-question framing words
        "again happen happens mean means rule rules work works explain tell about"
    ).split()
)


def _stem(w: str) -> str:
    """Deliberately crude suffix stripping; only needs to be consistent.

    Length guards keep a >=2-3 char stem so short words aren't mangled.
    """
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _content_tokens(question: str) -> frozenset[str]:
    """Salient stemmed content tokens (stopwords + framing words removed)."""
    raw = _TOKEN_SPLIT.split(question.lower())
    return frozenset(_stem(t) for t in raw if t and t not in _STOPWORDS)


def _jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    """Jaccard similarity of two token sets (0.0 when both are empty)."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def normalize_question(question: str) -> str:
    """Lowercase, collapse whitespace, strip surrounding punctuation (incl. '?')."""
    q = _WS.sub(" ", question.strip().lower())
    return _EDGE_PUNCT.sub("", q)


def index_version(index_db_path: Path) -> str:
    """Cheap version token for the rules index: mtime + size."""
    try:
        st = Path(index_db_path).stat()
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return "missing"


class AnswerCache:
    def __init__(
        self,
        path: str | Path,
        index_db_path: str | Path,
        ttl_days: int = 30,
        max_rows: int = 500,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.index_db_path = Path(index_db_path)
        self.ttl_seconds = ttl_days * 86400
        self.max_rows = max_rows
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS answers ("
            "norm TEXT PRIMARY KEY, text TEXT NOT NULL, sources_json TEXT NOT NULL, "
            "index_version TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, question: str) -> Answer | None:
        norm = normalize_question(question)
        row = self._conn.execute("SELECT * FROM answers WHERE norm = ?", (norm,)).fetchone()
        if row is None:
            return None
        stale = row["index_version"] != index_version(self.index_db_path)
        expired = (time.time() - row["created_at"]) > self.ttl_seconds
        if stale or expired:
            self._conn.execute("DELETE FROM answers WHERE norm = ?", (norm,))
            self._conn.commit()
            return None
        sources = [tuple(s) for s in json.loads(row["sources_json"])]
        return Answer(text=row["text"], sources=sources, engine="cache")

    def put(self, question: str, answer: Answer) -> None:
        norm = normalize_question(question)
        self._conn.execute(
            "INSERT OR REPLACE INTO answers (norm, text, sources_json, index_version, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                norm,
                answer.text,
                json.dumps([list(s) for s in answer.sources]),
                index_version(self.index_db_path),
                time.time(),
            ),
        )
        self._conn.execute(
            "DELETE FROM answers WHERE norm NOT IN "
            "(SELECT norm FROM answers ORDER BY created_at DESC LIMIT ?)",
            (self.max_rows,),
        )
        self._conn.commit()
