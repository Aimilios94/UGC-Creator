"""The fixed structure every prompt is read into (strategy plan, D31). DB-free.

One cast and world sheet (written once, reused in every clip) plus 1-5 scene cards. Every slot
holds a value and where it came from:
- `user`: the user typed it;
- `story`: the user's story says it, in other words (code checks a meaningful word of it is there);
- `photo`: the photo reader saw it;
- `answer`: the user picked or typed it in a quick question;
- `ai_guess`: the AI filled a gap.
Only `ai_guess` slots may be changed by the AI later; the others are locked, and code puts them
back if a model changes them (`restore_locked`).

Since phase 3 the slot filler (`slot_filler.py`) fills it before the writer, and the storyboard
carries it (`Storyboard.structure`, each card matched to its scene by uid) so the page can mark
every guess. Since phase 4 the clip builder (`video_gen.clip_prompt`) builds every clip from it,
and a value the user edits on the page becomes theirs (`merge_structure`). `from_storyboard` reads
an older storyboard into the structure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..models import MAX_SCENES, MIN_SCENES, STORY_MAX, Brief, ProductAnalysis, Storyboard

SlotSource = Literal["user", "story", "photo", "answer", "ai_guess"]
LOCKED_SOURCES: frozenset[str] = frozenset({"user", "story", "photo", "answer"})
SplitShape = Literal["time_ranges", "headings", "list", "paragraphs", "none"]
SLOT_MAX = STORY_MAX  # a slot never cuts what the user typed (D30): long text is checked per clip


class Slot(BaseModel):
    value: str = Field(default="", max_length=SLOT_MAX)
    source: SlotSource = "ai_guess"

    @property
    def empty(self) -> bool:
        return not self.value.strip()

    @property
    def locked(self) -> bool:
        return self.source in LOCKED_SOURCES and not self.empty


def user(value: str) -> Slot:
    return Slot(value=value, source="user")


def guess(value: str = "") -> Slot:
    return Slot(value=value, source="ai_guess")


class Person(BaseModel):
    """One person in the ad, referred to by id (P1, P2...) in the scene cards."""

    id: str = Field(pattern=r"^P[1-9]$")
    label: str = Field(default="", max_length=60)  # a short name for the page: "the man", "the woman"
    look: Slot = Field(default_factory=guess)  # face, hair, skin, age range
    clothes: Slot = Field(default_factory=guess)
    unseen: Slot = Field(default_factory=guess)  # details off camera or on the hidden side (a back print)


class CastSheet(BaseModel):
    """The video's anchors, the same in every clip."""

    product: Slot = Field(default_factory=guess)  # exact look: from the photo reader, or the brief with no photo
    product_unseen: Slot = Field(default_factory=guess)  # details the photo does not show
    people: list[Person] = Field(default_factory=list, max_length=6)
    place: Slot = Field(default_factory=guess)
    time_light: Slot = Field(default_factory=guess)  # time of day, light source, mood
    look: Slot = Field(default_factory=guess)  # style, lens, colour grade
    camera_style: Slot = Field(default_factory=guess)  # how the whole ad is filmed
    never: Slot = Field(default_factory=guess)  # things to avoid in every clip (the negative prompt)


class CastRefs(BaseModel):
    """Who is in a shot: cast ids, plus "product" when the product is in frame."""

    ids: list[str] = Field(default_factory=list, max_length=7)
    source: SlotSource = "ai_guess"

    @property
    def empty(self) -> bool:
        return not self.ids


class Swap(BaseModel):
    """An action the writer replaced because Kling does it badly (plan A1): the clip gets `value`
    instead of the user's `original`, the page says "AI changed: reason", and Undo removes the swap."""

    original: str = Field(max_length=SLOT_MAX)
    value: str = Field(default="", max_length=SLOT_MAX)
    reason: str = Field(max_length=200)


class SceneCard(BaseModel):
    uid: str = Field(default="", max_length=16)  # the storyboard scene it belongs to (Scene.uid)
    text: Slot = Field(default_factory=guess)  # the scene's own words as split from the prompt, kept whole
    who: CastRefs = Field(default_factory=CastRefs)
    action: Slot = Field(default_factory=guess)  # one main action, in plain verbs
    camera: Slot = Field(default_factory=guess)  # shot size, move, speed
    timeline: Slot = Field(default_factory=guess)  # 2-4 time marks for 5 s, up to 5 for 10 s
    start: Slot = Field(default_factory=guess)  # the first moment of the shot
    end: Slot = Field(default_factory=guess)  # the last moment; for the last scene, how the ad ends
    product_moment: Slot = Field(default_factory=guess)  # worn, held, close-up, in use
    place_change: Slot = Field(default_factory=guess)  # only when this scene differs from the sheet
    spoken_line: Slot = Field(default_factory=guess)  # the voiceover, word for word
    headline: Slot = Field(default_factory=guess)  # drawn by us in compose
    avoid: Slot = Field(default_factory=guess)  # this scene's extra negatives
    length_s: int = Field(default=5, ge=2, le=10)
    length_source: SlotSource = "ai_guess"
    swap: Swap | None = None


