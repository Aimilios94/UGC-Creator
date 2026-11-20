"""SQL access (plain SQL over psycopg 3). Routers and the worker call these; services stay DB-free.

Connections: Neon scales to zero, so the first connection after idle can fail or be
slow. `Database.connect` retries with backoff and a generous connect timeout. One
short connection per unit of work; no transaction is held open while a job runs
(Neon closes idle connections). Prepared statements are off for Neon's pooler.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .errors import BudgetExceeded

log = logging.getLogger(__name__)

SPEND_LOCK_KEY = 7_301_001  # pg_advisory_xact_lock key serialising spend reservations


class Database:
    def __init__(
        self,
        url: str,
        *,
        connect_timeout_s: int = 20,
        retries: int = 5,
        connect_fn: Callable[..., psycopg.Connection] = psycopg.connect,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not url:
            raise RuntimeError("DATABASE_URL is not set")
        self.url = url
        self.connect_timeout_s = connect_timeout_s
        self.retries = max(1, retries)
        self._connect_fn = connect_fn
        self._sleep = sleep

    def connect(self) -> psycopg.Connection:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                return self._connect_fn(
                    self.url,
                    connect_timeout=self.connect_timeout_s,
                    row_factory=dict_row,
                    prepare_threshold=None,
                )
            except psycopg.OperationalError as e:
                last = e
                wait = min(0.5 * 2**attempt, 8.0)
                log.warning(
                    "database connect failed (attempt %d/%d), retrying in %.1fs", attempt + 1, self.retries, wait
                )
                if attempt + 1 < self.retries:
                    self._sleep(wait)
        raise last  # type: ignore[misc]

    @contextmanager
    def tx(self) -> Iterator[psycopg.Connection]:
        """One short transaction: commit on success, roll back on error, always close."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _one(conn: psycopg.Connection, sql: str, params: Any = None) -> dict | None:
    return conn.execute(sql, params).fetchone()


def _all(conn: psycopg.Connection, sql: str, params: Any = None) -> list[dict]:
    return conn.execute(sql, params).fetchall()


# --- jobs ---------------------------------------------------------------------
def create_job(
    db: Database,
    *,
    job_id: str,
    session_hash: str,
    brief: dict,
    upload_key: str,
    upload_sha256: str,
    campaign_id: str | None = None,
    brand: dict | None = None,
) -> dict:
    with db.tx() as c:
        return _one(
            c,
            """insert into jobs (id, session_hash, brief, upload_key, upload_sha256, campaign_id, brand)
               values (%s, %s, %s, %s, %s, %s, %s) returning *""",
            (
                job_id,
                session_hash,
                Jsonb(brief),
                upload_key,
                upload_sha256,
                campaign_id,
                Jsonb(brand) if brand is not None else None,
            ),
        )


def set_job_error(db: Database, job_id: str, error: str | None) -> None:
    with db.tx() as c:
        c.execute("update jobs set last_error = %s, updated_at = now() where id = %s", (error, job_id))


def get_job(db: Database, job_id: str) -> dict | None:
    with db.tx() as c:
        return _one(c, "select * from jobs where id = %s", (job_id,))


def get_job_for_session(db: Database, job_id: str, session_hash: str) -> dict | None:
    """A job is reachable only from the browser session that created it."""
    with db.tx() as c:
        return _one(c, "select * from jobs where id = %s and session_hash = %s", (job_id, session_hash))


def set_analysis(db: Database, job_id: str, analysis: dict) -> None:
    with db.tx() as c:
        c.execute("update jobs set analysis = %s, updated_at = now() where id = %s", (Jsonb(analysis), job_id))


def set_brief(db: Database, job_id: str, brief: dict) -> bool:
    """The brief changes only while the job is a draft (for example the user's own story)."""
    with db.tx() as c:
        row = _one(
            c,
            "update jobs set brief = %s, updated_at = now() where id = %s and status = 'draft' returning id",
            (Jsonb(brief), job_id),
        )
        return row is not None


