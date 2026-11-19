# Decisions

*Each entry is **Problem → Evidence → Decision → Result**. This is the record of why the product is built the way it is. The plan is [docs/plan/ugc-v2-full-plan.md](docs/plan/ugc-v2-full-plan.md).*

Evidence tags: `[user]` agreed with the project owner before M1 (18 Nov 2026); `[plan]` from the plan; `[eng]` an engineering decision made while building; `[verified]` checked against a provider's docs or API on the date given.

---

## D1 — Milestone PRs merge only when "Done when" passes and the backend is deployed `[user]`

- **Problem:** A milestone can look finished in code while it does not run where users are.
- **Decision:** Work happens on `v2`; one PR per milestone goes `v2` → `main` and is merged only when that milestone's "Done when" list passes on the deployed backend. If the deploy slips to M2, M1 is not merged until then.
- **Result:** `main` only ever holds deployed, verified milestones. M1: PR #1 merged by the owner on 19 Nov 2026 as a merge commit (`64156d1`) after every "Done when" item passed on the deployed stack; `v2` is kept and fast-forwarded to `main` after each merge.

## D2 — All user-facing money is in EUR `[user]`

- **Problem:** Providers bill in USD; the budget and the user think in EUR.
- **Decision:** Costs are stored in USD as billed and converted at one app-wide fixed rate (`USD_TO_EUR_RATE`, 0.87). Everything the user sets or sees is EUR, with a USD display option under Advanced settings. M1 limits: `JOB_COST_CAP_EUR=1`, `DAILY_SPEND_LIMIT_EUR=3`, raised in M2 for full 3-scene ads (the reason will be recorded here then). `DEMO_POT_EUR` from M4.
- **Result:** The API returns both currencies, so the display switch is instant and no figure is converted twice.

## D3 — OpenAI is the default text provider until the M4 eval `[user]` `[verified 2026-11-18]`

- **Decision:** `LLM_PROVIDER=openai` with `gpt-5-mini-2025-08-07` (0.25 / 2.00 USD per 1M input/output tokens), a dated snapshot so a model cannot change under the evals without a config change. Reasoning effort `low`. The M4 comparison decides the default.

## D4 — Old project files are removed in M1 `[user]`

- **Decision:** `.agent/skills/` (two generic copied skills) and `context.md` (folded into `APP_OVERVIEW.md`) are removed; the project document set is created in M1.

## D5 — "Git history no longer holds the key" means this repo's history `[user]`

- **Problem:** The leaked fal key and a personal address were in every commit of a public repo with one fork.
- **Evidence:** The key was still valid on 18 Nov 2026 (it belonged to a second fal account); revoked the same day, confirmed by HTTP 401.
- **Decision:** Revoking the key is the fix. The history purge (`git filter-repo --replace-text`, force-pushed on 18 Nov 2026) cleans this repo only; the fork and GitHub's cache of old commit SHAs are out of reach.
- **Result:** A fresh clone has 0 occurrences of the key or the address in any object.

## D6 — Scheduled cleanup and sweep run every 15 minutes, at an odd minute `[user]`

- **Decision:** The GitHub Actions cron (M2) runs every 15 minutes at an odd minute (fewer collisions with the top-of-the-hour rush), so a crashed job is recovered within about 15–30 minutes. GitHub disables scheduled workflows in public repos after 60 days without repository activity; this is documented in `docs/SETUP.md`.

## D7 — The job's lifecycle lives in one `jobs` row; Approve flips it once `[eng]`

