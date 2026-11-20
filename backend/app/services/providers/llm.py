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


def _story_lines(story: str) -> list[str] | None:
    """The story split into three spoken lines, kept word for word (mock only)."""
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", story.strip()) if x.strip()]
    if not sentences:
        return None
    thirds = [sentences[i * len(sentences) // 3 : (i + 1) * len(sentences) // 3] for i in range(3)]
    return [" ".join(t)[:220] if t else sentences[-1][:220] for t in thirds]


def mock_storyboard(brief: dict) -> dict:
    """A detailed, schema-valid storyboard built from the brief, as the real model is asked to write."""
    name = brief.get("product_name", "the product")
    offer = brief.get("offer") or ""
    keep = f"Keep {name} exactly as in the reference photo: same shape, colours, logo and packaging text."
    lines = _story_lines(brief.get("story") or "") or [
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
            "voiceover": lines[0],
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
            "voiceover": lines[1],
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
            "voiceover": lines[2],
            "on_screen_text": offer[:80],
        },
    ]
    return {
        "title": f"{name}: quick UGC ad",
        "scenes": scenes,
        "hooks": [
            {"formula": "pov", "text": f"POV: you finally found {name}"},
            {"formula": "problem_first", "text": f"Tired of the old way? Try {name}"},
            {"formula": "three_reasons", "text": f"3 reasons people pick {name}"},
        ],
        "cta_text": "Shop now",
    }


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
