"""Calculation engines (pure functions over data already stored by the collectors).

Nothing here fetches from external sources or invents values: every output is
computed from stored observations/forecasts, and inputs that are missing stay
missing (None) with the reason reported.
"""
import json
from functools import lru_cache
from pathlib import Path

ENGINES_CONFIG = Path(__file__).resolve().parent.parent / "config" / "engines.json"


@lru_cache
def engine_config() -> dict:
    return json.loads(ENGINES_CONFIG.read_text(encoding="utf-8"))
