"""Runtime configuration with sensible local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pf_helper import userconfig

_DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Config:
    data_dir: Path = _DEFAULT_DATA
    foundry_repo_url: str = "https://github.com/foundryvtt/pf2e"
    retriever: str = "fts5"
    aon_es_url: str = "https://elasticsearch.aonprd.com/aon/_search"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pf2e.db"

    @property
    def aon_dir(self) -> Path:
        return self.data_dir / "aon"

    @property
    def aon_links_dir(self) -> Path:
        return self.data_dir / "aon_links"

    @property
    def foundry_dir(self) -> Path:
        return self.data_dir / "foundry-pf2e"

    @property
    def foundry_packs_root(self) -> Path:
        # FoundrySource expects the dir containing `pf2e/`.
        return self.foundry_dir / "packs"

    @classmethod
    def from_env(cls) -> Config:
        file_cfg = userconfig.load_file_config()
        data = os.environ.get("PF_HELPER_DATA_DIR") or file_cfg.get("data_dir")
        data_dir = Path(data) if data else userconfig.data_dir_default()
        return cls(data_dir=data_dir)
