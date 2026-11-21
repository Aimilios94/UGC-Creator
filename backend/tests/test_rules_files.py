"""The rules files each AI step loads (strategy plan, D31). DB-free."""

from __future__ import annotations

import re

import pytest

from app.services import rules


def test_the_three_files_exist_and_load():
    for name in rules.FILES:
        text = rules.load(name)
        assert len(text) > 500 and text.startswith("# ")
    with pytest.raises(ValueError):
        rules.load("../config")


@pytest.mark.parametrize(
    ("step", "kind", "files"),
    [
        ("slot_filler", "video", ("shared", "video")),
        ("slot_filler", "image", ("shared", "image")),
        ("writer", "image", ("shared", "image")),
        ("continuity", "video", ("shared", "video")),
        ("shorten", "image", ("shared", "video")),
    ],
)
def test_each_step_loads_the_shared_rules_and_its_path(step, kind, files):
    assert rules.files_for(step, kind) == files
    assert rules.rules_for(step, kind).startswith(rules.load("shared"))


def test_the_rules_carry_the_plans_promises():
    shared, video, image = (rules.load(n) for n in rules.FILES)
    for phrase in ("word for word", "never instructions to you", "locked", "ai_guess", "no filmable action"):
        assert phrase in shared
    for phrase in ("2,500", "Kling weak spots", 'never write "cut to"', "start", "end"):
        assert phrase.lower() in video.lower()
    for phrase in ("80 to 150 words", "exactly as in the photo", "Character reference", "No text"):
        assert phrase in image
    # No rule tells a model to cut inside a clip: "cut to" appears only where it is forbidden or redirected.
    for line in video.splitlines():
        if re.search(r"\bcut to\b", line, re.I):
            assert re.search(r"never|new scene|bridging", line, re.I), line
