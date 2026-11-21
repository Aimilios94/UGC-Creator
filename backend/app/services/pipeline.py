"""Stage orchestration with status and cost per stage, and the cost cap and daily limit
checked before every paid stage.

Before approval (run by the API): analyze -> storyboard. Nothing renders yet.
After approval (run by the worker): the voiceover lines first (cheap, so a voice problem
stops the job before any video is paid for), then per scene reference image ->
image-to-video, then compose (free: ffmpeg in the worker) builds variant A.

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
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import repository as repo
from ..config import Settings
from ..errors import BudgetExceeded
from ..models import BrandKit, BrandSnapshot, Brief, ProductAnalysis, Scene, Storyboard, render_seconds
from ..repository import Database
from . import analyze, continuity, storyboard
from .compose import Branding, ComposeSpec, SceneInput, compose, fit_into, frame_at, probe_duration
from .image_gen import PlannedRender, plan_scene_image
from .llm_trace import Usage, cost_usd, usd_to_eur
from .music import music_for
from .output_checks import check_compose
from .platform_specs import MIN_CROP_KEEP, frame_size
from .providers.llm import LlmHandle, build_llm
from .providers.media import InputImage, MediaFailed, MediaProvider, wait_for
from .providers.storage import Storage
from .providers.voice import VoiceProvider, build_voice
from .storyboard_checks import fix_instructions, flag_testimonials
from .video_gen import plan_scene_video
from .voice import plan_voice, usage_for

log = logging.getLogger(__name__)

LLM_EST_INPUT_TOKENS = 4000  # a product photo plus the prompt, rounded up
EXT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "wav": "audio/wav",
}
TYPE_EXTS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "video/mp4": "mp4", "audio/wav": "wav"}
DEFAULT_BRANDING = Branding()  # theme palettes and fonts arrive with the theme YAMLs (M2 item 3)


@dataclass
class Context:
    settings: Settings
    db: Database
    storage: Storage
    media: MediaProvider
    llm_factory: Callable[[str], LlmHandle] = field(default=None)  # type: ignore[assignment]
    sleep: Callable[[float], None] = time.sleep
    voice: VoiceProvider | None = None  # the worker sets it; built on first use otherwise

    def __post_init__(self):
        if self.llm_factory is None:
            self.llm_factory = lambda task: build_llm(self.settings, task)

    def voice_provider(self) -> VoiceProvider:
        if self.voice is None:
            self.voice = build_voice(self.settings)
        return self.voice


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


def write_board(
    ctx: Context, job_id: str, brief: Brief, analysis: ProductAnalysis, brand: BrandKit | None, attempt: int = 1
) -> Storyboard:
    """Write (or rewrite, for example from the user's own story) the storyboard and save it.

    Testimonial rule: if the code check flags lines, the storyboard is written once more
    with those lines as feedback. Lines still flagged after that are left for the user to
    edit on the Storyboard step (Approve is refused while any remain).
    """
    llm = ctx.llm_factory("storyboard")
    board = _run_llm_stage(
        ctx,
        job_id,
        "storyboard",
        llm,
        lambda: storyboard.write_storyboard(llm, brief, analysis, brand=brand, end_card_s=ctx.settings.end_card_s),
        attempt=attempt,
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
                llm,
                lambda: storyboard.write_storyboard(
                    llm, brief, analysis, brand=brand, feedback=feedback, end_card_s=ctx.settings.end_card_s
                ),
                attempt=attempt + 1,
            )
        except Exception:  # noqa: BLE001 - keep the first storyboard; its flagged lines go to the user
            log.exception("storyboard rewrite failed for job %s; keeping the first version", job_id)
            sr = repo.get_stage_run(ctx.db, job_id, "storyboard")
            if sr:
                repo.stage_done(ctx.db, sr["id"], {"model": llm.model_name, "rewrite_failed": True})
    board = check_scene_flow(ctx, job_id, board, brief, attempt=attempt)
    repo.set_storyboard(ctx.db, job_id, board.model_dump(mode="json"))
    return board


def check_scene_flow(ctx: Context, job_id: str, board: Storyboard, brief: Brief, attempt: int = 1) -> Storyboard:
    """The continuity check (D30): one cheap LLM call that writes how each scene starts and ends, so
    every cut matches. It fills only the hidden AI instructions; if it fails, the storyboard is kept."""
    llm = ctx.llm_factory("continuity")
    try:
        return _run_llm_stage(
            ctx,
            job_id,
            "continuity",
            llm,
            lambda: continuity.check_continuity(llm, board, brief),
            attempt=attempt,
        )
    except Exception:  # noqa: BLE001 - the ad still works without it; the scenes keep their own prompts
        log.exception("continuity check failed for job %s; keeping the storyboard as written", job_id)
        return board


def prepare_storyboard(ctx: Context, job: dict, photo: bytes, content_type: str) -> tuple[ProductAnalysis, Storyboard]:
    """Analyze the photo and write the storyboard. Cheap LLM calls only; nothing renders."""
    job_id = str(job["id"])
    brief = Brief.model_validate(job["brief"])
    brand = BrandKit.model_validate(job["brand"]) if job.get("brand") else None
    llm = ctx.llm_factory("analyze")
    analysis = _run_llm_stage(
        ctx, job_id, "analyze", llm, lambda: analyze.analyze_product(llm, brief, photo, content_type)
    )
    repo.set_analysis(ctx.db, job_id, analysis.model_dump(mode="json"))
    return analysis, write_board(ctx, job_id, brief, analysis, brand)


def storyboard_from_story(ctx: Context, job: dict, story: str) -> Storyboard:
    """The user's own story leads: the storyboard is written again from it (one cheap LLM call)."""
    job_id = str(job["id"])
    brief = Brief.model_validate({**job["brief"], "story": story})
    repo.set_brief(ctx.db, job_id, brief.model_dump(mode="json"))
    analysis = ProductAnalysis.model_validate(job["analysis"])
    brand = BrandKit.model_validate(job["brand"]) if job.get("brand") else None
    sr = repo.get_stage_run(ctx.db, job_id, "storyboard")
    return write_board(ctx, job_id, brief, analysis, brand, attempt=(sr["attempt"] + 1) if sr else 1)


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
        kind={"voice": "audio"}.get(stage, stage),
        storage_key=key,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        width=w,
        height=h,
    )


