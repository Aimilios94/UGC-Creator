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
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import repository as repo
from ..config import Settings
from ..errors import BudgetExceeded
from ..models import BrandKit, BrandSnapshot, Brief, ProductAnalysis, Scene, Storyboard, render_seconds
from ..repository import Database
from . import add_scenes, analyze, continuity, shorten, slot_filler, storyboard
from .ad_structure import AdStructure
from .compose import Branding, ComposeSpec, SceneInput, compose, fit_into, frame_at, probe_duration
from .image_gen import PlannedRender, cast_line, plan_extend_image, plan_scene_image
from .llm_trace import Usage, cost_usd, usd_to_eur
from .music import music_for
from .output_checks import check_compose
from .platform_specs import MIN_CROP_KEEP, frame_size
from .providers.llm import LlmHandle, build_llm
from .providers.media import InputImage, MediaFailed, MediaProvider, wait_for
from .providers.storage import Storage
from .providers.voice import VoiceProvider, build_voice
from .scene_plan import end_card_for
from .scene_splitter import Beat, Split, split_story, story_length_s
from .shots import voice_rooms
from .storyboard_checks import drop_flagged_ideas, fix_instructions, flag_testimonials
from .video_gen import ClipText, clip_prompt, plan_scene_video
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
def _run_llm_stage(
    ctx: Context, job_id: str, stage: str, llm: LlmHandle, call, *, attempt: int = 1, scene_idx: int = -1
):
    sr = repo.start_stage(
        ctx.db, job_id, stage, scene_idx, provider=llm.provider, model=llm.model_name, attempt=attempt
    )
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
    ctx: Context,
    job_id: str,
    brief: Brief,
    analysis: ProductAnalysis,
    brand: BrandKit | None,
    attempt: int = 1,
    *,
    ask: bool = True,
    filled: tuple[AdStructure | None, Split | None] | None = None,
) -> Storyboard | None:
    """Write (or rewrite, for example from the user's own story) the storyboard and save it.

    Quick questions (D31 phase 5): when the slot filler leaves key slots to the AI's guess and has
    questions about them, they are saved with the structure and nothing more is written (returns
    None); `answer_questions` writes the storyboard once the user answers or skips them.

    Testimonial rule: if the code check flags lines, the storyboard is written once more
    with those lines as feedback. Lines still flagged after that are left for the user to
    edit on the Storyboard step (Approve is refused while any remain).
    """
    if not brief.video_length_s and (asked := story_length_s(brief.story)):
        # No length chosen but the story names one ("a 20-second commercial"): that is the ad's
        # length, so the number of shots and their lengths follow it (the owner's hoodie test, 27 Nov 2026).
        brief = brief.model_copy(update={"video_length_s": asked})
        repo.set_brief(ctx.db, job_id, brief.model_dump(mode="json"))
    structure, split = filled or fill_slots(ctx, job_id, brief, analysis, attempt=attempt)
    # A vague idea (code asks when the AI did not, D32): a short story with no scenes and no spoken
    # lines, like "guy wearing my hoodie in the rain" or a one-paragraph concept.
    story = brief.story.strip()
    vague = (
        bool(story)
        and not (split is not None and split.beats)
        and not re.search(r"[\"“”]", story)
        and len(story.split()) <= 80
    )
    if ask and structure is not None and (questions := slot_filler.open_questions(structure, vague=vague)):
        structure.questions = questions
        repo.set_pending(ctx.db, job_id, {"structure": structure.model_dump(mode="json"), "split": dump_split(split)})
        return None
    llm = ctx.llm_factory("storyboard")
    board = _run_llm_stage(
        ctx,
        job_id,
        "storyboard",
        llm,
        lambda: storyboard.write_storyboard(
            llm, brief, analysis, brand=brand, end_card_s=ctx.settings.end_card_s, split=split, structure=structure
        ),
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
                    llm,
                    brief,
                    analysis,
                    brand=brand,
                    feedback=feedback,
                    end_card_s=ctx.settings.end_card_s,
                    split=split,
                    structure=structure,
                ),
                attempt=attempt + 1,
            )
        except Exception:  # noqa: BLE001 - keep the first storyboard; its flagged lines go to the user
            log.exception("storyboard rewrite failed for job %s; keeping the first version", job_id)
            sr = repo.get_stage_run(ctx.db, job_id, "storyboard")
            if sr:
                repo.stage_done(ctx.db, sr["id"], {"model": llm.model_name, "rewrite_failed": True})
    board = drop_flagged_ideas(board, brief)
    board = check_scene_flow(ctx, job_id, board, brief, attempt=attempt)
    repo.set_storyboard(ctx.db, job_id, board.model_dump(mode="json"))
    repo.set_pending(ctx.db, job_id, None)
    return board


