"""Jobs: brief + photo -> storyboard (draft) -> approve -> render -> result.

Every route is scoped to the browser session: another session gets 404, the same
answer as for a job that does not exist. Generation (create, approve, try again)
needs the access code on the public deployment.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError

from .. import repository as repo
from ..deps import get_ctx, require_access_code, session_hash
from ..errors import BudgetExceeded, ProviderNotConfigured, UploadRejected
from ..models import (
    NO_PHOTO_NOTE,
    STORY_MAX,
    AnswersIn,
    ApproveIn,
    AssetView,
    BrandKit,
    BrandSnapshot,
    Brief,
    ClipView,
    CostLine,
    Estimate,
    HistoryItem,
    JobView,
    LengthIn,
    LengthLine,
    Money,
    ProductAnalysis,
    QuestionView,
    ShortenOut,
    SoundIn,
    StageCost,
    StageView,
    Storyboard,
    VariantView,
)
from ..services import job_trigger
from ..services.ad_structure import AdStructure, merge_structure
from ..services.llm_trace import money
from ..services.pipeline import (
    Context,
    add_scenes_to_board,
    answer_questions,
    clip_texts,
    estimate_board_usd,
    own_to_extend,
    prepare_storyboard,
    scenes_too_long,
    shorten_scene,
    storyboard_from_story,
)
from ..services.scene_plan import end_card_for, length_line
from ..services.slot_filler import fill_gaps
from ..services.storyboard_checks import flag_testimonials
from ..services.uploads import sanitise_image

log = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


def _questions(job: dict) -> list[QuestionView]:
    """The quick questions waiting before the storyboard (D31 phase 5), if any."""
    if job["status"] != "draft" or not job.get("pending"):
        return []
    qs = (job["pending"].get("structure") or {}).get("questions") or []
    return [QuestionView(slot=q["slot"], text=q["text"], options=q["options"]) for q in qs]


STAGE_LABELS = {
    "analyze": "Reading your photo",
    "slots": "Reading your story",
    "storyboard": "Writing the storyboard",
    "add_scenes": "Adding scenes",
    "continuity": "Continuity check",
    "shorten": "Shortening a scene",
    "image": "Starting pictures",
    "video": "Video clips",
    "voice": "Voiceover",
    "compose": "Editing the ad",
    "other": "Other",
}


def stage_costs(ctx: Context, job_id: str) -> list[StageCost]:
    rate = ctx.settings.usd_to_eur_rate
    return [
        StageCost(
            stage=r["stage"],
            label=STAGE_LABELS.get(r["stage"], r["stage"]),
            calls=int(r["calls"]),
            cost=Money(**money(float(r["usd"]), rate)),
        )
        for r in repo.job_costs_by_stage(ctx.db, job_id)
    ]


def history_item(ctx: Context, job: dict) -> HistoryItem:
    """A History row: the cover (else the first picture, else the product photo) as a signed URL."""
    pick = {"cover": 0, "image": 1, "upload": 2}
    assets = sorted(
        (a for a in repo.list_assets(ctx.db, str(job["id"])) if a["kind"] in pick),
        key=lambda a: (pick[a["kind"]], a["created_at"]),
    )
    brief = job["brief"]
    return HistoryItem(
        id=str(job["id"]),
        status=job["status"],
        phase=job.get("phase") or "video",
        product_name=brief.get("product_name", ""),
        theme=brief.get("theme"),
        platform=brief.get("platform", "tiktok"),
        created_at=job["created_at"].isoformat(),
        finished_at=job["finished_at"].isoformat() if job.get("finished_at") else None,
        picture_url=ctx.storage.signed_url(assets[0]["storage_key"], ctx.settings.signed_url_ttl_seconds)
        if assets
        else None,
        cost=Money(**money(float(job["usd"]), ctx.settings.usd_to_eur_rate)),
    )


def job_view(ctx: Context, job: dict) -> JobView:
    s = ctx.settings
    job_id = str(job["id"])
    ttl = s.signed_url_ttl_seconds
    stages = [
        StageView(stage=r["stage"], scene_idx=r["scene_idx"], status=r["status"], error=r["error"])
        for r in repo.list_stage_runs(ctx.db, job_id)
    ]
    assets: list[AssetView] = []
    # An own picture follows its scene when scenes are moved, joined or removed: the page matches it
    # by the scene's id, never by the position it was uploaded at.
    owner = {
        sc.get("image_upload_key"): sc.get("uid")
        for sc in (job.get("storyboard") or {}).get("scenes", [])
        if sc.get("image_upload_key")
    }
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
                scene_uid=owner.get(a["storage_key"]) if a["kind"] == "upload" else None,
                ratio=ratio,
                name=name,
                url=ctx.storage.signed_url(a["storage_key"], ttl),
                content_type=a["content_type"],
                expires_in_s=ttl,
                width=a.get("width"),
                height=a.get("height"),
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
        stage_costs=stage_costs(ctx, job_id),
        estimate=_estimate(ctx, board, spent, job) if board is not None else None,
        length_line=_length_line(s, board, brief) if board is not None and job["status"] == "draft" else None,
        questions=_questions(job),
        clips=[ClipView(**asdict(c)) for c in clip_texts(s, board, brief)] if board is not None else [],
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
        has_photo=bool(job.get("upload_key")),
        photo_note="" if job.get("upload_key") else NO_PHOTO_NOTE,
        storyboard=public_board(board) if board is not None else None,
        attempts=job["attempts"],
        last_error=job.get("last_error"),
        stages=stages,
        assets=assets,
        spend=Money(**money(spent, s.usd_to_eur_rate)),
        cost_cap=Money(usd=round(s.job_cost_cap_usd, 4), eur=s.job_cost_cap_eur),
        created_at=job["created_at"].isoformat(),
    )


def _length_line(s, board: Storyboard, brief: Brief) -> LengthLine | None:
    end_s = end_card_for(board.scenes, s.end_card_s)  # none extra when the story ends on its own card (D32)
    line = length_line([sc.duration_s for sc in board.scenes], brief.video_length_s, end_s)
    return LengthLine(**line) if line else None


def public_board(board: Storyboard) -> Storyboard:
    """Storage keys stay on the server: the browser only sees where each image comes from."""
    return board.model_copy(
        update={"scenes": [sc.model_copy(update={"image_upload_key": None}) for sc in board.scenes]}
    )


def _estimate(ctx: Context, board: Storyboard, spent_usd: float, job: dict) -> Estimate:
    s = ctx.settings
    rate = s.usd_to_eur_rate
    extend = _to_extend(ctx, board, job) if job["status"] == "draft" else frozenset()
    images, video = estimate_board_usd(s, board, job["brief"].get("voice", "marin"), extend)
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


def _to_extend(ctx: Context, board: Storyboard, job: dict) -> set[int]:
    """Scenes whose own picture is too far from the ad's shape to crop: the image model extends it."""
    if all(sc.image_source == "generate" for sc in board.scenes):
        return set()
    sizes = {
        a["storage_key"]: (a["width"], a["height"])
        for a in repo.list_assets(ctx.db, str(job["id"]))
        if a["kind"] == "upload" and a.get("width") and a.get("height")
    }
    return own_to_extend(board, job["brief"].get("aspect_ratio", "9:16"), job.get("upload_key"), sizes)