def run_media_stage(
    ctx: Context, job: dict, stage: str, idx: int, plan: Callable[[], PlannedRender], meta: dict | None = None
) -> dict:
    """Run one paid render, resuming from stage_runs. Returns the asset row. `meta` is kept with the
    finished stage (for example that a clip ends on the next scene's picture)."""
    meta = meta or {}
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
                repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "cache_hit": True, **meta})
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
        kind={"voice": "audio"}.get(stage, stage),
        model=req.model,
        storage_key=asset["storage_key"],
        content_type=asset["content_type"],
        cost_usd=actual,
        meta={"prediction_id": prediction_id},
    )
    repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "prediction_id": prediction_id, **meta})
    return asset


def run_voice_stage(ctx: Context, job: dict, idx: int, text: str, voice: str, tone: str | None) -> dict | None:
    """One voiceover line (paid, a fraction of a cent), resuming from stage_runs. Returns the WAV asset."""
    if not text.strip():
        return None
    s = ctx.settings
    job_id = str(job["id"])
    sr = repo.get_stage_run(ctx.db, job_id, "voice", idx)
    if sr and sr["status"] == "done":
        return repo.get_asset(ctx.db, sr["output"]["asset_id"])
    provider = ctx.voice_provider()
    planned = plan_voice(model=s.tts_model, text=text, voice=voice, tone=tone)
    sr = repo.start_stage(
        ctx.db, job_id, "voice", idx, provider=provider.name, model=s.tts_model, attempt=int(job.get("attempts") or 1)
    )
    hit = repo.cache_get(ctx.db, planned.cache_key)
    if hit is not None:
        try:
            data = ctx.storage.get(hit["storage_key"])
        except Exception:  # noqa: BLE001 - cached file gone: synthesise again
            data = None
        if data is not None:
            asset = _store_output(ctx, job_id, "voice", idx, data, "audio/wav")
            repo.record_cache_hit(
                ctx.db, job_id=job_id, stage_run_id=sr["id"], kind="tts", provider=provider.name, model=s.tts_model
            )
            repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "cache_hit": True, **(hit["meta"] or {})})
            return asset
    est = cost_usd(s.tts_model, planned.usage)
    try:
        res_id = _reserve(
            ctx,
            job_id=job_id,
            stage_run_id=sr["id"],
            kind="tts",
            provider=provider.name,
            model=s.tts_model,
            est_usd=est,
        )
    except BudgetExceeded as e:
        repo.stage_failed(ctx.db, sr["id"], e.message)
        raise
    started = time.perf_counter()
    try:
        clip = provider.synthesize(planned.request)
    except Exception as e:
        # A failed request is not billed by OpenAI; the estimate is released.
        repo.release(ctx.db, res_id, f"tts failed: {type(e).__name__}")
        repo.stage_failed(ctx.db, sr["id"], f"{type(e).__name__}: {e}")
        raise
    asset = _store_output(ctx, job_id, "voice", idx, clip.wav, "audio/wav")
    usage = usage_for(planned.request, clip.duration_s)
    actual = cost_usd(s.tts_model, usage)
    repo.bill(
        ctx.db,
        res_id,
        cost_usd=actual,
        usage={**usage.as_dict(), "estimated_tokens": True, "seconds": clip.duration_s},
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    meta = {"duration_s": clip.duration_s}
    repo.cache_put(
        ctx.db,
        cache_key=planned.cache_key,
        kind="audio",
        model=s.tts_model,
        storage_key=asset["storage_key"],
        content_type="audio/wav",
        cost_usd=actual,
        meta=meta,
    )
    repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), **meta})
    return asset


