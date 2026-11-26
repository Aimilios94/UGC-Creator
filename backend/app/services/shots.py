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

from ..models import Brief, Scene, Storyboard


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
