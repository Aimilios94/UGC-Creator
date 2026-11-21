"""The fixed structure (strategy plan phase 1, D31): slots with their source, locked slots, gaps,
and today's storyboard read into it. DB-free."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import Brief, Hook, ProductAnalysis, Scene, Storyboard
from app.services.ad_structure import (
    AdStructure,
    CastRefs,
    CastSheet,
    Person,
    Question,
    SceneCard,
    Slot,
    from_storyboard,
    guess,
    guesses,
    key_gaps,
    restore_locked,
    user,
)


def _ad(**kw) -> AdStructure:
    scene = SceneCard(
        text=user("he walks in the rain, hood up"),
        who=CastRefs(ids=["P1", "product"], source="user"),
        action=user("walks in the rain"),
        product_moment=guess("worn, chest print to camera"),
        end=guess("he stops and smiles"),
        length_s=5,
        length_source="user",
    )
    sheet = CastSheet(
        product=Slot(value="black hoodie, embroidered City Harmony print", source="photo"),
        people=[Person(id="P1", label="the man", look=guess("late 20s, short dark hair"), clothes=user("the hoodie"))],
        place=user("rainy street at night"),
    )
    return AdStructure(sheet=sheet, scenes=[scene], **kw)


def test_slots_know_their_source_and_lock_what_is_not_a_guess():
    assert Slot().source == "ai_guess" and Slot().empty
    assert user("x").locked and Slot(value="x", source="photo").locked and Slot(value="x", source="answer").locked
    assert not guess("x").locked and not user("").locked  # an empty slot has nothing to protect
    with pytest.raises(ValidationError):
        Slot(value="x", source="model")
    with pytest.raises(ValidationError):
        Person(id="hero")  # cast ids are P1-P9
    with pytest.raises(ValidationError):
        Question(slot="who", text="Who is in the video?", options=["Only hands"])  # 2-4 buttons
    with pytest.raises(ValidationError):
        AdStructure(scenes=[])  # 1-5 scenes


def test_a_long_user_text_is_never_cut():
    long = "he walks on " * 900  # 10,800 characters: the story box takes 12,000
    assert SceneCard(text=user(long)).text.value == long


def test_a_model_cannot_change_a_locked_slot():
    before = _ad()
    after = before.model_copy(deep=True)
    after.scenes[0].text = guess("A man strolls through the rain.")  # reworded the user's words
    after.scenes[0].action = user("runs")  # even if it claims the user wrote it
    after.scenes[0].end = guess("he stops, turns and smiles")  # a guess may change
    after.scenes[0].length_s = 10
    after.sheet.product = guess("a hoodie")
    after.sheet.people = []  # dropped the person holding the user's words
    fixed, log = restore_locked(before, after)
    assert fixed.scenes[0].text == before.scenes[0].text and fixed.scenes[0].action == before.scenes[0].action
    assert fixed.scenes[0].end.value == "he stops, turns and smiles"
    assert fixed.scenes[0].length_s == 5 and fixed.sheet.product.source == "photo"
    assert [p.id for p in fixed.sheet.people] == ["P1"] and fixed.sheet.people[0].clothes.value == "the hoodie"
    assert len(log) == 5 and all("put back" in line for line in log)
    assert restore_locked(before, before.model_copy(deep=True))[1] == []


def test_gaps_are_empty_key_slots_and_guesses_are_listed_for_the_marks():
    ad = _ad()
    assert key_gaps(ad) == []
    assert "scene 1: product_moment" in guesses(ad) and "P1: look" in guesses(ad)
    assert "scene 1: text" not in guesses(ad)
    ad.scenes[0].product_moment = Slot()
    ad.scenes[0].end = Slot()
    ad.sheet.place = Slot()
    assert key_gaps(ad) == ["place", "scene 1: product moment", "scene 1: end"]


def _board(story_parts: list[str]) -> Storyboard:
    scenes = [
        Scene(role="demo", description=p, image_prompt="pic", motion_prompt=f"0-2 s: {p}", voiceover="", duration_s=4)
        for p in story_parts
    ]
    hooks = [Hook(formula=f, text="Look") for f in ("pov", "problem_first", "three_reasons")]
    return Storyboard(title="Hoodie", scenes=scenes, hooks=hooks, cta_text="Shop now", notes="Night, rain, neon.")


def test_todays_storyboard_reads_into_the_structure():
    parts = ["0:00 - 0:04 | he walks in the rain.", "0:04 - 0:08 | he pulls the hood up."]
    story = "Night, rain, neon.\n" + "\n".join(parts)
    brief = Brief(product_name="City Harmony hoodie", description="Black heavy cotton hoodie.", story=story)
    analysis = ProductAnalysis(
        product_type="hoodie", visual_description="black hoodie, City Harmony print", people_in_photo=False
    )
    ad = from_storyboard(_board(parts), brief, analysis)
    assert ad.kind == "video" and ad.has_photo and ad.split == "time_ranges" and len(ad.scenes) == 2
    assert ad.sheet.product.source == "photo" and ad.notes == "Night, rain, neon."
    assert all(s.text.source == "user" and s.length_source == "user" for s in ad.scenes)
    assert all(s.action.source == "ai_guess" for s in ad.scenes)  # today the writer writes the movement
    assert ad.scenes[0].text.value == parts[0]

    written = from_storyboard(_board(["A man walks."]), Brief(product_name="X", description="A hoodie for rain."))
    assert written.split == "none" and written.scenes[0].text.source == "ai_guess"
    assert written.sheet.product.source == "user"  # no photo reading: the brief's own words
