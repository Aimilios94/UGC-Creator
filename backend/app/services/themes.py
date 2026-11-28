"""Themes (plan §9, M2 item 3): one YAML per theme in app/themes/, loaded here. DB-free.

A theme gives an ad its defaults: the tone of voice, how lines are written, the settings, props and
pace, the caption style, colours and font, the music bed, the end card's look, and scene and hook
ideas (Sport also has a football pack). A new theme is a new YAML file; no code changes.

Who wins (D25, D27, D31): the user's story, answers and brief always lead; the brand kit's tone,
colours and font beat the theme's; the theme fills only what nobody set. Scene and hook ideas are
offered to the writer only when there is no story of the user's.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from ..models import HEX_COLOR, CaptionStyle, Font, HookFormula, Tone

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"
FORMULAS = ("pov", "problem_first", "three_reasons", "unboxing_tease")


class Palette(BaseModel):
    primary: str = Field(pattern=HEX_COLOR)  # captions' headline box, the end card's button
    secondary: str = Field(pattern=HEX_COLOR)
    background: str = Field(pattern=HEX_COLOR)  # the end card


class EndCardLook(BaseModel):
    button: Literal["pill", "square"] = "pill"
    uppercase: bool = False  # the button's words in capitals


class HookIdea(BaseModel):
    formula: HookFormula
    idea: str = Field(min_length=10, max_length=200)


class Pack(BaseModel):
    """Extra ideas used when the brief is about something specific (Sport's football pack)."""

    title: str
    keywords: list[str] = Field(min_length=1)  # whole words in the product name or description
    scene_ideas: list[str] = Field(min_length=2)
    hook_ideas: list[HookIdea] = Field(min_length=2)

    def matches(self, text: str) -> bool:
        return any(re.search(rf"\b{re.escape(k)}\b", text, re.I) for k in self.keywords)


class ThemeSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,30}$")
    title: str = Field(min_length=2, max_length=30)
    summary: str = Field(min_length=10, max_length=160)  # one line on the create page
    tone: Tone  # the voiceover's tone and the writer's, unless the brand kit sets one
    writing: str = Field(min_length=10, max_length=300)  # how lines are written
    setting: str = Field(min_length=10, max_length=400)  # settings, props and pace
    captions: CaptionStyle
    font: Font
    palette: Palette
    music: str  # a bed in app/music/music.yaml
    end_card: EndCardLook = EndCardLook()
    scene_ideas: list[str] = Field(min_length=3, max_length=10)
    hook_ideas: list[HookIdea] = Field(min_length=4, max_length=12)
    packs: dict[str, Pack] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _every_formula(self):
        missing = set(FORMULAS) - {h.formula for h in self.hook_ideas}
        if missing:
            raise ValueError(f"theme {self.id}: no hook idea for {', '.join(sorted(missing))}")
        return self

    def pack_for(self, text: str) -> Pack | None:
        return next((p for p in self.packs.values() if p.matches(text)), None)


@lru_cache(maxsize=1)
def load_themes() -> dict[str, ThemeSpec]:
    """Every theme file, in a fixed order (by file name). A broken file fails loudly at start-up."""
    themes: dict[str, ThemeSpec] = {}
    for path in sorted(THEMES_DIR.glob("*.yaml")):
        spec = ThemeSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if spec.id != path.stem:
            raise ValueError(f"{path.name}: id {spec.id!r} must match the file name")
        themes[spec.id] = spec
    return themes


def theme_for(theme_id: str | None) -> ThemeSpec | None:
    return load_themes().get(theme_id or "")


def writer_block(theme: ThemeSpec, *, product_text: str, has_story: bool, brand_tone: str | None) -> str:
    """The <theme> block for the storyboard writer: data, never instructions. The tone is left out
    when the brand kit sets one; scene and hook ideas only when the user gave no story."""
    data: dict = {"name": theme.title, "writing": theme.writing, "settings_props_pace": theme.setting}
    if not brand_tone:
        data["tone_of_voice"] = theme.tone
    if not has_story:
        pack = theme.pack_for(product_text)
        scenes = list(theme.scene_ideas) + (pack.scene_ideas if pack else [])
        hooks = list(theme.hook_ideas) + (pack.hook_ideas if pack else [])
        data["scene_ideas"] = scenes
        data["hook_ideas"] = [h.model_dump(mode="json") for h in hooks]
        if pack:
            data["pack"] = pack.title
    return "<theme>" + json.dumps(data, ensure_ascii=False) + "</theme>"
