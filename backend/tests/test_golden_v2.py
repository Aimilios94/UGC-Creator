"""Golden prompts v2 (strategy plan, D31): every fixture loads, maps to a brief, and every expected
result is either checked now or reported with the phase that will check it. DB-free.

Phase 1 checks the fixed rules (A2, A6) and the projected cost under the safety cap; phase 2 the
scene count and lengths from the scene splitter. The rest arrive with the slot filler and the
length line (3), the clip builder (4), the questions (5) and the image path (6)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.models import Brief, Hook, ProductAnalysis, Scene, Storyboard
from app.services.llm_trace import usd_to_eur
from app.services.pipeline import estimate_board_usd
from app.services.providers.llm import build_llm, mock_analysis
from app.services.scene_splitter import split_story
from app.services.storyboard import write_storyboard
from app.services.video_gen import RULES_MAX, clip_rules
from conftest import make_settings

GOLDEN = Path(__file__).parent / "fixtures" / "golden_v2"
FIXTURES = sorted(GOLDEN.glob("*.json"))
CHECKED_NOW = 2

# The phase of the plan that can check each expected result.
PHASE = {
    "blocked": 3,
    "scene_count": 2,
    "scene_lengths_s": 2,
    "clip_durations": 4,
    "user_scene_text_kept_verbatim": 4,
    "user_text_kept_verbatim_somewhere": 3,
    "scenes_1_and_3_action_verbatim": 4,
    "every_key_slot_filled_or_marked_ai_guess": 3,
    "questions": 5,
    "question_buttons_per_question": 5,
    "question_has_let_ai_decide": 5,
    "max_clip_prompt_chars": 4,
    "max_projected_cost": 1,
    "projected_cost_shown_on_storyboard": 3,
    "projected_cost_eur_approx": 1,
    "projected_cost_tolerance_eur": 1,
    "tradeoff_offered": 3,
    "length_picker_max_seconds": 1,
    "route": 6,
    "picture_source_per_scene": 6,
    "product_slot_source_in": 3,
    "product_description_mentions": 3,
    "fixed_rules_product_line": 1,
    "fixed_rules_must_not_contain": 1,
    "no_photo_note_shown": 6,
    "real_total_seconds": 3,
    "length_mismatch_line_shown": 3,
    "buttons": 3,
    "no_scene_stretched": 3,
    "no_hold_frame_added_to_fill_length": 3,
    "photo_person_visible": 6,
    "photo_face_visible": 6,
    "character_reference": 6,
    "extra_reference_pictures": 6,
    "live_review": 0,  # read by a person after a live run
    "scene_N.clip_seconds": 4,
    "scene_N.clip_must_not_contain_whole_word": 4,
    "scene_N.clip_contains_all": 4,
    "scene_N.ai_changed": 4,
    "scene_N.ai_changed_reason_mentions_any": 4,
    "scene_N.clip_must_not_contain_any": 4,
    "scene_N.undo_available": 4,
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _keys(expect: dict) -> list[str]:
    out = []
    for key, value in expect.items():
        if re.fullmatch(r"scene_\d+", key):
            out += [f"scene_N.{k}" for k in value]
        else:
            out.append(key)
    return out


def brief_from_fixture(inp: dict) -> Brief:
    """The fixture's input as the app's brief (the photo and the ad kind travel separately)."""
    return Brief(
        product_name=inp["product_name"],
        description=inp["brief"],
        story=inp.get("story") or "",
        video_length_s=None if inp["length"] == "auto" else int(inp["length"]),
        visual_style=inp["style"],
    )


def board_from_lengths(lengths: list[int], continuity: str = "continuous") -> Storyboard:
    scenes = [
        Scene(role="demo", description="d", image_prompt="i", motion_prompt="m", voiceover="A short spoken line.",
              duration_s=n)
        for n in lengths
    ]  # fmt: skip
    hooks = [Hook(formula=f, text="h") for f in ("pov", "problem_first", "three_reasons")]
    return Storyboard(title="t", scenes=scenes, hooks=hooks, cta_text="Shop", continuity=continuity)


def test_there_are_fixtures_and_their_ids_are_unique():
    ids = [_load(p)["id"] for p in FIXTURES]
    assert len(ids) >= 7 and len(set(ids)) == len(ids)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_each_fixture_is_well_formed_and_maps_to_a_brief(path):
    fx = _load(path)
    assert set(fx["runs_in"]) <= {"ci", "live"} and fx["runs_in"]
    inp = fx["input"]
    assert inp["kind"] in ("video", "image") and inp["mode"] in ("connected", "separate")
    assert inp["photo"] is None or (Path(inp["photo"]).suffix in (".jpg", ".png") and "/" not in inp["photo"])
    brief = brief_from_fixture(inp)
    assert brief.story == (inp.get("story") or "").strip()
    unmapped = [k for k in _keys(fx["expect"]) if k not in PHASE]
    assert not unmapped, f"expected results with no phase to check them: {unmapped}"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_phase_1_checks(path):
    fx = _load(path)
    inp, expect = fx["input"], fx["expect"]
    has_photo = inp["photo"] is not None
    if "fixed_rules_product_line" in expect:
        rules = clip_rules(style=inp["style"], duration_s=5, used_s=5, idx=0, count=1, continuous=True,
                           ends_on_next=False, has_photo=has_photo)  # fmt: skip
        assert expect["fixed_rules_product_line"] in rules
        assert expect["fixed_rules_must_not_contain"] not in rules
        assert len(rules) <= RULES_MAX
    if "length_picker_max_seconds" in expect:
        assert Brief.model_fields["video_length_s"].metadata[-1].le == expect["length_picker_max_seconds"]
    lengths = expect.get("scene_lengths_s")
    if lengths and "max_projected_cost" in expect:
        s = make_settings()
        assert expect["max_projected_cost"] == "config.job_cost_cap_eur"
        images, video = estimate_board_usd(s, board_from_lengths(lengths))
        eur = usd_to_eur(images + video, s.usd_to_eur_rate)
        assert eur <= s.job_cost_cap_eur  # quality first: the planned ad fits the safety cap as asked
        if "projected_cost_eur_approx" in expect:
            assert abs(eur - expect["projected_cost_eur_approx"]) <= expect["projected_cost_tolerance_eur"], eur


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_phase_2_checks(path):
    """The scene splitter: the scene count and lengths come from the story in code, whatever the
    writer does (the mock writer here; the real one gets the same corrections)."""
    fx = _load(path)
    expect = fx["expect"]
    if "scene_count" not in expect and "scene_lengths_s" not in expect:
        pytest.skip("no scene count or lengths to check")
    brief = brief_from_fixture(fx["input"])
    analysis = ProductAnalysis.model_validate(mock_analysis(brief.model_dump()))
    board, _ = write_storyboard(build_llm(make_settings(), "storyboard"), brief, analysis)
    if "scene_count" in expect:
        assert expect["scene_count"]["min"] <= len(board.scenes) <= expect["scene_count"]["max"]
    if "scene_lengths_s" in expect:
        assert [s.duration_s for s in board.scenes] == expect["scene_lengths_s"]  # as asked, never stretched
    split = split_story(brief.story)
    for scene, beat in zip(board.scenes, split.beats, strict=False):
        assert scene.description == beat.text  # the user's words for the scene, whole


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_later_phases_are_listed_not_dropped(path):
    fx = _load(path)
    pending = sorted({(PHASE[k], k) for k in _keys(fx["expect"]) if PHASE[k] > CHECKED_NOW})
    if fx["runs_in"] == ["live"]:
        pytest.skip("live fixture: run by hand with the real writer (owner's go)")
    if pending:
        pytest.skip("to check in later phases: " + ", ".join(f"{k} (phase {n})" for n, k in pending))