def _branding(ctx: Context, job: dict, work: Path) -> Branding:
    if not job.get("brand"):
        return DEFAULT_BRANDING
    kit = BrandSnapshot.model_validate(job["brand"])
    logo = None
    if kit.logo_key:
        try:
            logo = work / ("logo." + kit.logo_key.rsplit(".", 1)[-1])
            logo.write_bytes(ctx.storage.get(kit.logo_key))
        except Exception:  # noqa: BLE001 - a missing logo must not stop the ad
            log.warning("logo %s not found for job %s", kit.logo_key, job["id"])
            logo = None
    d = DEFAULT_BRANDING
    return Branding(
        font=kit.font or d.font,
        primary=kit.colors.primary or d.primary,
        secondary=kit.colors.secondary or d.secondary,
        background=kit.colors.background or d.background,
        logo=logo,
    )


ASSET_KIND = {"ad": "ad", "cover": "cover", "still": "still", "carousel": "carousel"}


def run_compose_stage(ctx: Context, job: dict, brief: Brief, board: Storyboard) -> None:
    """Compose variant A from the stored clips (free: ffmpeg in the worker). Safe to run again."""
    s = ctx.settings
    job_id = str(job["id"])
    sr = repo.get_stage_run(ctx.db, job_id, "compose")
    if sr and sr["status"] == "done":
        return
    sr = repo.start_stage(
        ctx.db, job_id, "compose", -1, provider="ffmpeg", model="compose", attempt=int(job.get("attempts") or 1)
    )
    try:
        with tempfile.TemporaryDirectory(prefix="compose-") as tmp:
            work = Path(tmp)
            scenes: list[SceneInput] = []
            last_image = None
            rows = repo.list_scenes(ctx.db, job_id)[: s.render_scenes]
            for pos, row in enumerate(rows):
                idx = row["idx"]
                scene = Scene.model_validate(row["data"])
                video_sr = repo.get_stage_run(ctx.db, job_id, "video", idx) or {}
                ends_on_next = bool((video_sr.get("output") or {}).get("ends_on_next"))
                cut = "separate"
                if pos + 1 < len(rows) and board.continuity == "continuous":
                    nxt = Scene.model_validate(rows[pos + 1]["data"])
                    if is_chained(board, rows[pos + 1]["idx"], nxt):
                        cut = "chain"
                    elif ends_on_next:
                        cut = "end_frame"
                video = repo.get_asset(ctx.db, str(row["video_asset_id"]))
                clip = work / f"clip_{idx}.mp4"
                clip.write_bytes(ctx.storage.get(video["storage_key"]))
                if row["image_asset_id"]:
                    last_image = repo.get_asset(ctx.db, str(row["image_asset_id"]))
                voice_sr = repo.get_stage_run(ctx.db, job_id, "voice", idx)
                voice_path, voice_s = None, 0.0
                if voice_sr and voice_sr["status"] == "done":
                    wav = repo.get_asset(ctx.db, voice_sr["output"]["asset_id"])
                    voice_path = work / f"voice_{idx}.wav"
                    voice_path.write_bytes(ctx.storage.get(wav["storage_key"]))
                    voice_s = float(voice_sr["output"]["duration_s"])
                scenes.append(
                    SceneInput(
                        clip=clip,
                        length_s=float(scene.duration_s),
                        voiceover=scene.voiceover,
                        headline=scene.on_screen_text,
                        voice=voice_path,
                        voice_s=voice_s,
                        fit_clip=ends_on_next,
                        blend_out_s=CUT_BLEND_S[cut],
                    )
                )
            end_image = None
            if last_image is not None:
                end_image = work / f"endcard_product.{TYPE_EXTS.get(last_image['content_type'], 'jpg')}"
                end_image.write_bytes(ctx.storage.get(last_image["storage_key"]))
            spec = ComposeSpec(
                scenes=scenes,
                master_ratio=brief.aspect_ratio,
                platform=brief.platform,
                cta_text=board.cta_text,
                offer=brief.offer,
                product_name=brief.product_name,
                end_card_image=end_image,
                music=music_for(brief, s.default_music_theme),
                captions=brief.captions,
                branding=_branding(ctx, job, work),
                scale=s.compose_scale,
                end_card_s=s.end_card_s,
            )
            result = compose(spec, work / "out")
            checks = check_compose(spec, result)
            base = f"jobs/{job_id}/variant-A"
            files = [("ad", r.path) for r in result.exported]
            files += [("cover", result.cover)] + [("still", p) for p in result.stills]
            files += [("carousel", p) for p in result.carousel]
            for kind, path in files:
                data = path.read_bytes()
                key = f"{base}/{path.name}"
                ctype = "video/mp4" if path.suffix == ".mp4" else "image/jpeg"
                ctx.storage.put(key, data, ctype)
                repo.add_asset(
                    ctx.db,
                    job_id=job_id,
                    kind=ASSET_KIND[kind],
                    storage_key=key,
                    content_type=ctype,
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            output = {
                "duration_s": result.duration_s,
                "ratios": [r.ratio for r in result.exported],
                "skipped": {r.ratio: r.reason for r in result.ads if not r.passed},
                "checks": checks,
                "timeline": [t.__dict__ for t in result.timeline],
            }
    except Exception as e:
        repo.stage_failed(ctx.db, sr["id"], f"{type(e).__name__}: {e}")
        raise
    repo.set_variant_output(ctx.db, job_id, "A", output)
    repo.stage_done(ctx.db, sr["id"], {k: output[k] for k in ("duration_s", "ratios", "skipped")})


def use_own_image(ctx: Context, job: dict, idx: int, scene: Scene, ratio: str) -> dict:
    """A scene image the user already has (their upload, or the product photo): free, no render.

    It is fitted to the ad's master ratio first (crop, or a blurred fill when a crop would cut
    too much), because the video model takes the clip's shape from its input image."""
    job_id = str(job["id"])
    sr = repo.get_stage_run(ctx.db, job_id, "image", idx)
    if sr and sr["status"] == "done":
        return repo.get_asset(ctx.db, sr["output"]["asset_id"])
    source_key = job["upload_key"] if scene.image_source == "product" else scene.image_upload_key
    if not source_key:
        raise RuntimeError(f"scene {idx + 1} has no uploaded image")
    sr = repo.start_stage(ctx.db, job_id, "image", idx, provider="own", model=f"own-{scene.image_source}", attempt=1)
    from PIL import Image

    w, h = frame_size(ratio)
    with Image.open(io.BytesIO(ctx.storage.get(source_key))) as im:
        mode = "crop" if crop_keep_image(im.width / im.height, w / h) >= MIN_CROP_KEEP else "pad"
        fitted = fit_into(im, w, h, mode)
    buf = io.BytesIO()
    fitted.save(buf, "JPEG", quality=92)
    asset = _store_output(ctx, job_id, "image", idx, buf.getvalue(), "image/jpeg")
    repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "own": scene.image_source, "fit": mode})
    return asset


