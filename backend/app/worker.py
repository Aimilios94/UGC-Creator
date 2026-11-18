"""Worker entrypoint. The same code runs as the Cloud Run Job and as the Compose worker.

    python -m app.worker          # Cloud Run Job: drain the queue, then exit 0
    python -m app.worker --loop   # Compose: poll forever

An execution that finds the queue empty exits with code 0, so a spurious trigger is
not a failure. A job that raises is requeued while it has attempts left (max 2),
otherwise marked failed with its error stored; a budget refusal fails it at once.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from . import repository as repo
from .config import Settings, get_settings
from .errors import BudgetExceeded
from .repository import Database
from .services.pipeline import Context, run_job
from .services.providers.media import build_media
from .services.providers.storage import build_storage

log = logging.getLogger("worker")


def build_context(settings: Settings) -> Context:
    db = Database(
        settings.database_url, connect_timeout_s=settings.db_connect_timeout_s, retries=settings.db_connect_retries
    )
    return Context(settings=settings, db=db, storage=build_storage(settings), media=build_media(settings))


def run_once(ctx: Context) -> bool:
    """Claim and run one job. False when the queue is empty."""
    s = ctx.settings
    job = repo.claim_next_job(ctx.db, s.max_job_attempts)
    if job is None:
        return False
    job_id = str(job["id"])
    log.info("claimed job %s (attempt %s)", job_id, job["attempts"])
    try:
        run_job(ctx, job)
        log.info("job %s done", job_id)
    except BudgetExceeded as e:
        repo.fail_job(ctx.db, job_id, e.message)
        log.warning("job %s stopped by a spend limit (%s)", job_id, e.reason)
    except Exception as e:  # noqa: BLE001 - the handler decides retry or fail
        status = repo.handle_job_failure(ctx.db, job_id, f"{type(e).__name__}: {e}", s.max_job_attempts)
        log.exception("job %s raised; now %s", job_id, status)
    return True


def drain(ctx: Context) -> int:
    n = 0
    while run_once(ctx):
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UGC Ad Builder worker")
    parser.add_argument("--loop", action="store_true", help="poll forever (Compose worker)")
    args = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ctx = build_context(settings)
    if not args.loop:
        n = drain(ctx)
        log.info("queue empty after %d job(s); exiting", n)
        return 0
    while True:
        if not run_once(ctx):
            time.sleep(settings.worker_poll_interval_s)


if __name__ == "__main__":
    sys.exit(main())
