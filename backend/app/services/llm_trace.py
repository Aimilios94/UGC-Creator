"""Price table and cost tracing for every provider call (adapted from Receipt-Ghostbuster).

Estimates (before a paid stage) and recorded costs (after it) use this one table,
so the only estimate error is vendor price drift. Providers bill in USD; costs are
stored in USD as billed and converted to EUR at one app-wide fixed rate.

Billing units handled: per image, per megapixel, per second (video or audio), per
video, per token (input / cached input / output), per character, per generic unit.
Modifiers: a fixed base fee per call, an audio-on multiplier, and per-resolution
multipliers. A model that is not in the table raises `UnknownPrice`: a paid call
is never estimated at 0, which would let it slip past the cost cap.

DB-free: this module computes; repository.py persists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

Unit = Literal["image", "megapixel", "second", "video", "token", "character", "unit"]

# fal's pricing API returns plural unit names.
_UNIT_ALIASES = {
    "images": "image",
    "megapixels": "megapixel",
    "seconds": "second",
    "videos": "video",
    "tokens": "token",
    "characters": "character",
    "units": "unit",
}


def normalise_unit(unit: str) -> Unit:
    u = unit.strip().lower()
    u = _UNIT_ALIASES.get(u, u)
    if u not in ("image", "megapixel", "second", "video", "token", "character", "unit"):
        raise ValueError(f"unknown billing unit: {unit!r}")
    return u  # type: ignore[return-value]


class UnknownPrice(LookupError):
    """No price for this model: refuse to estimate rather than guess 0."""


@dataclass(frozen=True)
class Price:
    unit: Unit
    usd: float = 0.0  # per unit; for "character" it is per 1M characters
    input_per_m: float = 0.0  # token unit: USD per 1M input tokens
    cached_input_per_m: float | None = None  # None = cached tokens priced as input
    output_per_m: float = 0.0  # token unit: USD per 1M output tokens
    base_usd: float = 0.0  # fixed fee per call, on top of the unit cost
    audio_on_multiplier: float = 1.0  # applied when Usage.audio is True
    resolution_multipliers: tuple[tuple[str, float], ...] = ()
    source: str = ""
    checked: str = ""


@dataclass(frozen=True)
class Usage:
    images: float = 0
    megapixels: float = 0
    seconds: float = 0
    videos: float = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    units: float = 0
    audio: bool = False
    resolution: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (0, None, False)}


# Prices checked on 2026-11-18: fal via its pricing API (GET api.fal.ai/v1/models/pricing),
# OpenAI on developers.openai.com/api/docs/pricing (standard tier, contexts under 272K).
# Prefix-matched, longest prefix first, so a dated snapshot resolves to its family.
PRICES: dict[str, Price] = {
    "fal-ai/nano-banana/edit": Price(unit="image", usd=0.0398, source="fal pricing API", checked="2026-11-18"),
    # Text to image, for an ad with no product photo (strategy plan A6).
    "fal-ai/nano-banana": Price(unit="image", usd=0.0398, source="fal pricing API", checked="2026-11-27"),
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": Price(
        unit="second", usd=0.07, source="fal pricing API", checked="2026-11-18"
    ),
    "gpt-5-mini": Price(
        unit="token",
        input_per_m=0.25,
        cached_input_per_m=0.025,
        output_per_m=2.00,
        source="OpenAI pricing page",
        checked="2026-11-18",
    ),
    "gpt-5-nano": Price(
        unit="token",
        input_per_m=0.05,
        cached_input_per_m=0.005,
        output_per_m=0.40,
        source="OpenAI pricing page",
        checked="2026-11-18",
    ),
    "gpt-4o-mini-tts": Price(
        unit="token", input_per_m=0.60, output_per_m=12.00, source="OpenAI pricing page", checked="2026-11-18"
    ),
    "tts-1": Price(unit="character", usd=15.00, source="OpenAI pricing page", checked="2026-11-18"),
    # Mock providers cost nothing for LLM calls. Mock media is priced as the real model it
    # stands in for (see providers/media.py), so the budget logic is exercised in tests.
    "mock": Price(unit="token", source="mock provider", checked="2026-11-18"),
}


def price_for(model: str) -> Price:
    key = (model or "").lower()
    for prefix in sorted(PRICES, key=len, reverse=True):
        if key.startswith(prefix):
            return PRICES[prefix]
    raise UnknownPrice(f"no price for model {model!r}; add it to llm_trace.PRICES before using it")


def cost_usd(model: str, usage: Usage, price: Price | None = None) -> float:
    """USD cost of one call under the price table (estimate and record use the same formula)."""
    p = price or price_for(model)
    if p.unit == "token":
        cached = min(usage.cached_input_tokens, usage.input_tokens)
        cached_rate = p.input_per_m if p.cached_input_per_m is None else p.cached_input_per_m
        variable = (
            (usage.input_tokens - cached) / 1_000_000 * p.input_per_m
            + cached / 1_000_000 * cached_rate
            + usage.output_tokens / 1_000_000 * p.output_per_m
        )
    elif p.unit == "character":
        variable = usage.characters / 1_000_000 * p.usd
    else:
        quantity = {
            "image": usage.images,
            "megapixel": usage.megapixels,
            "second": usage.seconds,
            "video": usage.videos,
            "unit": usage.units,
        }[p.unit]
        variable = quantity * p.usd
    if usage.resolution is not None and p.resolution_multipliers:
        mult = dict(p.resolution_multipliers)
        if usage.resolution not in mult:
            raise UnknownPrice(f"no price for resolution {usage.resolution!r} of {model!r}")
        variable *= mult[usage.resolution]
    if usage.audio:
        variable *= p.audio_on_multiplier
    return round(p.base_usd + variable, 6)


def usd_to_eur(usd: float, rate: float) -> float:
    return round(usd * rate, 4)


def eur_to_usd(eur: float, rate: float) -> float:
    return eur / rate


def money(usd: float, rate: float) -> dict[str, float]:
    """Both currencies, so the UI can switch display without another request."""
    return {"usd": round(usd, 4), "eur": usd_to_eur(usd, rate)}


def tokens_from_run_usage(run_usage: Any) -> Usage:
    """Usage from a Pydantic AI RunUsage (input, cache-read and output tokens)."""
    return Usage(
        input_tokens=int(getattr(run_usage, "input_tokens", 0) or 0),
        cached_input_tokens=int(getattr(run_usage, "cache_read_tokens", 0) or 0),
        output_tokens=int(getattr(run_usage, "output_tokens", 0) or 0),
    )


@dataclass
class LlmCall:
    """One provider round-trip, ready to persist in llm_calls."""

    kind: Literal["llm", "image", "video", "tts"]
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    cost_usd: float = 0.0
    cache_hit: bool = False
    error: str | None = None

    @classmethod
    def timed(cls, *, kind, provider: str, model: str, started: float, usage: Usage, price_model: str | None = None):
        return cls(
            kind=kind,
            provider=provider,
            model=model,
            usage=usage,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=cost_usd(price_model or model, usage),
        )
