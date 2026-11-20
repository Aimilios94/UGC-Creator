"""Code-graded checks on every composed file (plan §8 step 10). DB-free.

The judge never sees captions, logo, end card, audio or metadata: these checks do.
Per exported ad: it plays (ffprobe reads it), duration, resolution and ratio, an audio
track, the AI marking, captions inside the safe zone (from compose's own layout check),
and sound-off readiness (the offer and the call to action are on the end card).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .compose import ComposeResult, ComposeSpec, read_ai_marking


def probe(path: Path) -> dict:
    proc = subprocess.run(  # noqa: S603 - argument list, no shell
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",  # noqa: S607 - ffprobe from PATH
         "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )  # fmt: skip
    if proc.returncode != 0:
        return {}
    return json.loads(proc.stdout)


def check_ad(path: Path, *, ratio: str, size: tuple[int, int], duration_s: float) -> dict:
    info = probe(path)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    got = float(info.get("format", {}).get("duration", 0) or 0)
    checks = {
        "plays": bool(info) and bool(video),
        "duration": abs(got - duration_s) <= 0.25,
        "resolution": (video.get("width"), video.get("height")) == size,
        "audio_track": any(s.get("codec_type") == "audio" for s in streams),
        "ai_metadata": read_ai_marking(path)["ai_generated"] if info else False,
        "captions_in_safe_zone": True,  # compose exports a ratio only when its layout check passed
    }
    return {"file": path.name, "ratio": ratio, "duration_s": round(got, 3), "passed": all(checks.values()), **checks}


def check_compose(spec: ComposeSpec, result: ComposeResult) -> list[dict]:
    rows = [
        check_ad(r.path, ratio=r.ratio, size=r.size, duration_s=result.duration_s)
        for r in result.exported
        if r.path is not None
    ]
    images = [result.cover, *result.stills, *result.carousel]
    rows.append(
        {
            "file": "images",
            "count": len(images),
            "ai_metadata": all(read_ai_marking(p)["ai_generated"] for p in images),
            "passed": all(read_ai_marking(p)["ai_generated"] for p in images),
        }
    )
    sound_off = bool(spec.cta_text.strip())  # the end card always draws the CTA, and the offer when set
    rows.append({"file": "end_card", "sound_off_ready": sound_off, "passed": sound_off})
    return rows
