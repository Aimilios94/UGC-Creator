"""The timed beats of the user's own story, read in code (not left to the writer). DB-free.

A story written as a shot list ("0:00 - 0:02 (Establish): ...") has one scene per timed beat.
The writer is told the exact number, and the scene text and length are taken from the story
itself, so the storyboard follows the user's structure even when the model would merge beats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import MAX_SCENES

_STAMP = r"\d{1,2}:\d{2}(?:\.\d+)?"
_BEAT_START = re.compile(rf"(?=(?<![\d:]){_STAMP}\s*[-–—]\s*{_STAMP})")
_RANGE = re.compile(rf"({_STAMP})\s*[-–—]\s*({_STAMP})")


@dataclass
class Beat:
    text: str  # the story's own words for this beat
    seconds: int  # from its timestamps, 2-10


def _secs(stamp: str) -> float:
    m, s = stamp.split(":")
    return int(m) * 60 + float(s)


def story_beats(story: str) -> list[Beat] | None:
    """The timed beats, in order; None when the story has fewer than two timestamp ranges."""
    text = (story or "").strip()
    pieces = [p.strip() for p in _BEAT_START.split(text) if p.strip()]
    timed = [p for p in pieces if _RANGE.match(p)]
    if len(timed) < 2:
        return None
    if pieces and not _RANGE.match(pieces[0]):  # a heading before the first beat joins it
        timed[0] = f"{pieces[0]} {timed[0]}"
    beats = []
    for p in timed:
        start, end = _RANGE.search(p).groups()
        beats.append(Beat(text=p, seconds=max(2, min(10, round(_secs(end) - _secs(start))))))
    while len(beats) > MAX_SCENES:  # merge the two shortest neighbours
        i = min(range(len(beats) - 1), key=lambda k: beats[k].seconds + beats[k + 1].seconds)
        a, b = beats[i], beats[i + 1]
        beats[i : i + 2] = [Beat(text=f"{a.text} {b.text}", seconds=min(10, a.seconds + b.seconds))]
    return beats
