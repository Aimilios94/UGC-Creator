# M1 design note: secure base and first pipeline leg

Status: in progress (18 Nov 2026). Branch `v2`.

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
See [DECISIONS.md](../../DECISIONS.md) D1–D18. The ones that shape the code most: one `jobs` row as draft, queue and record (D7); spend reservations under an advisory lock (D8); no price means no call (D9); fal request storage off and outputs expiring after one hour (D10).

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
| Deployed site: photo + brief → approved storyboard → playable scene video, with an access code | Works locally with mock providers (Compose, browser-tested); deploy and one live smoke run pending |
| The job finishes after the tab is closed | Worker runs server-side; to confirm on the deployed site |
| A second browser cannot open it | Tested (404) |
| An asset URL stops working after it expires | Tested (403) |
| A double-clicked Approve creates one job | Tested (API and browser double-click) |
| Cost estimate correct for every billing unit | Tested |
| CI is green | Done: run on `v2` green (60 backend tests, none skipped; lint; build; Docker) |
| Git history no longer holds the key or the address | Done (Step 0; fresh clone scans 0) |

## What is next
1. ~~CI green on GitHub~~ (done).
2. ~~Apply the schema to Neon~~ (done: 6 tables, pgvector 0.8.7, re-run is a no-op).
3. Deploy: install gcloud (needs an admin prompt), create the Cloud Run service, job, bucket and secrets, connect Vercel.
4. One live smoke run on the deployed site (paid, about 0.35 EUR) — only with the owner's go.
5. M2: full 3-scene ads.