def dump_split(split: Split | None) -> dict | None:
    return asdict(split) if split is not None else None


def load_split(data: dict | None) -> Split | None:
    if not data:
        return None
    beats = [Beat(**b) for b in data.get("beats", [])]
    return Split(data["shape"], beats, data.get("notes", ""), list(data.get("messages", [])))


def answer_questions(ctx: Context, job: dict, answers: dict[str, str], *, skip: bool = False) -> Storyboard:
    """The quick questions answered (or skipped): the answers go into their slots, locked, and the
    storyboard is written from the stored structure. No extra AI call: the writer runs as it would have."""
    job_id = str(job["id"])
    pending = job["pending"]
    structure = AdStructure.model_validate(pending["structure"])
    if not skip:
        structure = slot_filler.apply_answers(structure, answers)
    brief = Brief.model_validate(job["brief"])
    analysis = ProductAnalysis.model_validate(job["analysis"])
    brand = BrandKit.model_validate(job["brand"]) if job.get("brand") else None
    sr = repo.get_stage_run(ctx.db, job_id, "storyboard")
    board = write_board(
        ctx, job_id, brief, analysis, brand, attempt=(sr["attempt"] + 1) if sr else 1,
        ask=False, filled=(structure, load_split(pending.get("split"))),
    )  # fmt: skip
    assert board is not None
    return board


def fill_slots(
    ctx: Context, job_id: str, brief: Brief, analysis: ProductAnalysis | None, attempt: int = 1
) -> tuple[AdStructure | None, Split | None]:
    """The slot filler (D31 phase 3): one cheap LLM call that reads the ad into the fixed structure
    and, for a story of plain paragraphs, which paragraphs are scenes. If it fails, the writer works
    as before (the story split in code, or read whole) and the storyboard has no marks."""
    split = split_story(brief.story) if brief.story else None
    llm = ctx.llm_factory("slots")
    try:
        return _run_llm_stage(
            ctx,
            job_id,
            "slots",
            llm,
            lambda: slot_filler.fill_slots(
                llm, brief, analysis, split or Split("none", [], ""), end_card_s=ctx.settings.end_card_s
            ),
            attempt=attempt,
        )
    except BudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 - the ad still works without the structure
        log.exception("slot filler failed for job %s; writing the storyboard without it", job_id)
        return None, split


def add_scenes_to_board(ctx: Context, job: dict) -> Storyboard:
    """'Add scenes to reach N s' (plan v2.3): the writer adds scenes, then the joins are checked again."""
    job_id = str(job["id"])
    brief = Brief.model_validate(job["brief"])
    board = Storyboard.model_validate(job["storyboard"])
    analysis = ProductAnalysis.model_validate(job["analysis"]) if job.get("analysis") else None
    llm = ctx.llm_factory("add_scenes")
    sr = repo.get_stage_run(ctx.db, job_id, "add_scenes")
    attempt = (sr["attempt"] + 1) if sr else 1
    board = _run_llm_stage(
        ctx,
        job_id,
        "add_scenes",
        llm,
        lambda: add_scenes.add_scenes(
            llm, board, brief, analysis, end_card_s=end_card_for(board.scenes, ctx.settings.end_card_s)
        ),
        attempt=attempt,
    )
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


def prepare_storyboard(
    ctx: Context, job: dict, photo: bytes, content_type: str
) -> tuple[ProductAnalysis, Storyboard | None]:
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


