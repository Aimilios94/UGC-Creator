"""Music beds: one licensed CC0 bed per theme (app/music/, record in docs/MUSIC.md). DB-free."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

MUSIC_DIR = Path(__file__).resolve().parents[1] / "music"


@lru_cache
def manifest() -> dict:
    return yaml.safe_load((MUSIC_DIR / "music.yaml").read_text(encoding="utf-8"))


def music_for(brief, default_theme: str) -> Path | None:
    """The bed the brief asks for: none, the theme's (default), or a named one."""
    if brief.music == "none":
        return None
    if brief.music == "theme":
        return bed_for(brief.theme, default_theme)
    return bed_for(brief.music, default_theme)


def bed_for(theme: str | None, default_theme: str) -> Path:
    """The bed for the brief's theme, or the default theme's bed when it has none."""
    beds = manifest()
    entry = beds.get(theme or "") or beds[default_theme]
    return MUSIC_DIR / entry["file"]
