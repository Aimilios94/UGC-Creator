"""Golden prompts v2 (strategy plan, D31): every fixture loads, maps to a brief, and every expected
result is either checked now or reported with the phase that will check it. DB-free.

Phase 1 checks the fixed rules (A2, A6) and the projected cost under the safety cap; phase 2 the
scene count and lengths from the scene splitter; phase 3 the slot filler's marks, the product slot
and the real-length line. The rest arrive with the clip builder (4), the questions (5) and the image
path (6)."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from app.models import Brief, Hook, JobView, ProductAnalysis, QuestionView, Scene, Storyboard, render_seconds
from app.services import compose as compose_module
from app.services.ad_structure import AdStructure, key_gaps
from app.services.continuity import check_continuity
from app.services.image_gen import character_reference, plan_scene_image
from app.services.llm_trace import usd_to_eur
from app.services.pipeline import clip_texts, estimate_board_usd
from app.services.providers.llm import build_llm, mock_analysis
from app.services.providers.media import InputImage
from app.services.scene_plan import length_line, real_length
from app.services.scene_splitter import split_story
from app.services.slot_filler import LET_AI_DECIDE, fill_slots, open_questions
from app.services.storyboard import write_storyboard
from app.services.video_gen import RULES_MAX, clip_rules
from conftest import make_settings

GOLDEN = Path(__file__).parent / "fixtures" / "golden_v2"
FIXTURES = sorted(GOLDEN.glob("*.json"))
CHECKED_NOW = 5

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


PHASE_3_KEYS = {k for k, n in PHASE.items() if n == 3}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_phase_3_checks(path):
    """The slot filler (mock writer): every key slot filled or marked as the AI's guess, the user's
    words kept, the product slot's source; the real-length line and its buttons; the cost shown."""
    fx = _load(path)
    expect = fx["expect"]
    if "ci" not in fx["runs_in"] or not PHASE_3_KEYS & set(expect):
        pytest.skip("no phase 3 checks in CI for this fixture")
    inp = fx["input"]
    brief = brief_from_fixture(inp)
    analysis = ProductAnalysis.model_validate(mock_analysis(brief.model_dump())) if inp["photo"] else None
    s = make_settings()
    (ad, split), _ = fill_slots(build_llm(s, "slots"), brief, analysis, split_story(brief.story))
    board, _ = write_storyboard(
        build_llm(s, "storyboard"), brief, analysis or mock_photo_analysis(brief), split=split, structure=ad
    )
    structure = AdStructure.model_validate(board.structure)
    durations = [sc.duration_s for sc in board.scenes]
    line = length_line(durations, brief.video_length_s, s.end_card_s)
    if expect.get("every_key_slot_filled_or_marked_ai_guess"):
        assert key_gaps(structure) == []
    if text := expect.get("user_text_kept_verbatim_somewhere"):
        kept = [board.notes, *(sc.description for sc in board.scenes), *(c.text.value for c in structure.scenes)]
        assert any(text in k for k in kept)
    if "product_slot_source_in" in expect:
        assert structure.sheet.product.source in expect["product_slot_source_in"]
    for word in expect.get("product_description_mentions", []):
        assert word in structure.sheet.product.value.lower()
    if "blocked" in expect or expect.get("projected_cost_shown_on_storyboard"):
        images, video = estimate_board_usd(s, board)
        eur = usd_to_eur(images + video, s.usd_to_eur_rate)
        assert eur > 0 and "estimate" in JobView.model_fields  # the storyboard shows the projected cost
        assert (eur > s.job_cost_cap_eur) == expect.get("blocked", False)
    if "tradeoff_offered" in expect:
        assert (line is not None) == expect["tradeoff_offered"]  # nothing to trade: the ad is as asked
    if "real_total_seconds" in expect:
        assert real_length(durations, s.end_card_s) == expect["real_total_seconds"]
    if "length_mismatch_line_shown" in expect:
        assert line is not None and line["text"] == expect["length_mismatch_line_shown"]
    if "buttons" in expect:
        assert [line["add"], line["keep"]] == expect["buttons"]
    if expect.get("no_scene_stretched"):
        assert durations == [b.seconds for b in split.beats]  # the user's seconds, as written
    if expect.get("no_hold_frame_added_to_fill_length"):
        # Compose plays the scenes as they are, then the end card: it never reads the picked length.
        assert "video_length_s" not in inspect.getsource(compose_module)


PHASE_4_KEYS = {k for k, n in PHASE.items() if n == 4}