def storyboard_from_story(ctx: Context, job: dict, story: str) -> Storyboard | None:
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
    # The exact text the model got, kept with the stage for the findings archive (D31).
    meta = {**meta, "sent": {k: req.arguments[k] for k in SENT_FIELDS if k in req.arguments}}

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
            all_scenes = [Scene.model_validate(r["data"]) for r in rows]
            rooms = voice_rooms(all_scenes)
            card_row = rows[-1] if rows and all_scenes[-1].kind == "card" else None
            if card_row is not None:
                rows = rows[:-1]  # the story's own end card is drawn by us (D32), never filmed
            for pos, row in enumerate(rows):
                idx = row["idx"]
                scene = all_scenes[pos]
                video_sr = repo.get_stage_run(ctx.db, job_id, "video", idx) or {}
                ends_on_next = bool((video_sr.get("output") or {}).get("ends_on_next"))
                cut = "separate"
                if pos + 1 < len(rows) and board.continuity == "continuous":
                    nxt = all_scenes[pos + 1]
                    if is_chained(board, rows[pos + 1]["idx"], nxt):
                        cut = "chain"
                    elif ends_on_next:
                        cut = "end_frame"
                    elif nxt.join == "cut":
                        cut = "cut"
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
                        voice_room_s=rooms[pos],
                    )
                )
            end_card_s = s.end_card_s
            card_voice, card_voice_s, card_line, card_headline = None, 0.0, "", ""
            if card_row is not None:
                card = all_scenes[-1]
                end_card_s = float(card.duration_s)
                card_line, card_headline = card.voiceover, card.on_screen_text or brief.product_name
                voice_sr = repo.get_stage_run(ctx.db, job_id, "voice", card_row["idx"])
                if voice_sr and voice_sr["status"] == "done":
                    wav = repo.get_asset(ctx.db, voice_sr["output"]["asset_id"])
                    card_voice = work / "voice_card.wav"
                    card_voice.write_bytes(ctx.storage.get(wav["storage_key"]))
                    card_voice_s = float(voice_sr["output"]["duration_s"])
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
                end_card_s=end_card_s,
                end_card_voice=card_voice,
                end_card_voice_s=card_voice_s,
                end_card_voiceover=card_line,
                end_card_headline=card_headline,
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


def own_fit(width: int, height: int, ratio: str) -> str:
    """How an own picture becomes the ad's shape: "crop" when a centre crop keeps at least 75% of
    it (free), else "extend" (the image model continues the scene to the full frame, one picture's
    price). Never a blurred fill: Kling animates the bands into every scene that follows (D31)."""
    w, h = frame_size(ratio)
    return "crop" if crop_keep_image(width / height, w / h) >= MIN_CROP_KEEP else "extend"


def use_own_image(ctx: Context, job: dict, idx: int, scene: Scene, ratio: str) -> dict:
    """A scene image the user already has (their upload, or the product photo).

    It is made the ad's master shape first, because the video model takes the clip's shape from
    its input image: a free centre crop, or, when that would cut too much, extended to the full
    frame by the image model (see `own_fit`)."""
    job_id = str(job["id"])
    sr = repo.get_stage_run(ctx.db, job_id, "image", idx)
    if sr and sr["status"] == "done":
        return repo.get_asset(ctx.db, sr["output"]["asset_id"])
    source_key = job["upload_key"] if scene.image_source == "product" else scene.image_upload_key
    if not source_key:
        raise RuntimeError(f"scene {idx + 1} has no uploaded image")
    from PIL import Image

    w, h = frame_size(ratio)
    with Image.open(io.BytesIO(ctx.storage.get(source_key))) as im:
        mode = own_fit(im.width, im.height, ratio)
        fitted = fit_into(im, w, h, "crop" if mode == "crop" else "pad")
    buf = io.BytesIO()
    fitted.save(buf, "JPEG", quality=92)
    data = buf.getvalue()
    if mode == "extend":
        # The picture on its blurred copy is only the model's input; it is never shown or animated.
        key = f"jobs/{job_id}/scene-{idx}/own-placed.jpg"
        ctx.storage.put(key, data, "image/jpeg")
        placed = InputImage(data=data, content_type="image/jpeg", url=ctx.storage.provider_url(key, 3600))
        return run_media_stage(
            ctx,
            job,
            "image",
            idx,
            lambda: plan_extend_image(
                model=ctx.settings.image_model,
                aspect_ratio=ratio,
                seed=job_seed(job_id),
                placed=placed,
                placed_sha256=hashlib.sha256(data).hexdigest(),
            ),
            meta={"own": scene.image_source, "fit": "extend"},
        )
    sr = repo.start_stage(ctx.db, job_id, "image", idx, provider="own", model=f"own-{scene.image_source}", attempt=1)
    asset = _store_output(ctx, job_id, "image", idx, data, "image/jpeg")
    repo.stage_done(ctx.db, sr["id"], {"asset_id": str(asset["id"]), "own": scene.image_source, "fit": mode})
    return asset


