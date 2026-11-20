"""Voiceover planning: the request, its cache key and its cost. DB-free.

OpenAI's speech endpoint returns audio only, so tokens are estimated, on the high side:
- text input: about 1 token per 3 characters of text plus instructions;
- audio output: AUDIO_TOKENS_PER_S tokens per second of speech (OpenAI's realtime docs bill
  assistant audio at about 1 token per 50 ms; 25/s adds a 25% margin).
Before the call the length is estimated from the word count; after it, the real duration
is used. At 12 USD per 1M audio tokens a 4-second line costs about 0.001 USD (D26).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .llm_trace import Usage
from .media_cache import cache_key
from .providers.voice import VoiceRequest

AUDIO_TOKENS_PER_S = 25
WORDS_PER_S = 2.2  # a slow speaker, so the estimate is on the high side

VOICES = ("marin", "cedar", "coral", "onyx")  # built-in gpt-4o-mini-tts voices offered in the app
VOICE_LABELS = {
    "marin": "Marin (OpenAI's recommended voice)",
    "cedar": "Cedar (OpenAI's recommended voice)",
    "coral": "Coral",
    "onyx": "Onyx",
}

TONE_STYLE = {
    "energetic": "upbeat and energetic, quick pace, like an excited creator",
    "calm": "calm, warm and relaxed, unhurried",
    "playful": "playful and light, with a smile in the voice",
    "premium": "confident, polished and smooth, measured pace",
}


def instructions_for(tone: str | None) -> str:
    style = TONE_STYLE.get(tone or "", "natural and friendly")
    return (
        "You are voicing a short user-generated-content style social video ad filmed on a phone. "
        f"Sound like a real person talking to camera, not an announcer. Tone: {style}."
    )


@dataclass
class PlannedVoice:
    request: VoiceRequest
    cache_key: str
    usage: Usage  # estimated, for the reservation


def _input_tokens(req: VoiceRequest) -> int:
    return math.ceil((len(req.text) + len(req.instructions)) / 3)


def estimate_seconds(text: str) -> float:
    return len(text.split()) / WORDS_PER_S + 1.0


def usage_for(req: VoiceRequest, seconds: float) -> Usage:
    return Usage(input_tokens=_input_tokens(req), output_tokens=math.ceil(seconds * AUDIO_TOKENS_PER_S))


def plan_voice(*, model: str, text: str, voice: str, tone: str | None) -> PlannedVoice:
    req = VoiceRequest(model=model, text=text.strip(), voice=voice, instructions=instructions_for(tone))
    key = cache_key(
        model=model,
        prompt=req.text,
        seed=0,
        input_sha256="",
        settings={"voice": voice, "instructions": req.instructions, "format": "pcm"},
    )
    return PlannedVoice(request=req, cache_key=key, usage=usage_for(req, estimate_seconds(req.text)))
