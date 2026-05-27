"""Prompt loader. Reads the markdown files shipped next to this module."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    """Return the contents of `<name>.md`. Raises FileNotFoundError if missing."""
    path = _DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