def built_ad(fx: dict):
    """The fixture through the slot filler, the writer and the continuity check (mock), and every
    clip as the worker would send it."""
    inp = fx["input"]
    brief = brief_from_fixture(inp)
    analysis = ProductAnalysis.model_validate(mock_analysis(brief.model_dump())) if inp["photo"] else None
    s = make_settings()
    (ad, split), _ = fill_slots(build_llm(s, "slots"), brief, analysis, split_story(brief.story))
    board, _ = write_storyboard(
        build_llm(s, "storyboard"), brief, analysis or mock_photo_analysis(brief), split=split, structure=ad
    )
    board, _ = check_continuity(build_llm(s, "continuity"), board, brief)
    return brief, board, clip_texts(s, board, brief)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_phase_4_checks(path):
    """The clip builder (mock writer): the user's words reach the clip word for word, every clip
    within the 2,310 budget, each scene's clip length, no cut inside a take."""
    fx = _load(path)
    expect = fx["expect"]
    keys = set(_keys(expect))
    if "ci" not in fx["runs_in"] or not PHASE_4_KEYS & keys:
        pytest.skip("no phase 4 checks in CI for this fixture")
    brief, board, clips = built_ad(fx)
    structure = AdStructure.model_validate(board.structure)
    if limit := expect.get("max_clip_prompt_chars"):
        assert all(c.chars <= limit for c in clips), [c.chars for c in clips]
        assert all(c.too_long_by == 0 for c in clips)
    if "clip_durations" in expect:
        assert [str(render_seconds(sc.duration_s)) for sc in board.scenes] == expect["clip_durations"]
    if expect.get("user_scene_text_kept_verbatim"):
        for card, clip in zip(structure.scenes, clips, strict=True):
            assert card.text.source == "user" and card.text.value in clip.text
    for n, sc in enumerate(board.scenes, start=1):
        want = expect.get(f"scene_{n}") or {}
        text = clips[n - 1].text
        if "clip_seconds" in want:
            assert render_seconds(sc.duration_s) == want["clip_seconds"]
        if word := want.get("clip_must_not_contain_whole_word"):
            assert not re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text, re.I), text
        for part in want.get("clip_contains_all", []):
            assert part in text
        for part in want.get("clip_must_not_contain_any", []):
            assert part not in text


PHASE_5_KEYS = {k for k, n in PHASE.items() if n == 5}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_phase_5_checks(path):
    """Quick questions (mock slot filler): how many code keeps, their buttons, "Let the AI decide"."""
    fx = _load(path)
    expect = fx["expect"]
    if "ci" not in fx["runs_in"] or not PHASE_5_KEYS & set(expect):
        pytest.skip("no phase 5 checks in CI for this fixture")
    inp = fx["input"]
    brief = brief_from_fixture(inp)
    analysis = ProductAnalysis.model_validate(mock_analysis(brief.model_dump())) if inp["photo"] else None
    (ad, _), _ = fill_slots(build_llm(make_settings(), "slots"), brief, analysis, split_story(brief.story))
    questions = open_questions(ad)
    if want := expect.get("questions"):
        assert want["min"] <= len(questions) <= want["max"]
    if want := expect.get("question_buttons_per_question"):
        assert all(want["min"] <= len(q.options) <= want["max"] for q in questions)
    if expect.get("question_has_let_ai_decide"):
        assert QuestionView(slot="who", text="t", options=["a", "b"]).let_ai_decide == LET_AI_DECIDE


# In CI a photo's reader flags come from its name (the repo is public, the owner's photos stay local);
# a live run reads the real photo.
PHOTO_FLAGS = {
    "hoodie_person_face.jpg": {"people_in_photo": True, "face_visible": True,
                               "person_look": "woman in her late 20s, long dark hair, warm brown skin"},
    "mug_hand_no_face.jpg": {"people_in_photo": True, "face_visible": False},
}  # fmt: skip
A4_KEYS = {"photo_person_visible", "photo_face_visible", "character_reference", "extra_reference_pictures"}


def photo_analysis(brief: Brief, photo: str | None) -> ProductAnalysis | None:
    if not photo:
        return None
    return ProductAnalysis.model_validate({**mock_analysis(brief.model_dump()), **PHOTO_FLAGS.get(photo, {})})


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_phase_6_character_reference(path):
    """A4: a person whose face shows in the photo is the reference for every picture of them, and
    no extra reference picture is made (the mock slot filler; the image prompts as the pipeline plans them)."""
    fx = _load(path)
    expect = fx["expect"]
    if "ci" not in fx["runs_in"] or not A4_KEYS & set(expect):
        pytest.skip("no character reference checks in CI for this fixture")
    inp = fx["input"]
    brief = brief_from_fixture(inp)
    analysis = photo_analysis(brief, inp["photo"])
    if "photo_person_visible" in expect:
        assert analysis.people_in_photo is expect["photo_person_visible"]
    if "photo_face_visible" in expect:
        assert analysis.face_visible is expect["photo_face_visible"]
    (ad, _), _ = fill_slots(build_llm(make_settings(), "slots"), brief, analysis, split_story(brief.story))
    main = ad.sheet.people[0]
    if want := expect.get("character_reference"):
        assert character_reference(main) == want
        assert main.look.source == "photo" and "long dark hair" in main.look.value
    if "extra_reference_pictures" in expect:
        photo = InputImage(data=b"x", content_type="image/jpeg")
        extra = 0
        for card in ad.scenes:
            shown = [p.id for p in ad.sheet.people if p.in_photo and p.id in card.who.ids]
            sc = Scene(role="demo", description=card.action.value or "d", image_prompt="i", motion_prompt="m")
            req = plan_scene_image(model="m", scene=sc, aspect_ratio="9:16", seed=1, product=photo,
                                   product_sha256="a", in_photo=shown).request  # fmt: skip
            extra += len(req.extra_images)
            assert all(f"Reference photo 1 also shows {p}" in req.arguments["prompt"] for p in shown)
        assert extra == expect["extra_reference_pictures"]


def mock_photo_analysis(brief):
    """The writer still needs an analysis today; with no photo it reads only the brief (phase 6)."""
    return ProductAnalysis.model_validate(mock_analysis(brief.model_dump()))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_later_phases_are_listed_not_dropped(path):
    fx = _load(path)
    pending = sorted({(PHASE[k], k) for k in _keys(fx["expect"]) if PHASE[k] > CHECKED_NOW and k not in A4_KEYS})
    if fx["runs_in"] == ["live"]:
        pytest.skip("live fixture: run by hand with the real writer (owner's go)")
    if pending:
        pytest.skip("to check in later phases: " + ", ".join(f"{k} (phase {n})" for n, k in pending))
