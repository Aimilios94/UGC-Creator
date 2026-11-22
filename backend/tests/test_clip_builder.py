"""Strategy plan phase 4 (D31): the clip builder from the structure's slots, with a budget per part;
the writer fills only gaps; swaps of Kling weak spots with "AI changed" and Undo; the marks edited
in place on the page become the user's and reach the clips."""

from __future__ import annotations

import copy

from app.models import Brief, ProductAnalysis, Scene
from app.services.ad_structure import (
    AdStructure,
    CastRefs,
    CastSheet,
    Person,
    SceneCard,
    Swap,
    guess,
    merge_structure,
    user,
)
from app.services.providers.llm import build_llm, mock_analysis
from app.services.scene_splitter import split_story
from app.services.slot_filler import fill_slots
from app.services.storyboard import write_storyboard
from app.services.video_gen import (
    MOVE_BORROW_MAX,
    TOTAL_MAX,
    VIDEO_NEGATIVE,
    WHO_MAX,
    clip_prompt,
    negative_prompt,
)
from conftest import BRIEF, make_settings
from helpers import create_job

THROW = (
    "Scene 1: he walks out of a concert, hood up.\n"
    "Scene 2: he throws the hoodie to his friend in the crowd.\n"
    "Scene 3: his friend pulls it on and grins at the camera."
)


def _scene(description="he walks in the rain", motion="0-2 s: slow push in. 2-5 s: the camera holds.", **kw):
    return Scene(role="demo", description=description, image_prompt="i", motion_prompt=motion, **kw)


def _sheet(**kw) -> CastSheet:
    base = dict(
        product=guess("Black hoodie with an embroidered city print on the chest."),
        people=[
            Person(id="P1", label="the man", look=guess("late 20s, short dark hair"), clothes=guess("the hoodie")),
            Person(id="P2", label="the friend", look=guess("early 20s, curly hair"), clothes=guess("denim jacket")),
        ],
        place=guess("wet city street at night"),
        time_light=guess("night, neon signs"),
        look=guess("realistic, 35 mm"),
        camera_style=guess("handheld phone"),
        never=guess("no other people"),
    )
    return CastSheet(**{**base, **kw})


def _card(**kw) -> SceneCard:
    return SceneCard(who=CastRefs(ids=["P1", "product"]), **kw)


def _clip(scene=None, card=None, sheet=None, **kw):
    return clip_prompt(scene or _scene(), card=card or _card(), sheet=sheet or _sheet(), idx=0, count=1, **kw)


def _brief(story: str) -> Brief:
    return Brief(product_name="City Harmony hoodie", description="Black heavy cotton hoodie.", story=story)


def _board(story: str):
    brief = _brief(story)
    analysis = ProductAnalysis.model_validate(mock_analysis(brief.model_dump()))
    s = make_settings()
    (ad, split), _ = fill_slots(build_llm(s, "slots"), brief, analysis, split_story(story))
    board, _ = write_storyboard(build_llm(s, "storyboard"), brief, analysis, split=split, structure=ad)
    return board


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


# --- the build: parts, budgets, the user's words -----------------------------------------------
def test_the_users_scene_text_goes_to_the_clip_word_for_word_first():
    card = _card(text=user("he walks in the rain"))
    clip = _clip(card=card)
    assert clip.text.startswith("he walks in the rain.")
    assert [p.name for p in clip.parts] == ["movement", "who", "start_end", "place", "rules"]
    assert clip.chars <= TOTAL_MAX and clip.too_long_by == 0


def test_only_the_people_in_the_shot_are_described():
    clip = _clip(card=_card(text=user("he walks in the rain")))
    assert "P1, the man" in clip.text and "P2" not in clip.text and "curly hair" not in clip.text


def test_never_and_avoid_go_to_the_negative_prompt_not_the_clip():
    card = _card(text=user("he walks"), avoid=guess("umbrellas"))
    clip = _clip(card=card)
    assert clip.negative == f"{VIDEO_NEGATIVE}, no other people, umbrellas"
    assert "umbrellas" not in clip.text and "no other people" not in clip.text
    assert negative_prompt() == VIDEO_NEGATIVE


def test_a_timed_user_scene_keeps_its_own_moves_and_gets_no_guessed_timeline():
    own = "0-2 s: full-body shot, he walks. 2-4 s: the camera pushes in to his footsteps. 4-5 s: it pulls back."
    clip = _clip(scene=_scene(description=own), card=_card(text=user(own), camera=guess("slow orbit")))
    assert own in clip.text
    assert "slow push in" not in clip.text and "slow orbit" not in clip.text  # the writer's and the guess stay out


def test_a_long_user_scene_borrows_room_and_is_never_cut():
    own = ("he walks along the wet street past the shops, " * 30)[:1300].strip()
    clip = _clip(scene=_scene(description=own), card=_card(text=user(own)))
    assert own in clip.text and clip.too_long_by == 0 and clip.chars <= TOTAL_MAX
    movement = next(p for p in clip.parts if p.name == "movement")
    assert movement.chars <= MOVE_BORROW_MAX < movement.budget + 1  # the guessed timeline fits what is left


def test_a_user_scene_over_the_movement_budget_asks_to_be_shortened():
    own = ("he walks along the wet street past the shops, " * 40)[:1500].strip()
    clip = _clip(scene=_scene(description=own), card=_card(text=user(own)))
    assert clip.too_long_by == len(own) - MOVE_BORROW_MAX
    assert clip.shorten_field == "description"  # "Shorten it for me" rewrites the scene text


