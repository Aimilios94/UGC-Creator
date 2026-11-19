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


@dataclass
class LlmHandle:
    model: Model
    provider: str  # openai | anthropic | mock
    model_name: str  # priced via llm_trace.PRICES
    settings: dict


def _brief_from(messages) -> dict:
    for m in messages:
        for part in getattr(m, "parts", []):
            content = getattr(part, "content", None)
            texts = content if isinstance(content, list) else [content]
            for t in texts:
                if isinstance(t, str) and (match := BRIEF_RE.search(t)):
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        return {}
    return {}


def mock_analysis(brief: dict) -> dict:
    name = brief.get("product_name", "the product")
    return {
        "product_type": f"{name} (mock analysis)",
        "visual_description": f"{name}: product as shown in the uploaded photo, same shape, colours and label.",
        "packaging_text": [name],
        "key_features": ["as described in the brief"],
        "people_in_photo": False,
    }


def mock_storyboard(brief: dict) -> dict:
    name = brief.get("product_name", "the product")
    offer = brief.get("offer") or ""
    keep = f"Keep {name} exactly as in the reference photo."
    return {
        "title": f"{name}: quick UGC ad",
        "scenes": [
            {
                "role": "hook",
                "description": f"Close-up of {name} on a kitchen counter, phone-camera look.",
                "image_prompt": f"Smartphone photo of {name} on a bright kitchen counter, natural light. {keep}",
                "motion_prompt": "Slow handheld push-in toward the product.",
                "voiceover": f"Stop scrolling: this is {name}.",
                "on_screen_text": f"Meet {name}",
            },
            {
                "role": "demo",
                "description": f"Hands using {name}.",
                "image_prompt": f"Hands holding {name} in a casual home setting, UGC style. {keep}",
                "motion_prompt": "Hands turn the product to show the label.",
                "voiceover": "Here is how it works, in one step.",
                "on_screen_text": "How it works",
            },
            {
                "role": "cta",
                "description": f"{name} centred with space for the call to action.",
                "image_prompt": f"{name} centred on a clean background with empty space above. {keep}",
                "motion_prompt": "Gentle orbit around the product.",
                "voiceover": f"Get yours today. {offer}".strip(),
                "on_screen_text": offer[:80],
            },
        ],
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
