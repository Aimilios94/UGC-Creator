"""Strategy plan phase 3 (D31): the slot filler, the paragraph split it makes, the "AI's guess" marks
and the real-length line with "Add scenes" and "Keep" (plan v2.3)."""

from __future__ import annotations

from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.models import Brief, ProductAnalysis
from app.services.ad_structure import AdStructure, key_gaps
from app.services.providers.llm import LlmHandle, build_llm, mock_analysis, mock_slots
from app.services.scene_plan import add_plan, length_line
from app.services.scene_splitter import split_story
from app.services.slot_filler import (
    FALLBACK,
    ParagraphUse,
    SlotDraft,
    build_structure,
    check_paragraphs,
    fill_slots,
    paragraphs_split,
)
from app.services.storyboard import write_storyboard
from conftest import BRIEF, make_settings
from helpers import create_job

PARAS = (
    "Style: cinematic, cold blue dawn light, slow camera moves.\n\n"
    "A woman in a yellow raincoat waits at a bus stop at dawn.\n\n"
    "Close-up of the mug in her hand, steam rising from the open lid.\n\n"
    "She steps onto the bus, mug in hand."
)


def _brief(story: str = "", **kw) -> Brief:
    return Brief(product_name="Lumo travel mug", description="Matte green steel travel mug.", story=story, **kw)


def _analysis(brief: Brief) -> ProductAnalysis:
    return ProductAnalysis.model_validate(mock_analysis(brief.model_dump()))


def _fill(brief: Brief, analysis: ProductAnalysis | None = None, llm: LlmHandle | None = None):
    llm = llm or build_llm(make_settings(), "slots")
    return fill_slots(llm, brief, analysis, split_story(brief.story))


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


# --- paragraphs: the AI marks them, code checks and builds the scenes ------------------------------
def test_paragraphs_become_scenes_and_notes_in_the_users_words():
    brief = _brief(PARAS)
    (ad, split), call = _fill(brief, _analysis(brief))
    assert split.shape == "paragraphs" and call.cost_usd == 0
    paras = PARAS.split("\n\n")
    assert [b.text for b in split.beats] == paras[1:]  # whole paragraphs, word for word
    assert split.notes == paras[0]
    assert [c.text.value for c in ad.scenes] == paras[1:] and all(c.text.source == "user" for c in ad.scenes)
    assert split.summary() == (
        "The AI read your paragraphs into scenes, in your words; one paragraph kept as notes for every scene."
    )


def test_paragraph_marks_are_checked():
    def uses(*marks):
        return [
            ParagraphUse(paragraph=i + 1, use="notes" if m is None else "scene", scene=m) for i, m in enumerate(marks)
        ]

    assert check_paragraphs(uses(None, 1, 2, 2), 4) is None  # notes, then scenes 1, 2 (two paragraphs)
    assert check_paragraphs(uses(1, None, 2), 3) is None  # a note between scenes is fine
    assert "exactly once" in check_paragraphs(uses(1, 2), 3)  # a paragraph left out
    assert "exactly once" in check_paragraphs([*uses(1, 2), ParagraphUse(paragraph=2, use="scene", scene=2)], 3)
    assert "no gap" in check_paragraphs(uses(1, 3), 2)
    assert "no gap" in check_paragraphs(uses(2, 1), 2)  # out of order
    assert "at least one" in check_paragraphs(uses(None, None), 2)
    split = paragraphs_split("A walks in.\n\nB smiles.\n\nLight: neon.", uses(1, 1, None))
    assert [b.text for b in split.beats] == ["A walks in.\n\nB smiles."] and split.notes == "Light: neon."


def _scripted(*replies) -> LlmHandle:
    """A slot filler model that answers with the given drafts in turn."""
    calls = []

    def respond(messages, info):
        draft = replies[min(len(calls), len(replies) - 1)]
        calls.append(messages)
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=draft)])

    handle = LlmHandle(
        model=FunctionModel(respond, model_name="scripted"), provider="mock", model_name="mock", settings={}
    )
    handle.calls = calls  # type: ignore[attr-defined]
    return handle


