"""Configuration for the answering layer (engine choice + cache knobs)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pf_helper.config import Config


@dataclass(frozen=True)
class AnswerConfig:
    engine: str = "auto"  # "auto" (A->B) | "a" | "b"
    cache_enabled: bool = True
    cache_ttl_days: int = 30
    cache_max: int = 500
    core: Config = field(default_factory=Config.from_env)

    @classmethod
    def from_env(cls) -> AnswerConfig:
        return cls(
            engine=os.environ.get("PF_HELPER_ASK_ENGINE", "auto").lower(),
            cache_enabled=os.environ.get("PF_HELPER_ASK_CACHE", "1") != "0",
            cache_ttl_days=int(os.environ.get("PF_HELPER_ASK_CACHE_TTL_DAYS", "30")),
            cache_max=int(os.environ.get("PF_HELPER_ASK_CACHE_MAX", "500")),
            core=Config.from_env(),
        )