- **Problem:** A double-click or a client retry on Approve must not create two paid jobs.
- **Decision:** A brief creates a `draft` job. Approve is one conditional `UPDATE ... WHERE status = 'draft'`; a repeat finds no draft and changes nothing. The queue is the same table, claimed with `FOR UPDATE SKIP LOCKED` in a short committed `UPDATE` (no transaction held open, which Neon's idle timeout would break). An empty queue exits with code 0.
- **Result:** Pinned by tests: one row and one video submit after a double Approve; an empty-queue execution returns 0.

## D8 — Spend is reserved before each paid stage, under an advisory lock `[eng]`

- **Problem:** "Spend so far plus the estimate must fit under the cap" is racy if two stages check at once, and a crash between submit and record could hide spend.
- **Decision:** Before a paid stage, one transaction takes `pg_advisory_xact_lock`, sums billed costs plus open reservations (job and UTC day), checks the cap and the daily limit, and inserts a `reserved` row with the estimate. After the call the row is `billed` with the cost from the same price table. A submit that fails is `released` (nothing reached the provider). A render the provider finishes with an error keeps its estimate (billing not confirmed, so the cap stays safe). A "try again" never resets spend.
- **Result:** The cap and limit can only be passed by vendor price drift. Pinned by the cap, daily-limit, open-reservation and try-again tests.

## D9 — A model without a price cannot be used `[eng]`

- **Problem:** A price table that returns 0 for an unknown model would let a new model slip past every spend limit.
- **Decision:** `llm_trace.price_for` raises `UnknownPrice`. The table covers every fal billing unit (image, megapixel, second, video, token, character, generic unit) plus modifiers (base fee, audio-on multiplier, per-resolution multiplier). fal's plural unit names are normalised.
- **Result:** One test per unit and modifier; prices carry their source and check date.

## D10 — fal: verified models, request storage off, outputs expire after one hour `[verified 2026-11-18]`

- **Evidence:** fal pricing API: `fal-ai/nano-banana/edit` 0.0398 USD per image; `fal-ai/kling-video/v2.5-turbo/pro/image-to-video` 0.07 USD per second (5 s = 0.35 USD). Both model pages show the "Commercial use" label. Kling has no aspect-ratio input: the clip follows its input image. fal's docs: generated files are kept forever and publicly readable unless a lifecycle is set.
- **Decision:** Every request sends `X-Fal-Store-IO: 0` and `X-Fal-Object-Lifecycle-Preference: {"expiration_duration_seconds": 3600}`; the worker copies each output into our storage at once. The reference image is generated at the master ratio. Inputs are passed as URLs (fal: URLs work with every model, data URIs only with some): a GCS V4 signed URL when hosted; in local dev a fal CDN upload with the same one-hour expiry.
- **Result:** A planned 15 s ad costs about 1.05 USD of video (about 0.91 EUR), below the plan's 1.30 EUR estimate.

## D11 — Jobs are private to the browser session; another session gets 404 `[eng]`

- **Decision:** The browser creates a random session ID (`X-Session-Id`); the server stores only its SHA-256, and every job route filters on it. Another session gets the same 404 as a missing job, so job IDs cannot be probed. Files are served only through signed, expiring URLs: an HMAC over (key, expiry) for local storage, V4 signed URLs for GCS.

## D12 — Generation needs an access code, and production fails closed `[eng]`

- **Decision:** Creating a job, Approve and "try again" require `X-Access-Code` to match `ACCESS_CODES` (constant-time compare). With `APP_ENV=prod` and no codes configured, every generation request is refused. Local dev without codes is open.

## D13 — One short database connection per unit of work, with wake-up retries `[eng]`

- **Problem:** Neon scales to zero; the first connection after idle can fail or be slow.
- **Decision:** `Database.connect` retries with backoff (0.5 s doubling, max 8 s) and a 20 s connect timeout; prepared statements are off for Neon's pooler. No pool: at this scale a connection per unit of work is simpler and never holds a transaction open during a render. The API and the worker build their connection the same way.

## D14 — Mock media is priced as the real model it stands in for `[eng]`

- **Decision:** The mock media provider renders locally (a Pillow image, a 2 KB H.264 clip) but its calls are costed with the real model's price, so tests exercise the cap and daily limit with real numbers. Mock LLM calls cost 0. Docker Compose defaults to mock providers; real providers must be set explicitly.

## D15 — Tests cannot reach a paid API `[eng]`

- **Decision:** `tests/conftest.py` forces mock providers and blanks every key and database URL before the app is imported (environment overrides `backend/.env`), blocks every non-local socket connection, and turns off Pydantic AI's `ALLOW_MODEL_REQUESTS`. In CI, database tests may not be skipped. CI has no secrets.

## D16 — Cloud Run: the API may only start the job; the job has a 45-minute timeout and 1 retry `[verified 2026-11-18]`

- **Evidence:** Cloud Run docs: a job task's default timeout is 10 minutes (max 168 h). `roles/run.jobsExecutor` grants `run.jobs.run` and `run.executions.cancel` but not `run.jobs.runWithOverrides`.
- **Decision:** Worker job: `--task-timeout=45m --max-retries=1`. The API's service account gets `roles/run.jobsExecutor` on the worker job only and starts executions with an empty body (no overrides). The job's service account reads and writes the bucket. Both sign URLs through IAM signBlob (no key files), so each needs `roles/iam.serviceAccountTokenCreator` on itself. Region `europe-west4`.

## D17 — M1 renders scene 1 only `[plan]`

- **Decision:** `RENDER_SCENES=1`: the first pipeline leg is analyze → storyboard → approval → one reference image + one 5 s video. M2 renders all three scenes and composes the ad.

## D18 — Line endings are LF in the repo `[eng]`

- **Problem:** On a Windows checkout with `core.autocrlf`, the Dockerfile's shell commands and YAML can get CRLF line endings.
- **Decision:** `.gitattributes` pins `eol=lf` for text and marks media as binary.

## D19 — Deploy: least privilege per service, cost guards, settings in files `[eng]` `[user]`

- **Decision:** Two service accounts. `ugc-api` reads only the OpenAI key, the database URL and the access codes, and holds `roles/run.jobsExecutor` on the worker job only; it has no fal key, because it never renders (it gets a media stand-in that refuses). `ugc-worker` reads only the fal key and the database URL. Secrets live in Secret Manager in europe-west4. Cost guards (owner's request): the API scales to zero (min 0, max 2 instances); Artifact Registry keeps the last 5 images; the bucket deletes `jobs/*` after 30 days, matching `RETENTION_DAYS`, so future seeded demo ads under another prefix stay. Non-secret settings are in `deploy/gcp/*.env.yaml`.
- **Result (18 Nov 2026):** an execution on the empty Neon queue exited 0; `/health/db` answers; generation without the access code gets 403; CORS allows only the listed site.

## D20 — v1 is preserved as a tag, a release and screenshots `[user]`

- **Problem:** The M1 merge replaces the v1 site, but a later before/after comparison needs v1 as it was.
- **Decision:** Tag `v1-final` on `main` before the merge (`2404369`), a GitHub release "v1 — n8n prototype", full-page screenshots and a list of known issues in `docs/before-after/v1/`, and the v1 build's permanent Vercel URL recorded there. The v1 code is not kept on `main`.

## D21 — The access code is rotated by adding a secret version and disabling the old one `[eng]`

- **Decision:** A new code is generated into `backend/.env` and added as a new version of the `access-codes` secret; the API gets a new revision so it reads `latest`; the old version is disabled. The code is never printed or committed. Done on 18 Nov 2026 and again on 19 Nov 2026 (each time: old code refused, new code accepted, old version disabled). Steps in `docs/SETUP.md`.