def test_the_product_is_kept_and_people_trimmed_within_the_who_budget():
    long_look = "tall, " + "freckles and a warm smile, " * 30
    sheet = _sheet(people=[Person(id="P1", label="the man", look=guess(long_look))])
    clip = _clip(card=_card(text=user("he walks")), sheet=sheet)
    who = next(p for p in clip.parts if p.name == "who")
    assert who.chars <= WHO_MAX and "Black hoodie with an embroidered city print" in clip.text


def test_without_a_structure_the_older_build_is_used():
    clip = clip_prompt(_scene(), idx=0, count=1)
    assert clip.parts == [] and clip.text.startswith("0-2 s: slow push in")


# --- the writer fills only gaps; A1 swaps -------------------------------------------------------
def test_the_writer_writes_only_a_timeline_and_the_users_words_lead_the_clip():
    board = _board("guy wearing my hoodie in the rain")
    ad = AdStructure.model_validate(board.structure)
    assert ad.scenes[0].action.source == "user"
    assert ad.scenes[0].timeline.source == "ai_guess" and ad.scenes[0].timeline.value == board.scenes[0].motion_prompt
    sheet, card = ad.sheet, ad.scenes[0]
    clip = clip_prompt(board.scenes[0], card=card, sheet=sheet, idx=0, count=3)
    assert clip.text.startswith("guy wearing my hoodie in the rain.")


def test_a_throw_is_swapped_marked_and_undone():
    board = _board(THROW)
    ad = AdStructure.model_validate(board.structure)
    swap = ad.scenes[1].swap
    assert swap is not None and "throws" in swap.original and "throw" in swap.reason.lower()
    assert ad.scenes[0].swap is None and ad.scenes[2].swap is None  # the other actions stay word for word
    clip = clip_prompt(board.scenes[1], card=ad.scenes[1], sheet=ad.sheet, idx=1, count=3)
    assert "throws" not in clip.text and swap.value in clip.text
    # Undo: the page sends the card without the swap; the user's words go back to the clip.
    edits = ad.model_copy(deep=True)
    edits.scenes[1].swap = None
    undone = merge_structure(ad, edits, board.scenes, board.scenes)
    assert undone.scenes[1].swap is None
    clip = clip_prompt(board.scenes[1], card=undone.scenes[1], sheet=undone.sheet, idx=1, count=3)
    assert "he throws the hoodie to his friend in the crowd." in clip.text


def test_the_page_cannot_make_a_swap_or_change_a_source():
    board = _board(THROW)
    ad = AdStructure.model_validate(board.structure)
    edits = ad.model_copy(deep=True)
    edits.scenes[0].swap = Swap(original="x", value="forged", reason="forged")
    edits.sheet.place = guess(ad.sheet.place.value)  # same value: its source stays
    edits.sheet.time_light = user(ad.sheet.time_light.value)  # a forged source with the same value
    merged = merge_structure(ad, edits, board.scenes, board.scenes)
    assert merged.scenes[0].swap is None
    assert merged.sheet.time_light.source == ad.sheet.time_light.source


# --- editing the marks in place ------------------------------------------------------------------
def test_an_edited_value_becomes_the_users_and_reaches_every_clip(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": THROW}).json()
    board = copy.deepcopy(job["storyboard"])
    board["structure"]["sheet"]["place"] = {"value": "a rooftop at sunset", "source": "ai_guess"}
    board["structure"]["sheet"]["people"][0]["clothes"]["value"] = "black hoodie, grey joggers"
    board["structure"]["scenes"][0]["product_moment"]["value"] = "the chest print faces the camera"
    r = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=_h(session_id))
    assert r.status_code == 200, r.text
    saved = r.json()
    ad = saved["storyboard"]["structure"]
    assert ad["sheet"]["place"] == {"value": "a rooftop at sunset", "source": "user"}
    assert ad["sheet"]["people"][0]["clothes"]["source"] == "user"
    assert ad["scenes"][0]["product_moment"]["source"] == "user"
    assert all("Place: a rooftop at sunset." in c["text"] for c in saved["clips"])
    assert "black hoodie, grey joggers" in saved["clips"][0]["text"]


def test_the_preview_shows_unsaved_edits_and_an_emptied_key_slot_gets_a_guess(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": THROW}).json()
    board = copy.deepcopy(job["storyboard"])
    board["structure"]["sheet"]["time_light"]["value"] = "golden hour, low sun"
    board["structure"]["sheet"]["place"]["value"] = ""
    r = client.post(f"/jobs/{job['id']}/clip-texts", json=board, headers=_h(session_id))
    assert r.status_code == 200
    clips = r.json()
    assert all("Golden hour, low sun." in c["text"] for c in clips)
    assert all("Place: " in c["text"] for c in clips)  # the emptied place is guessed again
    assert {p["name"] for p in clips[0]["parts"]} >= {"movement", "who", "start_end", "place", "rules"}


def test_an_edited_scene_text_is_the_users_and_drops_the_swap(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": THROW}).json()
    board = copy.deepcopy(job["storyboard"])
    assert board["structure"]["scenes"][1]["swap"] is not None
    board["scenes"][1]["description"] = "he hands the hoodie to his friend."
    r = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=_h(session_id))
    saved = r.json()
    card = saved["storyboard"]["structure"]["scenes"][1]
    assert card["swap"] is None and card["text"] == {"value": "he hands the hoodie to his friend.", "source": "user"}
    assert "he hands the hoodie to his friend." in saved["clips"][1]["text"]
