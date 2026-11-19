# Changelog

All notable changes to UGC Ad Builder. Format based on [Keep a Changelog](https://keepachangelog.com). The *why* behind changes lives in [DECISIONS.md](DECISIONS.md).

## [Unreleased]
Nothing yet. M2 (full 3-scene ads) is next.

## [v2 M1] — 2026-11-19 (PR #1, merge commit `64156d1`)

Secure base and first pipeline leg. Live at https://ugc-creator-delta.vercel.app (API on Cloud Run, europe-west4). Production checked after the merge: the site reaches the API, CORS allows it, and the access-code gate refuses a wrong code.

### Added
- **Python backend** (`backend/`): FastAPI API and a worker that share one Docker image. A brief and one product photo produce a product analysis and a 3-scene storyboard with three tagged hooks; after approval, scene 1 gets a reference image of the real product (Nano Banana edit on fal) and a 5-second image-to-video clip (Kling 2.5 Turbo Pro on fal).
- **Spend controls:** one price table for every billing unit, a per-job cost cap and a global daily spend limit checked before every paid stage, all in EUR at one fixed rate ([D2](DECISIONS.md), [D8](DECISIONS.md), [D9](DECISIONS.md)).
- **Job runner:** idempotent Approve, `SKIP LOCKED` claim, resume from `stage_runs` (a submitted render is polled, never paid twice), max 2 attempts with the error stored and shown, empty queue exits 0.
- **Privacy and access:** session-scoped jobs, signed expiring file URLs, an access-code gate that fails closed in production, an upload guard that strips EXIF/GPS, fal request storage off and fal outputs expiring after one hour.
- **Database:** `db/schema.sql` (jobs, scenes, stage_runs, assets, media_cache, llm_calls) with pgvector, applied by `backend/scripts/apply_schema.py`; Neon connections retry while the database wakes up.
- **Frontend:** a guided flow (Brief → Storyboard → Generate) with stage status, live cost and a player; an honest landing page; a privacy notice naming each provider; `lib/api.js`.
- **Docker Compose** (postgres with pgvector, api, worker, frontend; mock providers by default) and **CI** (eslint + build, ruff + pytest on a Postgres service container with mock providers and blocked network, Docker build and start).
- 61 backend tests, including the ten M1 guardrails of the plan.
- **Deployed:** Cloud Run API and worker job in europe-west4, private bucket with a 30-day rule on `jobs/`, secrets in Secret Manager with per-service access, Artifact Registry keeping the last 5 images ([D19](DECISIONS.md)).
- **Live smoke test (18 Nov 2026):** one paid run on the v2 preview: storyboard → approval → reference image → 5 s video, finished with the browser closed; recorded cost 0.3425 EUR.
- Project documents: DECISIONS, APP_OVERVIEW, problem statement, roadmap, setup and privacy docs, M1 design note.

### Changed
- The page title is "UGC Ad Builder"; the landing page no longer shows invented statistics or view counts, and its illustrations are labelled as such.

### Removed
- The v1 n8n frontend components, unused CSS and `framer-motion`.
- `frontend/public/assets/user_upload.png` (a browser screenshot, not a product photo; it stays in old history).
- The "portfolio project" wording from the footer, the privacy notice and APP_OVERVIEW.
- `.agent/skills/` (two generic copied skills) and `context.md` (folded into `APP_OVERVIEW.md`).

## v1 preserved (18 Nov 2026)
- Tag `v1-final` on `main` before the M1 merge and the GitHub release "v1 — n8n prototype".
- `docs/before-after/v1/`: full-page screenshots of the v1 production site and its known issues; the build stays online at its permanent Vercel URL.

### Security
- The access code was rotated (new value in `backend/.env` and Secret Manager, old secret version disabled, old code refused).

## Author identity (18 Nov 2026)

### Changed
- Every commit's author and committer rewritten from an unlinked `aimilios944` noreply address to `Aimilios94 <181588880+Aimilios94@users.noreply.github.com>` (`git filter-repo --mailmap`), so GitHub links them to the account. File contents, dates and messages (including the `Co-Authored-By` lines) are unchanged. Force-pushed on the owner's go.

## Step 0 — security clean-up (18 Nov 2026)

### Security
- The fal key that was public in the v1 workflow file was revoked (confirmed dead: HTTP 401).
- The v1 workflow moved to `legacy/n8n/`, sanitised: placeholders for the key, the recipient address and credential IDs; instance, workflow and webhook IDs removed.
- The key and the address were purged from this repo's git history with `git filter-repo --replace-text` and force-pushed. A fork and GitHub's cache of old commits are out of reach ([D5](DECISIONS.md)).
- `backend/.env.example` and `frontend/.env.example` list every setting by name.

## v1 — January 2026 (prototype, kept in `legacy/n8n/`)

A React/Vite landing page posting to an n8n workflow (GPT-4o → Flux Schnell → Kling → Gmail) through an ngrok tunnel. An audit in November 2026 found that it never worked end to end: the form's email field was never read, the frontend posted to n8n's test-only webhook path, and the text-to-image step meant the real product never appeared in the ad. The workflow's notes and the landing page named NanoBanana and Veo 3.1 while the nodes used Flux and Kling. v2 is the rebuild.
