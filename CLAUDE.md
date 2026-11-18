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

## Decisions agreed before M1 (to be recorded in `DECISIONS.md` in M1)

1. Milestone PRs go `v2` → `main`, merged only when "Done when" passes and the backend is deployed. If the deploy slips to M2, M1 is not merged until then.
2. All user-facing money is in EUR, with a USD display option under Advanced settings. M1: `JOB_COST_CAP_EUR=1`, `DAILY_SPEND_LIMIT_EUR=3`; raise both in M2 for full 3-scene ads and record why. `DEMO_POT_EUR` from M4.
3. OpenAI is the default text provider until the M4 eval decides.
4. Removing `.agent/skills` and `context.md` and creating the project documents happens in M1.
5. "Git history no longer holds the key" means this repo's history; the fork (jovimars) and GitHub's cache are out of reach.
6. Cron every 15 minutes at an odd minute (recovery window about 15–30 min). GitHub disables scheduled workflows after 60 days without activity in public repos: documented.

Verified facts (18 Nov 2026): fal `fal-ai/nano-banana/edit` 0.0398 USD per image; `fal-ai/kling-video/v2.5-turbo/pro/image-to-video` 0.07 USD per second (fal returns units as `images` / `seconds`). Use the `X-Fal-Store-IO: 0` header. Clip ratio comes from the reference image, so generate it at the master ratio. Cloud Run Job: `--task-timeout=45m`, `--max-retries=1`; the API's service account gets `roles/run.jobsExecutor` on the job only.

## Current status

2026-11-18: Old leaked fal key confirmed revoked (401). Step 0 in progress on `main` (backup done, CLAUDE.md rewritten); history purge awaiting verification and the user's separate go for the force push. Next: v2 branch and M1 (plan §17).
