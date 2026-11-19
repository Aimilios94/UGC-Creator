"""Health and public configuration. Work with no secret set."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import __version__
from ..config import ASPECT_RATIOS, PLATFORMS, Settings, get_settings
from ..deps import access_ok, get_ctx
from ..models import Money
from ..services.llm_trace import money
from ..services.pipeline import Context, estimate_job_usd

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness plus which integrations are configured (never the secrets)."""
    return {
        "status": "ok",
        "version": __version__,
        "config": {
            "llm_provider": settings.llm_provider,
            "llm_configured": settings.llm_configured,
            "media_provider": settings.media_provider,
            "media_configured": settings.media_configured,
            "storage_provider": settings.storage_provider,
            "database_configured": settings.database_configured,
            "job_runner": settings.job_runner,
            "access_code_required": settings.access_code_required,
        },
    }


@router.get("/health/db")
def health_db(ctx: Context = Depends(get_ctx)) -> dict:
    """One tiny query. Slow on the first call after Neon has scaled to zero."""
    with ctx.db.tx() as c:
        c.execute("select 1")
    return {"status": "ok"}


@router.get("/config")
def public_config(settings: Settings = Depends(get_settings)) -> dict:
    rate = settings.usd_to_eur_rate
    return {
        "currency": settings.display_currency,
        "usd_to_eur_rate": rate,
        "access_code_required": settings.access_code_required,
        "max_upload_mb": settings.max_upload_mb,
        "platforms": list(PLATFORMS),
        "aspect_ratios": list(ASPECT_RATIOS),
        "render_scenes": settings.render_scenes,
        "job_estimate": Money(**money(estimate_job_usd(settings), rate)),
        "job_cost_cap": Money(usd=round(settings.job_cost_cap_usd, 4), eur=settings.job_cost_cap_eur),
        "models": {"llm": settings.llm_model, "image": settings.image_model, "video": settings.video_model},
    }


@router.post("/access/check")
def access_check(body: dict, settings: Settings = Depends(get_settings)) -> dict:
    return {"ok": access_ok(settings, str(body.get("code") or ""))}
