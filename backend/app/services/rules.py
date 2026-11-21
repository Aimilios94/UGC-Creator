"""The rules files each AI step loads (strategy plan, D31). DB-free.

The rules live in `app/prompts/rules/` as Markdown, versioned in git. Each AI step loads the
shared rules plus the rules of its own path (video or image), and nothing else. Phase 1: the
files and this loader exist; the AI steps switch to them in later phases.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

RULES_DIR = Path(__file__).resolve().parents[1] / "prompts" / "rules"
Step = Literal["slot_filler", "writer", "continuity", "shorten"]
Kind = Literal["video", "image"]

FILES = ("shared", "video", "image")


@cache
def load(name: str) -> str:
    """One rules file's text ("shared", "video" or "image")."""
    if name not in FILES:
        raise ValueError(f"unknown rules file: {name}")
    return (RULES_DIR / f"rules_{name}.md").read_text(encoding="utf-8").strip()


def files_for(step: Step, kind: Kind = "video") -> tuple[str, ...]:
    """Which files an AI step loads: the slot filler and the writer follow the ad's path; the
    continuity check and "Shorten it for me" exist only for video."""
    if step in ("slot_filler", "writer"):
        return ("shared", kind)
    return ("shared", "video")


def rules_for(step: Step, kind: Kind = "video") -> str:
    return "\n\n".join(load(name) for name in files_for(step, kind))
