"""The scheduled cleanup and "delete my data" (plan §8 and §11, M2 item 6, D6, D34).

`run_cleanup` is what the GitHub Actions cron calls every 15 minutes through `POST /admin/cleanup`:
1. the stale-job sweep: a job killed mid-run is queued again (and a worker started) or failed;
2. retention: ads older than RETENTION_DAYS are deleted with their files;
3. brand kits, logos and campaigns with no use for RETENTION_DAYS are deleted.

`delete_my_data` removes everything of one browser session at once, but waits while one of its
ads is being made, so a paid render is never thrown away halfway (D34).

Database rows go first and files after: a job approved meanwhile keeps its files, and a file
left behind by an error is caught by the next run (and by the bucket's 30-day rule under jobs/).
"""

from __future__ import annotations

import logging

from .. import repository as repo
from .job_trigger import trigger_worker
from .pipeline import Context

log = logging.getLogger(__name__)


def _delete_files(ctx: Context, prefixes: list[str]) -> int:
    n = 0
    for prefix in prefixes:
        try:
            n += ctx.storage.delete_prefix(prefix)
        except Exception:  # noqa: BLE001 - one folder must not stop the rest; logged and retried next run
            log.exception("could not delete the files under %s", prefix.split("/")[0])
    return n


def run_cleanup(ctx: Context) -> dict:
    s = ctx.settings
    swept = repo.sweep_stale_jobs(ctx.db, stale_minutes=s.stale_job_minutes, max_attempts=s.max_job_attempts)
    if swept["requeued"]:
        try:
            trigger_worker(s)
        except Exception:  # noqa: BLE001 - the jobs stay queued; the next run or approval starts a worker
            log.exception("could not start a worker for %d requeued job(s)", len(swept["requeued"]))

    jobs = repo.delete_jobs(ctx.db, repo.expired_job_ids(ctx.db, s.retention_days))
    files = _delete_files(ctx, [f"jobs/{j}/" for j in jobs])

    kits, campaigns = repo.unused_brand_data(ctx.db, s.retention_days)
    hashes = [k["session_hash"] for k in kits]
    files += _delete_files(ctx, [f"brand/{h}/" for h in hashes])
    n_kits = repo.delete_brand_kits(ctx.db, hashes)
    n_campaigns = repo.delete_campaigns(ctx.db, campaigns)

    out = {
        "requeued": len(swept["requeued"]),
        "failed": len(swept["failed"]),
        "jobs_deleted": len(jobs),
        "brand_kits_deleted": n_kits,
        "campaigns_deleted": n_campaigns,
        "files_deleted": files,
    }
    log.info("cleanup: %s", out)
    return out


class SessionBusy(Exception):
    """One of the session's ads is queued or being made."""


def delete_my_data(ctx: Context, session_hash: str) -> dict:
    if repo.session_busy(ctx.db, session_hash):
        raise SessionBusy
    jobs = repo.delete_session_jobs(ctx.db, session_hash)
    kits, campaigns = repo.delete_session_brand(ctx.db, session_hash)
    files = _delete_files(ctx, [f"jobs/{j}/" for j in jobs] + [f"brand/{session_hash}/"])
    busy = repo.session_busy(ctx.db, session_hash)  # an ad approved while this ran is kept
    return {
        "jobs_deleted": len(jobs),
        "brand_kits_deleted": kits,
        "campaigns_deleted": campaigns,
        "files_deleted": files,
        "kept_busy": busy,
    }
