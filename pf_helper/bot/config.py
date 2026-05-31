"""Discord-bot configuration from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BotConfig:
    token: str
    guild_id: int | None = None

    @classmethod
    def from_env(cls) -> BotConfig:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            raise ValueError("DISCORD_BOT_TOKEN is required to run the bot")
        gid = os.environ.get("PF_HELPER_DISCORD_GUILD_ID")
        return cls(token=token, guild_id=int(gid) if gid else None)
