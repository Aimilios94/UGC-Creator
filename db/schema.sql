-- ============================================================================
-- UGC Ad Builder v2 schema (Postgres 16+ with pgvector).
-- One idempotent file, applied by backend/scripts/apply_schema.py. No migration
-- tool: each table is added here when its feature is built (plan §12).
-- M1 tables: jobs, scenes, stage_runs, assets, media_cache, llm_calls.
-- ============================================================================

create extension if not exists vector;  -- used from M6 (doc_chunks); created now to prove it works

-- jobs -----------------------------------------------------------------------
-- One row per brief. 'draft' holds the storyboard until the user approves it;
-- Approve flips draft -> queued exactly once (enqueue idempotency). The queue is
-- this table: workers claim the oldest queued row with FOR UPDATE SKIP LOCKED.
create table if not exists jobs (
  id             uuid primary key default gen_random_uuid(),
  session_hash   text not null,                 -- sha256 of the creating browser session
  status         text not null default 'draft'
                 check (status in ('draft', 'queued', 'running', 'done', 'failed')),
  brief          jsonb not null,
  analysis       jsonb,                         -- ProductAnalysis
  storyboard     jsonb,                         -- Storyboard, editable while draft
  upload_key     text not null,                 -- storage key of the sanitised product photo
  upload_sha256  text not null,
  attempts       int not null default 0,
  last_error     text,
  approved_at    timestamptz,
  claimed_at     timestamptz,
  finished_at    timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists jobs_queue_idx on jobs (approved_at) where status = 'queued';
create index if not exists jobs_session_idx on jobs (session_hash, created_at desc);

-- scenes ---------------------------------------------------------------------
-- The approved storyboard's scenes, frozen at approval, with their rendered assets.
create table if not exists scenes (
  job_id          uuid not null references jobs (id) on delete cascade,
  idx             smallint not null,
  role            text not null check (role in ('hook', 'demo', 'cta')),
  data            jsonb not null,
  image_asset_id  uuid,
  video_asset_id  uuid,
  primary key (job_id, idx)
);

-- stage_runs -----------------------------------------------------------------
-- One row per stage per scene. The provider prediction ID is saved as soon as a
-- render is submitted, so a re-attempt polls it instead of paying again.
create table if not exists stage_runs (
  id             uuid primary key default gen_random_uuid(),
  job_id         uuid not null references jobs (id) on delete cascade,
  stage          text not null check (stage in ('analyze', 'storyboard', 'image', 'video')),
  scene_idx      smallint not null default -1,  -- -1 for job-level stages
  status         text not null check (status in ('running', 'submitted', 'done', 'failed')),
  provider       text,
  model          text,
  prediction_id  text,
  output         jsonb,
  error          text,
  attempt        int not null default 1,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  unique (job_id, stage, scene_idx)
);

-- assets ---------------------------------------------------------------------
-- Files in storage (local folder or private GCS bucket), served by signed URLs.
create table if not exists assets (
  id            uuid primary key default gen_random_uuid(),
  job_id        uuid references jobs (id) on delete cascade,
  kind          text not null check (kind in ('upload', 'image', 'video')),
  storage_key   text not null unique,
  content_type  text not null,
  bytes         bigint,
  width         int,
  height        int,
  sha256        text,
  created_at    timestamptz not null default now()
);

-- media_cache ----------------------------------------------------------------
-- Every generation keyed by model, prompt, seed, input image hash and settings,
-- so evals, replays and the gallery never pay twice for the same render.
create table if not exists media_cache (
  cache_key     text primary key,
  kind          text not null check (kind in ('image', 'video')),
  model         text not null,
  storage_key   text not null,
  content_type  text not null,
  cost_usd      numeric(12, 6) not null default 0,
  meta          jsonb,
  created_at    timestamptz not null default now()
);

-- llm_calls ------------------------------------------------------------------
-- Every paid call (LLM, image, video, TTS). A row is written as a 'reserved'
-- estimate before the call starts (under an advisory lock, so concurrent stages
-- see each other's in-flight spend), then 'billed' with the cost, or 'released'
-- when nothing was spent. Spend = billed cost + open reservations.
-- job_id is kept on delete as null, so deleted jobs still count toward the day.
create table if not exists llm_calls (
  id             uuid primary key default gen_random_uuid(),
  job_id         uuid references jobs (id) on delete set null,
  stage_run_id   uuid references stage_runs (id) on delete set null,
  kind           text not null check (kind in ('llm', 'image', 'video', 'tts')),
  provider       text not null,
  model          text not null,
  status         text not null check (status in ('reserved', 'billed', 'released')),
  est_cost_usd   numeric(12, 6) not null,
  cost_usd       numeric(12, 6),
  usage          jsonb,
  latency_ms     int,
  cache_hit      boolean not null default false,
  error          text,
  created_at     timestamptz not null default now()
);
create index if not exists llm_calls_created_idx on llm_calls (created_at);
create index if not exists llm_calls_job_idx on llm_calls (job_id);
create index if not exists llm_calls_stage_idx on llm_calls (stage_run_id);
