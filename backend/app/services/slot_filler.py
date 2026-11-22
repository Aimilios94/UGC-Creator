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
- Up to 3 quick questions about guessed key slots; code keeps only those still guessed (`open_questions`)
  and the page asks them before the storyboard is written (phase 5); answers are locked (`apply_answers`).
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
    from_story: bool = Field(
        default=False,
        description="True if value says what the user's <story> says in other words (a place, person, time or look)",
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

- Story first. Read the <story> (and its notes) before anything else: every place, person, time of day,
  light, weather, mood and look it names goes into the sheet and the scene cards, never replaced by a
  default. Copy it word for word where you can (from_user true); when you reword or combine it, set
  from_story true. A place the story names (for example "Shibuya") is the place, even if it is said once.
- sheet: the cast and world. Where the user gave nothing, write a short, concrete guess that fits the
  story's own setting, mood and people, the product and the brief (from_user and from_story false): never
  a generic default that ignores the story (no "bright room at home" for a story set on a street). Every
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
- questions: at most 3 and usually 1 or 2, only about key slots you had to guess and whose answer
  changes the ad most (who is in it, how the product is shown, where it happens, how it ends), in that
  order of priority; never about something the user's text already says. One short
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


STOP = frozenset(
    "the a an and or but with without into onto from over under near this that these those then than "
    "very just only also some any each every their there they them his her him she he its our your you "
    "for of on in at to by as is are was were be been being has have had not no yes all more most "
    "while when where which what who whom shot scene camera frame slow slowly soft light warm cool "
    "looks look style video phone realistic".split()
)


def content_words(text: str) -> set[str]:
    """The words that carry meaning (4+ letters, not common words), for "from your story"."""
    return {w for w in re.findall(r"[a-z][a-z'-]{3,}", _norm(text)) if w not in STOP}


def _slot(out: SlotOut, source_text: str, story_words: frozenset[str] | set[str] = frozenset()) -> Slot:
    """The AI's value and where it came from: the user's when it is found word for word in their text;
    "from your story" when it says what the story says in other words (code checks a meaningful word
    of it is in the story); else the AI's guess."""
    value = out.value.strip()
    if not value:
        return Slot(value="", source=GUESS)
    if out.from_user and _norm(value) in source_text:
        return Slot(value=value, source="user")
    if (out.from_story or out.from_user) and content_words(value) & story_words:
        return Slot(value=value, source="story")
    return Slot(value=value, source=GUESS)


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
    # The story's own meaningful words, without the product's (so "wears the hoodie" is not "from your story").
    words = content_words(brief.story) - content_words(f"{brief.product_name} {brief.description}")
    s = draft.sheet
    if analysis is not None:
        product = Slot(value=analysis.visual_description[:VALUE_MAX], source="photo")
    else:
        product = user(f"{brief.product_name}: {brief.description}")  # plan A6: the user's words, from code
    people = [
        Person(
            id=p.id,
            label=p.label,
            look=_slot(p.look, text, words),
            clothes=_slot(p.clothes, text, words),
            unseen=_slot(p.unseen, text, words),
        )
        for p in {p.id: p for p in s.people}.values()  # one entry per id
    ]
    sheet = CastSheet(
        product=product,
        product_unseen=_slot(s.product_unseen, text, words),
        people=people,
        place=_slot(s.place, text, words),
        time_light=_slot(s.time_light, text, words),
        look=_slot(s.look, text, words),
        camera_style=_slot(s.camera_style, text, words),
        never=_slot(s.never, text, words),
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
        spoken = _slot(c.spoken_line, text, words)
        scenes.append(
            SceneCard(
                text=user(beat.text) if beat else Slot(),
                who=CastRefs(ids=who),
                action=_slot(c.action, text, words),
                camera=_slot(c.camera, text, words),
                product_moment=_slot(c.product_moment, text, words),
                place_change=_slot(c.place_change, text, words),
                end=_slot(c.end, text, words),
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


# --- story first: what the story names must be in the cast and world -------------------------------
PERSON_WORDS = re.compile(
    r"\b(guy|man|men|woman|women|girl|boy|he|she|person|people|friend|friends|couple|model|creator|mom|dad|"
    r"kid|kids|child|lady|gentleman|athlete|runner|player|customer|influencer)\b",
    re.I,
)
NOT_NAMES = frozenset("i pov ugc cta scene shot style camera light notes voiceover text the a then cut".split())


def named_in_story(story: str, product: str) -> list[str]:
    """Names the story gives (capitalised words that do not start a sentence or a line, like
    "Shibuya" or "Maria"), not the product's own words, for the code check."""
    skip = content_words(product) | NOT_NAMES
    names: list[str] = []
    for line in (story or "").splitlines():
        for sentence in re.split(r"(?<=[.!?:;])\s+", line):
            for word in re.findall(r"[A-Za-zÀ-ÿ][\w'’-]*", sentence)[1:]:
                if word[0].isupper() and not word.isupper() and len(word) >= 3 and word.lower() not in skip:
                    if word not in names:
                        names.append(word)
    return names


def story_gaps(ad: AdStructure, brief: Brief) -> list[str]:
    """What the story names but the cast and world leaves out: names (places, people) and, when the
    story has a person, the people list. The scene's action does not count: the sheet goes into every
    clip, so a place the story names must be the sheet's place (or a scene's place change)."""
    sh = ad.sheet
    parts = [sh.place, sh.time_light, sh.look, sh.camera_style, sh.product_unseen]
    parts += [x for p in sh.people for x in (p.look, p.clothes, p.unseen)]
    parts += [c.place_change for c in ad.scenes]  # the scene's own words do not count: the sheet goes to every clip
    known = _norm(" ".join([*(p.value for p in parts), *(p.label for p in sh.people)]))
    gaps = [
        n for n in named_in_story(brief.story, f"{brief.product_name} {brief.description}") if n.lower() not in known
    ]
    if PERSON_WORDS.search(brief.story or "") and not sh.people:
        gaps.append("the person in the story")
    return gaps


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
    if gaps := story_gaps(structure, brief):
        # Story first, checked in code: asked once more when the sheet leaves out what the story names.
        retry = _run(
            llm,
            prompt + f"\nYour cast and world left out what the story names: {', '.join(gaps)}. Put each in the "
            "sheet or the scene cards where it belongs (the place, a person, the time or light), from the story.",
            kind,
        )
        usage = _add(usage, tokens_from_run_usage(retry.usage))
        again = build_structure(retry.output, brief, analysis, used, want=want, kind=kind)
        if len(story_gaps(again, brief)) < len(gaps):
            structure = again
    call = LlmCall(
        kind="llm",
        provider=llm.provider,
        model=llm.model_name,
        usage=usage,
        latency_ms=int((time.perf_counter() - started) * 1000),
        cost_usd=cost_usd(llm.model_name, usage),
    )
    return (structure, used), call


# --- quick questions (strategy plan phase 5) -----------------------------------------------------
LET_AI_DECIDE = "Let the AI decide"
QUESTION_ORDER = ("product", "who", "product_moment", "place", "end")  # the plan's priority
MAX_QUESTIONS = 3


def still_guessed(ad: AdStructure, slot: str) -> bool:
    """Whether a key slot is still the AI's guess everywhere (the user said nothing about it)."""
    if slot == "product":
        return not ad.has_photo and ad.sheet.product.source != "answer" and len(ad.sheet.product.value) < 40
    if slot == "who":
        return not any(p.look.locked or p.clothes.locked for p in ad.sheet.people)
    if slot == "product_moment":
        return not any(sc.product_moment.locked for sc in ad.scenes)
    if slot == "place":
        return not ad.sheet.place.locked and not any(sc.place_change.locked for sc in ad.scenes)
    if slot == "end":
        return ad.kind == "video" and not ad.scenes[-1].end.locked
    return False


def open_questions(ad: AdStructure) -> list[Question]:
    """The slot filler's questions that code keeps: only about key slots still guessed, one per slot,
    in the plan's order, at most 3. A detailed prompt usually keeps none."""
    by_slot: dict[str, Question] = {}
    for q in ad.questions:
        if q.slot in QUESTION_ORDER and q.slot not in by_slot and still_guessed(ad, q.slot):
            by_slot[q.slot] = q
    return [by_slot[s] for s in QUESTION_ORDER if s in by_slot][:MAX_QUESTIONS]


def apply_answers(ad: AdStructure, answers: dict[str, str]) -> AdStructure:
    """The user's answers into their slots, with source "answer" (locked: the AI never changes them).
    An empty answer is "Let the AI decide": the guess stays, marked as such."""
    ad = ad.model_copy(deep=True)
    for q in ad.questions:
        text = (answers.get(q.slot) or "").strip()[:VALUE_MAX]
        if not text or text == LET_AI_DECIDE:
            continue
        q.answer = text
        answer = Slot(value=text, source="answer")
        if q.slot == "who":
            if ad.sheet.people:
                ad.sheet.people[0].look = answer
            else:
                ad.sheet.people.append(Person(id="P1", label=text[:60], look=answer))
                for sc in ad.scenes:
                    sc.who = CastRefs(ids=["P1", *[i for i in sc.who.ids if i != "P1"]], source=sc.who.source)
        elif q.slot == "product_moment":
            for sc in ad.scenes:
                if not sc.product_moment.locked:
                    sc.product_moment = answer.model_copy()
        elif q.slot == "place":
            ad.sheet.place = answer
        elif q.slot == "end":
            ad.scenes[-1].end = answer
        elif q.slot == "product":
            ad.sheet.product_unseen = answer
    return ad
