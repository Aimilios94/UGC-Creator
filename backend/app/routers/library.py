"""Voices and music to choose from, each with a short preview (public files, no session needed)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services.music import MUSIC_DIR, manifest
from ..services.voice import VOICE_LABELS, VOICES

router = APIRouter(tags=["library"])
VOICE_DIR = Path(__file__).resolve().parents[1] / "voices"


@router.get("/voices")
def list_voices() -> list[dict]:
    out = []
    for v in VOICES:
        sample = VOICE_DIR / f"{v}.m4a"
        out.append({"id": v, "label": VOICE_LABELS[v], "sample": f"/voices/{v}.m4a" if sample.exists() else None})
    return out


@router.get("/voices/{voice}.m4a")
def voice_sample(voice: str) -> FileResponse:
    if voice not in VOICES or not (VOICE_DIR / f"{voice}.m4a").exists():
        raise HTTPException(status_code=404)
    return FileResponse(
        VOICE_DIR / f"{voice}.m4a", media_type="audio/mp4", headers={"Cache-Control": "public, max-age=86400"}
    )


@router.get("/music")
def list_music() -> list[dict]:
    return [
        {"id": theme, "title": e["title"], "artist": e["artist"], "licence": "CC0 1.0", "sample": f"/music/{theme}.m4a"}
        for theme, e in manifest().items()
    ]


@router.get("/music/{theme}.m4a")
def music_sample(theme: str) -> FileResponse:
    beds = manifest()
    if theme not in beds:
        raise HTTPException(status_code=404)
    return FileResponse(
        MUSIC_DIR / beds[theme]["file"], media_type="audio/mp4", headers={"Cache-Control": "public, max-age=86400"}
    )
