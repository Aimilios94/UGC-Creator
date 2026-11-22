"""The user's own story split into scenes in code, not left to the writer (strategy plan phase 2,
D31). DB-free.

Shapes, tried in this order; the first that matches wins:
1. Time ranges ("0:00 - 0:04 ..."): one scene per timed beat, its length from the range.
2. "Scene N" or "Shot N" headings, 2 or more: one scene per heading; seconds from the heading
   ("Scene 1 (10 seconds):", "Shot 2, 3 s:"), or from a timeline inside it ("0-2 s ... 4-5 s"),
   otherwise from the length plan.
3. A numbered or bulleted list of 2-5 items, each describing an action: one scene per item.
4. Paragraphs (2-5, no times): the AI marks each one a scene or notes inside the slot filler call
   (`slot_filler.py`, phase 3); code checks the marks and builds the scenes from the paragraphs.
5. No shape: the scene count comes from the chosen length, or 3 (hook, demo, call to action).

For every shape: text that is not a scene (style, place, characters, rules, headings) becomes the
story's notes, never dropped; more than 5 scenes are joined, shortest neighbours first, and the
user is told; "cut to" inside a scene starts a new scene when there is room, because one Kling
clip is one continuous take. Each scene keeps the user's own words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..models import MAX_SCENES

Shape = Literal["time_ranges", "headings", "list", "paragraphs", "none"]
SOURCE = {"time_ranges": "your timestamps", "headings": "your scene headings", "list": "your list"}
MIN_S, MAX_S = 2, 10

_STAMP = r"\d{1,2}[:.]\d{2}(?:\.\d+)?"
_BEAT_START = re.compile(rf"(?=(?<![\d:.]){_STAMP}\s*[-–—]\s*{_STAMP})")
_RANGE = re.compile(rf"({_STAMP})\s*[-–—]\s*({_STAMP})")
_BULLET = re.compile(r"^[\s•○◦*\-]+", re.M)

# "Scene 2", "Shot 3", "**Scene 1**", "## Shot 2" at a line start or after a sentence end.
_HEADING = re.compile(r"(?:^|(?<=[.!?;])[ \t]+)[ \t>#*_•-]*(?:scene|shot)[ \t]*(\d{1,2})\b(?:\*\*|__)?", re.I | re.M)
_SECONDS = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s*(?:s|sec|secs|second|seconds)\b", re.I)
_INNER_RANGE = re.compile(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s*(?:s|sec|secs|seconds)\b", re.I)
_ITEM = re.compile(r"^[ \t]*(?:\d{1,2}[.)]|[-*•–])[ \t]+(\S.*)$")
# A paragraph or item that is a note, not a scene: "Style: ...", "Lighting - ...".
_NOTE_LABEL = re.compile(
    r"^[ \t>#*_•-]*(?:style|look|visual style|notes?|lighting|light|setting|location|place|world|mood|tone|"
    r"colou?rs?|palette|music|sound|rules?|characters?|cast|product|brand|format|camera style|"
    r"continuity|consistency|wardrobe|clothes|outfit|aspect ratio|negative|avoid)\b[^:\n]{0,30}[:\-–—]",
    re.I,
)
_CUT_TO = re.compile(r"[,;]?\s*\b(?:and\s+then\s+|then\s+|and\s+)?(?:hard\s+)?cut(?:s|ting)?\s+to\b[:,]?\s*", re.I)


@dataclass
class Beat:
    text: str  # the user's own words for this scene
    seconds: int | None  # 2-10 when the story gives it, else None (the length plan decides)
    numbers: list[int] = field(default_factory=list)  # the user's scene numbers in it (for messages)


@dataclass
class Split:
    shape: Shape
    beats: list[Beat]  # empty for paragraphs and no shape: the writer decides
    notes: str  # everything that is not a scene: added to every scene's instructions
    messages: list[str] = field(default_factory=list)  # joins and splits, said to the user

    def summary(self) -> str:
        """One plain line for the storyboard. No scene count, so it stays true when the user adds or
        joins scenes later."""
        if not self.beats:
            return ""
        if self.shape == "paragraphs":  # the AI read which paragraphs are scenes (phase 3)
            line = "The AI read your paragraphs into scenes, in your words"
            if self.notes:
                line += f"; {_count(self.notes)} kept as notes for every scene"
        else:
            line = f"The scenes follow {SOURCE[self.shape]}, in your words"
            if self.notes:
                line += "; the rest of your text is kept as notes for every scene"
        return " ".join([line + ".", *self.messages])


def _count(notes: str) -> str:
    n = len(_paragraphs(notes))
    return "one paragraph" if n == 1 else f"{n} paragraphs"


def _clamp(s: float) -> int:
    return max(MIN_S, min(MAX_S, round(s)))


# --- 1. time ranges ---------------------------------------------------------------------------------
def _secs(stamp: str) -> float:
    m, s = re.split(r"[:.]", stamp, maxsplit=1)
    return int(m) * 60 + float(s)


def _time_ranges(story: str) -> Split | None:
    text = _BULLET.sub("", story)
    pieces = [p.strip() for p in _BEAT_START.split(text) if p.strip()]
    notes = [p for p in pieces if not _RANGE.match(p)]
    timed = [p for p in pieces if _RANGE.match(p)]
    if len(timed) < 2:
        return None
    beats: list[Beat] = []
    span: tuple[float, float] | None = None  # the time range of the last beat
    for p in timed:
        start, end = (_secs(x) for x in _RANGE.search(p).groups())
        if span and span[0] <= start and end <= span[1]:
            # A moment inside the last beat ("0:00 - 0:04 ... Around 0:02-0:04, ..."): the same scene.
            beats[-1].text = f"{beats[-1].text} {p}"
            continue
        beats.append(Beat(text=p, seconds=_clamp(end - start), numbers=[len(beats) + 1]))
        span = (start, end)
    if len(beats) < 2:
        return None
    return Split("time_ranges", beats, "\n".join(notes).strip())


# --- 2. "Scene N" / "Shot N" headings -------------------------------------------------------------
_LABEL_ONLY = re.compile(
    r"^[\s*_#.\-–—]*(?:\([^)]{0,40}\)|\d{1,2}(?:[.,]\d+)?\s*(?:s|sec|secs|seconds))?[\s*_#.\-–—]*$", re.I
)


def _short_label(label: str) -> bool:
    """A heading's label ("(10 seconds)", "- Hook, 3 s", "The walk"), not the scene's words."""
    return bool(_SECONDS.search(label)) or len(re.sub(r"[()\[\]*_#\-–—,.]", " ", label).split()) <= 4


def _heading_end(text: str, pos: int) -> tuple[str, int]:
    """The heading's label after "Scene N" and where the scene's own words start. Words are never
    dropped: anything that does not look like a short label stays in the scene."""
    line_end = text.find("\n", pos)
    line_end = len(text) if line_end < 0 else line_end
    rest = text[pos:line_end]
    colon = rest.find(":")
    if 0 <= colon <= 60 and _short_label(rest[:colon]):
        return rest[:colon], pos + colon + 1
    if _LABEL_ONLY.match(rest):
        return rest, line_end  # the heading is the whole line; the scene starts on the next
    lead = re.match(r"[ \t*_)\].,\-–—]*", rest)
    return "", pos + (lead.end() if lead else 0)


def _seconds_in(label: str, body: str) -> int | None:
    m = _SECONDS.search(label)
    if m:
        return _clamp(float(m.group(1).replace(",", ".")))
    ends = [int(b) for _, b in _INNER_RANGE.findall(body)]
    if ends and MIN_S <= max(ends) <= MAX_S:
        return max(ends)  # a timeline inside the scene ("0-2 s ... 4-5 s"): its end
    return None


def _split_trailing_notes(body: str) -> tuple[str, str]:
    """Labelled paragraphs at the end of the last scene ("Style: ...") are notes, not the scene."""
    paras = re.split(r"\n\s*\n", body.strip())
    keep, notes = paras, []
    while len(keep) > 1 and _NOTE_LABEL.match(keep[-1]):
        notes.insert(0, keep.pop())
    return "\n\n".join(keep).strip(), "\n\n".join(notes).strip()


def _headings(story: str) -> Split | None:
    marks = list(_HEADING.finditer(story))
    if len(marks) < 2:
        return None
    beats: list[Beat] = []
    for i, m in enumerate(marks):
        label, start = _heading_end(story, m.end())
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(story)
        body = story[start:stop].strip()
        if not body:
            continue
        beats.append(Beat(text=body, seconds=_seconds_in(label, body), numbers=[int(m.group(1))]))
    if len(beats) < 2:
        return None
    beats[-1].text, trailing = _split_trailing_notes(beats[-1].text)
    preamble = story[: marks[0].start()].strip()
    return Split("headings", beats, "\n\n".join(x for x in (preamble, trailing) if x))


# --- 3. a list ------------------------------------------------------------------------------------
def _is_action(item: str) -> bool:
    return len(item.split()) >= 3 and not _NOTE_LABEL.match(item)


def _list(story: str) -> Split | None:
    """Items that describe an action are scenes; labelled items ("- Style: ...") and the text
    around the list are notes."""
    items: list[str] = []
    before: list[str] = []
    after: list[str] = []
    for line in story.splitlines():
        m = _ITEM.match(line)
        if after:
            after.append(line)
        elif m:
            items.append(m.group(1).strip())
        elif items and not line.strip():
            continue  # a blank line between items
        elif items and line[:1] in " \t":
            items[-1] += " " + line.strip()  # an indented continuation of the item
        elif items:
            after.append(line)
        else:
            before.append(line)
    scenes = [x for x in items if _is_action(x)]
    if not 2 <= len(scenes) <= MAX_SCENES:
        return None
    labelled = [x for x in items if not _is_action(x)]
    beats = [Beat(text=x, seconds=_seconds_in("", x), numbers=[i + 1]) for i, x in enumerate(scenes)]
    notes = "\n".join(x for x in ("\n".join(before).strip(), *labelled, "\n".join(after).strip()) if x)
    return Split("list", beats, notes)


# --- rules for every shape ------------------------------------------------------------------------
def _names(numbers: list[int]) -> str:
    return " and ".join(", ".join(str(n) for n in numbers).rsplit(", ", 1))


def _join_extra(split: Split) -> None:
    """More than 5 scenes: join the shortest neighbours (by seconds, else by words) and say so."""
    beats = split.beats
    joined = []
    while len(beats) > MAX_SCENES:

        def size(b: Beat) -> float:
            return b.seconds if b.seconds is not None else len(b.text.split()) / 100

        i = min(range(len(beats) - 1), key=lambda k: size(beats[k]) + size(beats[k + 1]))
        a, b = beats[i], beats[i + 1]
        secs = None if a.seconds is None or b.seconds is None else min(MAX_S, a.seconds + b.seconds)
        beats[i : i + 2] = [Beat(text=f"{a.text} {b.text}", seconds=secs, numbers=a.numbers + b.numbers)]
        joined.append(i)
    if joined:
        groups = [b.numbers for b in beats if len(b.numbers) > 1]
        parts = "; ".join(f"scenes {_names(g)}" for g in groups)
        split.messages.append(f"An ad has at most {MAX_SCENES} scenes, so these were joined: {parts}.")


def _split_cuts(split: Split) -> None:
    """ "Cut to" inside a scene starts a new scene while there is room (one clip is one take)."""
    out: list[Beat] = []
    pending = list(split.beats)
    while pending:
        beat = pending.pop(0)
        m = _CUT_TO.search(beat.text)
        head = beat.text[: m.start()].rstrip(" ,;-–—") if m else ""
        tail = beat.text[m.end() :].strip() if m else ""
        room = len(out) + 1 + len(pending) < MAX_SCENES
        short = beat.seconds is not None and beat.seconds < 2 * MIN_S
        # Both sides must say something (a time stamp alone is not a scene).
        if not (m and len(_RANGE.sub("", head).split()) >= 3 and len(tail.split()) >= 2):
            out.append(beat)
            continue
        name = _names(beat.numbers)
        if not room or short:
            why = f"there are already {MAX_SCENES} scenes" if not room else f"it is only {beat.seconds} s"
            split.messages.append(
                f'Scene {name} says "cut to", but {why}: it stays one shot, '
                "so the cut may look like a fast camera move."
            )
            out.append(beat)
            continue
        if beat.seconds is None:
            a = b = None
        else:
            a = max(MIN_S, min(beat.seconds - MIN_S, round(beat.seconds * len(head) / (len(head) + len(tail)))))
            b = beat.seconds - a
        tail = tail[0].upper() + tail[1:]
        out.append(Beat(text=head, seconds=a, numbers=beat.numbers))
        pending.insert(0, Beat(text=tail, seconds=b, numbers=beat.numbers))
        split.messages.append(f'Scene {name} says "cut to", so it became two scenes (one clip is one take).')
    split.beats = out


def _paragraphs(story: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", story) if p.strip()]


def split_story(story: str) -> Split:
    """The story's scenes and notes, from the first shape that matches (see the module doc)."""
    text = (story or "").strip()
    if not text:
        return Split("none", [], "")
    for find in (_time_ranges, _headings, _list):
        found = find(text)
        if found is not None:
            _join_extra(found)
            _split_cuts(found)
            # Repeated messages (two cuts in one scene) are said once.
            found.messages = list(dict.fromkeys(found.messages))
            return found
    if 2 <= len(_paragraphs(text)) <= MAX_SCENES:
        return Split("paragraphs", [], "")
    return Split("none", [], "")


def story_beats(story: str) -> list[Beat] | None:
    """The story's scenes when code can read them (time ranges, headings, a list), else None."""
    return split_story(story).beats or None


def story_notes(story: str) -> str:
    """Everything in such a story that is not a scene (empty when the writer reads the story whole)."""
    split = split_story(story)
    return split.notes if split.beats else ""