def set_storyboard(db: Database, job_id: str, storyboard: dict) -> bool:
    """Storyboards are editable only while the job is a draft."""
    with db.tx() as c:
        row = _one(
            c,
            """update jobs set storyboard = %s, updated_at = now()
               where id = %s and status = 'draft' returning id""",
            (Jsonb(storyboard), job_id),
        )
        return row is not None


def approve_job(db: Database, job_id: str, session_hash: str, phase: str = "images") -> tuple[dict | None, bool]:
    """Flip draft -> queued once and freeze the scenes. Returns (job, transitioned).

    A double-click or client retry finds the job no longer a draft and changes
    nothing, so one approved storyboard is one paid job (enqueue idempotency).
    """
    with db.tx() as c:
        row = _one(
            c,
            """update jobs set status = 'queued', phase = %s, approved_at = now(), updated_at = now()
               where id = %s and session_hash = %s and status = 'draft' and storyboard is not null
               returning *""",
            (phase, job_id, session_hash),
        )
        if row is None:
            return _one(c, "select * from jobs where id = %s and session_hash = %s", (job_id, session_hash)), False
        for idx, scene in enumerate(row["storyboard"]["scenes"]):
            c.execute(
                """insert into scenes (job_id, idx, role, data) values (%s, %s, %s, %s)
                   on conflict (job_id, idx) do nothing""",
                (job_id, idx, scene["role"], Jsonb(scene)),
            )
        # Variant A uses the hook the user picked (or the first); B and C come from Hook Lab (M3).
        c.execute(
            """insert into variants (job_id, label, hook_idx) values (%s, 'A', %s)
               on conflict (job_id, label) do nothing""",
            (job_id, row["storyboard"].get("hook_choice") or 0),
        )
        return row, True


def start_video(db: Database, job_id: str, session_hash: str, storyboard: dict) -> tuple[dict | None, bool]:
    """Step 2: a job whose images are done is queued again to make the video, once.

    The storyboard's video fields (voiceover, text, motion, clip length) may have been edited
    after the images; the scenes are refreshed from it. A repeat finds the job no longer in
    the images phase and changes nothing. Attempts restart; spend so far still counts.
    """
    with db.tx() as c:
        row = _one(
            c,
            """update jobs set status = 'queued', phase = 'video', storyboard = %s, attempts = 0,
                      last_error = null, finished_at = null, approved_at = now(), updated_at = now()
               where id = %s and session_hash = %s and status = 'done' and phase = 'images'
               returning *""",
            (Jsonb(storyboard), job_id, session_hash),
        )
        if row is None:
            return _one(c, "select * from jobs where id = %s and session_hash = %s", (job_id, session_hash)), False
        for idx, scene in enumerate(storyboard["scenes"]):
            c.execute("update scenes set data = %s where job_id = %s and idx = %s", (Jsonb(scene), job_id, idx))
        return row, True


def retry_job(db: Database, job_id: str, session_hash: str) -> tuple[dict | None, bool]:
    """User "try again": failed -> queued with attempts reset. Spend is never reset."""
    with db.tx() as c:
        row = _one(
            c,
            """update jobs set status = 'queued', attempts = 0, last_error = null,
                      finished_at = null, approved_at = now(), updated_at = now()
               where id = %s and session_hash = %s and status = 'failed' returning *""",
            (job_id, session_hash),
        )
        if row is None:
            return _one(c, "select * from jobs where id = %s and session_hash = %s", (job_id, session_hash)), False
        _set_variants(c, job_id, "queued", only="failed")
        return row, True


def claim_next_job(db: Database, max_attempts: int) -> dict | None:
    """Claim the oldest queued job: a short committed UPDATE, nothing held open."""
    with db.tx() as c:
        return _one(
            c,
            """update jobs set status = 'running', claimed_at = now(), attempts = attempts + 1, updated_at = now()
               where id = (
                 select id from jobs
                 where status = 'queued' and attempts < %s
                 order by approved_at nulls last, created_at
                 for update skip locked
                 limit 1)
               returning *""",
            (max_attempts,),
        )


def _set_variants(c: psycopg.Connection, job_id: str, status: str, *, only: str = "queued") -> None:
    c.execute(
        "update variants set status = %s, updated_at = now() where job_id = %s and status = %s",
        (status, job_id, only),
    )