def is_chained(board: Storyboard, idx: int, scene: Scene) -> bool:
    """Continuous mode: a shot after the first that flows on (D32), without a picture of its own,
    starts from the frame where the previous shot is cut (D29). A shot after a cut gets its own picture."""
    return (
        board.continuity == "continuous"
        and idx > 0
        and scene.image_source == "generate"
        and scene.join == "flow"
        and scene.kind == "clip"
        and board.scenes[idx - 1].kind == "clip"
    )


def ends_on_next_picture(board: Storyboard, next_idx: int, next_scene: Scene) -> bool:
    """Continuous mode (D30): a shot with its own picture that flows on is reached by the clip before
    it, which ends on that picture (Kling's end frame), so the cut between them matches. A cut (D32)
    is a clean cut to the new picture instead: one person never morphs into another."""
    return (
        board.continuity == "continuous"
        and next_idx > 0
        and next_scene.image_source != "generate"
        and next_scene.join == "flow"
        and next_scene.kind == "clip"
    )


def flows_out(board: Storyboard, idx: int) -> bool:
    """Whether the shot after this one flows on from its last frame (D32)."""
    nxt = board.scenes[idx + 1] if idx + 1 < len(board.scenes) else None
    return nxt is not None and nxt.join == "flow" and nxt.kind == "clip"


SENT_FIELDS = ("prompt", "negative_prompt", "duration", "aspect_ratio", "seed")

# How each cut is joined in compose (D30): a chained cut has the same frame on both sides, so a
# clean cut; a cut onto the clip's end picture gets a very short blend for the model's small
# difference; separate shots keep the 0.3 s soft blend (D29).
CUT_BLEND_S = {"chain": 0.0, "end_frame": 0.1, "separate": 0.3, "cut": 0.0}  # cut: a story's clean cut (D32)


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


def board_structure(board: Storyboard):
    """The cast and world sheet and the scene cards by scene id, or (None, {}) for an older board."""
    if not board.structure:
        return None, {}
    ad = AdStructure.model_validate(board.structure)
    return ad.sheet, {c.uid: c for c in ad.scenes if c.uid}


def clip_texts(s: Settings, board: Storyboard, brief: Brief) -> list[ClipText]:
    """The exact text each scene's clip gets, as the worker will send it (D30), for the preview."""
    scenes = board.scenes[: s.render_scenes]
    n = len(scenes)
    sheet, cards = board_structure(board)
    return [
        ClipText(text="", chars=0, notes="none", negative="")  # the end card: drawn by us, never filmed (D32)
        if sc.kind == "card"
        else clip_prompt(
            sc,
            idx=i,
            count=n,
            style=brief.visual_style,
            notes=board.notes,
            continuous=board.continuity == "continuous",
            ends_on_next=i + 1 < n and ends_on_next_picture(board, i + 1, scenes[i + 1]),
            flows_out=flows_out(board, i),
            keep_same=board.keep_same,
            sheet=sheet,
            card=cards.get(sc.uid),
        )
        for i, sc in enumerate(scenes)
    ]


def scenes_too_long(s: Settings, board: Storyboard, brief: Brief) -> list[tuple[int, int]]:
    """(scene number, characters over) for every scene whose own text cannot fit its clip."""
    return [(i + 1, c.too_long_by) for i, c in enumerate(clip_texts(s, board, brief)) if c.too_long_by > 0]


