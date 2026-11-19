# M1 design note: secure base and first pipeline leg

Status: complete pending review (18 Nov 2026). Branch `v2`, PR to `main`.

## How it works

```
Browser ──X-Session-Id──▶ API (FastAPI, Cloud Run service)
  POST /jobs (photo + brief)      upload guard → storage → analyze (vision LLM) → storyboard (LLM)   [draft]
  PUT  /jobs/{id}/storyboard      edit while draft
  POST /jobs/{id}/approve         draft → queued (once) → start a worker execution (no overrides)
  GET  /jobs/{id}                 status, stages, spend (EUR/USD), signed asset URLs

Worker (Cloud Run Job / Compose loop, same image)
  claim oldest queued job (SKIP LOCKED, attempts+1)
  scene 1: reference image (fal Nano Banana edit) → 5 s clip (fal Kling i2v)
     each paid stage: cache? → reserve estimate (cap + daily limit, advisory lock) → submit
                      → save prediction ID → poll → copy output to storage → bill → cache
  done | exception → requeue while attempts < 2, else failed (error stored) | budget refusal → failed
```

Cost before approval is a few cents of LLM; the render costs 0.0398 USD (image) + 0.35 USD (5 s video) ≈ 0.34 EUR, under the M1 cap of 1 EUR.

## What was built
- Backend: `config.py` (pydantic-settings, imports with no secrets, mock providers), `models.py`, `repository.py` (plain SQL, Neon wake-up retries), `db/schema.sql` + `apply_schema.py`, providers for LLM (Pydantic AI: openai | anthropic | mock), media (fal | mock) and storage (local | gcs), `pipeline.py`, `worker.py`, routers.
- Price table for every fal billing unit and modifier; the estimate and the record use the same table.
- Frontend: Brief → Storyboard → Generate, honest landing page, privacy notice.
- Docker Compose; CI (eslint, build, ruff, pytest with a Postgres service container, Docker build and start).

## What was decided
See [DECISIONS.md](../../DECISIONS.md) D1–D19. The ones that shape the code most: one `jobs` row as draft, queue and record (D7); spend reservations under an advisory lock (D8); no price means no call (D9); fal request storage off and outputs expiring after one hour (D10).

## Verified at the start of M1 (plan §20)
| Item | Result |
| --- | --- |
| fal model IDs, prices, units, "Commercial use" | Nano Banana edit 0.0398 USD/image; Kling 2.5 Turbo Pro i2v 0.07 USD/s; both labelled "Commercial use" |
| Neon free plan, EU, pgvector | Frankfurt, Postgres 18.7, pgvector 0.8.7 available |
| Cloud Run Job timeout and role | Default 10 min, set 45 min; `roles/run.jobsExecutor` (no overrides) |
| Providers in the privacy notice | fal and OpenAI (US), Neon (Frankfurt), Google Cloud (europe-west4), Vercel |
| Pydantic AI → LangSmith tracing | Deferred to M4 (LangSmith arrives then) |
| Music licence | Deferred to M2 (music arrives then) |
| Cron interval | 15 min at an odd minute (D6) |

## "Done when" status
| Item | Status |
| --- | --- |
| Deployed site: photo + brief → approved storyboard → playable scene video, with an access code | **Passed** on the v2 preview against the Cloud Run API (18 Nov 2026, one paid run): storyboard in ~35 s, image + 5 s video in ~2 min, 1088×1904 (9:16) clip plays from a signed GCS URL |
| The job finishes after the tab is closed | **Passed**: the browser was closed right after Approve; the job finished on attempt 1 and reopened as done |
| A second browser cannot open it | **Passed** on the deployed site (isolated browser: "not found"); also tested in the suite (404) |
| An asset URL stops working after it expires | **Passed** on the deployed site: a signed GCS video URL (valid 900 s, signed 22:39:44 UTC) loaded before and failed after expiry (22:55 UTC); a reload issued a fresh URL that loads. Also in the test suite (local HMAC URLs: 403) |
| A double-clicked Approve creates one job | Passed (test suite, and a browser double-click on Compose) |
| Cost estimate correct for every billing unit | Passed (one test per unit and modifier) |
| CI is green | Passed (61 backend tests, none skipped; lint; build; Docker) |
| Git history no longer holds the key or the address | Passed (Step 0; a fresh clone scans 0) |

## Live smoke test (18 Nov 2026)
One paid run on the deployed stack, with the job cap lowered to 0.50 EUR for the run (owner's hard limit) and restored to 1 EUR after.

| Step | Model | Recorded cost |
| --- | --- | --- |
| Analyze | gpt-5-mini-2025-08-07 (1,957 in / 433 out tokens) | 0.0014 USD |
| Storyboard | gpt-5-mini-2025-08-07 (994 in / 1,130 out tokens) | 0.0025 USD |
| Reference image | fal-ai/nano-banana/edit (1 image) | 0.0398 USD |
| Video | Kling 2.5 Turbo Pro i2v (5 s) | 0.3500 USD |
| **Total** | | **0.3937 USD = 0.3425 EUR** |

The estimate before approval was 0.3391 EUR for the render; the LLM steps cost 0.003 EUR against a reserved ceiling of 0.03 EUR. Costs are recorded with the same price table as the estimate; fal's own billing record needs a billing-scoped key, so the fal dashboard is the place to confirm the charge. The product kept its label text ("PEAKFUEL", "PROTEIN SHAKER", "700 ML · BPA FREE"), shape and cap; the teal body came out lighter and more translucent. The storyboard used the offer verbatim and made no first-person claims.

## What is next
- M2: full 3-scene ads (compose, voiceover, captions, music, ratios), themes, History, Sentry, the cleanup and sweep cron. The cost cap and daily limit go up for 3-scene ads (to be recorded in DECISIONS.md with the reason).
- The smoke-test product photo was a drawn product (no people), because the repo's sample images all show people.
