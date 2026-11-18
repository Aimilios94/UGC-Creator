"""Jobs: brief + photo -> storyboard (draft) -> approve -> render -> result.

Every route is scoped to the browser session: another session gets 404, the same
answer as for a job that does not exist. Generation (create, approve, try again)
needs the access code on the public deployment.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from .. import repository as repo
from ..deps import get_ctx, require_access_code, session_hash
from ..errors import BudgetExceeded, ProviderNotConfigured, UploadRejected
from ..models import AssetView, Brief, JobView, Money, ProductAnalysis, StageView, Storyboard
from ..services import job_trigger
from ..services.llm_trace import money
from ..services.pipeline import Context, prepare_storyboard
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
        if a["kind"] in ("image", "video"):
            try:
                idx = int(a["storage_key"].split("/scene-")[1].split("/")[0])
            except (IndexError, ValueError):
                idx = None
        assets.append(
            AssetView(
                kind=a["kind"],
                scene_idx=idx,
                url=ctx.storage.signed_url(a["storage_key"], ttl),
                content_type=a["content_type"],
                expires_in_s=ttl,
            )
        )
    return JobView(
        id=job_id,
        status=job["status"],
        brief=Brief.model_validate(job["brief"]),
        analysis=ProductAnalysis.model_validate(job["analysis"]) if job.get("analysis") else None,
        storyboard=Storyboard.model_validate(job["storyboard"]) if job.get("storyboard") else None,
        attempts=job["attempts"],
        last_error=job.get("last_error"),
        stages=stages,
        assets=assets,
        spend=Money(**money(repo.job_spend_usd(ctx.db, job_id), s.usd_to_eur_rate)),
        cost_cap=Money(usd=round(s.job_cost_cap_usd, 4), eur=s.job_cost_cap_eur),
        created_at=job["created_at"].isoformat(),
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


@router.post("", status_code=201, dependencies=[Depends(require_access_code)])
def create_job(
    brief: str = Form(..., description="Brief as JSON"),
    photo: UploadFile = File(...),
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
    if not repo.set_storyboard(ctx.db, str(job["id"]), board.model_dump(mode="json")):
        raise HTTPException(status_code=409, detail="The storyboard is locked once approved.")
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
def approve(job_id: str, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> JobView:
    """Idempotent: a double-click or retry changes nothing after the first approval."""
    _own_job(ctx, job_id, sess)
    job, _ = repo.approve_job(ctx.db, job_id, sess)
    if job["status"] == "draft":
        raise HTTPException(status_code=409, detail="There is no storyboard to approve yet.")
    if job["status"] == "queued":
        _start_worker(ctx)  # also on a repeat click: an extra execution finds nothing and exits 0
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