def test_bad_paragraph_marks_are_asked_once_more():
    brief = _brief(PARAS)
    good = mock_slots({"product_name": "Lumo", "story": PARAS, "_paragraphs": [
        {"paragraph": i + 1, "text": t} for i, t in enumerate(PARAS.split("\n\n"))]})  # fmt: skip
    bad = {**good, "paragraphs": good["paragraphs"][:2]}  # two paragraphs left out
    llm = _scripted(bad, good)
    (ad, split), _ = _fill(brief, _analysis(brief), llm)
    assert len(llm.calls) == 2 and len(split.beats) == 3
    assert "could not be used: list every paragraph exactly once" in str(llm.calls[1])


def test_paragraph_marks_wrong_twice_leave_the_story_to_the_writer():
    brief = _brief(PARAS)
    bad = {"paragraphs": [{"paragraph": 1, "use": "scene", "scene": 1}], "scenes": [{}]}
    llm = _scripted(bad, bad)
    (ad, split), _ = _fill(brief, _analysis(brief), llm)
    assert len(llm.calls) == 2 and split.shape == "paragraphs" and split.beats == []  # read whole, as before
    assert not key_gaps(ad)


# --- the structure: sources checked in code, every key slot filled or marked ------------------------
def test_a_value_claimed_as_the_users_must_be_in_the_users_text():
    brief = _brief("He walks through the rain in the hoodie.\n\nHe smiles at the camera.")
    draft = SlotDraft.model_validate(
        {
            "sheet": {
                "place": {"value": "through the rain", "from_user": True},  # found: the user's
                "time_light": {"value": "neon night", "from_user": True},  # not found: a guess
            },
            "scenes": [{"action": {"value": "he walks through the rain", "from_user": True}}, {}],
        }
    )
    ad = build_structure(draft, brief, _analysis(brief), split_story(brief.story), want=2)
    assert ad.sheet.place.source == "user" and ad.sheet.time_light.source == "ai_guess"
    assert ad.scenes[0].action.source == "user"  # case and spacing do not matter
    assert ad.sheet.product.source == "photo"  # the product's look comes from code


def test_key_slots_the_ai_left_empty_are_guessed_in_code():
    brief = _brief()
    ad = build_structure(SlotDraft(scenes=[{}]), brief, _analysis(brief), split_story(""), want=3)
    assert len(ad.scenes) == 3 and not key_gaps(ad)
    assert ad.sheet.place.value == FALLBACK["place"] and ad.sheet.place.source == "ai_guess"
    assert ad.scenes[-1].end.value == FALLBACK["end"] and ad.scenes[0].who.ids == ["product"]


def test_without_a_photo_the_product_is_the_users_own_words():
    brief = _brief("A woman waits at a bus stop at dawn.\n\nShe steps onto the bus.")
    (ad, _), _ = _fill(brief, None)
    assert ad.sheet.product.source == "user" and not ad.has_photo
    assert "Matte green steel travel mug" in ad.sheet.product.value


def test_only_the_users_own_spoken_words_fill_the_spoken_line():
    brief = _brief('He holds up the mug. "Best tea in town."\n\nHe smiles.')
    draft = SlotDraft.model_validate(
        {
            "scenes": [
                {"spoken_line": {"value": "Best tea in town.", "from_user": True}},
                {"spoken_line": {"value": "Try it today!", "from_user": True}},
            ]
        }  # fmt: skip
    )
    ad = build_structure(draft, brief, _analysis(brief), split_story(brief.story), want=2)
    assert ad.scenes[0].spoken_line.value == "Best tea in town." and ad.scenes[1].spoken_line.empty


# --- the writer follows the structure; the storyboard carries it --------------------------------------
def test_the_writer_follows_the_paragraph_split_and_carries_the_marks():
    brief = _brief(PARAS)
    analysis = _analysis(brief)
    (ad, split), _ = _fill(brief, analysis)
    board, _ = write_storyboard(build_llm(make_settings(), "storyboard"), brief, analysis, split=split, structure=ad)
    paras = PARAS.split("\n\n")
    assert [s.description for s in board.scenes] == paras[1:]
    assert board.notes == paras[0] and board.split_note.startswith("The AI read your paragraphs")
    structure = AdStructure.model_validate(board.structure)
    assert [c.uid for c in structure.scenes] == [s.uid for s in board.scenes]
    assert [c.length_s for c in structure.scenes] == [s.duration_s for s in board.scenes]
    assert all(c.length_source == "ai_guess" for c in structure.scenes)  # no seconds in the story