class Question(BaseModel):
    """A quick question about an empty key slot (plan: at most 3, always skippable)."""

    slot: str = Field(max_length=60)  # what it fills, for example "who", "place", "end"
    text: str = Field(max_length=120)
    # Suggestion buttons; the page adds "Let the AI decide" and a free-text box.
    options: list[str] = Field(min_length=2, max_length=4)
    answer: str = Field(default="", max_length=600)


class AdStructure(BaseModel):
    kind: Literal["video", "image"] = "video"
    has_photo: bool = True
    split: SplitShape = "none"  # how the prompt was split into scenes
    sheet: CastSheet = Field(default_factory=CastSheet)
    scenes: list[SceneCard] = Field(min_length=MIN_SCENES, max_length=MAX_SCENES)
    notes: str = Field(default="", max_length=STORY_MAX)  # the prompt's text that is not a scene, kept whole
    merged: list[str] = Field(default_factory=list)  # plain messages: "Scenes 4 and 5 were joined"
    questions: list[Question] = Field(default_factory=list, max_length=3)


# --- key slots and gaps -------------------------------------------------------------------------
SCENE_SLOTS = (
    "text", "action", "camera", "timeline", "start", "end", "product_moment",
    "place_change", "spoken_line", "headline", "avoid",
)  # fmt: skip
SHEET_SLOTS = ("product", "product_unseen", "place", "time_light", "look", "camera_style", "never")
PERSON_SLOTS = ("look", "clothes", "unseen")


def key_gaps(ad: AdStructure) -> list[str]:
    """Key slots with no value at all (neither typed nor guessed), as "scene 2: action" or "product".
    A finished structure has none: every key slot is either the user's or marked as the AI's guess."""
    gaps = ["product"] if ad.sheet.product.empty else []
    if ad.kind == "video" and ad.sheet.place.empty and not all(not sc.place_change.empty for sc in ad.scenes):
        gaps.append("place")
    for i, sc in enumerate(ad.scenes, start=1):
        if sc.who.empty:
            gaps.append(f"scene {i}: who")
        if sc.action.empty and sc.text.empty:
            gaps.append(f"scene {i}: action")
        if sc.product_moment.empty:
            gaps.append(f"scene {i}: product moment")
    if ad.kind == "video" and ad.scenes[-1].end.empty:
        gaps.append(f"scene {len(ad.scenes)}: end")
    return gaps


def guesses(ad: AdStructure) -> list[str]:
    """Every filled slot the AI guessed, for the light "AI's guess" marks on the page."""
    out = [f"sheet: {n}" for n in SHEET_SLOTS if _is_guess(getattr(ad.sheet, n))]
    for p in ad.sheet.people:
        out += [f"{p.id}: {n}" for n in PERSON_SLOTS if _is_guess(getattr(p, n))]
    for i, sc in enumerate(ad.scenes, start=1):
        out += [f"scene {i}: {n}" for n in SCENE_SLOTS if _is_guess(getattr(sc, n))]
    return out


def _is_guess(slot: Slot) -> bool:
    return slot.source == "ai_guess" and not slot.empty


# --- locked slots -------------------------------------------------------------------------------
def restore_locked(before: AdStructure, after: AdStructure) -> tuple[AdStructure, list[str]]:
    """Put back every locked slot (user, photo, answer) that a model changed or dropped.

    Returns the corrected structure and a log line per slot put back. Scenes are matched by
    position, people by id; a scene the model removed cannot be put back here (the scene count
    is checked where the scenes are split)."""
    fixed = after.model_copy(deep=True)
    log: list[str] = []

    def keep(where: str, old: Slot, new_owner, name: str) -> None:
        new = getattr(new_owner, name)
        if old.locked and (new.value != old.value or new.source != old.source):
            setattr(new_owner, name, old.model_copy())
            log.append(f"{where}: {name} put back (it was the {old.source}'s)")

    for name in SHEET_SLOTS:
        keep("sheet", getattr(before.sheet, name), fixed.sheet, name)
    people = {p.id: p for p in fixed.sheet.people}
    for p in before.sheet.people:
        if p.id not in people:
            if any(getattr(p, n).locked for n in PERSON_SLOTS):
                fixed.sheet.people.append(p.model_copy(deep=True))
                log.append(f"{p.id}: put back (it held the user's details)")
            continue
        for name in PERSON_SLOTS:
            keep(p.id, getattr(p, name), people[p.id], name)
    for i, (old, new) in enumerate(zip(before.scenes, fixed.scenes, strict=False), start=1):
        for name in SCENE_SLOTS:
            keep(f"scene {i}", getattr(old, name), new, name)
        if old.who.source in LOCKED_SOURCES and old.who.ids and new.who != old.who:
            new.who = old.who.model_copy()
            log.append(f"scene {i}: who put back")
        if old.length_source in LOCKED_SOURCES and new.length_s != old.length_s:
            new.length_s, new.length_source = old.length_s, old.length_source
            log.append(f"scene {i}: length put back")
    return fixed, log


