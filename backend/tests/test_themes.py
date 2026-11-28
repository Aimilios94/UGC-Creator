"""Themes (plan §9, M2 item 3): the YAML files, who wins, and what reaches the writer and the ad."""

from __future__ import annotations

import re

import pytest

from app.models import BrandKit, Brief
from app.services import compose as C
from app.services.music import manifest, music_for
from app.services.pipeline import DEFAULT_BRANDING, _branding, theme_branding
from app.services.platform_specs import safe_zone
from app.services.storyboard import build_prompt
from app.services.themes import FORMULAS, THEMES_DIR, load_themes, theme_for, writer_block
from conftest import BRIEF
from helpers import create_job

PLAN_THEMES = {"sport", "beauty", "tech", "food", "fashion"}
FONT_FILES = {"Inter": "Inter.ttf", "Montserrat": "Montserrat.ttf", "Bebas Neue": "BebasNeue.ttf",
              "Playfair Display": "PlayfairDisplay.ttf"}  # fmt: skip


def test_the_five_themes_of_the_plan_load_complete():
    themes = load_themes()
    assert set(themes) == PLAN_THEMES
    fonts_dir = THEMES_DIR.parent / "fonts"
    for t in themes.values():
        assert t.music in manifest(), t.id  # a real CC0 bed
        assert (fonts_dir / FONT_FILES[t.font]).exists(), t.id  # a bundled OFL font
        assert {h.formula for h in t.hook_ideas} == set(FORMULAS)
        assert len(t.scene_ideas) >= 3


def test_sport_has_the_football_pack_and_only_football_turns_it_on():
    sport = theme_for("sport")
    assert sport.pack_for("Grip socks for football, made for the pitch").title == "Football pack"
    assert sport.pack_for("Trail running shoes") is None
    assert sport.pack_for("A make-up kit") is None  # no loose words


def test_theme_ideas_make_no_claims_of_use_or_results():
    """The testimonial rule (D25) holds for the theme's own ideas: no "I", "my" or "me"."""
    for t in load_themes().values():
        hooks = [h.idea for h in t.hook_ideas] + [h.idea for p in t.packs.values() for h in p.hook_ideas]
        for line in hooks + t.scene_ideas:
            assert not re.search(r"\b(I|my|me|I've|I'm)\b", line), (t.id, line)


def test_writer_gets_ideas_only_without_a_story_and_the_brand_tone_wins():
    sport = theme_for("sport")
    free = writer_block(sport, product_text="Football boots", has_story=False, brand_tone=None)
    assert '"scene_ideas"' in free and '"hook_ideas"' in free and "Football pack" in free
    assert '"tone_of_voice": "energetic"' in free
    story = writer_block(sport, product_text="Football boots", has_story=True, brand_tone="calm")
    assert "scene_ideas" not in story and "hook_ideas" not in story and "tone_of_voice" not in story
    assert "settings_props_pace" in story  # the look of the world still helps where the story is silent


def test_build_prompt_carries_the_theme_and_never_replaces_the_story():
    brief = Brief.model_validate({**BRIEF, "theme": "food", "story": "A man opens the jar at night and smiles."})
    prompt = build_prompt(brief, None, brand=BrandKit(tone="premium"))
    assert "<theme>" in prompt and "scene_ideas" not in prompt and 'tone_of_voice": "playful' not in prompt
    assert "A man opens the jar at night and smiles." in prompt
    plain = build_prompt(Brief.model_validate({**BRIEF, "theme": None}), None)
    assert "<theme>" not in plain


def test_an_unknown_theme_is_refused(client, session_id, photo_bytes):
    with pytest.raises(ValueError):
        Brief.model_validate({**BRIEF, "theme": "space"})
    r = create_job(client, session_id, photo_bytes, brief={**BRIEF, "theme": "space"})
    assert r.status_code == 422


def test_themes_endpoint_lists_every_theme_for_the_create_page(client):
    r = client.get("/themes")
    assert r.status_code == 200
    rows = {t["id"]: t for t in r.json()}
    assert set(rows) == PLAN_THEMES
    assert rows["sport"]["packs"] == ["Football pack"] and rows["sport"]["music_title"]
    assert rows["beauty"]["captions"] == "clean" and rows["beauty"]["palette"]["primary"].startswith("#")


def test_the_theme_sets_the_look_and_the_brand_kit_wins():
    assert theme_branding(None) == DEFAULT_BRANDING
    sport = theme_branding("sport")
    assert (sport.font, sport.primary, sport.button, sport.uppercase) == ("Bebas Neue", "#f97316", "square", True)
    plain = _branding(None, {"brief": {"theme": "sport"}}, None)
    assert plain == sport
    kit = {"tone": None, "font": "Inter", "colors": {"primary": "#123456"}, "logo_key": None}
    mixed = _branding(None, {"brief": {"theme": "sport"}, "brand": kit}, None)
    assert (mixed.font, mixed.primary) == ("Inter", "#123456")  # the brand kit's values
    assert (mixed.background, mixed.button) == (sport.background, "square")  # the theme fills the rest


def test_the_theme_names_its_music_bed():
    brief = Brief.model_validate({**BRIEF, "theme": "beauty", "music": "theme"})
    assert music_for(brief, "food").name == manifest()[theme_for("beauty").music]["file"]


def test_end_card_button_follows_the_theme():
    zone = safe_zone("tiktok", "9:16")

    def card(branding):
        spec = C.ComposeSpec(scenes=[], master_ratio="9:16", platform="tiktok", cta_text="Shop now", branding=branding)
        img, ok, _ = C.render_end_card(spec, 540, 960, zone)
        assert ok
        return img.tobytes()

    pill, square = card(theme_branding("beauty")), card(theme_branding("sport"))
    assert pill != square
    # "SHOP NOW" in capitals (shown with Inter: Bebas Neue, the sport font, has only capitals)
    caps = {**theme_branding("sport").__dict__, "font": "Inter"}
    assert card(C.Branding(**caps)) != card(C.Branding(**{**caps, "uppercase": False}))
