"""Best-effort append-only JSONL log of /ask queries, for offline cache tuning.

Never raises into the request path: a logging failure is swallowed (warned).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def log_query(path: str | Path, record: dict) -> None:
    """Append one JSON record as a line. Failures are logged, never raised."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        _log.warning("query log write failed: %s", exc)
    except (TypeError, ValueError) as exc:  # non-serializable record
        _log.warning("query log serialize failed: %s", exc)
