"""Loader settings.yaml — nguồn sự thật duy nhất của hằng số (PLAN M0: code không hardcode)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"


@lru_cache(maxsize=1)
def settings() -> dict:
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)
