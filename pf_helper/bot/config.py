"""Discord-bot configuration from env vars, falling back to config.toml."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pf_helper import userconfig


@dataclass(frozen=True)
class BotConfig:
    token: str
    guild_id: int | None = None

    @classmethod
    def from_env(cls) -> BotConfig:
        disc = userconfig.load_file_config().get("discord", {})
        token = os.environ.get("DISCORD_BOT_TOKEN") or disc.get("token")
        if not token:
            raise ValueError("DISCORD_BOT_TOKEN is required to run the bot (env or config.toml)")
        gid_env = os.environ.get("PF_HELPER_DISCORD_GUILD_ID")
        gid = gid_env if gid_env else disc.get("guild_id")
        return cls(token=str(token), guild_id=int(gid) if gid else None)
