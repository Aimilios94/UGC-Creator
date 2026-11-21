"""Jobs: brief + photo -> storyboard (draft) -> approve -> render -> result.

Every route is scoped to the browser session: another session gets 404, the same
answer as for a job that does not exist. Generation (create, approve, try again)
needs the access code on the public deployment.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError

from .. import repository as repo
from ..deps import get_ctx, require_access_code, session_hash
from ..errors import BudgetExceeded, ProviderNotConfigured, UploadRejected
from ..models import (
    ApproveIn,
    AssetView,
    BrandKit,
    BrandSnapshot,
    Brief,
    CostLine,
    Estimate,
    JobView,
    Money,
    ProductAnalysis,
    SoundIn,
    StageView,
    Storyboard,
    VariantView,
)
from ..services import job_trigger
from ..services.llm_trace import money
from ..services.pipeline import Context, estimate_board_usd, prepare_storyboard, storyboard_from_story
from ..services.storyboard_checks import flag_testimonials
from ..services.uploads import sanitise_image

log = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


def job_view(ctx: Context, job: dict) -> JobView:
    s = ctx.settings
    job_id = str(job["id"])
    ttl = s.signed_url_ttl_seconds
    stages = [
        StageView(stage=r["stage"], scene_idx=r["scene_idx"], status=r["status"], error=r["error"])
        for r in repo.list_stage_runs(ctx.db, job_id)
    ]
    assets: list[AssetView] = []
    for a in repo.list_assets(ctx.db, job_id):
        idx = None
        if "/scene-" in a["storage_key"]:
            try:
                idx = int(a["storage_key"].split("/scene-")[1].split("/")[0])
            except (IndexError, ValueError):
                idx = None
        name = a["storage_key"].rsplit("/", 1)[-1]
        ratio = name[3:-4].replace("x", ":") if a["kind"] == "ad" else None
        assets.append(
            AssetView(
                kind=a["kind"],
                scene_idx=idx,
                ratio=ratio,
                name=name,
                url=ctx.storage.signed_url(a["storage_key"], ttl),
                content_type=a["content_type"],
                expires_in_s=ttl,
            )
        )
    brief = Brief.model_validate(job["brief"])
    board = Storyboard.model_validate(job["storyboard"]) if job.get("storyboard") else None
    spent = repo.job_spend_usd(ctx.db, job_id)
    return JobView(
        id=job_id,
        status=job["status"],
        phase=job.get("phase") or "video",
        costs=[
            CostLine(
                kind=r["kind"],
                model=r["model"],
                calls=int(r["calls"]),
                cost=Money(**money(float(r["usd"]), s.usd_to_eur_rate)),
            )
            for r in repo.job_costs(ctx.db, job_id)
        ],
        estimate=_estimate(ctx, board, spent, job) if board is not None else None,
        brief=brief,
        campaign_id=str(job["campaign_id"]) if job.get("campaign_id") else None,
        brand=BrandKit.model_validate(job["brand"]) if job.get("brand") else None,
        flags=flag_testimonials(board, brief) if board is not None and job["status"] == "draft" else [],
        variants=[
            VariantView(
                label=v["label"],
                hook_idx=v["hook_idx"],
                status=v["status"],
                duration_s=(v.get("output") or {}).get("duration_s"),
                ratios=(v.get("output") or {}).get("ratios", []),
                skipped=(v.get("output") or {}).get("skipped", {}),
                checks=(v.get("output") or {}).get("checks", []),
            )
            for v in repo.list_variants(ctx.db, job_id)
        ],
        analysis=ProductAnalysis.model_validate(job["analysis"]) if job.get("analysis") else None,
        storyboard=public_board(board) if board is not None else None,
        attempts=job["attempts"],
        last_error=job.get("last_error"),
        stages=stages,
        assets=assets,
        spend=Money(**money(spent, s.usd_to_eur_rate)),
        cost_cap=Money(usd=round(s.job_cost_cap_usd, 4), eur=s.job_cost_cap_eur),
        created_at=job["created_at"].isoformat(),
    )


def public_board(board: Storyboard) -> Storyboard:
    """Storage keys stay on the server: the browser only sees where each image comes from."""
    return board.model_copy(
        update={"scenes": [sc.model_copy(update={"image_upload_key": None}) for sc in board.scenes]}
    )


def _estimate(ctx: Context, board: Storyboard, spent_usd: float, job: dict) -> Estimate:
    s = ctx.settings
    rate = s.usd_to_eur_rate
    images, video = estimate_board_usd(s, board, job["brief"].get("voice", "marin"))
    if job["status"] != "draft":
        images = 0.0  # already made
    if job["status"] != "draft" and (job.get("phase") or "video") == "video":
        video = 0.0
    total = images + video
    return Estimate(
        images=Money(**money(images, rate)),
        video=Money(**money(video, rate)),
        total=Money(**money(total, rate)),
        fits_cap=spent_usd + total <= s.job_cost_cap_usd + 1e-9,
    )


def merge_board(new: Storyboard, old: Storyboard, *, lock_images: bool) -> Storyboard:
    """Apply the user's edits, but never from the browser: storage keys (set only by the upload
    route) and, once the images exist, everything that made them, including how many scenes
    there are. Before approval scenes may be added or removed (1-5); a scene keeps its uploaded
    image only while it stays at the same position."""
    if lock_images and len(new.scenes) != len(old.scenes):
        raise HTTPException(status_code=422, detail="The scenes are fixed once the images are made.")
    scenes = []
    by_uid = {s.uid: s for s in old.scenes if s.uid}
    for i, n in enumerate(new.scenes):
        # Match each scene to the stored one by its id (scenes can be joined, added or removed).
        o = by_uid.get(n.uid) if n.uid else (old.scenes[i] if i < len(old.scenes) else None)
        keep = {"image_upload_key": o.image_upload_key if o else None}
        if lock_images:
            keep |= {"image_prompt": o.image_prompt, "image_source": o.image_source}
        sc = n.model_copy(update=keep)
        if sc.image_source == "generate" and not (sc.image_prompt.strip() or sc.description.strip()):
            raise HTTPException(status_code=422, detail=f"Scene {i + 1} needs a description or an image prompt.")
        if sc.image_source == "upload" and not sc.image_upload_key:
            raise HTTPException(
                status_code=422, detail="Upload an image for that scene first, or choose another source."
            )
        scenes.append(sc)
    return new.model_copy(update={"scenes": scenes})


def _check_ready(ctx: Context, job: dict, board: Storyboard, *, phase: str) -> None:
    """Refuse a step that breaks the testimonial rule or cannot fit the cost cap."""
    flags = flag_testimonials(board, Brief.model_validate(job["brief"]))
    if flags:
        raise HTTPException(
            status_code=409,
            detail=f"Edit the {len(flags)} flagged line(s) first: claims of use, results or reviews "
            "need to come from your brief.",
        )
    s = ctx.settings
    images, video = estimate_board_usd(s, board, job["brief"].get("voice", "marin"))
    need = (images + video) if phase == "images" else video
    if repo.job_spend_usd(ctx.db, str(job["id"])) + need > s.job_cost_cap_usd + 1e-9:
        raise HTTPException(
            status_code=409,
            detail=f"This ad would cost more than the cap of {s.job_cost_cap_eur:.2f} EUR. "
            "Use shorter clips (5 s) or your own images for some scenes.",
        )


def _own_job(ctx: Context, job_id: str, sess: str) -> dict:
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found.") from None
    job = repo.get_job_for_session(ctx.db, job_id, sess)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _campaign_for(ctx: Context, sess: str, brief: Brief, campaign_id: str | None, campaign_name: str) -> str:
    """The ad's campaign: one of this session's campaigns, or a new one built from the brief."""
    if campaign_id:
        try:
            uuid.UUID(campaign_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Campaign not found.") from None
        row = repo.get_campaign_for_session(ctx.db, campaign_id, sess)
        if row is None:
            raise HTTPException(status_code=404, detail="Campaign not found.")
        return str(row["id"])
    row = repo.create_campaign(
        ctx.db,
        session_hash=sess,
        name=(campaign_name.strip() or brief.product_name)[:80],
        goal=brief.goal,
        audience=brief.audience,
        offer=brief.offer,
        landing_url=str(brief.landing_url) if brief.landing_url else None,
    )
    return str(row["id"])


def _brand_snapshot(ctx: Context, sess: str) -> dict | None:
    kit = repo.get_brand_kit(ctx.db, sess)
    if kit is None:
        return None
    snap = BrandSnapshot(tone=kit["tone"], colors=kit["colors"] or {}, font=kit["font"], logo_key=kit["logo_key"])
    return snap.model_dump(mode="json")


@router.post("", status_code=201, dependencies=[Depends(require_access_code)])
def create_job(
    brief: str = Form(..., description="Brief as JSON"),
    photo: UploadFile = File(...),
    campaign_id: str | None = Form(default=None, description="An existing campaign of this session"),
    campaign_name: str = Form(default="", max_length=80, description="Name for a new campaign"),
    use_brand_kit: bool = Form(default=False, description="Apply this session's brand kit"),
    sess: str = Depends(session_hash),
    ctx: Context = Depends(get_ctx),
) -> JobView:
    s = ctx.settings
    try:
        parsed = Brief.model_validate(json.loads(brief))
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid brief: {e}") from None
    raw = photo.file.read(s.max_upload_bytes + 1)
    try:
        clean = sanitise_image(raw, max_bytes=s.max_upload_bytes, max_side=s.max_image_side_px)
    except UploadRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    campaign = _campaign_for(ctx, sess, parsed, campaign_id, campaign_name)
    brand = _brand_snapshot(ctx, sess) if use_brand_kit else None
    job_id = str(uuid.uuid4())
    key = f"jobs/{job_id}/upload.{clean.ext}"
    ctx.storage.put(key, clean.data, clean.content_type)
    job = repo.create_job(
        ctx.db,
        job_id=job_id,
        session_hash=sess,
        brief=parsed.model_dump(mode="json"),
        upload_key=key,
        upload_sha256=clean.sha256,
        campaign_id=campaign,
        brand=brand,
    )
    repo.add_asset(
        ctx.db,
        job_id=job_id,
        kind="upload",
        storage_key=key,
        content_type=clean.content_type,
        size=len(clean.data),
        sha256=clean.sha256,
        width=clean.width,
        height=clean.height,
    )
    try:
        prepare_storyboard(ctx, job, clean.data, clean.content_type)
    except BudgetExceeded as e:
        repo.set_job_error(ctx.db, job_id, e.message)
    except ProviderNotConfigured as e:
        log.error("provider not configured: %s", e)
        repo.set_job_error(ctx.db, job_id, "The AI provider is not configured on this server.")
    except Exception:  # noqa: BLE001 - the user sees a retryable message, details go to the log
        log.exception("storyboard failed for job %s", job_id)
        repo.set_job_error(ctx.db, job_id, "Writing the storyboard failed. Please try again.")
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.get("/{job_id}")
def get_job(job_id: str, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> JobView:
    return job_view(ctx, _own_job(ctx, job_id, sess))


@router.put("/{job_id}/storyboard")
def edit_storyboard(
    job_id: str, board: Storyboard, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)
) -> JobView:
    job = _own_job(ctx, job_id, sess)
    if job["status"] != "draft" or not job.get("storyboard"):
        raise HTTPException(status_code=409, detail="The storyboard is locked once approved.")
    merged = merge_board(board, Storyboard.model_validate(job["storyboard"]), lock_images=False)
    if not repo.set_storyboard(ctx.db, str(job["id"]), merged.model_dump(mode="json")):
        raise HTTPException(status_code=409, detail="The storyboard is locked once approved.")
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.put("/{job_id}/sound")
def set_sound(
    job_id: str, body: SoundIn, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)
) -> JobView:
    """Voice, music and captions can change until the video is made."""
    job = _own_job(ctx, job_id, sess)
    editable = job["status"] == "draft" or (job["status"] == "done" and job.get("phase") == "images")
    if not editable:
        raise HTTPException(status_code=409, detail="The sound is fixed once the video is being made.")
    brief = {**job["brief"], **body.model_dump(exclude_none=True)}
    Brief.model_validate(brief)
    with ctx.db.tx() as c:
        c.execute("update jobs set brief = %s, updated_at = now() where id = %s", (repo.Jsonb(brief), job_id))
    return job_view(ctx, repo.get_job(ctx.db, job_id))


class StoryIn(BaseModel):
    story: str = Field(min_length=20, max_length=4000)


@router.post("/{job_id}/story", dependencies=[Depends(require_access_code)])
def from_story(
    job_id: str, body: StoryIn, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)
) -> JobView:
    """ "My own story": the storyboard is written again from the user's story (a few cents)."""
    job = _own_job(ctx, job_id, sess)
    if job["status"] != "draft" or not job.get("analysis"):
        raise HTTPException(status_code=409, detail="The story can be changed only before you approve.")
    try:
        storyboard_from_story(ctx, job, body.story.strip())
    except BudgetExceeded as e:
        raise HTTPException(status_code=409, detail=e.message) from None
    except Exception:  # noqa: BLE001 - details go to the log
        log.exception("storyboard from story failed for job %s", job_id)
        raise HTTPException(
            status_code=502, detail="Writing the storyboard from your story failed. Try again."
        ) from None
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.post("/{job_id}/scenes/{idx}/image", dependencies=[Depends(require_access_code)])
def upload_scene_image(
    job_id: str,
    idx: int,
    image: UploadFile = File(...),
    sess: str = Depends(session_hash),
    ctx: Context = Depends(get_ctx),
) -> JobView:
    """Use the user's own image for a scene instead of generating one (free)."""
    job = _own_job(ctx, job_id, sess)
    if job["status"] != "draft" or not job.get("storyboard"):
        raise HTTPException(status_code=409, detail="Scene images can be changed only before you approve.")
    board = Storyboard.model_validate(job["storyboard"])
    if not 0 <= idx < len(board.scenes):
        raise HTTPException(status_code=404, detail="Scene not found.")
    s = ctx.settings
    raw = image.file.read(s.max_upload_bytes + 1)
    try:
        clean = sanitise_image(raw, max_bytes=s.max_upload_bytes, max_side=s.max_image_side_px)
    except UploadRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    key = f"jobs/{job['id']}/scene-{idx}/own-{uuid.uuid4().hex[:8]}.{clean.ext}"
    ctx.storage.put(key, clean.data, clean.content_type)
    repo.add_asset(
        ctx.db,
        job_id=str(job["id"]),
        kind="upload",
        storage_key=key,
        content_type=clean.content_type,
        size=len(clean.data),
        sha256=clean.sha256,
        width=clean.width,
        height=clean.height,
    )
    scenes = list(board.scenes)
    scenes[idx] = scenes[idx].model_copy(update={"image_source": "upload", "image_upload_key": key})
    repo.set_storyboard(ctx.db, str(job["id"]), board.model_copy(update={"scenes": scenes}).model_dump(mode="json"))
    return job_view(ctx, repo.get_job(ctx.db, job_id))