def finish_job(db: Database, job_id: str) -> None:
    with db.tx() as c:
        row = _one(
            c,
            """update jobs set status = 'done', finished_at = now(), last_error = null, updated_at = now()
               where id = %s and status = 'running' returning phase""",
            (job_id,),
        )
        if row and row["phase"] == "video":
            _set_variants(c, job_id, "done")


def fail_job(db: Database, job_id: str, error: str) -> None:
    """Terminal failure (for example a budget refusal): no automatic retry."""
    with db.tx() as c:
        row = _one(
            c,
            """update jobs set status = 'failed', last_error = %s, finished_at = now(), updated_at = now()
               where id = %s and status in ('running', 'queued') returning id""",
            (error[:1000], job_id),
        )
        if row:
            _set_variants(c, job_id, "failed")


def handle_job_failure(db: Database, job_id: str, error: str, max_attempts: int) -> str:
    """Exception handler: requeue while attempts remain, else fail. Returns the new status."""
    with db.tx() as c:
        row = _one(
            c,
            """update jobs set
                 status = case when attempts >= %(max)s then 'failed' else 'queued' end,
                 finished_at = case when attempts >= %(max)s then now() else null end,
                 last_error = %(err)s, updated_at = now()
               where id = %(id)s and status = 'running'
               returning status""",
            {"max": max_attempts, "err": error[:1000], "id": job_id},
        )
        if row and row["status"] == "failed":
            _set_variants(c, job_id, "failed")
        return row["status"] if row else "unknown"


def set_variant_output(db: Database, job_id: str, label: str, output: dict) -> None:
    with db.tx() as c:
        c.execute(
            "update variants set output = %s, updated_at = now() where job_id = %s and label = %s",
            (Jsonb(output), job_id, label),
        )


def list_variants(db: Database, job_id: str) -> list[dict]:
    with db.tx() as c:
        return _all(c, "select * from variants where job_id = %s order by label", (job_id,))


# --- campaigns (private to the browser session) -------------------------------------
def create_campaign(
    db: Database,
    *,
    session_hash: str,
    name: str,
    goal: str | None,
    audience: str,
    offer: str,
    landing_url: str | None,
) -> dict:
    with db.tx() as c:
        return _one(
            c,
            """insert into campaigns (session_hash, name, goal, audience, offer, landing_url)
               values (%s, %s, %s, %s, %s, %s) returning *""",
            (session_hash, name, goal, audience, offer, landing_url),
        )


def get_campaign_for_session(db: Database, campaign_id: str, session_hash: str) -> dict | None:
    with db.tx() as c:
        return _one(c, "select * from campaigns where id = %s and session_hash = %s", (campaign_id, session_hash))


def list_campaigns(db: Database, session_hash: str) -> list[dict]:
    with db.tx() as c:
        return _all(
            c,
            """select c.*, (select count(*) from jobs j where j.campaign_id = c.id) as ads
               from campaigns c where c.session_hash = %s order by c.created_at desc""",
            (session_hash,),
        )


# --- brand kit (one per browser session) -----------------------------------------
def get_brand_kit(db: Database, session_hash: str) -> dict | None:
    with db.tx() as c:
        return _one(c, "select * from brand_kits where session_hash = %s", (session_hash,))


def save_brand_kit(db: Database, session_hash: str, *, tone: str | None, colors: dict, font: str | None) -> dict:
    with db.tx() as c:
        return _one(
            c,
            """insert into brand_kits (session_hash, tone, colors, font) values (%s, %s, %s, %s)
               on conflict (session_hash) do update
                 set tone = excluded.tone, colors = excluded.colors, font = excluded.font, updated_at = now()
               returning *""",
            (session_hash, tone, Jsonb(colors), font),
        )


def set_brand_logo(db: Database, session_hash: str, logo_key: str) -> dict:
    with db.tx() as c:
        return _one(
            c,
            """insert into brand_kits (session_hash, logo_key) values (%s, %s)
               on conflict (session_hash) do update set logo_key = excluded.logo_key, updated_at = now()
               returning *""",
            (session_hash, logo_key),
        )