# --- today's storyboard, read into the structure ------------------------------------------------
def _from_story(text: str, story: str) -> bool:
    return bool(text.strip()) and text.strip() in (story or "")


def from_storyboard(
    board: Storyboard, brief: Brief, analysis: ProductAnalysis | None = None, *, has_photo: bool = True
) -> AdStructure:
    """Today's storyboard as the new structure, so the models are tested on real data before the
    pipeline writes them. Text found word for word in the user's story or brief is the user's;
    the writer's prompts and lines are the AI's guesses; the product's look is the photo reader's."""
    story = brief.story or ""
    if analysis is not None:
        product = Slot(value=analysis.visual_description, source="photo")
    else:
        product = user(brief.description)
    sheet = CastSheet(
        product=product,
        look=guess(brief.visual_style),
        camera_style=guess(board.keep_same) if board.continuity == "continuous" else guess(),
    )
    scenes = []
    for sc in board.scenes:
        mine = _from_story(sc.description, story)
        scenes.append(
            SceneCard(
                text=Slot(value=sc.description, source="user" if mine else "ai_guess"),
                who=CastRefs(ids=["product"]),
                action=guess(sc.motion_prompt),
                start=guess(sc.starts),
                end=guess(sc.ends),
                product_moment=guess(),
                spoken_line=Slot(value=sc.voiceover, source="user" if _from_story(sc.voiceover, story) else "ai_guess"),
                headline=guess(sc.on_screen_text),
                length_s=sc.duration_s,
                length_source="user" if mine else "ai_guess",
            )
        )
    return AdStructure(
        kind="video",
        has_photo=has_photo,
        split="time_ranges" if any(s.text.source == "user" for s in scenes) else "none",
        sheet=sheet,
        scenes=scenes,
        notes=board.notes,
    )


# --- the user's edits on the page (phase 4) -----------------------------------------------------
def _edited(old: Slot, new: Slot) -> Slot:
    """A value the user changed on the page becomes theirs; an unchanged one keeps its source."""
    if new.value.strip() == old.value.strip():
        return old
    return user(new.value.strip()) if new.value.strip() else guess()


def merge_structure(old: AdStructure, new: AdStructure | None, old_scenes=(), new_scenes=()) -> AdStructure:
    """The stored structure with the user's edits from the page. Only values change (an edited value
    is the user's); sources, who is in each shot, the questions and the swaps stay the server's,
    except that the user may undo a swap. The scene texts follow the storyboard's own fields: an
    edited description is the user's scene text, an edited movement the user's timeline."""
    ad = old.model_copy(deep=True)
    if new is not None:
        for name in SHEET_SLOTS:
            setattr(ad.sheet, name, _edited(getattr(ad.sheet, name), getattr(new.sheet, name)))
        people = {p.id: p for p in new.sheet.people}
        for p in ad.sheet.people:
            if p.id in people:
                for name in PERSON_SLOTS:
                    setattr(p, name, _edited(getattr(p, name), getattr(people[p.id], name)))
        cards = {c.uid: c for c in new.scenes if c.uid}
        for card in ad.scenes:
            edit = cards.get(card.uid) if card.uid else None
            if edit is None:
                continue
            for name in SCENE_SLOTS:
                if name != "text":
                    setattr(card, name, _edited(getattr(card, name), getattr(edit, name)))
            if card.swap is not None and edit.swap is None:
                card.swap = None  # "Undo the change": the user's own words go back to the clip
    before = {s.uid: s for s in old_scenes if s.uid}
    for sc in new_scenes:
        card = next((c for c in ad.scenes if c.uid and c.uid == sc.uid), None)
        was = before.get(sc.uid)
        if card is None or was is None:
            continue
        if sc.description.strip() != was.description.strip() and sc.description.strip():
            card.text = user(sc.description.strip())
            card.swap = None  # the user rewrote the scene: their new words go to the clip
        if sc.motion_prompt.strip() != was.motion_prompt.strip():
            card.timeline = user(sc.motion_prompt.strip()) if sc.motion_prompt.strip() else guess()
    return ad
