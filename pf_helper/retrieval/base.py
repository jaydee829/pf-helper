"""Retriever interface. Implementations: Fts5Retriever (v1); Vector/Hybrid later."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pf_helper.models import EntryDetail, SearchHit

MAX_LIMIT = 50


class Retriever(ABC):
    @abstractmethod
    def search(self, query: str, category: str | None, limit: int) -> list[SearchHit]: ...

    @abstractmethod
    def get(self, name: str, category: str | None) -> EntryDetail | None: ...
