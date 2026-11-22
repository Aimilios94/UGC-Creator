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

All decisions are in `DECISIONS.md` (D1–D31; D1–D6 are the ones agreed before M1, D22–D24 the owner's calls on account timing, the M2 starter tasks and the landing refresh, D25 the campaign brief, brand kit and testimonial rule, D26 compose, voiceover and music, D27 the user-steered storyboard and the two steps, D28 1–5 scenes and the ad's sound, D29 video length, recommended scenes, the continuous shot and style notes, D30 every scene flows into the next: end frames on own pictures, the continuity check, clean and short cuts, D31 any prompt through one fixed structure (`docs/plan/prompt-to-ad-strategy-plan.md`), quality first with caps 5 EUR per ad and 10 EUR per day, the local findings archive). Read it before changing spend, queue, privacy or provider code.

## Working notes

- Backend: `cd backend`, venv `.venv` (Python 3.12). Tests need a Postgres: `docker run -d --name ugc-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=ugc_test -p 55432:5432 pgvector/pgvector:pg18`, then `TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/ugc_test .venv/Scripts/python -m pytest` and `.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .`.
- Frontend: `cd frontend && npm run lint && npm run build`.
- Whole stack, mock providers: `docker compose up --build` (http://localhost:5173). After frontend edits: `docker compose restart frontend` (Vite in Docker misses Windows file changes). Local paid test (owner's go only): `LLM_PROVIDER=openai MEDIA_PROVIDER=fal VOICE_PROVIDER=openai docker compose up -d`, passed again on every `up` (caps 5 EUR per ad, 10 EUR per day, D31). The local worker writes every test ad to the findings archive `C:\dev\ugc-archive` (outside the repo; never commit or upload it). The owner's test photos are in `local-handoff/photos/` (local only). Clearing mock spend and more: `docs/SETUP.md` "Local stack: tips and a paid test".
- Plans: `docs/plan/ugc-v2-full-plan.md` (the whole project) and `docs/plan/prompt-to-ad-strategy-plan.md` (D31: how any prompt becomes an ad, 6 phases, before the rest of M2). Read both.
- Live: site https://ugc-creator-delta.vercel.app, API https://ugc-api-1002867777166.europe-west4.run.app (Cloud Run service `ugc-api`, job `ugc-worker`, bucket `ugc-ad-builder-media`, europe-west4).
- Vercel project `ugc-creator`, root directory `frontend`. `VITE_API_BASE_URL` is set for Production and for Preview on `v2`; the stable `v2` preview is https://ugc-creator-git-v2-aimilios-projects-21450502.vercel.app. Vercel Authentication is off.
- After each milestone merge (a merge commit by the owner), fast-forward `v2` to `main` (`git merge --ff-only origin/main`) and push; no rewrite.
- v1 is preserved: tag `v1-final`, release "v1 — n8n prototype", `docs/before-after/v1/`.
- gcloud: installed per user, on PATH; active account is the project owner's.
- Git identity: `Aimilios94 <181588880+Aimilios94@users.noreply.github.com>` (global and repo). Commits must use it so GitHub links them.
- Setup and deploy commands: `docs/SETUP.md`. Milestone design notes: `docs/notes/`.

## Current status

2026-11-22 (UTC times): **M1 complete, merged and live; M2 in progress on `v2` (not deployed).** Merged into `main` by the owner: PR #1 (M1, 00:08 19 Nov, `64156d1`), docs PRs #2 (`f657691`) and #3 (`360cfbc`), PR #4 (23:39 19 Nov, `b9ee79e`: landing refresh, Create page with "Soon" previews, spend limits 1.75 EUR per job / 4 EUR per day live on Cloud Run). M2 done on `v2`: CI on `actions/*@v7` with a pinned `ubuntu-24.04` runner and the ruleset "main protection" on `main` (id `27687215`, D23); campaign brief, brand kit, testimonial rule (D25); compose, OpenAI voiceover, CC0 music, captions, end card, every shape, AI metadata (D26); the user-steered storyboard: own story, own scene pictures, pictures then video, 1–5 scenes, Sound card with previews, video length with about 2.5 s per scene, the recommended number of scenes, one continuous shot or separate shots, optional style notes, the Video page summary with models and costs (D27–D29); every scene flows into the next whatever pictures are given: the clip before an own picture ends on it (Kling end frame), a continuity check after the writer, clean cuts or a 0.1 s blend; stories up to 12,000 characters with no silent cut, every clip within Kling's 2,500 (notes shortened per scene, "Shorten it for me" for a long scene, the exact clip text shown) (D30). The owner's real tests on the local stack: about 2.16 EUR over two videos before D30, then the 20 s D30 test (5 × 4 s, 15:14 UTC 21 Nov): 1.60 EUR, all 4 cuts clean. **D31 (21 Nov): the prompt-to-ad strategy plan, built in 6 phases before the rest of M2; phase 1 done on `v2`:** the fixed structure (`services/ad_structure.py`), the three rules files (`app/prompts/rules/`), shorter fixed clip rules (worst case 300, CI-checked), golden test prompts v2, the local findings archive (`C:\dev\ugc-archive`); caps 5 EUR per ad and 10 EUR per day at 0.91 EUR per USD (Cloud Run keeps 1.75 / 4 until the M2 deploy). Then (21 Nov): own pictures of another shape are extended to the full frame by Nano Banana, never a blurred fill (the real-test finding); **phase 2 done:** the scene splitter (`services/scene_splitter.py`: time ranges, "Scene N" headings, lists; notes kept; joins and "cut to" splits said on the storyboard). 22 Nov: the full-frame extension checked with the real AI (one picture, 0.036 EUR: seamless); **phase 3 done:** the slot filler (`services/slot_filler.py`, stage `slots`: the cast and world sheet and scene cards, every guess marked and checked in code, paragraphs read into scenes and notes), "Cast and world" and "What the AI used" on the storyboard, the real-length line with "Add scenes" (`services/add_scenes.py`, stage `add_scenes`) or "Keep"; the real slot filler checked live (golden 01 and 02, 0.0085 EUR: honest marks; it no longer invents product facts); **phase 4 done:** every clip built from the structure within a budget (`video_gen.build_clip`, 2,310 at most), the user's scene text reaching Kling word for word (the writer adds only a timeline), "AI changed" with Undo for Kling weak spots (A1), "Never"/"Avoid" in the negative prompt, the marks editable in place. 270 tests pass, 8 skip (golden checks of phases 5–6). Project budget **50 EUR** (raised from ~26, D31); spend about **12.72 EUR** (M1 0.68, landing 8.20, voice previews 0.006, local real tests 3.81), about 37.3 EUR left. **Next:** golden 03 live with the real writer (the A1 swap, a few cents, owner's go), then phases 5–6 of the strategy plan (quick questions; the image path, no-photo route and character reference), each checked on mock and with a real run only on the owner's go; then M2 items 3–6 (themes, cost tracking and History, Sentry and docs page, cleanup cron and "delete my data"), then the M2 deploy (SETUP "M2 deploy"; the new API and frontend must go live together), each paid step with the owner's go. Replace the voice model before 6 Jan 2027 (D26). The plan's fixed 3 scenes and one-step approval are superseded by D27–D30; its photo-only promise and caps are amended by D31. Backups in `C:\dev\backups` await the owner's confirmation to delete. Handoff: `local-handoff/` (local only).