def is_chained(board: Storyboard, idx: int, scene: Scene) -> bool:
    """Continuous mode: a scene after the first, without a picture of its own, starts from the frame
    where the previous scene is cut (D29)."""
    return board.continuity == "continuous" and idx > 0 and scene.image_source == "generate"


def ends_on_next_picture(board: Storyboard, next_idx: int, next_scene: Scene) -> bool:
    """Continuous mode (D30): a scene with its own picture is reached by the clip before it, which
    ends on that picture (Kling's end frame), so the cut between them matches."""
    return board.continuity == "continuous" and next_idx > 0 and next_scene.image_source != "generate"


# How each cut is joined in compose (D30): a chained cut has the same frame on both sides, so a
# clean cut; a cut onto the clip's end picture gets a very short blend for the model's small
# difference; separate shots keep the 0.3 s soft blend (D29).
CUT_BLEND_S = {"chain": 0.0, "end_frame": 0.1, "separate": 0.3}


def chain_frame(ctx: Context, job: dict, idx: int, prev_video: dict, cut_s: float) -> dict:
    """The starting picture of a chained scene: the previous clip's frame at the cut. Free; resumable."""
    job_id = str(job["id"])
    sr = repo.get_stage_run(ctx.db, job_id, "image", idx)
    if sr and sr["status"] == "done":
        return repo.get_asset(ctx.db, sr["output"]["asset_id"])
    sr = repo.start_stage(ctx.db, job_id, "image", idx, provider="chain", model="previous-clip-frame", attempt=1)
    with tempfile.TemporaryDirectory(prefix="chain-") as tmp:
        clip = Path(tmp) / "prev.mp4"
        clip.write_bytes(ctx.storage.get(prev_video["storage_key"]))
        t = max(0.0, min(cut_s, probe_duration(clip)) - 0.05)
        frame = None
        for back in (0.0, 0.2, 0.5, t):  # a seek just past the last frame gives no picture: step back
            try:
                frame = frame_at(clip, max(0.0, t - back), Path(tmp) / f"frame{back}.png")
                t = max(0.0, t - back)
                break
            except (FileNotFoundError, OSError):
                continue
        if frame is None:
            raise RuntimeError(f"could not read the last frame of scene {idx}")
        buf = io.BytesIO()
        frame.save(buf, "JPEG", quality=92)
    asset = _store_output(ctx, job_id, "image", idx, buf.getvalue(), "image/jpeg")
    repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "chained_from": idx - 1, "at_s": round(t, 3)})
    return asset


