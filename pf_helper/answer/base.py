"""Core types for the shared answering layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Answer:
    """An LLM answer plus the AON sources it was grounded in."""

    text: str
    sources: list[tuple[str, str]] = field(default_factory=list)  # (name, source_url)
    engine: str = ""  # "agent" | "rag" | "cache"
    match_score: float | None = None  # fuzzy-cache similarity, when applicable
    matched_question: str | None = None  # the cached (normalized) question matched


class AnswerError(Exception):
    """An answering failure with a user-facing reason: 'auth' | 'quota' | 'error'."""

    def __init__(self, reason: str, message: str = ""):
        self.reason = reason
        super().__init__(message or reason)


class Answerer(ABC):
    """Produces an Answer for a question."""

    @abstractmethod
    async def answer(self, question: str) -> Answer: ...
