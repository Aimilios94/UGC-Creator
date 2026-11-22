"""The slot filler (strategy plan phase 3, D31): one cheap AI call that reads the brief, the photo
analysis and the split story into the fixed structure (`ad_structure.AdStructure`). DB-free.

- The cast and world sheet and one scene card per scene; every value says where it came from.
  The AI may claim a value is the user's only when it is copied word for word from the user's
  text: code checks every such claim and marks the value "ai_guess" when it is not found.
- The product's look comes from code: the photo reader's description, or the user's own words
  when there is no photo (plan A6), never from the AI.
- A story of 2-5 plain paragraphs (no times, headings or list): the AI marks each paragraph a
  scene or notes, by number. Code checks every paragraph is used exactly once, in order, and
  builds the scenes from the paragraphs themselves, so the user's words are kept whole. If the
  check fails it asks once more; if that fails too, the writer reads the story whole, as before.
- Every key slot (who, the action, how the product is shown, the place, how the ad ends) ends up
  filled: by the user, or by a guess that the storyboard marks "AI's guess".
- Up to 3 quick questions about guessed key slots (shown in phase 5).
"""

from __future__ import annotations

import json
import re
import time
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..models import MAX_SCENES, Brief, ProductAnalysis
from .ad_structure import (
    AdStructure,
    CastRefs,
    CastSheet,
    Person,
    Question,
    SceneCard,
    Slot,
    user,
)
from .analyze import brief_block
from .llm_trace import LlmCall, Usage, cost_usd, tokens_from_run_usage
from .providers.llm import LlmHandle
from .rules import rules_for
from .scene_plan import scenes_for_length
from .scene_splitter import Beat, Split, _paragraphs, _split_cuts
from .styles import LABELS as STYLE_LABELS

VALUE_MAX = 600
GUESS = "ai_guess"


class SlotOut(BaseModel):
    value: str = Field(default="", max_length=VALUE_MAX)
    from_user: bool = Field(
        default=False,
        description="True only if value is copied word for word from the user's <story> or <brief>",
    )


class PersonOut(BaseModel):
    id: str = Field(pattern=r"^P[1-9]$")
    label: str = Field(default="", max_length=60, description='A short name for the page: "the man", "the woman"')
    look: SlotOut = Field(default_factory=SlotOut, description="Face, hair, skin, age range")
    clothes: SlotOut = Field(default_factory=SlotOut)
    unseen: SlotOut = Field(default_factory=SlotOut, description="Details off camera or on the hidden side")


class SheetOut(BaseModel):
    product_unseen: SlotOut = Field(default_factory=SlotOut, description="Product details the photo does not show")
    people: list[PersonOut] = Field(default_factory=list, max_length=6)
    place: SlotOut = Field(default_factory=SlotOut)
    time_light: SlotOut = Field(default_factory=SlotOut, description="Time of day, light source, mood")
    look: SlotOut = Field(default_factory=SlotOut, description="Style, lens, colour grade")
    camera_style: SlotOut = Field(default_factory=SlotOut, description="How the whole ad is filmed")
    never: SlotOut = Field(default_factory=SlotOut, description="Things to avoid in every scene")


class CardOut(BaseModel):
    who: list[str] = Field(default_factory=list, max_length=7, description='Cast ids in the shot, plus "product"')
    action: SlotOut = Field(default_factory=SlotOut, description="One main action, in plain verbs")
    camera: SlotOut = Field(default_factory=SlotOut, description="Shot size, move, speed")
    product_moment: SlotOut = Field(default_factory=SlotOut, description="Worn, held, close-up, in use")
    place_change: SlotOut = Field(default_factory=SlotOut, description="Only if this scene's place or light differs")
    end: SlotOut = Field(default_factory=SlotOut, description="The last moment; for the last scene, how the ad ends")
    spoken_line: SlotOut = Field(default_factory=SlotOut, description="Only the user's own spoken words, else empty")


class ParagraphUse(BaseModel):
    paragraph: int = Field(ge=1, le=MAX_SCENES, description="The paragraph's number")
    use: Literal["scene", "notes"]
    scene: int | None = Field(default=None, ge=1, le=MAX_SCENES, description="The scene it belongs to (scene only)")


