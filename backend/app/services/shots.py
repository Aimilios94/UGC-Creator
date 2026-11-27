"""Scenes and shots (D32): where each shot flows on from the one before and where it cuts. DB-free.

A storyboard "scene" is one shot: one clip, one continuous take. The user's story decides the cuts
(`scene_splitter.py`: "cut to", "rapid cuts of A, B and C", headings, timestamps); shots cut from
one part of the story share its `part` number, so the page groups them as one scene.

How each shot meets the one before (`join`), by the brief's "How it's cut" choice:
- auto (default): it flows on from the last frame, unless the story cuts there or the person or
  the place changes (then a new picture and a clean cut: one person never morphs into another);
- flowing: one flowing take; only a new person or place cuts;
- cuts: a clean cut at every shot, each with its own picture;
- separate: separate shots, each with its own picture, joined with a soft blend.
The story's own end card (a logo on screen) is drawn by us, never filmed (`kind == "card"`).
"""

from __future__ import annotations

import copy
import re
import uuid

from ..models import MAX_SCENES, MIN_SHOT_S, SPLIT_NOTE_MAX, Brief, Scene, Storyboard
from .scene_splitter import card_sentence, fast_story

CARD_NOTE = "Your story's logo line becomes the ad's end card, made by us: the video AI writes letters badly."
KEPT_NOTE = (
    "Your story ends on the logo: the last shot shows the print on the product (the video AI never writes a logo), "
    "then the end card, made by us, shows your product name."
)
CARD_TEXT = "Your end card: the product name, your offer and your button, made by us."
# The logo as a graphic on the screen (drawn by us), not on the product someone wears or holds.
_ON_SCREEN = re.compile(
    r"\b(?:black|screen|slams?|appears?|pops?|fades?\s+in|title\s+card|end\s+card|end\s+screen|on\s+white)\b", re.I
)
_LOGO = re.compile(r"\b(?:the\s+)?(?:brand(?:'s)?\s+)?logo\b", re.I)


def _end_card_after(board: Storyboard, last: Scene, end_card_s: float, description: str) -> Scene:
    card = last.model_copy(
        deep=True,
        update={
            "uid": uuid.uuid4().hex[:8],
            "description": description,
            "kind": "card",
            "join": "cut",
            "voiceover": "",
            "voiceover_ideas": [],
            "on_screen_text": "",
            "image_prompt": "",
            "motion_prompt": "",
            "starts": "",
            "ends": "",
            "ai_added": False,
            "duration_s": max(MIN_SHOT_S, round(end_card_s)),
        },
    )
    last.role = "demo"
    board.scenes.append(card)
    return card


def _twin_card(board: Storyboard, card: Scene, before_text: str, card_text: str, said: str) -> None:
    if not board.structure or len(board.structure.get("scenes", [])) != len(board.scenes) - 1:
        return
    before = board.structure["scenes"][-1]
    twin = copy.deepcopy(before)
    twin["uid"] = card.uid
    for card_dict, text in ((before, before_text), (twin, card_text)):
        slot = card_dict.get("text")
        if isinstance(slot, dict) and said in (slot.get("value") or ""):
            slot["value"] = text
    board.structure["scenes"].append(twin)


def split_end_card(board: Storyboard, end_card_s: float) -> bool:
    """The last shot ending on a logo or brand reveal gets the ad's own end card (drawn by us, free),
    so the video AI never writes a logo. A logo as a graphic on screen ("slams onto black") is the
    card itself; a reveal on the product (someone turns to show the print) stays a filmed shot, its
    logo words made "the print", and the card follows: no shot is lost (D31). Works whatever made
    the scenes (the splitter, the slot filler or the writer). True when a card was made."""
    if not board.scenes or board.scenes[-1].kind == "card":
        return False
    last = board.scenes[-1]
    found = card_sentence(last.description)
    if not found:
        return False
    rest, said = found
    if not _ON_SCREEN.search(said):
        if len(board.scenes) >= MAX_SCENES:
            return False
        last.description = _LOGO.sub("the print", last.description)
        last.motion_prompt = _LOGO.sub("the print", last.motion_prompt)
        card = _end_card_after(board, last, end_card_s, CARD_TEXT)
        _twin_card(board, card, last.description, CARD_TEXT, said)
        board.split_note = " ".join(x for x in (board.split_note, KEPT_NOTE) if x)[:SPLIT_NOTE_MAX]
        return True
    if len(rest.split()) < 3:  # the whole shot is the reveal
        if len(board.scenes) < 2:
            return False
        last.kind = "card"
    elif len(board.scenes) >= MAX_SCENES:
        return False
    else:
        last.description = rest
        card = _end_card_after(board, last, end_card_s, said)
        _twin_card(board, card, rest, said, said)
    board.split_note = " ".join(x for x in (board.split_note, CARD_NOTE) if x)[:SPLIT_NOTE_MAX]
    return True


def _people(card) -> set[str]:
    return {i for i in (card.who.ids if card else []) if i != "product"}


def _place(card) -> str:
    return card.place_change.value.strip().casefold() if card else ""


def changes_scene(prev_card, card) -> bool:
    """A new person (nobody from the shot before) or another place: the shot needs its own picture."""
    a, b = _people(prev_card), _people(card)
    if a and b and not a & b:
        return True
    return _place(prev_card) != _place(card)


def plan_joins(board: Storyboard, brief: Brief) -> Storyboard:
    """Set each shot's part (when it has none) and how it joins the one before, from the brief's
    "How it's cut" choice, the story's own cuts (already on the shots) and the structure's cards."""
    from .ad_structure import AdStructure  # imports this package's models

    cards = {}
    if board.structure:
        cards = {c.uid: c for c in AdStructure.model_validate(board.structure).scenes if c.uid}
    mode = brief.cutting
    story_cuts = any(sc.join == "cut" for sc in board.scenes[1:] if sc.kind == "clip")
    if mode == "auto" and not story_cuts and fast_story(brief.story):
        mode = "cuts"  # "fast-paced shots" with no cuts of its own: each shot its own picture, a clean cut
    board.continuity = "separate" if mode == "separate" else "continuous"
    prev = None
    for i, sc in enumerate(board.scenes):
        if not sc.part:
            sc.part = (board.scenes[i - 1].part + 1) if i else 1
        card = cards.get(sc.uid)
        if i == 0:
            sc.join = "flow"
        elif mode in ("cuts", "separate") or sc.kind == "card":
            sc.join = "cut"
        elif changes_scene(prev, card):
            sc.join = "cut"
        elif mode == "flowing":
            sc.join = "flow"
        # auto: a cut the story asked for stays a cut; otherwise the shot flows on
        prev = card
    return board


def voice_rooms(scenes: list[Scene]) -> list[float]:
    """Seconds each shot's spoken line may run: its own length plus the following shots of the same
    part that say nothing, so one line can play over a part's quick cuts without holding a frame."""
    rooms = []
    for i, sc in enumerate(scenes):
        room = float(sc.duration_s)
        for nxt in scenes[i + 1 :]:
            if nxt.part != sc.part or nxt.voiceover.strip() or nxt.kind == "card":
                break
            room += nxt.duration_s
        rooms.append(room)
    return rooms
