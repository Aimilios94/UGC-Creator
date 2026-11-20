"""Text and vision LLM behind Pydantic AI: openai | anthropic | mock.

The mock provider is a Pydantic AI FunctionModel that returns deterministic, schema-valid
outputs built from the brief in the prompt, so the whole flow runs offline in tests and CI.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ...config import Settings
from ...errors import ProviderNotConfigured

BRIEF_RE = re.compile(r"<brief>(.*?)</brief>", re.S)
STORY_RE = re.compile(r"<story>(.*?)</story>", re.S)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"”])\s+")  # a sentence may end inside quotes


@dataclass
class LlmHandle:
    model: Model
    provider: str  # openai | anthropic | mock
    model_name: str  # priced via llm_trace.PRICES
    settings: dict


def _texts(messages):
    for m in messages:
        for part in getattr(m, "parts", []):
            content = getattr(part, "content", None)
            for t in content if isinstance(content, list) else [content]:
                if isinstance(t, str):
                    yield t


def _brief_from(messages) -> dict:
    """The brief (and the user's story, if any) from the prompt, for the mock outputs."""
    brief: dict = {}
    for t in _texts(messages):
        if not brief and (match := BRIEF_RE.search(t)):
            try:
                brief = json.loads(match.group(1))
            except json.JSONDecodeError:
                brief = {}
        if match := STORY_RE.search(t):
            try:
                brief["story"] = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    return brief


def mock_analysis(brief: dict) -> dict:
    name = brief.get("product_name", "the product")
    return {
        "product_type": f"{name} (mock analysis)",
        "visual_description": f"{name}: product as shown in the uploaded photo, same shape, colours and label.",
        "packaging_text": [name],
        "key_features": ["as described in the brief"],
        "people_in_photo": False,
    }


def _story_parts(story: str) -> list[str] | None:
    """The story in three parts, in order (mock only): by its timestamped beats if it has them, else by sentences."""
    text = story.strip()
    if not text:
        return None
    beats = [b.strip() for b in re.split(r"\n\s*\n|(?=\b\d{1,2}:\d{2}\s*[-\u2013]\s*\d{1,2}:\d{2})", text) if b.strip()]
    timed = re.compile(r"^\d{1,2}:\d{2}")
    if len(beats) > 1 and not timed.match(beats[0]) and timed.match(beats[1]):
        beats = [beats[0] + " " + beats[1], *beats[2:]]  # a heading before the first timestamp joins it
    if len(beats) < 3:
        beats = [x.strip() for x in SENTENCE_END.split(text) if x.strip()]
    if timed.match(beats[0]) or any(timed.match(b) for b in beats[1:]):
        n = min(len(beats), 5)  # a timed story: one scene per beat (1-5), as the real writer is told
    else:
        n = 3
        if len(beats) < 3:
            beats = (beats * 3)[:3]
    return [" ".join(beats[i * len(beats) // n : (i + 1) * len(beats) // n]) for i in range(n)]


def _seconds(part: str) -> int | None:
    """A story part's length from its timestamps, for example "0:02 - 0:06" -> 4 (mock only)."""
    stamps = [int(m) * 60 + int(sec) for m, sec in re.findall(r"(\d{1,2}):(\d{2})", part)]
    if len(stamps) < 2:
        return None
    return max(2, min(10, max(stamps) - min(stamps)))


def _spoken(part: str) -> str:
    """Quoted text in a story part is its spoken line (mock only)."""
    quotes = re.findall(r"[\"\u201c]([^\"\u201d]{3,200})[\"\u201d]", part)
    return " ".join(quotes)[:220]


def mock_storyboard(brief: dict) -> dict:
    """A detailed, schema-valid storyboard built from the brief, as the real model is asked to write."""
    name = brief.get("product_name", "the product")
    offer = brief.get("offer") or ""
    keep = f"Keep {name} exactly as in the reference photo: same shape, colours, logo and packaging text."
    parts = _story_parts(brief.get("story") or "")
    lines = [
        f"Stop scrolling: this is {name}.",
        "Here is how it works, in one step.",
        f"Get yours today. {offer}".strip(),
    ]
    scenes = [
        {
            "role": "hook",
            "description": f"Close-up of {name} on a bright kitchen counter, filmed like a phone video.",
            "image_prompt": (
                f"A close-up of {name} standing upright on a light oak kitchen counter, slightly left of centre, "
                "with a ceramic mug and a folded linen towel softly out of focus behind it. Morning in a small "
                "city apartment. Medium close-up from chest height, a 26 mm phone lens, slight downward angle, "
                "the product filling about a third of the frame. Soft window light from the left, warm 4,500 K, "
                "gentle shadows to the right. Palette of cream, oak and soft green; calm, fresh mood. " + keep
            ),
            "motion_prompt": (
                "0-1 s: the phone camera holds on the product with a slight natural handheld sway, sunlight "
                "flickering softly through the window. 1-3 s: a slow push-in toward the product, about 20 percent "
                "closer, focus staying on the logo while the mug behind blurs further. 3-5 s: the camera eases "
                "to a stop, a hand enters from the right and rests next to the product; final frame is a tight, "
                "well-lit close-up of the product, ready to cut to the demo."
            ),
            "on_screen_text": f"Meet {name}"[:80],
        },
        {
            "role": "demo",
            "description": f"Hands showing {name} in use at home.",
            "image_prompt": (
                f"Two hands holding {name} at chest height in a cosy living room, the product turned three "
                "quarters toward the camera. A sofa with a knitted throw and a plant in the soft background. "
                "Medium shot, eye level, 26 mm phone lens, product centred. Soft daylight from a large window "
                "behind the camera, slight warm fill from a lamp. Palette of warm neutrals with one green accent; "
                "relaxed, practical mood. " + keep
            ),
            "motion_prompt": (
                "0-1 s: static handheld framing on the hands and product. 1-3 s: the hands slowly turn the "
                "product to show its front, then its side, while the camera follows with a gentle pan of a few "
                "degrees. 3-4 s: a short tilt down as the hands demonstrate the main feature, focus following "
                "the product. 4-5 s: the hands bring the product back to face the camera and pause; final frame "
                "shows the front of the product clearly, centred."
            ),
            "on_screen_text": "How it works",
        },
        {
            "role": "cta",
            "description": f"{name} centred on a clean background with space for the call to action.",
            "image_prompt": (
                f"{name} centred on a clean, softly lit seamless background in a pale warm grey, a subtle shadow "
                "under the product. Product shot, straight on at product height, 50 mm lens look, the product "
                "filling half the frame with empty space above and below for text added later. Large soft key "
                "light from the upper left, a faint rim light from behind. Palette of warm grey and the "
                "product's own colours; confident, premium mood. " + keep
            ),
            "motion_prompt": (
                "0-2 s: a slow, smooth orbit of about 15 degrees around the product from left to right, the "
                "product staying centred and sharp. 2-4 s: the camera settles and makes a gentle push-in, the "
                "rim light adding a soft glint on the product's edge. 4-5 s: hold still on a clean, centred "
                "frame with empty space above the product for the call to action."
            ),
            "on_screen_text": offer[:80],
        },
    ]
    hooks = [
        {"formula": "pov", "text": f"POV: you finally found {name}"},
        {"formula": "problem_first", "text": f"Tired of the old way? Try {name}"},
        {"formula": "three_reasons", "text": f"3 reasons people pick {name}"},
    ]
    if parts:
        # The user's story leads: one scene per part, its spoken lines kept, the hooks open it.
        template = scenes
        scenes = [dict(template[0 if i == 0 else (2 if i == len(parts) - 1 else 1)]) for i in range(len(parts))]
        for scene, part in zip(scenes, parts, strict=True):
            # Like the real writer: a short summary, a still first frame, and the timed movement.
            plain = re.sub(r"^.*?\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\s*(\([^)]*\))?:?\s*", "", part).strip() or part
            first = SENTENCE_END.split(plain)[0]
            scene["description"] = (first if len(first) <= 160 else first[:157].rstrip() + "...")[:800]
            scene["image_prompt"] = (f"Still first frame of this scene, before anything moves: {first} {keep}")[:2500]
            scene["motion_prompt"] = part[:2200]
            scene["voiceover"] = _spoken(part)
            scene["duration_s"] = _seconds(part) or 5
        opening = re.sub(r"^.*?\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\s*(\([^)]*\))?:?\s*", "", parts[0].strip())
        opening = SENTENCE_END.split(opening)[0][:120]
        hooks = [
            {"formula": "pov", "text": f"POV: {opening}"[:160]},
            {"formula": "problem_first", "text": f"Before {name}: {opening}"[:160]},
            {"formula": "three_reasons", "text": f"3 reasons this moment needs {name}"[:160]},
        ]
    else:
        for scene, line in zip(scenes, lines, strict=True):
            scene["voiceover"] = line
    return {"title": f"{name}: quick UGC ad", "scenes": scenes, "hooks": hooks, "cta_text": "Shop now"}


MOCK_TASKS: dict[str, Callable[[dict], dict]] = {"analyze": mock_analysis, "storyboard": mock_storyboard}


def _mock_model(task: str) -> FunctionModel:
    builder = MOCK_TASKS[task]

    def respond(messages, info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=builder(_brief_from(messages)))])

    return FunctionModel(respond, model_name=f"mock-{task}")


def build_llm(settings: Settings, task: str) -> LlmHandle:
    provider = settings.llm_provider
    if provider == "mock":
        return LlmHandle(model=_mock_model(task), provider="mock", model_name="mock", settings={})
    if provider == "openai":
        if not settings.openai_api_key:
            raise ProviderNotConfigured("OPENAI_API_KEY is not set")
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        model = OpenAIChatModel(settings.llm_model, provider=OpenAIProvider(api_key=settings.openai_api_key))
        model_settings: dict[str, Any] = {"max_tokens": settings.llm_max_output_tokens}
        if settings.llm_model.startswith(("gpt-5", "o")):
            model_settings["openai_reasoning_effort"] = "low"
        return LlmHandle(model=model, provider="openai", model_name=settings.llm_model, settings=model_settings)
    if provider == "anthropic":
        if not (settings.anthropic_api_key and settings.anthropic_model):
            raise ProviderNotConfigured("ANTHROPIC_API_KEY and ANTHROPIC_MODEL are required (M4)")
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        model = AnthropicModel(settings.anthropic_model, provider=AnthropicProvider(api_key=settings.anthropic_api_key))
        return LlmHandle(
            model=model,
            provider="anthropic",
            model_name=settings.anthropic_model,
            settings={"max_tokens": settings.llm_max_output_tokens},
        )
    raise ProviderNotConfigured(f"unknown LLM_PROVIDER {provider!r}")
