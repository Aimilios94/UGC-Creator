"""Strategy plan phase 5 (D31): quick questions before the storyboard, only about key slots still
guessed, at most 3, with suggestion buttons, "Let the AI decide" and Skip all; answers locked."""

from __future__ import annotations

from app.models import Brief, ProductAnalysis
from app.services.ad_structure import AdStructure, Question, Slot
from app.services.providers.llm import build_llm, mock_analysis
from app.services.scene_splitter import split_story
from app.services.slot_filler import LET_AI_DECIDE, apply_answers, fill_slots, open_questions
from conftest import BRIEF, make_settings
from helpers import create_job

VAGUE = "guy wearing my hoodie in the rain"


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


def _ad(story: str = VAGUE) -> AdStructure:
    brief = Brief(product_name="City Harmony hoodie", description="Black heavy cotton hoodie.", story=story)
    analysis = ProductAnalysis.model_validate(mock_analysis(brief.model_dump()))
    (ad, _), _ = fill_slots(build_llm(make_settings(), "slots"), brief, analysis, split_story(story))
    return ad


def _q(slot: str) -> Question:
    return Question(slot=slot, text=f"About {slot}?", options=["One", "Two"])


# --- which questions are kept --------------------------------------------------------------------
def test_a_vague_idea_keeps_its_questions_in_the_plans_order():
    ad = _ad()
    ad.questions = [_q("end"), _q("place"), _q("who"), _q("product_moment")]
    assert [q.slot for q in open_questions(ad)] == ["who", "product_moment", "place"]  # at most 3, by priority


def test_a_question_the_users_words_answer_is_dropped():
    ad = _ad()
    ad.sheet.place = Slot(value="a rainy street", source="user")
    ad.questions = [_q("place"), _q("place"), _q("who")]
    assert [q.slot for q in open_questions(ad)] == ["who"]  # place is the user's; duplicates go too


def test_a_detailed_story_gets_no_questions():
    story = "0:00-0:02: he walks out of the shop in light rain. 0:02-0:05: he pulls the hood up and smiles."
    assert open_questions(_ad(story)) == []


def test_answers_are_locked_into_their_slots_and_let_the_ai_decide_keeps_the_guess():
    ad = _ad()
    ad.questions = [_q("who"), _q("product_moment"), _q("place")]
    before = ad.sheet.place
    done = apply_answers(
        ad, {"who": "A young man with a beard", "product_moment": "worn, hood up", "place": LET_AI_DECIDE}
    )
    assert done.sheet.people[0].look == Slot(value="A young man with a beard", source="answer")
    assert all(sc.product_moment.source == "answer" for sc in done.scenes)
    assert done.sheet.place == before  # "Let the AI decide": the guess stays, marked
    assert [q.answer for q in done.questions] == ["A young man with a beard", "worn, hood up", ""]


# --- the flow through the API --------------------------------------------------------------------
def test_questions_come_before_the_storyboard_and_answers_reach_the_clips(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": VAGUE}).json()
    assert job["status"] == "draft" and job["storyboard"] is None
    qs = job["questions"]
    assert 1 <= len(qs) <= 3 and all(2 <= len(q["options"]) <= 4 for q in qs)
    assert all(q["let_ai_decide"] == LET_AI_DECIDE for q in qs)
    r = client.post(f"/jobs/{job['id']}/answers", json={"answers": {"who": "A young man with a beard"}},
                    headers=_h(session_id))  # fmt: skip
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["questions"] == [] and done["storyboard"] is not None
    ad = done["storyboard"]["structure"]
    assert ad["sheet"]["people"][0]["look"] == {"value": "A young man with a beard", "source": "answer"}
    assert "A young man with a beard" in done["clips"][0]["text"]
    again = client.post(f"/jobs/{job['id']}/answers", json={"skip": True}, headers=_h(session_id))
    assert again.status_code == 409  # nothing waiting any more


def test_skip_all_writes_the_storyboard_with_the_guesses(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": VAGUE}).json()
    r = client.post(f"/jobs/{job['id']}/answers", json={"skip": True}, headers=_h(session_id))
    done = r.json()
    assert r.status_code == 200 and done["storyboard"] is not None and done["questions"] == []
    ad = AdStructure.model_validate(done["storyboard"]["structure"])
    assert all(q.answer == "" for q in ad.questions)
    assert ad.sheet.place.source == "ai_guess"


def test_an_ad_from_the_brief_alone_goes_straight_to_the_storyboard(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    assert job["storyboard"] is not None and job["questions"] == []


def test_a_guess_that_contradicts_an_answer_is_corrected_by_the_writer(client, session_id, photo_bytes):
    # A story that says nothing about the time or light, so the light is the AI's guess.
    job = create_job(
        client, session_id, photo_bytes, brief={**BRIEF, "story": "guy wearing my hoodie, looking cool"}
    ).json()
    r = client.post(f"/jobs/{job['id']}/answers", json={"answers": {"place": "a rainy street at night"}},
                    headers=_h(session_id))  # fmt: skip
    sheet = r.json()["storyboard"]["structure"]["sheet"]
    assert sheet["place"] == {"value": "a rainy street at night", "source": "answer"}
    assert sheet["time_light"] == {"value": "night, street lamps and neon light", "source": "ai_guess"}
    assert "Night, street lamps and neon light." in r.json()["clips"][0]["text"]
