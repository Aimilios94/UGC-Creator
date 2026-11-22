"""Story first (owner, 22 Nov 2026): the cast and world comes from the user's story, guesses fit it,
and code checks that what the story names is there; voiceover and on-screen text start empty."""

from __future__ import annotations

from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.models import Brief, ProductAnalysis
from app.services.providers.llm import LlmHandle, _brief_from, build_llm, mock_analysis, mock_slots
from app.services.scene_splitter import split_story
from app.services.slot_filler import SlotOut, _slot, content_words, fill_slots, named_in_story
from app.services.storyboard import keep_users_lines, write_storyboard
from conftest import BRIEF, make_settings
from helpers import create_job

SHIBUYA = "a girl wearing my anime hoodie walks through Shibuya at night, neon signs everywhere"


def _brief(story: str) -> Brief:
    return Brief(product_name="Anime Hoodie", description="Black hoodie with an anime print.", story=story)


def _analysis(brief: Brief) -> ProductAnalysis:
    return ProductAnalysis.model_validate(mock_analysis(brief.model_dump()))


def test_a_reworded_story_value_is_from_your_story_and_a_made_up_one_is_a_guess():
    words = content_words(SHIBUYA)
    text = SHIBUYA.lower()
    assert _slot(SlotOut(value="Shibuya crossing, neon at night", from_story=True), text, words).source == "story"
    assert _slot(SlotOut(value="a bright, tidy room", from_story=True), text, words).source == "ai_guess"
    assert _slot(SlotOut(value="neon signs everywhere", from_user=True), text, words).source == "user"


def test_names_in_the_story_are_found_but_not_sentence_starts_or_the_product():
    story = "Scene 1: she meets Maria in Shibuya. The Anime Hoodie glows. Then she waves."
    assert named_in_story(story, "Anime Hoodie: black hoodie") == ["Maria", "Shibuya"]


def test_a_sheet_that_ignores_the_storys_place_is_asked_once_more():
    brief = _brief(SHIBUYA)
    calls = []

    def respond(messages, info):
        draft = mock_slots(_brief_from(messages))
        if not calls:
            draft["sheet"]["place"] = {"value": "a bright, tidy room at home"}  # a default that ignores the story
        calls.append(messages)
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=draft)])

    llm = LlmHandle(model=FunctionModel(respond, model_name="s"), provider="mock", model_name="mock", settings={})
    (ad, _), _ = fill_slots(llm, brief, _analysis(brief), split_story(SHIBUYA))
    assert len(calls) == 2 and "left out what the story names: Shibuya" in str(calls[1])
    assert "Shibuya" in ad.sheet.place.value and ad.sheet.place.source == "user"


def test_the_mock_reads_the_place_and_time_from_the_story():
    brief = _brief(SHIBUYA)
    (ad, _), _ = fill_slots(build_llm(make_settings(), "slots"), brief, _analysis(brief), split_story(SHIBUYA))
    assert ad.sheet.place.value == "Shibuya at night" and ad.sheet.place.source == "user"
    assert "night" in ad.sheet.time_light.value and ad.sheet.time_light.source == "story"
    assert [p.id for p in ad.sheet.people] == ["P1"]


# --- voiceover and on-screen text start empty -----------------------------------------------------
def test_the_writers_lines_become_ideas_and_the_users_own_lines_stay():
    scenes = [
        {"voiceover": "Stop scrolling.", "on_screen_text": "Meet it", "voiceover_ideas": ["Look at this."]},
        {"voiceover": "Rain? No problem.", "on_screen_text": "", "voiceover_ideas": []},
    ]
    keep_users_lines(scenes, 'He says "Rain? No problem." and walks on.')
    assert scenes[0]["voiceover"] == "" and scenes[0]["voiceover_ideas"] == ["Stop scrolling.", "Look at this."]
    assert scenes[0]["on_screen_text"] == "" and scenes[0]["text_ideas"] == ["Meet it"]
    assert scenes[1]["voiceover"] == "Rain? No problem."  # the user's own words, from the story


def test_a_new_storyboard_speaks_and_shows_nothing_until_the_user_picks(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    scenes = job["storyboard"]["scenes"]
    assert all(s["voiceover"] == "" and s["on_screen_text"] == "" for s in scenes)
    assert all(s["voiceover_ideas"] and s["text_ideas"] for s in scenes[:2])
    assert job["estimate"]["video"]["usd"] > 0


def test_the_writer_keeps_spoken_lines_from_the_story():
    story = 'Scene 1: he steps into the rain and says "Rain? No problem."\nScene 2: he zips the hoodie up.'
    brief = Brief(**{**BRIEF, "story": story})
    board, _ = write_storyboard(build_llm(make_settings(), "storyboard"), brief, _analysis(brief))
    assert board.scenes[0].voiceover == "Rain? No problem."
