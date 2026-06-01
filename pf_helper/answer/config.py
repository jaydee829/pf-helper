"""Configuration for the answering layer (provider + engine choice + cache knobs)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pf_helper import userconfig
from pf_helper.config import Config


@dataclass(frozen=True)
class AnswerConfig:
    provider: str = "claude-sdk"  # "claude-sdk" | "litellm"
    litellm_model: str = ""  # e.g. "gemini/gemini-2.5-pro", "ollama/llama3.1"
    litellm_api_base: str | None = None  # for local/self-hosted endpoints
    engine: str = "auto"  # "auto" (A->B) | "a" | "b"
    cache_enabled: bool = True
    cache_ttl_days: int = 30
    cache_max: int = 500
    cache_similarity: float = 0.5  # Jaccard threshold; 0 disables the fuzzy pass
    query_log_enabled: bool = True
    core: Config = field(default_factory=Config.from_env)

    @classmethod
    def from_env(cls) -> AnswerConfig:
        ask = userconfig.load_file_config().get("ask", {})
        lite = ask.get("litellm", {})
        _env_prov = os.environ.get("PF_HELPER_ASK_PROVIDER")
        provider = (_env_prov or ask.get("provider") or "claude-sdk").lower()
        model = os.environ.get("PF_HELPER_ASK_LITELLM_MODEL") or lite.get("model") or ""
        api_base = os.environ.get("PF_HELPER_ASK_LITELLM_API_BASE") or lite.get("api_base") or None
        return cls(
            provider=provider,
            litellm_model=model,
            litellm_api_base=api_base,
            engine=os.environ.get("PF_HELPER_ASK_ENGINE", "auto").lower(),
            cache_enabled=os.environ.get("PF_HELPER_ASK_CACHE", "1") != "0",
            cache_ttl_days=int(os.environ.get("PF_HELPER_ASK_CACHE_TTL_DAYS", "30")),
            cache_max=int(os.environ.get("PF_HELPER_ASK_CACHE_MAX", "500")),
            cache_similarity=float(os.environ.get("PF_HELPER_ASK_CACHE_SIMILARITY", "0.5")),
            query_log_enabled=os.environ.get("PF_HELPER_ASK_QUERY_LOG", "1") != "0",
            core=Config.from_env(),
        )