class QuestionOut(BaseModel):
    slot: Literal["who", "product_moment", "place", "end", "product"]
    text: str = Field(max_length=120)
    options: list[str] = Field(min_length=2, max_length=4)


class SlotDraft(BaseModel):
    paragraphs: list[ParagraphUse] = Field(default_factory=list, max_length=MAX_SCENES)
    sheet: SheetOut = Field(default_factory=SheetOut)
    scenes: list[CardOut] = Field(min_length=1, max_length=MAX_SCENES)
    questions: list[QuestionOut] = Field(default_factory=list, max_length=3)


TASK = """\
# Your task: the slot filler

Read the user's brief, the photo analysis and the user's story into the structure.

- sheet: the cast and world. Copy what the user wrote where they wrote it (from_user true, word for
  word, a short exact phrase from the <story> or <brief>). Where the user gave nothing, write a
  short, concrete guess that fits the product, the brief and the story (from_user false). Every
  person in the ad gets an entry with an id (P1, P2...). The product's own look is given in code:
  do not describe it. product_unseen: only visible details the photo or the user's text cannot show
  (the back, the inside, the other side), never facts the user did not give (sizes, capacity,
  materials, features, claims); empty when there are none.
- scenes: exactly the number of scene cards asked for, in order. For each: who (cast ids and
  "product" when it is in frame), action (one main action, plain verbs), camera (shot size and one
  move, a few words, no times: the writer adds the timeline), product_moment
  (how the product is shown), place_change (only when this scene's place or light differs from
  the sheet), end (the last moment; for the last scene, how the ad ends), spoken_line (only words
  the user wrote to be said, word for word; otherwise empty).
- Fill every key slot: who, action, product_moment, the sheet's place and the last scene's end.
  When the user did not say, guess, and set from_user false: the page marks it "AI's guess".
- from_user is true only when the value appears word for word in the user's text. A value you
  shortened, reworded or made up is a guess.
- questions: at most 3, only about key slots you had to guess and that matter most (who is in it,
  how the product is shown, where it happens, how it ends), in that order of priority. One short
  line each, with 2-4 short answer buttons that fit this product and story. None when the user's
  text already answers them.
- Keep every value short: a phrase or one sentence."""

PARAGRAPHS = """\
The story has {n} paragraphs, numbered in the paragraphs block below. Mark each one in "paragraphs": "scene"
(something the camera films: a moment, an action, a shot) or "notes" (style, look, place, people,
light, rules or other text true for the whole ad). Give each scene paragraph the number of its
scene: scenes are numbered from 1 in story order, and several neighbouring paragraphs may make one
scene. List every paragraph exactly once, in order. Write one scene card per scene you mark."""

agent = Agent(output_type=SlotDraft, name="slot_filler")


def instructions(kind: str = "video") -> str:
    return rules_for("slot_filler", kind) + "\n\n" + TASK


def scene_count(split: Split, brief: Brief, end_card_s: float) -> int | None:
    """The scene count when it is known before the AI reads the story: from the split, else the
    chosen length, else 3 (hook, demo, call to action). None for paragraphs: the AI decides."""
    if split.beats:
        return len(split.beats)
    if split.shape == "paragraphs":
        return None
    if brief.video_length_s:
        return scenes_for_length(brief.video_length_s, end_card_s)
    return 3


def build_prompt(
    brief: Brief,
    analysis: ProductAnalysis | None,
    split: Split,
    *,
    want: int | None,
    feedback: str | None = None,
) -> str:
    parts = [
        f"Visual style: {STYLE_LABELS.get(brief.visual_style, STYLE_LABELS['realistic'])}.",
        brief_block(brief.model_copy(update={"story": ""})),
    ]
    if analysis is not None:
        parts.append("<analysis>" + json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False) + "</analysis>")
    else:
        parts.append("There is no product photo: the product is only what the user's words say.")
    if brief.story:
        parts.append("<story>" + json.dumps(brief.story, ensure_ascii=False) + "</story>")
    if split.beats:
        scenes = [{"scene": i + 1, "text": b.text} for i, b in enumerate(split.beats)]
        parts.append(
            f"The story was split in code into exactly {len(scenes)} scenes: write exactly {len(scenes)} scene cards, "
            "one per scene, in order. <scenes>" + json.dumps(scenes, ensure_ascii=False) + "</scenes>"
        )
        if split.notes:
            parts.append("Text from the story that is not a scene: <notes>" + json.dumps(split.notes) + "</notes>")
    elif split.shape == "paragraphs":
        paras = _paragraphs(brief.story)
        parts.append(PARAGRAPHS.format(n=len(paras)))
        numbered = [{"paragraph": i + 1, "text": p} for i, p in enumerate(paras)]
        parts.append("<paragraphs>" + json.dumps(numbered, ensure_ascii=False) + "</paragraphs>")
    elif want:
        how = "spread the story across them, in order" if brief.story else "hook, demo and call to action"
        parts.append(f"Write exactly {want} scene cards ({how}).")
    if feedback:
        parts.append(feedback)
    return "\n".join(parts)


