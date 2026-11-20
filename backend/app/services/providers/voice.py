"""Voiceover (text to speech) behind one interface: openai (real) or mock (tests, CI, local dev).

OpenAI's speech endpoint returns only audio, no token counts, so the cost is computed
from the price table with conservatively estimated tokens (see services/voice.py).
`gpt-4o-mini-tts` shuts down on 6 Jan 2027 (OpenAI deprecation notice, read 20 Nov 2026):
a replacement provider is chosen and plugged in here before then (D26).

Audio is requested as raw PCM (24 kHz, 16-bit, mono) and wrapped in a WAV header here,
so the duration is exact and needs no decoder.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from dataclasses import dataclass, field
from typing import Protocol

from ...config import Settings
from ...errors import ProviderNotConfigured

PCM_RATE = 24_000  # OpenAI pcm: 24 kHz, 16-bit signed little-endian, mono


@dataclass
class VoiceRequest:
    model: str
    text: str
    voice: str
    instructions: str = ""


@dataclass
class VoiceClip:
    wav: bytes
    duration_s: float


class VoiceProvider(Protocol):
    name: str

    def synthesize(self, req: VoiceRequest) -> VoiceClip: ...


def pcm_to_wav(pcm: bytes, rate: int = PCM_RATE) -> VoiceClip:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return VoiceClip(wav=buf.getvalue(), duration_s=round(len(pcm) / 2 / rate, 3))


class OpenAIVoice:
    name = "openai"

    def __init__(self, api_key: str, timeout_s: float = 60.0):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=timeout_s, max_retries=1)

    def synthesize(self, req: VoiceRequest) -> VoiceClip:
        kwargs = {"model": req.model, "voice": req.voice, "input": req.text, "response_format": "pcm"}
        if req.instructions:
            kwargs["instructions"] = req.instructions
        resp = self._client.audio.speech.create(**kwargs)
        return pcm_to_wav(resp.read())


@dataclass
class MockVoice:
    """A soft tone whose length follows the text (about 0.3 s per word), so timing logic is exercised."""

    name: str = "mock"
    requests: list[VoiceRequest] = field(default_factory=list)

    def synthesize(self, req: VoiceRequest) -> VoiceClip:
        self.requests.append(req)
        words = max(1, len(req.text.split()))
        seconds = 0.3 + 0.3 * words
        n = int(seconds * PCM_RATE)
        pcm = b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * i / PCM_RATE))) for i in range(n))
        return pcm_to_wav(pcm)


def build_voice(settings: Settings) -> VoiceProvider:
    if settings.voice_provider == "mock":
        return MockVoice()
    if settings.voice_provider == "openai":
        if not settings.openai_api_key:
            raise ProviderNotConfigured("OPENAI_API_KEY is not set (needed for the voiceover)")
        return OpenAIVoice(settings.openai_api_key)
    raise ProviderNotConfigured(f"unknown VOICE_PROVIDER {settings.voice_provider!r}")