def crop_keep_image(a: float, b: float) -> float:
    return min(a, b) / max(a, b)


def run_job(ctx: Context, job: dict) -> None:
    """Run the job's current phase. Safe to call again after a crash: it resumes.

    Phase "images" (after Approve): one reference image per scene, generated or the user's own.
    Phase "video" (after "Make the video"): the voiceover lines first (cheap, so a voice problem
    stops the job before any video is paid), then one clip per scene, then compose.
    """
    s = ctx.settings
    job_id = str(job["id"])
    brief = Brief.model_validate(job["brief"])
    board = Storyboard.model_validate(job["storyboard"])
    brand = BrandKit.model_validate(job["brand"]) if job.get("brand") else None
    tone = brand.tone if brand else None
    rows = repo.list_scenes(ctx.db, job_id)[: s.render_scenes]
    photo = ctx.storage.get(job["upload_key"])
    product = InputImage(
        data=photo,
        content_type=content_type_for(job["upload_key"]),
        url=ctx.storage.provider_url(job["upload_key"], 3600),
    )
    seed = job_seed(job_id)
    images: dict[int, dict] = {}
    count = len(rows)
    for row in rows:
        idx = row["idx"]
        scene = Scene.model_validate(row["data"])
        if is_chained(board, idx, scene):
            continue  # its starting picture is the previous clip's last frame, made in the video phase
        if scene.image_source != "generate":
            image = use_own_image(ctx, job, idx, scene, brief.aspect_ratio)
        else:

            def plan_image(scene=scene):
                return plan_scene_image(
                    model=s.image_model,
                    scene=scene,
                    aspect_ratio=brief.aspect_ratio,
                    seed=seed,
                    product=product,
                    product_sha256=job["upload_sha256"],
                    style=brief.visual_style,
                    notes=board.notes,
                    keep_same=board.keep_same if board.continuity == "continuous" else None,
                )

            image = run_media_stage(ctx, job, "image", idx, plan_image)
        repo.set_scene_asset(ctx.db, job_id, idx, "image", str(image["id"]))
        images[idx] = image
    if job.get("phase", "video") == "images":
        repo.finish_job(ctx.db, job_id)
        return

    if brief.voice != "none":
        for row in rows:
            scene = Scene.model_validate(row["data"])
            run_voice_stage(ctx, job, row["idx"], scene.voiceover, brief.voice, tone)
    prev_video = None
    prev_scene = None
    scenes = [Scene.model_validate(r["data"]) for r in rows]
    for pos, row in enumerate(rows):
        idx = row["idx"]
        scene = scenes[pos]
        if is_chained(board, idx, scene):
            images[idx] = chain_frame(ctx, job, idx, prev_video, float(prev_scene.duration_s))
            repo.set_scene_asset(ctx.db, job_id, idx, "image", str(images[idx]["id"]))
        # D30: when the next scene has its own picture, this clip ends on it, so the cut matches.
        end = None
        if pos + 1 < len(rows) and ends_on_next_picture(board, idx + 1, scenes[pos + 1]):
            end = images[rows[pos + 1]["idx"]]

        def as_input(asset: dict) -> InputImage:
            return InputImage(
                data=ctx.storage.get(asset["storage_key"]),
                content_type=asset["content_type"],
                url=ctx.storage.provider_url(asset["storage_key"], 3600),
            )

        def plan_video(image=images[idx], scene=scene, idx=idx, end=end):
            return plan_scene_video(
                model=s.video_model,
                scene=scene,
                duration_s=render_seconds(scene.duration_s),
                used_s=scene.duration_s,
                reference=as_input(image),
                reference_sha256=image["sha256"],
                style=brief.visual_style,
                notes=board.notes,
                position=(idx, count),
                continuous=board.continuity == "continuous",
                end_image=as_input(end) if end else None,
                end_image_sha256=end["sha256"] if end else None,
                keep_same=board.keep_same,
            )

        video = run_media_stage(ctx, job, "video", idx, plan_video, meta={"ends_on_next": True} if end else None)
        repo.set_scene_asset(ctx.db, job_id, idx, "video", str(video["id"]))
        prev_video, prev_scene = video, scene
    run_compose_stage(ctx, job, brief, board)
    repo.finish_job(ctx.db, job_id)