# --- code checks ---------------------------------------------------------------------------------
def check_paragraphs(uses: list[ParagraphUse], count: int) -> str | None:
    """Why the AI's paragraph marks cannot be used, or None when they are sound: every paragraph
    once, in order; scene numbers from 1, in order, with no gap (so 1-5 scenes)."""
    if [u.paragraph for u in uses] != list(range(1, count + 1)):
        return f"list every paragraph exactly once, in order, from 1 to {count}"
    scenes = [u.scene for u in uses if u.use == "scene"]
    if not scenes:
        return "mark at least one paragraph as a scene"
    if any(s is None for s in scenes):
        return "give every scene paragraph the number of its scene"
    last = 0
    for s in scenes:
        if s not in (last, last + 1) or s < 1:
            return "number the scenes from 1 in story order, with no gap"
        last = s
    return None


def paragraphs_split(story: str, uses: list[ParagraphUse]) -> Split:
    """The scenes and notes from checked paragraph marks: the user's paragraphs, whole."""
    paras = _paragraphs(story)
    groups: dict[int, list[str]] = {}
    notes: list[str] = []
    for u in uses:
        text = paras[u.paragraph - 1]
        if u.use == "scene":
            groups.setdefault(int(u.scene or 1), []).append(text)
        else:
            notes.append(text)
    beats = [Beat(text="\n\n".join(groups[k]), seconds=None, numbers=[k]) for k in sorted(groups)]
    split = Split("paragraphs", beats, "\n\n".join(notes))
    _split_cuts(split)
    return split


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("’", "'")).strip().casefold()


def _slot(out: SlotOut, source_text: str) -> Slot:
    """The AI's value, marked the user's only when it is found word for word in the user's text."""
    value = out.value.strip()
    mine = out.from_user and bool(value) and _norm(value) in source_text
    return Slot(value=value, source="user" if mine else GUESS)


# Last-resort guesses so no key slot is ever left empty (the page marks them "AI's guess").
FALLBACK = {
    "place": "a simple, bright setting that suits the product",
    "action": "the product is shown clearly while the camera moves slowly",
    "product_moment": "the product in clear view",
    "end": "the camera settles on the product in clear view",
}


