"""The findings archive (owner's request, D31): every local test ad, kept with what went in, the
exact text each AI got and what came out, so we learn what each model can and cannot do.

Local only: it runs when `ARCHIVE_DIR` is set, which only the local Compose worker does (the
folder is `C:/dev/ugc-archive` by default, outside the repo). Cloud Run never sets it, so real
users' files are never kept here (PRIVACY.md). Written after every run of a job, finished or
failed; writing it can never fail the job. Notes the owner writes in `notes.md` are never
overwritten.

One folder per ad: `<date>_<time>_<title>_<id>/`
- input/: the brief, the brand kit, the product photo
- storyboard.json: the whole storyboard (scene text, prompts, starts and ends, notes)
- prompts/: the exact text each picture and clip got, and the negative prompt
- outputs/: every stored file (pictures, clips, voice, finished ads, cover, stills)
- frames/: the last frame before and the first frame after every cut, from the finished ad
- run.json: status, error, the stages with model and timing, and the cost per model
- notes.md: the owner's checklist (left alone once it exists)
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path

from .. import repository as repo
from ..models import Brief, Scene, Storyboard, render_seconds
from .compose import frame_at
from .image_gen import plan_scene_image
from .llm_trace import usd_to_eur
from .pipeline import Context, clip_texts, is_chained, job_seed
from .providers.media import InputImage
from .styles import VIDEO_NEGATIVE

log = logging.getLogger(__name__)
STAGE_FIELDS = ("stage", "scene_idx", "status", "provider", "model", "attempt", "output", "error")

NOTES = """\
# Notes on this ad

Fill in after watching. Each rule: yes / no / partly, and what you saw.

- Product the same as the photo (shape, colours, print, text):
- People the same in every scene (face, hair, clothes):
- No made-up text or logos in the picture:
- Each scene's action happened as written:
- No jump at the cuts (see frames/):
- Camera moves as written:
- Voice, captions and music:

What worked:

What did not:

Change for next time (prompt, rules, model):
"""

README = """\
# UGC Ad Builder: findings archive (local only)

One folder per test ad, written by the local worker after every run. See `notes.md` in each
folder for the checklist. Never commit or upload this folder: it holds photos and test outputs.
"""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "ad").lower()).strip("-")[:40] or "ad"


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def folder_for(root: Path, job: dict) -> Path:
    title = (job.get("storyboard") or {}).get("title") or (job.get("brief") or {}).get("product_name", "")
    stamp = job["created_at"].strftime("%Y-%m-%d_%H%M")
    return root / f"{stamp}_{_slug(title)}_{str(job['id'])[:8]}"


def _picture_prompts(ctx: Context, job: dict, brief: Brief, board: Storyboard) -> dict[int, str]:
    """The exact picture text for every generated (not chained, not own) scene, rebuilt with the
    same function and inputs the worker used."""
    s = ctx.settings
    product = InputImage(data=b"", content_type="image/jpeg")
    out = {}
    for i, sc in enumerate(board.scenes[: s.render_scenes]):
        if sc.image_source == "generate" and not is_chained(board, i, sc):
            out[i] = plan_scene_image(
                model=s.image_model,
                scene=sc,
                aspect_ratio=brief.aspect_ratio,
                seed=job_seed(str(job["id"])),
                product=product,
                product_sha256=job.get("upload_sha256") or "",
                style=brief.visual_style,
                notes=board.notes,
                keep_same=board.keep_same if board.continuity == "continuous" else None,
            ).request.arguments["prompt"]
    return out


def _write_prompts(ctx: Context, job: dict, brief: Brief, board: Storyboard, stages: list[dict], dst: Path) -> None:
    """The text each picture and clip got: as sent (kept with the stage since D31), or, for an ad
    made before that, rebuilt with today's code and marked as such."""
    dst.mkdir(parents=True, exist_ok=True)
    sent = {
        (r["stage"], r["scene_idx"]): (r.get("output") or {}).get("sent")
        for r in stages
        if r["stage"] in ("image", "video") and r["status"] == "done"
    }
    rebuilt = "# Rebuilt with today's code: this ad was made before the exact text was recorded, so it may differ.\n\n"
    pictures = _picture_prompts(ctx, job, brief, board)
    for i in range(len(board.scenes[: ctx.settings.render_scenes])):
        got = sent.get(("image", i))
        if got and got.get("prompt"):
            (dst / f"picture_{i + 1}.txt").write_text(got["prompt"], encoding="utf-8")
        elif i in pictures:
            (dst / f"picture_{i + 1}.txt").write_text(rebuilt + pictures[i], encoding="utf-8")
    negative = VIDEO_NEGATIVE
    for i, clip in enumerate(clip_texts(ctx.settings, board, brief)):
        sc = board.scenes[i]
        head = f"# scene {i + 1}: {sc.duration_s} s on screen, {render_seconds(sc.duration_s)} s clip"
        got = sent.get(("video", i))
        if got and got.get("prompt"):
            text, note = got["prompt"], "as sent"
            negative = got.get("negative_prompt", negative)
        else:
            text, note = clip.text, "rebuilt with today's code: it may differ from what was sent"
        head += f", {len(text)} of {clip.limit} characters ({note})\n\n"
        (dst / f"clip_{i + 1}.txt").write_text(head + text, encoding="utf-8")
    (dst / "negative.txt").write_text(negative, encoding="utf-8")


