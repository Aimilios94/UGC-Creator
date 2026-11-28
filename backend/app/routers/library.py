"""Voices and music to choose from, each with a short preview (public files, no session needed)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services.music import MUSIC_DIR, manifest
from ..services.themes import load_themes
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


@router.get("/themes")
def list_themes() -> list[dict]:
    """The themes for the create page: what each one sets by default (the brand kit still wins)."""
    beds = manifest()
    return [
        {
            "id": t.id,
            "title": t.title,
            "summary": t.summary,
            "tone": t.tone,
            "captions": t.captions,
            "font": t.font,
            "palette": t.palette.model_dump(),
            "music": t.music,
            "music_title": beds.get(t.music, {}).get("title", ""),
            "packs": [p.title for p in t.packs.values()],
        }
        for t in load_themes().values()
    ]


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