def build_structure(
    draft: SlotDraft,
    brief: Brief,
    analysis: ProductAnalysis | None,
    split: Split,
    *,
    want: int | None = None,
    kind: str = "video",
) -> AdStructure:
    """The structure from the AI's draft, checked in code. The number of cards is the split's
    scenes, else `want`, else as many as the AI wrote; missing cards are guessed in code."""
    text = _norm(" ".join([brief.story, brief.description, brief.product_name, brief.audience, brief.offer]))
    s = draft.sheet
    if analysis is not None:
        product = Slot(value=analysis.visual_description[:VALUE_MAX], source="photo")
    else:
        product = user(f"{brief.product_name}: {brief.description}")  # plan A6: the user's words, from code
    people = [
        Person(
            id=p.id,
            label=p.label,
            look=_slot(p.look, text),
            clothes=_slot(p.clothes, text),
            unseen=_slot(p.unseen, text),
        )
        for p in {p.id: p for p in s.people}.values()  # one entry per id
    ]
    sheet = CastSheet(
        product=product,
        product_unseen=_slot(s.product_unseen, text),
        people=people,
        place=_slot(s.place, text),
        time_light=_slot(s.time_light, text),
        look=_slot(s.look, text),
        camera_style=_slot(s.camera_style, text),
        never=_slot(s.never, text),
    )
    ids = {p.id for p in people} | {"product"}
    cards = list(draft.scenes)
    n = len(split.beats) or want or len(cards)
    while len(cards) < n:  # the AI wrote too few cards: a middle card, guessed in code below
        cards.insert(max(1, len(cards) - 1), CardOut())
    cards = cards[:n]
    scenes = []
    for i, c in enumerate(cards):
        beat = split.beats[i] if split.beats else None
        who = [w for w in dict.fromkeys(c.who) if w in ids]
        spoken = _slot(c.spoken_line, text)
        scenes.append(
            SceneCard(
                text=user(beat.text) if beat else Slot(),
                who=CastRefs(ids=who),
                action=_slot(c.action, text),
                camera=_slot(c.camera, text),
                product_moment=_slot(c.product_moment, text),
                place_change=_slot(c.place_change, text),
                end=_slot(c.end, text),
                spoken_line=spoken if spoken.source == "user" else Slot(),  # only the user's own words
                length_s=beat.seconds if beat and beat.seconds else 5,
                length_source="user" if beat and beat.seconds else GUESS,
            )
        )
    questions = [Question(slot=q.slot, text=q.text, options=q.options) for q in draft.questions[:3]]
    ad = AdStructure(
        kind=kind,
        has_photo=analysis is not None,
        split=split.shape,
        sheet=sheet,
        scenes=scenes,
        notes=split.notes,
        merged=list(split.messages),
        questions=questions,
    )
    fill_gaps(ad)
    return ad


def fill_gaps(ad: AdStructure) -> None:
    """Every key slot the AI left empty gets a plain guess, so none is empty without a mark."""
    if ad.sheet.place.empty:
        ad.sheet.place = Slot(value=FALLBACK["place"])
    for sc in ad.scenes:
        if sc.who.empty:
            sc.who = CastRefs(ids=["product"])
        if sc.action.empty and sc.text.empty:
            sc.action = Slot(value=FALLBACK["action"])
        if sc.product_moment.empty:
            sc.product_moment = Slot(value=FALLBACK["product_moment"])
    if ad.kind == "video" and ad.scenes[-1].end.empty:
        ad.scenes[-1].end = Slot(value=FALLBACK["end"])


# --- the call --------------------------------------------------------------------------------------
def _run(llm: LlmHandle, prompt: str, kind: str):
    return agent.run_sync(prompt, model=llm.model, model_settings=llm.settings or None, instructions=instructions(kind))


def _add(a: Usage, b: Usage) -> Usage:
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        cached_input_tokens=a.cached_input_tokens + b.cached_input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
    )


def fill_slots(
    llm: LlmHandle,
    brief: Brief,
    analysis: ProductAnalysis | None,
    split: Split,
    *,
    kind: str = "video",
    end_card_s: float = 2.0,
) -> tuple[tuple[AdStructure, Split], LlmCall]:
    """Read the ad into the structure. Returns the structure and the split the writer follows:
    for paragraphs, the AI's checked marks turn into scenes and notes (or, if the marks fail twice,
    the split stays as it was and the writer reads the story whole)."""
    started = time.perf_counter()
    want = scene_count(split, brief, end_card_s)
    prompt = build_prompt(brief, analysis, split, want=want)
    result = _run(llm, prompt, kind)
    usage = tokens_from_run_usage(result.usage)
    draft = result.output
    used = split
    if split.shape == "paragraphs":
        count = len(_paragraphs(brief.story))
        why = check_paragraphs(draft.paragraphs, count)
        if why:
            retry = _run(llm, prompt + f"\nYour paragraph marks could not be used: {why}. Mark them again.", kind)
            usage = _add(usage, tokens_from_run_usage(retry.usage))
            draft = retry.output
            why = check_paragraphs(draft.paragraphs, count)
        if why is None:
            used = paragraphs_split(brief.story, draft.paragraphs)
    structure = build_structure(draft, brief, analysis, used, want=want, kind=kind)
    call = LlmCall(
        kind="llm",
        provider=llm.provider,
        model=llm.model_name,
        usage=usage,
        latency_ms=int((time.perf_counter() - started) * 1000),
        cost_usd=cost_usd(llm.model_name, usage),
    )
    return (structure, used), call
