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
- Backups in `C:\dev\backups` hold pre-purge history: never upload them; delete them only on the owner's confirmation (M1 is merged and verified).
- `local-handoff/` (project root) is local-only: excluded via `.git/info/exclude`, never committed or pushed, never contains secrets.

## Standing rule: end-of-session update (every session, every agent, no exceptions)

At the end of every session, before telling the user you are done:
1. Update every product and project document that the session touched or that is now out of date. Check each one, one by one, even if you think nothing changed:
   - README.md
   - APP_OVERVIEW.md
   - problem-statement.md
   - roadmap.md
   - feedback-notes.md
   - DECISIONS.md
   - CHANGELOG.md
   - the design note for the current milestone in docs/notes/
   - docs/SETUP.md and docs/PRIVACY.md
   - CLAUDE.md (the "Current status" line)
2. Double-check consistency: the same facts (milestone status, decisions, costs, URLs, model names, what's live) must say the same thing in every file and match the plan. Fix any mismatch.
3. Refresh the three local-handoff files (`local-handoff/next-agent-prompt.md`, `local-handoff/HANDOFF.md`, `local-handoff/previous_chat.md`) with the new state and this session's ID and summary.
4. Commit and push the repo files, confirm the local-handoff files are still untracked, and give the user a checklist of every file above marked "updated" or "checked, no change needed".

## Environment

- Repo: `C:\dev\UGC-Ad-Builder`, GitHub `Aimilios94/UGC-Creator` (public).
- Secrets live only in `backend/.env` (gitignored): `FAL_KEY`, `OPENAI_API_KEY`, `DATABASE_URL` (Neon pooled), `DATABASE_URL_DIRECT`. Variable names are listed in `backend/.env.example` and `frontend/.env.example`.
- Neon project `ugc-ad-builder`, AWS Europe Central 1 (Frankfurt), database `neondb`, Postgres 18, pgvector available.
- Google Cloud project `ugc-ad-builder`, region `europe-west4`, budget alert 10 EUR. No service-account key files, ever: `gcloud` login locally, service accounts on Cloud Run.
- Python 3.12 via `uv`; Node for the frontend (`cd frontend && npm install`).
- Still to come: Anthropic key (before M4), Sentry (M2, EU org), Resend (M3), LangSmith (M4).

## Decisions

All decisions are in `DECISIONS.md` (D1–D26; D1–D6 are the ones agreed before M1, D22–D24 the owner's calls on account timing, the M2 starter tasks and the landing refresh, D25 the campaign brief, brand kit and testimonial rule, D26 compose, voiceover and music). Read it before changing spend, queue, privacy or provider code.

## Working notes

- Backend: `cd backend`, venv `.venv` (Python 3.12). Tests need a Postgres: `docker run -d --name ugc-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=ugc_test -p 55432:5432 pgvector/pgvector:pg18`, then `TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/ugc_test .venv/Scripts/python -m pytest` and `.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .`.
- Frontend: `cd frontend && npm run lint && npm run build`.
- Whole stack, mock providers: `docker compose up --build` (http://localhost:5173).
- Live: site https://ugc-creator-delta.vercel.app, API https://ugc-api-1002867777166.europe-west4.run.app (Cloud Run service `ugc-api`, job `ugc-worker`, bucket `ugc-ad-builder-media`, europe-west4).
- Vercel project `ugc-creator`, root directory `frontend`. `VITE_API_BASE_URL` is set for Production and for Preview on `v2`; the stable `v2` preview is https://ugc-creator-git-v2-aimilios-projects-21450502.vercel.app. Vercel Authentication is off.
- After each milestone merge (a merge commit by the owner), fast-forward `v2` to `main` (`git merge --ff-only origin/main`) and push; no rewrite.
- v1 is preserved: tag `v1-final`, release "v1 — n8n prototype", `docs/before-after/v1/`.
- gcloud: installed per user, on PATH; active account is the project owner's.
- Git identity: `Aimilios94 <181588880+Aimilios94@users.noreply.github.com>` (global and repo). Commits must use it so GitHub links them.
- Setup and deploy commands: `docs/SETUP.md`. Milestone design notes: `docs/notes/`.

## Current status

2026-11-19 (UTC times): **M1 complete, merged and live; M2 in progress on `v2`.** Merged into `main` by the owner: PR #1 (M1, 00:08, `64156d1`), docs PRs #2 (01:29, `f657691`) and #3 (07:35, `360cfbc`), and PR #4 (23:39, `b9ee79e`: landing refresh in the v1 look with example scenes, Create page with "Soon" previews (D24), the spend limits 1.75 EUR per job / 4 EUR per day (D2, live on Cloud Run as env vars) and the docs consistency fixes); production checked after each. M2 done so far: CI on `actions/*@v7` with a pinned `ubuntu-24.04` runner (green, no annotations) and the ruleset "main protection" on `main` (id `27687215`: no force push, no deletion, checks `frontend`/`backend`/`docker` required on an up-to-date branch, no reviews, no bypass; D23, SETUP). `v2` is ahead of `main` by those M2 commits; they reach `main` with the M2 PR. Spend: about 8.9 EUR of the ~26 EUR API budget used (M1 runs about 0.68 EUR, landing assets 8.20 EUR), about 17 EUR left for M2–M4. **Next: the plan §17 M2 items** (design note `docs/notes/m2-full-ads.md`); the sweep token is created with the cleanup endpoint; ask the owner before any paid call. Backups in `C:\dev\backups` await the owner's confirmation to delete. Handoff: `local-handoff/` (local only).
