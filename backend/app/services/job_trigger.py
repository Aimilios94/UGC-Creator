"""Start the worker after Approve.

local: the Compose worker polls the queue, so there is nothing to start.
cloudrun: start one Cloud Run Job execution with no overrides. The execution claims a
queued job itself; a second execution just claims another job or finds none and exits 0.
The API's service account holds roles/run.jobsExecutor on this job only (DECISIONS.md).
"""

from __future__ import annotations

import logging

import httpx

from ..config import Settings

log = logging.getLogger(__name__)


def trigger_worker(settings: Settings, *, http: httpx.Client | None = None, token: str | None = None) -> None:
    if settings.job_runner == "local":
        return
    if settings.job_runner != "cloudrun":
        raise RuntimeError(f"unknown JOB_RUNNER {settings.job_runner!r}")
    if not settings.cloud_run_job_name:
        raise RuntimeError("CLOUD_RUN_JOB_NAME is not set")
    if token is None:
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        token = creds.token
    url = (
        f"https://run.googleapis.com/v2/projects/{settings.gcp_project_id}/locations/{settings.gcp_region}"
        f"/jobs/{settings.cloud_run_job_name}:run"
    )
    client = http or httpx.Client(timeout=30)
    r = client.post(url, headers={"Authorization": f"Bearer {token}"}, json={})  # no overrides, ever
    r.raise_for_status()
    log.info("started a worker execution")
