"""The fixed rules at the end of every clip text, v2 (strategy plan A2 and A6, D31). DB-free.

The CI gate: the worst case may never pass the 300-character budget, so the clip plan's total
(2,310) stays under Kling's 2,500."""

from __future__ import annotations

import re

import pytest

from app.models import render_seconds
from app.services.styles import VIDEO as VIDEO_STYLE
from app.services.video_gen import RULES_MAX, clip_rules, speed_label

STYLES = tuple(VIDEO_STYLE)


def _rules(**kw) -> str:
    base = dict(style="realistic", duration_s=5, used_s=5, idx=1, count=3, continuous=True, ends_on_next=False)
    return clip_rules(**{**base, **kw})


def _every_case():
    for style in STYLES:
        for used in range(2, 11):
            for ends in (False, True):
                for continuous in (False, True):
                    for photo in (False, True):
                        for idx, count in ((0, 1), (0, 3), (1, 3), (2, 3)):
                            yield dict(
                                style=style, duration_s=render_seconds(used), used_s=used, idx=idx, count=count,
                                continuous=continuous, ends_on_next=ends and continuous and idx < count - 1,
                                has_photo=photo,
                            )  # fmt: skip


def test_the_worst_case_is_exactly_the_budget():
    lengths = [len(clip_rules(**case)) for case in _every_case()]
    assert max(lengths) == RULES_MAX == 300
    separate = [len(clip_rules(**c)) for c in _every_case() if not c["continuous"]]
    assert max(separate) == 170
    assert len(_rules(idx=0, count=1)) == 103  # one 5 s realistic scene: the shortest


def test_the_lines_are_word_for_word_the_plan():
    worst = _rules(style="cinematic", duration_s=10, used_s=9, ends_on_next=True)
    assert worst == (
        " One continuous take, no cuts; product exactly as in the photo. Cinematic, smooth stabilised moves,"
        " film grade. Ends exactly on the given end image; move steadily toward it. Played 1.11x faster: keep"
        " moves slow. Continues from the previous scene's last frame, same move; no restart. End mid-movement."
    )
    assert "Only the first 4 seconds are used: fit every beat in them." in _rules(used_s=4)
    assert "Spread the beats evenly over 10 seconds." in _rules(duration_s=10, used_s=10)
    no_photo = _rules(has_photo=False)
    assert "product as described above." in no_photo and "as in the photo" not in no_photo


@pytest.mark.parametrize(
    ("clip", "scene", "label"), [(5, 4, "1.25"), (5, 3, "1.67"), (5, 2, "2.5"), (10, 8, "1.25"), (10, 9, "1.11")]
)
def test_the_speed_keeps_two_decimals(clip, scene, label):
    assert speed_label(clip, scene) == label


def test_separate_shots_have_no_continue_lines():
    separate = _rules(continuous=False)
    assert "Continues from" not in separate and "End mid-movement" not in separate
    first, middle, last = (_rules(idx=i) for i in range(3))
    assert "Continues from" not in first and "End mid-movement" in first
    assert "Continues from" in middle and "End mid-movement" in middle
    assert "Continues from" in last and "End mid-movement" not in last


def test_no_clip_rule_asks_for_a_cut():
    for case in _every_case():
        assert not re.search(r"\bcut\b", clip_rules(**case), re.I)  # "no cuts" is fine; "cut to" never
