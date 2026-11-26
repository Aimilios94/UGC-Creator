"""The scene splitter (strategy plan phase 2, D31): every prompt shape becomes scenes in code, the
user's words kept, nothing dropped. DB-free; the writer is the mock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import Brief, ProductAnalysis
from app.services.providers.llm import build_llm, mock_analysis
from app.services.scene_splitter import split_story
from app.services.storyboard import write_storyboard
from conftest import make_settings

CASES = json.loads((Path(__file__).parent / "fixtures" / "prompt_shapes.json").read_text(encoding="utf-8"))["cases"]


def _story(case: dict) -> str:
    story = case["story"]
    if "long" in case:
        story = story.replace("{LONG}", (case["long"]["text"] * case["long"]["times"]).strip())
    return story


def _write(story: str, length: int | None = None):
    brief = Brief(product_name="City Harmony hoodie", description="Black hoodie.", story=story, video_length_s=length)
    analysis = ProductAnalysis.model_validate(mock_analysis(brief.model_dump()))
    board, _ = write_storyboard(build_llm(make_settings(), "storyboard"), brief, analysis)
    return board


# --- the 8 prompt shapes of the setup note ---------------------------------------------------------
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_each_prompt_shape_becomes_the_right_scenes(case):
    story, expect = _story(case), case["expect"]
    split = split_story(story)
    assert split.shape == expect["shape"]
    board = _write(story, case["length"])
    scenes = board.scenes
    if "scene_count" in expect:
        assert len(scenes) == expect["scene_count"]
    else:
        assert expect["scene_count_min"] <= len(scenes) <= expect["scene_count_max"]
    if "seconds" in expect:
        assert [s.duration_s for s in scenes] == expect["seconds"]
    if "total_seconds" in expect:
        assert sum(s.duration_s for s in scenes) == expect["total_seconds"]
    for i, text in enumerate(expect.get("scene_texts", [])):
        assert scenes[i].description == text  # word for word
    for i, text in enumerate(expect.get("scene_texts_contain", [])):
        assert text in scenes[i].description
    for text in expect.get("notes_contains", []):
        assert text in board.notes
    if "message_contains" in expect:
        assert expect["message_contains"] in board.split_note
    if "scene_2_longer_than" in expect:
        assert len(scenes[1].description) > expect["scene_2_longer_than"]  # kept whole, never cut


# --- each shape -------------------------------------------------------------------------------------
def test_headings_take_seconds_from_the_heading_and_keep_the_words():
    split = split_story(
        "## Scene 1 (10 seconds): a man picks up the mug.\n**Scene 2** - 3 s: he walks out.\nShot 3: he sips."
    )
    assert split.shape == "headings"
    assert [(b.text, b.seconds) for b in split.beats] == [
        ("a man picks up the mug.", 10),
        ("he walks out.", 3),
        ("he sips.", None),
    ]


def test_a_heading_on_its_own_line_and_a_timeline_inside_the_scene():
    split = split_story("Scene 1\n0-2 s: he walks. 2-4 s: the camera pushes in.\n\nScene 2\nHe smiles at the camera.")
    assert [(b.text, b.seconds) for b in split.beats] == [
        ("0-2 s: he walks. 2-4 s: the camera pushes in.", 4),
        ("He smiles at the camera.", None),
    ]


def test_a_heading_never_swallows_the_scene_words():
    split = split_story("Scene 1 he walks into the room and looks around: nobody\nScene 2 he leaves")
    assert split.beats[0].text == "he walks into the room and looks around: nobody"
    assert split.beats[1].text == "he leaves"


def test_text_before_and_after_the_scenes_is_kept_as_notes():
    split = split_story(
        "Cinematic, warm light.\n\nScene 1: he walks.\nScene 2: he waves at the camera.\n\nStyle: 35 mm film grain."
    )
    assert [b.text for b in split.beats] == ["he walks.", "he waves at the camera."]
    assert split.notes == "Cinematic, warm light.\n\nStyle: 35 mm film grain."


def test_a_list_of_actions_is_scenes_and_labelled_items_are_notes():
    split = split_story(
        "My ad:\n1. He opens the box on the bed.\n\n2. He pulls the hoodie on.\n- Style: soft morning light\n"
        "3. He checks the mirror and grins.\nThanks!"
    )
    assert split.shape == "list"
    assert [b.text for b in split.beats] == [
        "He opens the box on the bed.",
        "He pulls the hoodie on.",
        "He checks the mirror and grins.",
    ]
    assert "My ad:" in split.notes and "Style: soft morning light" in split.notes and "Thanks!" in split.notes


def test_a_list_of_notes_is_not_scenes():
    assert split_story("- Style: moody\n- Light: neon\n- Music: lo-fi").shape == "none"


def test_paragraphs_wait_for_the_ai_and_no_shape_is_one_block():
    assert split_story("He walks in the rain.\n\nHe smiles.").shape == "paragraphs"
    assert split_story("guy wearing my hoodie in the rain").shape == "none"
    assert split_story("").shape == "none"


def test_time_ranges_win_over_headings():
    split = split_story("Scene 1: 0:00 - 0:04 he walks.\nScene 2: 0:04 - 0:06 he waves.")
    assert split.shape == "time_ranges" and [b.seconds for b in split.beats] == [4, 2]


# --- rules for every shape ------------------------------------------------------------------------
def test_seven_headings_stay_seven_shots():
    """Free cuts (D32): a story may have as many scenes as it wants, up to 20 shots."""
    story = "\n".join(f"Scene {i} (2 s): beat number {i} happens here." for i in range(1, 8))
    split = split_story(story)
    assert len(split.beats) == 7 and [b.part for b in split.beats] == [1, 2, 3, 4, 5, 6, 7]
    assert "joined" not in split.summary()


def test_more_than_twenty_headings_are_joined_and_the_user_is_told():
    story = "\n".join(f"Scene {i} (2 s): beat number {i} happens here." for i in range(1, 23))
    split = split_story(story)
    assert len(split.beats) == 20 and sum(b.seconds for b in split.beats) == 44
    assert "at most 20 shots" in split.summary() and "scenes 1 and 2" in split.summary()
    text = " ".join(b.text for b in split.beats) + " "
    assert all(f"beat number {i} " in text for i in range(1, 23))  # nothing lost


def test_cut_to_starts_a_new_scene_when_there_is_room():
    split = split_story(
        "Scene 1 (8 seconds): he walks out of the concert into the rain, cut to a close-up of the print.\n"
        "Scene 2 (4 seconds): he smiles at the camera."
    )
    assert [(b.text, b.seconds) for b in split.beats] == [
        ("he walks out of the concert into the rain", 5),
        ("A close-up of the print.", 3),
        ("he smiles at the camera.", 4),
    ]
    assert '"cut to", so it became two shots' in split.summary()
    assert [(b.part, b.join) for b in split.beats] == [(1, ""), (1, "cut"), (2, "")]  # one part, two shots


def test_cut_to_with_no_room_stays_one_scene_and_says_so():
    story = "\n".join(f"Scene {i} (2 s): he does thing {i} in the rain." for i in range(1, 20))
    story += "\nScene 20 (4 s): he walks out of the hall, cut to the street outside."
    split = split_story(story)
    assert len(split.beats) == 20 and "cut to the street" in split.beats[19].text
    assert "there are already 20 shots" in split.summary()


def test_a_word_containing_cut_is_not_a_cut():
    split = split_story("Scene 1: he shows the clean cut of the hood.\nScene 2: he walks away to the shortcut.")
    assert len(split.beats) == 2 and not split.messages


def test_the_owners_shape_notes_first_then_timed_beats():
    """The shape of the owner's own 20 s prompt (kept local): paragraphs of notes, then the timeline.
    The notes must not become scenes."""
    notes = "\n\n".join(f"Notes paragraph {i}: style, light, people and rules for the whole ad." for i in range(5))
    beats = "\n".join(f"0:{i * 4:02d} - 0:{i * 4 + 4:02d}: beat {i + 1}, the camera keeps moving." for i in range(5))
    split = split_story(notes + "\n\n" + beats)
    assert split.shape == "time_ranges" and [b.seconds for b in split.beats] == [4] * 5
    assert split.notes.count("Notes paragraph") == 5


def test_the_storyboard_says_how_the_story_was_read():
    board = _write("Scene 1: he walks out of a concert.\nScene 2: he smiles at the camera.\n\nStyle: neon night.")
    assert board.split_note.startswith("The scenes follow your scene headings, in your words")
    assert board.notes == "Style: neon night."
    assert _write("guy wearing my hoodie in the rain").split_note == ""
