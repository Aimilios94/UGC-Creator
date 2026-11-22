"""'Add scenes to reach N s' (strategy plan v2.3, phase 3). DB-free.

When the user's scenes make a shorter ad than the length picked, the writer proposes extra scenes
that fit the story, up to 5 scenes in all. Code decides how many and how long (`scene_plan.add_plan`)
and where they may go (never after the last scene, which ends the ad); the user's scenes are kept as
they are. The new scenes are marked as the AI's guess on the storyboard, and the page offers Undo.
"""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..models import MAX_SCENES, Brief, ProductAnalysis, Scene, SceneDraft, Storyboard
from .ad_structure import AdStructure, CastRefs, SceneCard, guess
from .analyze import brief_block
from .llm_trace import LlmCall, cost_usd, tokens_from_run_usage
from .providers.llm import LlmHandle
from .scene_plan import add_plan
from .storyboard import INSTRUCTIONS as WRITER_RULES
from .storyboard import sheet_block
from .styles import LABELS as STYLE_LABELS


class NewScene(BaseModel):
    after: int = Field(ge=0, le=MAX_SCENES, description="The number of the scene it follows (0 = first)")
    scene: SceneDraft


class NewScenes(BaseModel):
    scenes: list[NewScene] = Field(min_length=1, max_length=MAX_SCENES - 1)


TASK = """\
# Your task now: add scenes
The storyboard below is shorter than the video the user picked. Write ONLY the new scenes asked for,
each with the number of the scene it follows ("after"). They must fit the story and the scenes around
them: the same people, product, place, light and style, a natural step between their neighbours.
Never repeat or rewrite the existing scenes, and never put a new scene after the last one: it ends the
ad. Each new scene's duration_s is given; its spoken line, if any, must fit it."""

agent = Agent(output_type=NewScenes, instructions=WRITER_RULES + "\n\n" + TASK, name="add_scenes")


def bounds(count: int) -> tuple[int, int]:
    """Where a new scene may go: after scene 1 up to before the last; before a single scene."""
    return (0, 0) if count <= 1 else (1, count - 1)


def build_prompt(board: Storyboard, brief: Brief, analysis: ProductAnalysis | None, lengths: list[int]) -> str:
    lo, hi = bounds(len(board.scenes))
    scenes = [
        {"scene": i + 1, "seconds": s.duration_s, "what_we_see": s.description[:1500], "voiceover": s.voiceover}
        for i, s in enumerate(board.scenes)
    ]
    parts = [
        f"Platform aspect ratio: {brief.aspect_ratio}. "
        f"Visual style: {STYLE_LABELS.get(brief.visual_style, STYLE_LABELS['realistic'])}.",
        brief_block(brief.model_copy(update={"story": ""})),
    ]
    if analysis is not None:
        parts.append("<analysis>" + json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False) + "</analysis>")
    if brief.story:
        parts.append("<story>" + json.dumps(brief.story, ensure_ascii=False) + "</story>")
    parts.append("<scenes>" + json.dumps(scenes, ensure_ascii=False) + "</scenes>")
    if board.structure:
        parts.append(sheet_block(AdStructure.model_validate(board.structure)))
    ask = {"count": len(lengths), "seconds": lengths, "after": hi}
    parts.append(
        f"Write exactly {len(lengths)} new scenes with duration_s {', '.join(map(str, lengths))}, each after a "
        f"scene from {lo} to {hi}. <add>" + json.dumps(ask) + "</add>"
    )
    return "\n".join(parts)


def insert(board: Storyboard, new: list[NewScene], lengths: list[int]) -> Storyboard:
    """The board with the new scenes in place, marked as the AI's, lengths as planned."""
    lo, hi = bounds(len(board.scenes))
    placed: dict[int, list[Scene]] = {}
    for item, seconds in zip(new, lengths, strict=False):
        data = item.scene.model_dump() | {"duration_s": seconds}
        scene = Scene.model_validate(data).model_copy(update={"ai_added": True, "uid": ""})
        placed.setdefault(min(hi, max(lo, item.after)), []).append(scene)
    scenes: list[Scene] = list(placed.get(0, []))
    for i, sc in enumerate(board.scenes, start=1):
        scenes.append(sc)
        scenes += placed.get(i, [])
    out = Storyboard.model_validate(board.model_copy(update={"scenes": scenes}).model_dump())
    if board.structure:
        ad = AdStructure.model_validate(board.structure)
        cards = {c.uid: c for c in ad.scenes if c.uid}
        new_cards: list[SceneCard] = []
        who = CastRefs(ids=["product"])
        for sc in out.scenes:
            card = cards.get(sc.uid)
            if card is None:  # a new scene: the cast of the scene before it, all marked as guesses
                card = SceneCard(uid=sc.uid, text=guess(sc.description), who=who.model_copy(),
                                 action=guess(sc.description), product_moment=guess("the product in clear view"),
                                 length_s=sc.duration_s)  # fmt: skip
            elif not card.who.empty:
                who = CastRefs(ids=list(card.who.ids))
            new_cards.append(card)
        ad.scenes = new_cards
        ad.scenes[-1].end = ad.scenes[-1].end if not ad.scenes[-1].end.empty else guess("the ad ends on the product")
        out.structure = ad.model_dump(mode="json")
    return out


def add_scenes(
    llm: LlmHandle,
    board: Storyboard,
    brief: Brief,
    analysis: ProductAnalysis | None,
    *,
    end_card_s: float = 2.0,
) -> tuple[Storyboard, LlmCall]:
    """Add scenes so the ad reaches the picked length (or as close as 5 scenes allow)."""
    lengths = add_plan([s.duration_s for s in board.scenes], brief.video_length_s or 0, end_card_s)
    if not lengths:
        raise ValueError("no scenes to add: the ad already has the picked length or 5 scenes")
    started = time.perf_counter()
    result = agent.run_sync(
        build_prompt(board, brief, analysis, lengths), model=llm.model, model_settings=llm.settings or None
    )
    usage = tokens_from_run_usage(result.usage)
    call = LlmCall(
        kind="llm",
        provider=llm.provider,
        model=llm.model_name,
        usage=usage,
        latency_ms=int((time.perf_counter() - started) * 1000),
        cost_usd=cost_usd(llm.model_name, usage),
    )
    return insert(board, result.output.scenes[: len(lengths)], lengths), call