# --- scenes, stages, assets -----------------------------------------------------
def list_scenes(db: Database, job_id: str) -> list[dict]:
    with db.tx() as c:
        return _all(c, "select * from scenes where job_id = %s order by idx", (job_id,))


def set_scene_asset(db: Database, job_id: str, idx: int, kind: str, asset_id: str) -> None:
    column = {"image": "image_asset_id", "video": "video_asset_id"}[kind]
    with db.tx() as c:
        c.execute(f"update scenes set {column} = %s where job_id = %s and idx = %s", (asset_id, job_id, idx))


def get_stage_run(db: Database, job_id: str, stage: str, scene_idx: int = -1) -> dict | None:
    with db.tx() as c:
        return _one(
            c,
            "select * from stage_runs where job_id = %s and stage = %s and scene_idx = %s",
            (job_id, stage, scene_idx),
        )


def start_stage(
    db: Database, job_id: str, stage: str, scene_idx: int, *, provider: str, model: str, attempt: int
) -> dict:
    """Create the stage row, or reset one that never got a prediction ID."""
    with db.tx() as c:
        return _one(
            c,
            """insert into stage_runs (job_id, stage, scene_idx, status, provider, model, attempt)
               values (%s, %s, %s, 'running', %s, %s, %s)
               on conflict (job_id, stage, scene_idx) do update
                 set status = 'running', provider = excluded.provider, model = excluded.model,
                     attempt = excluded.attempt, prediction_id = null, error = null,
                     started_at = now(), finished_at = null
               returning *""",
            (job_id, stage, scene_idx, provider, model, attempt),
        )


def mark_submitted(db: Database, stage_run_id: str, prediction_id: str) -> None:
    with db.tx() as c:
        c.execute(
            "update stage_runs set status = 'submitted', prediction_id = %s where id = %s",
            (prediction_id, stage_run_id),
        )


def stage_done(db: Database, stage_run_id: str, output: dict) -> None:
    with db.tx() as c:
        c.execute(
            "update stage_runs set status = 'done', output = %s, error = null, finished_at = now() where id = %s",
            (Jsonb(output), stage_run_id),
        )


def stage_failed(db: Database, stage_run_id: str, error: str) -> None:
    with db.tx() as c:
        c.execute(
            "update stage_runs set status = 'failed', error = %s, finished_at = now() where id = %s",
            (error[:1000], stage_run_id),
        )


def list_stage_runs(db: Database, job_id: str) -> list[dict]:
    with db.tx() as c:
        return _all(c, "select * from stage_runs where job_id = %s order by started_at", (job_id,))