DEFAULT_SCENES = 3  # an ad written without the user's own story
VOICE_EST_WORDS = 14  # a voiceover line is about 12 words; a little more for the estimate


def voice_est_usd(s: Settings, text: str | None = None) -> float:
    words = text if text and text.strip() else " ".join(["word"] * VOICE_EST_WORDS)
    return cost_usd(s.tts_model, plan_voice(model=s.tts_model, text=words, voice=s.tts_voice, tone=None).usage)


def estimate_job_usd(s: Settings) -> float:
    """Default estimate for a full ad (3 generated images, 5 s clips, voiceover), shown before a brief."""
    per_scene = cost_usd(s.image_model, Usage(images=1)) + cost_usd(s.video_model, Usage(seconds=s.video_duration_s))
    per_scene += voice_est_usd(s)
    return round(per_scene * min(DEFAULT_SCENES, s.render_scenes), 6)


def estimate_board_usd(s: Settings, board: Storyboard, voice: str = "marin") -> tuple[float, float]:
    """(images, video) estimate for this storyboard: own images are free; clips by each scene's length."""
    scenes = board.scenes[: s.render_scenes]
    images = sum(
        cost_usd(s.image_model, Usage(images=1))
        for i, sc in enumerate(scenes)
        if sc.image_source == "generate" and not is_chained(board, i, sc)
    )
    video = sum(cost_usd(s.video_model, Usage(seconds=render_seconds(sc.duration_s))) for sc in scenes)
    if voice != "none":
        video += sum(voice_est_usd(s, sc.voiceover) for sc in scenes if sc.voiceover.strip())
    return round(images, 6), round(video, 6)


def estimate_job_eur(s: Settings) -> float:
    return usd_to_eur(estimate_job_usd(s), s.usd_to_eur_rate)