def shorten_scene(ctx: Context, job: dict, board: Storyboard, idx: int) -> tuple[str, str]:
    """ "Shorten it for me": one cheap LLM call; returns the scene's shorter text (not saved) and the
    field it goes in: the movement, or, for a clip built from the user's own scene text, the scene text."""
    s = ctx.settings
    brief = Brief.model_validate(job["brief"])
    scene = board.scenes[: s.render_scenes][idx]
    clip = clip_texts(s, board, brief)[idx]
    field = clip.shorten_field
    text = (scene.description if field == "description" else scene.motion_prompt).strip() or scene.description.strip()
    # Fit with some room left for how the shot starts and ends and the style notes.
    target = max(300, len(text) - clip.too_long_by - (100 if board.structure else 400))
    llm = ctx.llm_factory("shorten")
    sr = repo.get_stage_run(ctx.db, str(job["id"]), "shorten", idx)
    shorter = _run_llm_stage(
        ctx,
        str(job["id"]),
        "shorten",
        llm,
        lambda: shorten.shorten_text(llm, text, target),
        attempt=(sr["attempt"] + 1) if sr else 1,
        scene_idx=idx,
    )
    return shorter, field


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
    sheet, cards = board_structure(board)
    faces: dict[str, dict] = {}  # person id -> the first picture showing them alone (strategy plan A4)
    labels = {p.id: p.label or "the person" for p in (sheet.people if sheet else [])}
    in_photo = {p.id for p in (sheet.people if sheet else []) if p.in_photo}  # the photo is their reference

    def as_ref(asset: dict) -> InputImage:
        return InputImage(
            data=ctx.storage.get(asset["storage_key"]),
            content_type=asset["content_type"],
            url=ctx.storage.provider_url(asset["storage_key"], 3600),
        )

    for row in rows:
        idx = row["idx"]
        scene = Scene.model_validate(row["data"])
        if scene.kind == "card":
            continue  # the story's own end card: drawn by us in compose (D32), no picture
        if is_chained(board, idx, scene):
            continue  # its starting picture is the previous clip's last frame, made in the video phase
        card = cards.get(scene.uid)
        who = [p for p in (card.who.ids if card else []) if p in labels]
        if scene.image_source != "generate":
            image = use_own_image(ctx, job, idx, scene, brief.aspect_ratio)
        else:
            people = [(f"{p} ({labels[p]})", as_ref(faces[p]), faces[p]["sha256"]) for p in who if p in faces][:2]
            shown = [f"{p} ({labels[p]})" for p in who if p in in_photo]

            def plan_image(scene=scene, card=card, people=people, shown=shown):
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
                    cast=cast_line(card, sheet),
                    people=people,
                    in_photo=shown,
                )

            image = run_media_stage(ctx, job, "image", idx, plan_image)
        if len(who) == 1 and who[0] not in faces and who[0] not in in_photo:
            faces[who[0]] = image  # one person alone: their face for every later shot
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
    sheet, cards = board_structure(board)  # phase 4: every clip is built from the structure's slots
    scenes = [Scene.model_validate(r["data"]) for r in rows]
    for pos, row in enumerate(rows):
        idx = row["idx"]
        scene = scenes[pos]
        if scene.kind == "card":
            continue  # drawn by us in compose (D32), never filmed
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
                flows_out=flows_out(board, idx),
                end_image=as_input(end) if end else None,
                end_image_sha256=end["sha256"] if end else None,
                keep_same=board.keep_same,
                sheet=sheet,
                card=cards.get(scene.uid),
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


def own_to_extend(board: Storyboard, ratio: str, upload_key: str | None, sizes: dict[str, tuple[int, int]]) -> set[int]:
    """The scenes whose own picture must be extended to the ad's shape (`own_fit`), from the
    stored picture sizes (storage key -> width, height)."""
    out = set()
    for i, sc in enumerate(board.scenes):
        if sc.image_source == "generate":
            continue
        size = sizes.get((upload_key if sc.image_source == "product" else sc.image_upload_key) or "")
        if size and size[0] and size[1] and own_fit(size[0], size[1], ratio) == "extend":
            out.add(i)
    return out


def estimate_board_usd(
    s: Settings, board: Storyboard, voice: str = "marin", extend: set[int] | frozenset[int] = frozenset()
) -> tuple[float, float]:
    """(images, video) estimate for this storyboard: own pictures are free unless they must be
    extended to the ad's shape (`extend`, from `own_to_extend`); clips by each scene's length."""
    scenes = board.scenes[: s.render_scenes]
    filmed = [(i, sc) for i, sc in enumerate(scenes) if sc.kind == "clip"]  # an end card is free (D32)
    images = sum(
        cost_usd(s.image_model, Usage(images=1))
        for i, sc in filmed
        if (sc.image_source == "generate" and not is_chained(board, i, sc)) or i in extend
    )
    video = sum(cost_usd(s.video_model, Usage(seconds=render_seconds(sc.duration_s))) for _, sc in filmed)
    if voice != "none":
        video += sum(voice_est_usd(s, sc.voiceover) for sc in scenes if sc.voiceover.strip())
    return round(images, 6), round(video, 6)


def estimate_job_eur(s: Settings) -> float:
    return usd_to_eur(estimate_job_usd(s), s.usd_to_eur_rate)
