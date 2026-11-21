"""How many scenes an ad has and how long each one is, decided in code. DB-free.

- A story with timestamps sets both (story_beats.py).
- A chosen video length sets the number of scenes (about 2.5 s per scene: fast cuts, each moment
  with its own instruction) and the total; each scene gets the time its spoken line needs (about 2.5 words
  per second, plus a little air) and the rest is shared out.
- "Auto" leaves the number to the writer, and only makes sure every line has time to be said.
"""

from __future__ import annotations

import math

from ..models import MAX_SCENES, MIN_SCENES

SECONDS_PER_SCENE = 2.5  # owner's choice (D28): more, shorter scenes give more detail
WORDS_PER_SECOND = 2.5
MIN_SCENE_S, MAX_SCENE_S = 2, 10


def scenes_for_length(video_s: int, end_card_s: float) -> int:
    scenes_s = max(MIN_SCENE_S, video_s - end_card_s)
    return max(MIN_SCENES, min(MAX_SCENES, round(scenes_s / SECONDS_PER_SCENE)))


def speech_seconds(line: str) -> int:
    words = len(line.split())
    return 0 if words == 0 else math.ceil(words / WORDS_PER_SECOND + 0.5)


def fit_lengths(voiceovers: list[str], total_s: int) -> list[int]:
    """Whole seconds per scene (2-10) that add up to total_s where possible, speech first."""
    n = len(voiceovers)
    total_s = max(MIN_SCENE_S * n, min(MAX_SCENE_S * n, total_s))
    need = [max(MIN_SCENE_S, min(MAX_SCENE_S, speech_seconds(v))) for v in voiceovers]
    while sum(need) > total_s:  # too much speech for the time: shorten the longest (the voice speeds up a little)
        i = max(range(n), key=lambda k: need[k])
        if need[i] <= MIN_SCENE_S:
            break
        need[i] -= 1
    k = 0
    while sum(need) < total_s:  # share the rest out, one second at a time
        if need[k % n] < MAX_SCENE_S:
            need[k % n] += 1
        k += 1
    return need


def at_least_speech(lengths: list[int], voiceovers: list[str]) -> list[int]:
    """Auto mode: keep the writer's lengths but give every spoken line the time it needs."""
    return [
        max(MIN_SCENE_S, min(MAX_SCENE_S, max(d, speech_seconds(v)))) for d, v in zip(lengths, voiceovers, strict=True)
    ]