def merge_board(new: Storyboard, old: Storyboard, *, lock_images: bool, has_photo: bool = True) -> Storyboard:
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
        if sc.image_source == "product" and not has_photo:
            raise HTTPException(status_code=422, detail="This ad has no product photo: choose another picture.")
        scenes.append(sc)
    return with_structure(new.model_copy(update={"scenes": scenes}), old)


def with_structure(new: Storyboard, old: Storyboard | None) -> Storyboard:
    """The browser's storyboard with the stored structure and the user's edits to it (phase 4): an
    edited value becomes the user's; sources, swaps and who is in each shot stay the server's (a
    swap may only be undone). A key slot emptied on the page gets a plain guess back."""
    if old is None or not old.structure:
        return new.model_copy(update={"structure": None})
    stored = AdStructure.model_validate(old.structure)
    edits = AdStructure.model_validate(new.structure) if new.structure else None
    ad = merge_structure(stored, edits, old.scenes, new.scenes)
    fill_gaps(ad)
    return new.model_copy(update={"structure": ad.model_dump(mode="json")})


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
    long = scenes_too_long(s, board, Brief.model_validate(job["brief"]))
    if long:
        parts = ", ".join(f"scene {n} by {c:,} characters" for n, c in long)
        raise HTTPException(
            status_code=409,
            detail=f"The video AI reads at most 2,500 characters per clip, and the movement text is too long in "
            f'{parts}. Shorten it, or press "Shorten it for me".',
        )
    images, video = estimate_board_usd(s, board, job["brief"].get("voice", "marin"), _to_extend(ctx, board, job))
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
    photo: UploadFile | None = File(default=None, description="The product photo; optional (strategy plan A6)"),
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
    clean = None
    if photo is not None:
        raw = photo.file.read(s.max_upload_bytes + 1)
        try:
            clean = sanitise_image(raw, max_bytes=s.max_upload_bytes, max_side=s.max_image_side_px)
        except UploadRejected as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
    elif not parsed.description.strip():
        raise HTTPException(status_code=422, detail="With no photo, describe your product so the AI can show it.")

    campaign = _campaign_for(ctx, sess, parsed, campaign_id, campaign_name)
    brand = _brand_snapshot(ctx, sess) if use_brand_kit else None
    job_id = str(uuid.uuid4())
    key = f"jobs/{job_id}/upload.{clean.ext}" if clean else None
    if clean:
        ctx.storage.put(key, clean.data, clean.content_type)
    job = repo.create_job(
        ctx.db,
        job_id=job_id,
        session_hash=sess,
        brief=parsed.model_dump(mode="json"),
        upload_key=key,
        upload_sha256=clean.sha256 if clean else None,
        campaign_id=campaign,
        brand=brand,
    )
    if clean:
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
        prepare_storyboard(ctx, job, clean.data if clean else None, clean.content_type if clean else None)
    except BudgetExceeded as e:
        repo.set_job_error(ctx.db, job_id, e.message)
    except ProviderNotConfigured as e:
        log.error("provider not configured: %s", e)
        repo.set_job_error(ctx.db, job_id, "The AI provider is not configured on this server.")
    except Exception:  # noqa: BLE001 - the user sees a retryable message, details go to the log
        log.exception("storyboard failed for job %s", job_id)
        repo.set_job_error(ctx.db, job_id, "Writing the storyboard failed. Please try again.")
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.get("")
def list_jobs(sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> list[HistoryItem]:
    """History (M2 item 4): this browser's ads only, newest first (plan §15: no one else's)."""
    return [history_item(ctx, j) for j in repo.list_session_jobs(ctx.db, sess)]


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
    merged = merge_board(
        board, Storyboard.model_validate(job["storyboard"]), lock_images=False, has_photo=bool(job.get("upload_key"))
    )
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
    story: str = Field(min_length=20, max_length=STORY_MAX)


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


@router.post("/{job_id}/answers", dependencies=[Depends(require_access_code)])
def answer(job_id: str, body: AnswersIn, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> JobView:
    """The quick questions answered or skipped (D31 phase 5): the answers are locked into their slots
    and the storyboard is written (the writer's usual calls, a few cents)."""
    job = _own_job(ctx, job_id, sess)
    if job["status"] != "draft" or not job.get("pending"):
        raise HTTPException(status_code=409, detail="There are no questions waiting for this ad.")
    try:
        answer_questions(ctx, job, body.answers, skip=body.skip)
    except BudgetExceeded as e:
        raise HTTPException(status_code=409, detail=e.message) from None
    except Exception:  # noqa: BLE001 - details go to the log
        log.exception("writing the storyboard after the questions failed for job %s", job_id)
        raise HTTPException(status_code=502, detail="Writing the storyboard failed. Try again.") from None
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.put("/{job_id}/length")
def keep_length(
    job_id: str, body: LengthIn, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)
) -> JobView:
    """ "Keep 22 s" (plan v2.3): the picked length follows the scenes. Nothing else changes."""
    job = _own_job(ctx, job_id, sess)
    if job["status"] != "draft":
        raise HTTPException(status_code=409, detail="The length can be changed only before you approve.")
    brief = Brief.model_validate({**job["brief"], "video_length_s": body.video_length_s})
    repo.set_brief(ctx.db, job_id, brief.model_dump(mode="json"))
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.post("/{job_id}/scenes/add", dependencies=[Depends(require_access_code)])
def add_scenes(job_id: str, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> JobView:
    """ "Add scenes to reach 40 s" (plan v2.3): the writer adds scenes that fit the story (a cent or
    less); the page marks them as the AI's guess and offers Undo."""
    job = _own_job(ctx, job_id, sess)
    if job["status"] != "draft" or not job.get("storyboard"):
        raise HTTPException(status_code=409, detail="Scenes can be added only before you approve.")
    board = Storyboard.model_validate(job["storyboard"])
    if not _length_line(ctx.settings, board, Brief.model_validate(job["brief"])):
        raise HTTPException(status_code=409, detail="The scenes already make the length you picked.")
    try:
        add_scenes_to_board(ctx, job)
    except BudgetExceeded as e:
        raise HTTPException(status_code=409, detail=e.message) from None
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except Exception:  # noqa: BLE001 - details go to the log
        log.exception("adding scenes failed for job %s", job_id)
        raise HTTPException(status_code=502, detail="Adding scenes failed. Try again.") from None
    return job_view(ctx, repo.get_job(ctx.db, job_id))


@router.post("/{job_id}/clip-texts")
def preview_clips(
    job_id: str, board: Storyboard, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)
) -> list[ClipView]:
    """The exact text each clip would get for this (unsaved) storyboard. Free: nothing is called or saved."""
    job = _own_job(ctx, job_id, sess)
    brief = Brief.model_validate(job["brief"])
    stored = Storyboard.model_validate(job["storyboard"]) if job.get("storyboard") else None
    board = with_structure(board, stored)
    return [ClipView(**asdict(c)) for c in clip_texts(ctx.settings, board, brief)]


def _editable_text(job: dict) -> bool:
    """The movement text can change on the Storyboard step and on the Images step, before the video."""
    return job["status"] == "draft" or (job["status"] == "done" and job.get("phase") == "images")


@router.post("/{job_id}/scenes/{idx}/shorten", dependencies=[Depends(require_access_code)])
def shorten(
    job_id: str, idx: int, board: Storyboard, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)
) -> ShortenOut:
    """ "Shorten it for me": one cheap LLM call that returns a shorter movement text for this scene.
    Nothing is saved: the page shows it (with Undo) and saves it with the storyboard."""
    job = _own_job(ctx, job_id, sess)
    if not _editable_text(job):
        raise HTTPException(status_code=409, detail="The scenes are fixed once the video is being made.")
    if not 0 <= idx < min(len(board.scenes), ctx.settings.render_scenes):
        raise HTTPException(status_code=404, detail="No such scene.")
    board = with_structure(board, Storyboard.model_validate(job["storyboard"]) if job.get("storyboard") else None)
    try:
        text, field = shorten_scene(ctx, job, board, idx)
    except BudgetExceeded as e:
        raise HTTPException(status_code=409, detail=e.message) from None
    except Exception:  # noqa: BLE001 - details go to the log
        log.exception("shortening scene %s failed for job %s", idx, job_id)
        raise HTTPException(status_code=502, detail="Shortening failed. Try again, or shorten it yourself.") from None
    return ShortenOut(text=text, field=field)


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
    merged = (
        merge_board(board, old, lock_images=True, has_photo=bool(job.get("upload_key"))) if board is not None else old
    )
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