def add_asset(
    db: Database,
    *,
    job_id: str | None,
    kind: str,
    storage_key: str,
    content_type: str,
    size: int,
    sha256: str,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    with db.tx() as c:
        return _one(
            c,
            """insert into assets (job_id, kind, storage_key, content_type, bytes, sha256, width, height)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (storage_key) do update set content_type = excluded.content_type
               returning *""",
            (job_id, kind, storage_key, content_type, size, sha256, width, height),
        )


def get_asset(db: Database, asset_id: str) -> dict | None:
    with db.tx() as c:
        return _one(c, "select * from assets where id = %s", (asset_id,))


def list_assets(db: Database, job_id: str) -> list[dict]:
    with db.tx() as c:
        return _all(c, "select * from assets where job_id = %s order by created_at", (job_id,))


# --- media cache --------------------------------------------------------------
def cache_get(db: Database, cache_key: str) -> dict | None:
    with db.tx() as c:
        return _one(c, "select * from media_cache where cache_key = %s", (cache_key,))


def cache_put(
    db: Database,
    *,
    cache_key: str,
    kind: str,
    model: str,
    storage_key: str,
    content_type: str,
    cost_usd: float,
    meta: dict,
) -> None:
    with db.tx() as c:
        c.execute(
            """insert into media_cache (cache_key, kind, model, storage_key, content_type, cost_usd, meta)
               values (%s, %s, %s, %s, %s, %s, %s) on conflict (cache_key) do nothing""",
            (cache_key, kind, model, storage_key, content_type, cost_usd, Jsonb(meta)),
        )


# --- spend: reservations, billing, limits --------------------------------------
_SPENT = "coalesce(sum(coalesce(cost_usd, est_cost_usd)), 0)"
_LIVE = "status in ('reserved', 'billed')"
_TODAY = "created_at >= (date_trunc('day', now() at time zone 'utc') at time zone 'utc')"


def job_spend_usd(db: Database, job_id: str) -> float:
    with db.tx() as c:
        return float(_one(c, f"select {_SPENT} as s from llm_calls where {_LIVE} and job_id = %s", (job_id,))["s"])


def day_spend_usd(db: Database) -> float:
    with db.tx() as c:
        return float(_one(c, f"select {_SPENT} as s from llm_calls where {_LIVE} and {_TODAY}")["s"])


def reserve_spend(
    db: Database,
    *,
    job_id: str,
    stage_run_id: str | None,
    kind: str,
    provider: str,
    model: str,
    est_usd: float,
    job_cap_usd: float,
    daily_limit_usd: float,
    cap_label: str = "",
    limit_label: str = "",
) -> str:
    """Check the cap and the daily limit and record the estimate, atomically.

    The advisory lock serialises every reservation, so two stages running at once
    each see the other's in-flight estimate and cannot both slip under a limit.
    Spend so far counts every try of the job (a "try again" never resets it).
    """
    with db.tx() as c:
        c.execute("select pg_advisory_xact_lock(%s)", (SPEND_LOCK_KEY,))
        job_spent = float(_one(c, f"select {_SPENT} as s from llm_calls where {_LIVE} and job_id = %s", (job_id,))["s"])
        if job_spent + est_usd > job_cap_usd + 1e-9:
            raise BudgetExceeded(
                "job_cap",
                f"This step would pass the job's cost cap{cap_label}. Nothing was charged for it.",
            )
        day_spent = float(_one(c, f"select {_SPENT} as s from llm_calls where {_LIVE} and {_TODAY}")["s"])
        if day_spent + est_usd > daily_limit_usd + 1e-9:
            raise BudgetExceeded(
                "daily_limit",
                f"The app's daily spend limit{limit_label} is reached. Try again tomorrow.",
            )
        row = _one(
            c,
            """insert into llm_calls (job_id, stage_run_id, kind, provider, model, status, est_cost_usd)
               values (%s, %s, %s, %s, %s, 'reserved', %s) returning id""",
            (job_id, stage_run_id, kind, provider, model, est_usd),
        )
        return str(row["id"])


def bill(db: Database, reservation_id: str, *, cost_usd: float, usage: dict, latency_ms: int) -> None:
    with db.tx() as c:
        c.execute(
            """update llm_calls set status = 'billed', cost_usd = %s, usage = %s, latency_ms = %s
               where id = %s""",
            (cost_usd, Jsonb(usage), latency_ms, reservation_id),
        )


def release(db: Database, reservation_id: str, error: str | None = None) -> None:
    """Nothing was spent (the call never reached the provider)."""
    with db.tx() as c:
        c.execute(
            "update llm_calls set status = 'released', cost_usd = 0, error = %s where id = %s and status = 'reserved'",
            (error[:500] if error else None, reservation_id),
        )


def open_reservation(db: Database, stage_run_id: str) -> str | None:
    with db.tx() as c:
        row = _one(
            c,
            "select id from llm_calls where stage_run_id = %s and status = 'reserved' order by created_at desc limit 1",
            (stage_run_id,),
        )
        return str(row["id"]) if row else None


def record_cache_hit(db: Database, *, job_id: str, stage_run_id: str, kind: str, provider: str, model: str) -> None:
    with db.tx() as c:
        c.execute(
            """insert into llm_calls
                 (job_id, stage_run_id, kind, provider, model, status, est_cost_usd, cost_usd, cache_hit)
               values (%s, %s, %s, %s, %s, 'billed', 0, 0, true)""",
            (job_id, stage_run_id, kind, provider, model),
        )
