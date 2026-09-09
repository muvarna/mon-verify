from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(slots=True)
class AppConfig:
    rules_path: Path
    cache_dir: Path = Path("data/raw")
    output_dir: Path = Path("data/output")
    wos_api_key: str | None = None
    scopus_api_key: str | None = None
    scopus_insttoken: str | None = None

    @classmethod
    def from_env(cls, rules_path: str | Path = "config/rules_2025.yaml") -> "AppConfig":
        load_dotenv()
        return cls(
            rules_path=Path(rules_path),
            wos_api_key=os.getenv("WOS_API_KEY"),
            scopus_api_key=os.getenv("SCOPUS_API_KEY"),
            scopus_insttoken=os.getenv("SCOPUS_INSTTOKEN"),
        )

    def rules(self) -> dict[str, Any]:
        with self.rules_path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