def test_auto_without_a_story_makes_three_scenes_with_marks():
    brief = _brief()
    analysis = _analysis(brief)
    (ad, split), _ = _fill(brief, analysis)
    board, _ = write_storyboard(build_llm(make_settings(), "storyboard"), brief, analysis, split=split, structure=ad)
    assert len(board.scenes) == 3 and board.structure is not None


def test_the_browser_cannot_change_the_structure(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    forged = {**board, "structure": {**board["structure"], "notes": "forged"}}
    r = client.put(f"/jobs/{job['id']}/storyboard", json=forged, headers=_h(session_id))
    assert r.status_code == 200 and r.json()["storyboard"]["structure"]["notes"] != "forged"


# --- the real length vs the picked length (plan v2.3) ------------------------------------------------
def test_length_line_says_the_real_length_and_offers_fixes():
    assert length_line([10, 10], None, 2) is None  # Auto: nothing picked
    assert length_line([10, 10], 22, 2) is None  # as picked
    line = length_line([10, 10], 40, 2)
    assert line["text"] == "Your scenes make a 22 s ad (you picked 40 s)."
    assert line["add"] == "Add scenes to reach 40 s" and line["keep"] == "Keep 22 s"
    assert line["add_lengths"] == [9, 9]
    longer = length_line([10, 10, 10], 20, 2)
    assert longer["text"] == "Your scenes make a 32 s ad (you picked 20 s)." and longer["add"] == ""
    full = length_line([5, 5, 5, 5, 5], 40, 2)
    assert full["add"] == "" and full["keep"] == "Keep 27 s"  # 5 scenes already: only Keep
    assert add_plan([4, 4, 4], 52, 2) == [10, 10]  # as close as 5 scenes allow, never more than 10 s each
    assert add_plan([10, 10], 23, 2) == []  # one second short: no 2 s scene for it


TWO_SCENES = {
    **BRIEF,
    "story": "Scene 1 (10 seconds): he walks through a rainy street at night, hood up.\n"
    "Scene 2 (10 seconds): he stops under a neon sign, pulls the hood down and smiles at the camera.",
    "video_length_s": 40,
}


def test_scenes_are_never_stretched_and_the_line_shows(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief=TWO_SCENES).json()
    assert [s["duration_s"] for s in job["storyboard"]["scenes"]] == [10, 10]
    line = job["length_line"]
    assert line["text"] == "Your scenes make a 22 s ad (you picked 40 s)." and line["keep"] == "Keep 22 s"


def test_keep_sets_the_picked_length_to_the_real_one(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief=TWO_SCENES).json()
    r = client.put(f"/jobs/{job['id']}/length", json={"video_length_s": 22}, headers=_h(session_id))
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["brief"]["video_length_s"] == 22 and view["length_line"] is None
    assert [s["duration_s"] for s in view["storyboard"]["scenes"]] == [10, 10]  # the scenes are untouched


def test_add_scenes_reaches_the_picked_length_with_marked_ai_scenes(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief=TWO_SCENES).json()
    before = job["storyboard"]["scenes"]
    r = client.post(f"/jobs/{job['id']}/scenes/add", headers=_h(session_id))
    assert r.status_code == 200, r.text
    view = r.json()
    scenes = view["storyboard"]["scenes"]
    assert len(scenes) == 4 and sum(s["duration_s"] for s in scenes) + 2 == 40
    assert view["length_line"] is None
    # The user's scenes are kept as they were, first and last; the new ones go between, marked.
    assert (
        scenes[0]["description"] == before[0]["description"] and scenes[-1]["description"] == before[1]["description"]
    )
    assert [s["ai_added"] for s in scenes] == [False, True, True, False]
    structure = view["storyboard"]["structure"]
    assert [c["uid"] for c in structure["scenes"]] == [s["uid"] for s in scenes]
    assert structure["scenes"][1]["text"]["source"] == "ai_guess"
    assert structure["scenes"][1]["who"]["ids"] == structure["scenes"][0]["who"]["ids"]  # the cast carries on
    assert key_gaps(AdStructure.model_validate(structure)) == []
    stages = {s["stage"] for s in view["stages"]}
    assert {"add_scenes", "continuity"} <= stages
    again = client.post(f"/jobs/{job['id']}/scenes/add", headers=_h(session_id))
    assert again.status_code == 409  # nothing left to add
