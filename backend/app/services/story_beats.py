"""The user's own story, read in code (not left to the writer). DB-free.

A story written as a shot list ("0:00 - 0:02 (Establish): ...") has one scene per timed beat.
The writer is told the exact number, and the scene text and length are taken from the story
itself, so the storyboard follows the user's structure even when the model would merge beats.

Text that is not part of a timed beat (style, setting, lighting, continuity rules, headings) is
the story's notes: optional, shown on their own, and added to every scene's instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import MAX_SCENES

_STAMP = r"\d{1,2}[:.]\d{2}(?:\.\d+)?"
_BEAT_START = re.compile(rf"(?=(?<![\d:.]){_STAMP}\s*[-–—]\s*{_STAMP})")
_RANGE = re.compile(rf"({_STAMP})\s*[-–—]\s*({_STAMP})")
_BULLET = re.compile(r"^[\s•○◦*\-]+", re.M)


@dataclass
class Beat:
    text: str  # the story's own words for this beat
    seconds: int  # from its timestamps, 2-10


def _secs(stamp: str) -> float:
    m, s = re.split(r"[:.]", stamp, maxsplit=1)
    return int(m) * 60 + float(s)


def _split(story: str) -> tuple[str, list[str]]:
    text = _BULLET.sub("", (story or "").strip())
    pieces = [p.strip() for p in _BEAT_START.split(text) if p.strip()]
    notes = []
    timed = []
    for p in pieces:
        if _RANGE.match(p):
            timed.append(p)
        else:
            notes.append(p)
    return "\n".join(notes).strip(), timed


def story_notes(story: str) -> str:
    """Everything in a timed story that is not a timed beat (empty for a story without timestamps)."""
    notes, timed = _split(story)
    return notes if len(timed) >= 2 else ""


def story_beats(story: str) -> list[Beat] | None:
    """The timed beats, in order; None when the story has fewer than two timestamp ranges."""
    _, timed = _split(story)
    if len(timed) < 2:
        return None
    beats: list[Beat] = []
    span: tuple[float, float] | None = None  # the time range of the last beat
    for p in timed:
        start, end = (_secs(x) for x in _RANGE.search(p).groups())
        if span and span[0] <= start and end <= span[1]:
            # A moment inside the last beat ("0:00 - 0:04 ... Around 0:02-0:04, ..."): the same scene.
            beats[-1] = Beat(text=f"{beats[-1].text} {p}", seconds=beats[-1].seconds)
            continue
        beats.append(Beat(text=p, seconds=max(2, min(10, round(end - start)))))
        span = (start, end)
    if len(beats) < 2:
        return None
    while len(beats) > MAX_SCENES:  # merge the two shortest neighbours
        i = min(range(len(beats) - 1), key=lambda k: beats[k].seconds + beats[k + 1].seconds)
        a, b = beats[i], beats[i + 1]
        beats[i : i + 2] = [Beat(text=f"{a.text} {b.text}", seconds=min(10, a.seconds + b.seconds))]
    return beats
