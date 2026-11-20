"""Stage orchestration with status and cost per stage, and the cost cap and daily limit
checked before every paid stage.

Before approval (run by the API): analyze -> storyboard. Nothing renders yet.
After approval (run by the worker): per scene, reference image -> image-to-video.

Rules this module enforces (each pinned by a guardrail test):
- Before each paid stage, spend so far plus the stage estimate must fit under the job's
  cap and the app's daily limit, or the stage does not start (`BudgetExceeded`).
- A finished stage is never run again; a submitted render is polled, not resubmitted.
- A render already in the media cache is copied, not paid for again.
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import repository as repo
from ..config import Settings
from ..errors import BudgetExceeded
from ..models import BrandKit, Brief, ProductAnalysis, Scene, Storyboard
from ..repository import Database
from . import analyze, storyboard
from .image_gen import PlannedRender, plan_scene_image
from .llm_trace import Usage, cost_usd, usd_to_eur
from .providers.llm import LlmHandle, build_llm
from .providers.media import InputImage, MediaFailed, MediaProvider, wait_for
from .providers.storage import Storage
from .storyboard_checks import fix_instructions, flag_testimonials
from .video_gen import plan_scene_video

log = logging.getLogger(__name__)

LLM_EST_INPUT_TOKENS = 4000  # a product photo plus the prompt, rounded up
EXT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "mp4": "video/mp4"}
TYPE_EXTS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "video/mp4": "mp4"}


@dataclass
class Context:
    settings: Settings
    db: Database
    storage: Storage
    media: MediaProvider
    llm_factory: Callable[[str], LlmHandle] = field(default=None)  # type: ignore[assignment]
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self):
        if self.llm_factory is None:
            self.llm_factory = lambda task: build_llm(self.settings, task)


def _labels(s: Settings) -> dict[str, str]:
    return {
        "cap_label": f" ({s.job_cost_cap_eur:.2f} EUR)",
        "limit_label": f" ({s.daily_spend_limit_eur:.2f} EUR)",
    }


def _reserve(
    ctx: Context, *, job_id: str, stage_run_id: str, kind: str, provider: str, model: str, est_usd: float
) -> str:
    s = ctx.settings
    return repo.reserve_spend(
        ctx.db,
        job_id=job_id,
        stage_run_id=stage_run_id,
        kind=kind,
        provider=provider,
        model=model,
        est_usd=est_usd,
        job_cap_usd=s.job_cost_cap_usd,
        daily_limit_usd=s.daily_spend_limit_usd,
        **_labels(s),
    )


def content_type_for(key: str) -> str:
    return EXT_TYPES.get(key.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def job_seed(job_id: str) -> int:
    return int(hashlib.sha256(str(job_id).encode()).hexdigest()[:8], 16) % 2**31


# --- before approval (API) ------------------------------------------------------------
def _run_llm_stage(ctx: Context, job_id: str, stage: str, llm: LlmHandle, call, *, attempt: int = 1):
    sr = repo.start_stage(ctx.db, job_id, stage, -1, provider=llm.provider, model=llm.model_name, attempt=attempt)
    est = cost_usd(
        llm.model_name, Usage(input_tokens=LLM_EST_INPUT_TOKENS, output_tokens=ctx.settings.llm_max_output_tokens)
    )
    try:
        res_id = _reserve(
            ctx,
            job_id=job_id,
            stage_run_id=sr["id"],
            kind="llm",
            provider=llm.provider,
            model=llm.model_name,
            est_usd=est,
        )
    except BudgetExceeded as e:
        repo.stage_failed(ctx.db, sr["id"], e.message)
        raise
    started = time.perf_counter()
    try:
        output, record = call()
    except Exception as e:
        # Tokens may have been spent (for example on validation retries): count the estimate.
        repo.bill(
            ctx.db,
            res_id,
            cost_usd=est,
            usage={"estimated": True},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        repo.stage_failed(ctx.db, sr["id"], f"{type(e).__name__}: {e}")
        raise
    repo.bill(ctx.db, res_id, cost_usd=record.cost_usd, usage=record.usage.as_dict(), latency_ms=record.latency_ms)
    repo.stage_done(ctx.db, sr["id"], {"model": llm.model_name, "latency_ms": record.latency_ms})
    return output


def prepare_storyboard(ctx: Context, job: dict, photo: bytes, content_type: str) -> tuple[ProductAnalysis, Storyboard]:
    """Analyze the photo and write the storyboard. Cheap LLM calls only; nothing renders.

    Testimonial rule: if the code check flags lines, the storyboard is written once more
    with those lines as feedback. Lines still flagged after that are left for the user to
    edit on the Storyboard step (Approve is refused while any remain).
    """
    job_id = str(job["id"])
    brief = Brief.model_validate(job["brief"])
    brand = BrandKit.model_validate(job["brand"]) if job.get("brand") else None
    llm = ctx.llm_factory("analyze")
    analysis = _run_llm_stage(
        ctx, job_id, "analyze", llm, lambda: analyze.analyze_product(llm, brief, photo, content_type)
    )
    repo.set_analysis(ctx.db, job_id, analysis.model_dump(mode="json"))
    llm2 = ctx.llm_factory("storyboard")
    board = _run_llm_stage(
        ctx, job_id, "storyboard", llm2, lambda: storyboard.write_storyboard(llm2, brief, analysis, brand=brand)
    )
    flags = flag_testimonials(board, brief)
    if flags:
        log.info("storyboard for job %s broke the testimonial rule (%d lines); rewriting once", job_id, len(flags))
        feedback = fix_instructions(flags)
        try:
            board = _run_llm_stage(
                ctx,
                job_id,
                "storyboard",
                llm2,
                lambda: storyboard.write_storyboard(llm2, brief, analysis, brand=brand, feedback=feedback),
                attempt=2,
            )
        except Exception:  # noqa: BLE001 - keep the first storyboard; its flagged lines go to the user
            log.exception("storyboard rewrite failed for job %s; keeping the first version", job_id)
            sr = repo.get_stage_run(ctx.db, job_id, "storyboard")
            if sr:
                repo.stage_done(ctx.db, sr["id"], {"model": llm2.model_name, "rewrite_failed": True})
    repo.set_storyboard(ctx.db, job_id, board.model_dump(mode="json"))
    return analysis, board


# --- after approval (worker) ----------------------------------------------------------
def _image_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return im.width, im.height
    except Exception:  # noqa: BLE001 - size is informational
        return None, None


def _store_output(ctx: Context, job_id: str, stage: str, idx: int, data: bytes, content_type: str) -> dict:
    ext = TYPE_EXTS.get(content_type, "bin")
    key = f"jobs/{job_id}/scene-{idx}/{stage}.{ext}"
    ctx.storage.put(key, data, content_type)
    w, h = _image_size(data) if stage == "image" else (None, None)
    return repo.add_asset(
        ctx.db,
        job_id=job_id,
        kind=stage,
        storage_key=key,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        width=w,
        height=h,
    )


def run_media_stage(ctx: Context, job: dict, stage: str, idx: int, plan: Callable[[], PlannedRender]) -> dict:
    """Run one paid render, resuming from stage_runs. Returns the asset row."""
    job_id = str(job["id"])
    sr = repo.get_stage_run(ctx.db, job_id, stage, idx)
    if sr and sr["status"] == "done":
        return repo.get_asset(ctx.db, sr["output"]["asset_id"])

    planned = plan()
    req = planned.request
    est = cost_usd(req.model, planned.usage)

    if sr and sr["status"] == "submitted" and sr["prediction_id"]:
        prediction_id = sr["prediction_id"]  # resume: poll the render already paid for
        res_id = repo.open_reservation(ctx.db, sr["id"])
    else:
        sr = repo.start_stage(
            ctx.db, job_id, stage, idx, provider=ctx.media.name, model=req.model, attempt=int(job.get("attempts") or 1)
        )
        hit = repo.cache_get(ctx.db, planned.cache_key)
        if hit is not None:
            try:
                data = ctx.storage.get(hit["storage_key"])
            except Exception:  # noqa: BLE001 - cached file gone: render again
                data = None
            if data is not None:
                asset = _store_output(ctx, job_id, stage, idx, data, hit["content_type"])
                repo.record_cache_hit(
                    ctx.db, job_id=job_id, stage_run_id=sr["id"], kind=stage, provider=ctx.media.name, model=req.model
                )
                repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "cache_hit": True})
                return asset
        try:
            res_id = _reserve(
                ctx,
                job_id=job_id,
                stage_run_id=sr["id"],
                kind=stage,
                provider=ctx.media.name,
                model=req.model,
                est_usd=est,
            )
        except BudgetExceeded as e:
            repo.stage_failed(ctx.db, sr["id"], e.message)
            raise
        try:
            prediction_id = ctx.media.submit(req)
        except Exception as e:
            repo.release(ctx.db, res_id, f"submit failed: {type(e).__name__}")
            repo.stage_failed(ctx.db, sr["id"], f"{type(e).__name__}: {e}")
            raise
        repo.mark_submitted(ctx.db, sr["id"], prediction_id)

    started = time.perf_counter()
    try:
        wait_for(
            ctx.media,
            req.model,
            prediction_id,
            timeout_s=ctx.settings.media_timeout_s,
            interval_s=ctx.settings.media_poll_interval_s,
            sleep=ctx.sleep,
        )
        result = ctx.media.result(req.model, prediction_id, req.kind)
        data = ctx.media.download(result)
    except MediaFailed as e:
        # The provider finished with an error. Count the estimate (billing is not confirmed)
        # so the cap stays safe; a later attempt starts a fresh render.
        if res_id:
            repo.bill(
                ctx.db,
                res_id,
                cost_usd=est,
                usage={"estimated": True, **planned.usage.as_dict()},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        repo.stage_failed(ctx.db, sr["id"], str(e))
        raise
    # Any other error leaves the stage 'submitted', so the next attempt polls the same render.

    asset = _store_output(ctx, job_id, stage, idx, data, result.content_type)
    actual = cost_usd(req.model, planned.usage)
    if res_id:
        repo.bill(
            ctx.db,
            res_id,
            cost_usd=actual,
            usage=planned.usage.as_dict(),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    repo.cache_put(
        ctx.db,
        cache_key=planned.cache_key,
        kind=stage,
        model=req.model,
        storage_key=asset["storage_key"],
        content_type=asset["content_type"],
        cost_usd=actual,
        meta={"prediction_id": prediction_id},
    )
    repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "prediction_id": prediction_id})
    return asset


def run_job(ctx: Context, job: dict) -> None:
    """Render the approved scenes. Safe to call again after a crash: it resumes."""
    s = ctx.settings
    job_id = str(job["id"])
    brief = Brief.model_validate(job["brief"])
    photo = ctx.storage.get(job["upload_key"])
    product = InputImage(
        data=photo,
        content_type=content_type_for(job["upload_key"]),
        url=ctx.storage.provider_url(job["upload_key"], 3600),
    )
    seed = job_seed(job_id)
    for row in repo.list_scenes(ctx.db, job_id)[: s.render_scenes]:
        idx = row["idx"]
        scene = Scene.model_validate(row["data"])

        def plan_image(scene=scene):
            return plan_scene_image(
                model=s.image_model,
                scene=scene,
                aspect_ratio=brief.aspect_ratio,
                seed=seed,
                product=product,
                product_sha256=job["upload_sha256"],
            )

        image = run_media_stage(ctx, job, "image", idx, plan_image)
        repo.set_scene_asset(ctx.db, job_id, idx, "image", str(image["id"]))

        def plan_video(image=image, scene=scene):
            ref = InputImage(
                data=ctx.storage.get(image["storage_key"]),
                content_type=image["content_type"],
                url=ctx.storage.provider_url(image["storage_key"], 3600),
            )
            return plan_scene_video(
                model=s.video_model,
                scene=scene,
                duration_s=s.video_duration_s,
                reference=ref,
                reference_sha256=image["sha256"],
            )

        video = run_media_stage(ctx, job, "video", idx, plan_video)
        repo.set_scene_asset(ctx.db, job_id, idx, "video", str(video["id"]))
    repo.finish_job(ctx.db, job_id)


def estimate_job_usd(s: Settings) -> float:
    """Full estimate for one approved job under the current settings (shown before approval)."""
    per_scene = cost_usd(s.image_model, Usage(images=1)) + cost_usd(s.video_model, Usage(seconds=s.video_duration_s))
    return round(per_scene * s.render_scenes, 6)


def estimate_job_eur(s: Settings) -> float:
    return usd_to_eur(estimate_job_usd(s), s.usd_to_eur_rate)