def _cut_frames(ctx: Context, job_id: str, master_ratio: str, dst: Path) -> None:
    """The frame just before and just after every cut, from the finished ad in the main shape."""
    variant = next((v for v in repo.list_variants(ctx.db, job_id) if v.get("label") == "A"), None)
    timeline = ((variant or {}).get("output") or {}).get("timeline") or []
    tag = master_ratio.replace(":", "x")
    ad = next((a for a in repo.list_assets(ctx.db, job_id) if a["storage_key"].endswith(f"/ad_{tag}.mp4")), None)
    if ad is None or len(timeline) < 2:
        return
    with tempfile.TemporaryDirectory(prefix="archive-") as tmp:
        video = Path(tmp) / "ad.mp4"
        video.write_bytes(ctx.storage.get(ad["storage_key"]))
        for n, t in enumerate(timeline[:-1], start=1):
            cut = float(t["start"]) + float(t["duration"])
            for side, at in (("before", cut - 0.06), ("after", cut + 0.06)):
                img = frame_at(video, max(0.0, at), Path(tmp) / f"f{n}{side}.png")
                dst.mkdir(parents=True, exist_ok=True)
                img.save(dst / f"cut_{n}_{side}.jpg", "JPEG", quality=92)


def archive_job(ctx: Context, job_id: str) -> Path | None:
    """Write (or refresh) this job's folder in the archive. Never raises."""
    root = ctx.settings.archive_dir
    if not root:
        return None
    try:
        return _write(ctx, job_id, Path(root))
    except Exception:  # noqa: BLE001 - the archive is a record, never a reason to fail an ad
        log.exception("could not archive job %s", job_id)
        return None


def _write(ctx: Context, job_id: str, root: Path) -> Path:
    job = repo.get_job(ctx.db, job_id)
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "README.md").exists():
        (root / "README.md").write_text(README, encoding="utf-8")
    out = folder_for(root, job)
    out.mkdir(parents=True, exist_ok=True)
    brief = Brief.model_validate(job["brief"])

    _dump(out / "input" / "brief.json", job["brief"])
    if job.get("brand"):
        _dump(out / "input" / "brand.json", job["brand"])
    if job.get("upload_key"):
        ext = job["upload_key"].rsplit(".", 1)[-1]
        (out / "input" / f"photo.{ext}").write_bytes(ctx.storage.get(job["upload_key"]))

    stages = repo.list_stage_runs(ctx.db, job_id)
    if job.get("storyboard"):
        board = Storyboard.model_validate(job["storyboard"])
        rows = repo.list_scenes(ctx.db, job_id)
        if rows:  # the scenes as edited after approval (spoken lines, movement, lengths)
            board = board.model_copy(update={"scenes": [Scene.model_validate(r["data"]) for r in rows]})
        _dump(out / "storyboard.json", board.model_dump(mode="json"))
        _write_prompts(ctx, job, brief, board, stages, out / "prompts")

    outputs = out / "outputs"
    prefix = f"jobs/{job_id}/"
    for asset in repo.list_assets(ctx.db, job_id):
        key = asset["storage_key"]
        dst = outputs / (key[len(prefix) :] if key.startswith(prefix) else key.rsplit("/", 1)[-1]).replace("/", "_")
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(ctx.storage.get(asset["storage_key"]))
    _cut_frames(ctx, job_id, brief.aspect_ratio, out / "frames")

    rate = ctx.settings.usd_to_eur_rate
    costs = [
        {**c, "usd": float(c["usd"]), "eur": usd_to_eur(float(c["usd"]), rate)} for c in repo.job_costs(ctx.db, job_id)
    ]
    _dump(
        out / "run.json",
        {
            "job_id": job_id,
            "status": job["status"],
            "phase": job.get("phase"),
            "error": job.get("last_error"),
            "created_at": job["created_at"],
            "models_used": {
                st: sorted({f"{r['provider']}: {r['model']}" for r in stages if r["stage"] == st})
                for st in dict.fromkeys(r["stage"] for r in stages)
            },
            "cost_eur": round(sum(c["eur"] for c in costs), 4),
            "costs": costs,
            "stages": [{k: r.get(k) for k in STAGE_FIELDS} for r in repo.list_stage_runs(ctx.db, job_id)],
        },
    )
    if not (out / "notes.md").exists():
        (out / "notes.md").write_text(NOTES, encoding="utf-8")
    return out
