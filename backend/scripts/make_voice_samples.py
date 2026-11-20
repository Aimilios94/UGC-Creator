"""Make the short voice previews shown on the Storyboard step (paid, about 0.01 EUR in total; run by hand).

    python scripts/make_voice_samples.py

One line per voice with the real voice model (OPENAI_API_KEY from backend/.env, never printed),
saved as app/voices/<voice>.m4a. Prints the cost from the price table.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.services.llm_trace import cost_usd, usd_to_eur  # noqa: E402
from app.services.providers.voice import OpenAIVoice  # noqa: E402
from app.services.voice import VOICES, plan_voice, usage_for  # noqa: E402

LINE = "Hi! This is how your ad could sound: clear, natural and ready to post."
OUT = Path(__file__).resolve().parents[1] / "app" / "voices"


def main() -> int:
    s = Settings()
    if not s.openai_api_key:
        print("OPENAI_API_KEY is not set in backend/.env")
        return 2
    provider = OpenAIVoice(s.openai_api_key)
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for voice in VOICES:
        planned = plan_voice(model=s.tts_model, text=LINE, voice=voice, tone=None)
        clip = provider.synthesize(planned.request)
        cost = cost_usd(s.tts_model, usage_for(planned.request, clip.duration_s))
        total += cost
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "v.wav"
            wav.write_bytes(clip.wav)
            subprocess.run(  # noqa: S603 - argument list, no shell
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-map_metadata", "-1",  # noqa: S607
                 "-af", "loudnorm=I=-16:TP=-1.5", "-c:a", "aac", "-b:a", "96k", str(OUT / f"{voice}.m4a")],
                check=True,
            )  # fmt: skip
        print(f"{voice:6s} {clip.duration_s:4.1f} s  ~{cost:.4f} USD")
    print(f"total ~{total:.4f} USD = ~{usd_to_eur(total, s.usd_to_eur_rate):.4f} EUR (estimated tokens, D26)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
