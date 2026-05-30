"""Selects a Retriever implementation from config. Future vector/hybrid slot here."""

from __future__ import annotations

from pf_helper.config import Config
from pf_helper.retrieval.base import Retriever
from pf_helper.retrieval.fts5 import Fts5Retriever


def build_retriever(cfg: Config) -> Retriever:
    if cfg.retriever == "fts5":
        return Fts5Retriever(cfg.db_path)
    raise ValueError(f"Unknown retriever: {cfg.retriever!r}")
