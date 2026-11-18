# CLAUDE.md — UGC Ad Builder v2

## Summary

UGC Ad Builder turns one product photo and a short brief into a finished, ready-to-post video ad (storyboard → reference images → image-to-video → composed ad → Post Kit), with measured quality and known cost per ad. v1 (Jan 2026) was a React/Vite page plus an n8n workflow; it is kept, sanitised, under `legacy/n8n/`. v2 is a Python (FastAPI + Pydantic AI) backend with Postgres/pgvector (Neon), Google Cloud Storage and Cloud Run, plus the existing React frontend in `frontend/`.

## Source of truth

**`docs/plan/ugc-v2-full-plan.md` is the complete plan and the only source of truth.** Read it fully at the start of every session. If something in it looks wrong, tell the user instead of changing course.

Milestones: M1–M4 = MVP, M5–M6 = v2.1, week 7 = buffer (plan §17). Each milestone's "Done when" must pass before it is called finished.

## Rules (always)

- Never print, log or commit secret values. Never echo `.env` contents. Check keys only by result (works / does not work).
- No real paid API calls without asking the user first. Tests and CI use mock providers only.
- Git: branch `v2`, one PR per milestone (`v2` → `main`), merged only when that milestone's "Done when" passes and the backend is deployed. Never force-push or rewrite history without the user's explicit go at that moment.
- Receipt-Ghostbuster is read-only reference: cloned at `C:\dev\Receipt-Ghostbuster-ref` (outside this repo) with `git remote set-url --push origin DISABLED`. Never modify it or add it inside this repo.
- Record decisions in `DECISIONS.md`, changes in `CHANGELOG.md`, and a design note per milestone in `docs/notes/`.
- If something is unclear, wrong or blocked: stop and ask the user.
- Backups in `C:\dev\backups` hold pre-purge history: never upload them; delete them after M1 is merged and verified.
- Update the "Current status" line below at the end of every session.

## Environment

- Repo: `C:\dev\UGC-Ad-Builder`, GitHub `Aimilios94/UGC-Creator` (public).
- Secrets live only in `backend/.env` (gitignored): `FAL_KEY`, `OPENAI_API_KEY`, `DATABASE_URL` (Neon pooled), `DATABASE_URL_DIRECT`. Variable names are listed in `backend/.env.example` and `frontend/.env.example`.
- Neon project `ugc-ad-builder`, AWS Europe Central 1 (Frankfurt), database `neondb`, Postgres 18, pgvector available.
- Google Cloud project `ugc-ad-builder`, region `europe-west4`, budget alert 10 EUR. No service-account key files, ever: `gcloud` login locally, service accounts on Cloud Run.
- Python 3.12 via `uv`; Node for the frontend (`cd frontend && npm install`).
- Still to come: Anthropic key (before M4), Sentry (M2, EU org), Resend (M3), LangSmith (M4).

## Decisions

All decisions are in `DECISIONS.md` (D1–D6 are the ones agreed before M1). Read it before changing spend, queue, privacy or provider code.

## Working notes

- Backend: `cd backend`, venv `.venv` (Python 3.12). Tests need a Postgres: `docker run -d --name ugc-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=ugc_test -p 55432:5432 pgvector/pgvector:pg18`, then `TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/ugc_test .venv/Scripts/python -m pytest` and `.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .`.
- Frontend: `cd frontend && npm run lint && npm run build`.
- Whole stack, mock providers: `docker compose up --build` (http://localhost:5173).
- Vercel project `ugc-creator` (ugc-creator-delta.vercel.app), root directory `frontend`. The `v2` preview is https://ugc-creator-git-v2-aimilios-projects-21450502.vercel.app with `VITE_API_BASE_URL` set for Preview on `v2` only.
- Git identity: `Aimilios94 <181588880+Aimilios94@users.noreply.github.com>` (global and repo). Commits must use it so GitHub links them.
- Setup and deploy commands: `docs/SETUP.md`. Milestone design notes: `docs/notes/`.

## Current status

2026-11-18: **M1 complete; PR `v2` → `main` open for the owner's review (do not merge it yourself).** Every M1 "Done when" item passed on the deployed stack (v2 Vercel preview + Cloud Run API/worker in europe-west4); one paid smoke run cost 0.3425 EUR (recorded). Job cap is back to 1 EUR. Author identity rewritten to Aimilios94 and force-pushed earlier today. gcloud is installed per user and on PATH; only the project owner's account is signed in. Next: the owner merges after the PR's merge checklist (Vercel Production `VITE_API_BASE_URL`, delete `VITE_N8N_WEBHOOK_URL`), then check the production site; then M2 (plan §17). Backups in `C:\devackups` (delete after M1 is merged and verified).