def _start_worker(ctx: Context) -> None:
    try:
        job_trigger.trigger_worker(ctx.settings)
    except Exception:  # noqa: BLE001 - the job stays queued; approving again re-triggers
        log.exception("could not start a worker execution")
        raise HTTPException(
            status_code=503, detail="The job is queued but the worker did not start. Click Approve again in a minute."
        ) from None


@router.post("/{job_id}/approve", status_code=202, dependencies=[Depends(require_access_code)])
def approve(
    job_id: str,
    body: ApproveIn | None = Body(default=None),
    sess: str = Depends(session_hash),
    ctx: Context = Depends(get_ctx),
) -> JobView:
    """Idempotent: a double-click or retry changes nothing after the first approval.

    Refused while the storyboard has lines that break the testimonial rule."""
    current = _own_job(ctx, job_id, sess)
    if current["status"] == "draft" and current.get("storyboard"):
        _check_ready(ctx, current, Storyboard.model_validate(current["storyboard"]), phase="images")
    mode = body.mode if body else "images"
    job, _ = repo.approve_job(ctx.db, job_id, sess, phase=mode)
    if job["status"] == "draft":
        raise HTTPException(status_code=409, detail="There is no storyboard to approve yet.")
    if job["status"] == "queued":
        _start_worker(ctx)  # also on a repeat click: an extra execution finds nothing and exits 0
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.post("/{job_id}/video", status_code=202, dependencies=[Depends(require_access_code)])
def make_video(
    job_id: str,
    board: Storyboard | None = Body(default=None),
    sess: str = Depends(session_hash),
    ctx: Context = Depends(get_ctx),
) -> JobView:
    """Step 2: make the video from the finished images. The video fields of the storyboard
    (voiceover, on-screen text, motion, clip length, hook) may be edited first. Idempotent."""
    job = _own_job(ctx, job_id, sess)
    if job["status"] == "draft":
        raise HTTPException(status_code=409, detail="Approve the storyboard first: the images come before the video.")
    if (job.get("phase") or "video") == "video" or job["status"] in ("queued", "running"):
        if job["status"] in ("queued", "running"):
            _start_worker(ctx)
        return job_view(ctx, job)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Make the images first.")
    old = Storyboard.model_validate(job["storyboard"])
    merged = merge_board(board, old, lock_images=True) if board is not None else old
    _check_ready(ctx, job, merged, phase="video")
    job, changed = repo.start_video(ctx.db, job_id, sess, merged.model_dump(mode="json"))
    if changed or job["status"] == "queued":
        _start_worker(ctx)
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.post("/{job_id}/retry", status_code=202, dependencies=[Depends(require_access_code)])
def retry(job_id: str, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> JobView:
    """ "Try again" after a failure: attempts reset, the job's spend so far still counts."""
    _own_job(ctx, job_id, sess)
    job, changed = repo.retry_job(ctx.db, job_id, sess)
    if not changed and job["status"] != "queued":
        raise HTTPException(status_code=409, detail="Only a failed job can be tried again.")
    _start_worker(ctx)
    return job_view(ctx, repo.get_job(ctx.db, job_id))
