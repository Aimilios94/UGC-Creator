# Setup

## Run it locally with Docker (no keys needed)

```bash
docker compose up --build
```

Open http://localhost:5173. Compose runs Postgres (pgvector), the API (:8000), the worker and the frontend, with **mock providers**: nothing is paid and no key is needed. The API applies `db/schema.sql` on start.

Real providers are paid. Use them only on purpose, with keys in `backend/.env`:

```bash
LLM_PROVIDER=openai MEDIA_PROVIDER=fal docker compose up
```

### Local stack: tips and a paid test

- **Frontend changes:** Vite inside Docker does not see file changes on a Windows bind mount. After editing `frontend/`, run `docker compose restart frontend`.
- **Backend changes:** `docker compose up --build -d` rebuilds the API and worker.
- **Mock pictures and clips:** with `MOCK_PREVIEW=true` (the default) a "generated" picture is your product photo fitted to the frame (marked as a test) and a clip is its picture with a slow push-in, so timing, captions, music and the end card can be judged for free. Tests use plain placeholders.
- **Mock spend and the daily limit:** mock renders are priced like the real models (D14), so a day of local testing can reach the daily limit in the local database. Clear it (local database only) with `docker compose exec -T postgres psql -U postgres -d ugc -c "delete from llm_calls where provider = 'mock'"`.
- **A paid test with the real AI (only with the owner's go and limit):** keys come from `backend/.env`; the access code is off locally.

  ```bash
  LLM_PROVIDER=openai MEDIA_PROVIDER=fal VOICE_PROVIDER=openai DAILY_SPEND_LIMIT_EUR=5 docker compose up -d
  ```

  The same variables must be passed again on every `docker compose up`, or the stack falls back to mock. Real spend so far on the local stack: `docker compose exec -T postgres psql -U postgres -d ugc -c "select round(sum(coalesce(cost_usd, est_cost_usd))*0.87, 3) as eur from llm_calls where status in ('reserved','billed') and provider <> 'mock'"`.

## Run the backend without Docker

Python 3.12 with [uv](https://docs.astral.sh/uv/):

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements-dev.txt
cp .env.example .env            # then fill in what you need; never commit .env
.venv/Scripts/python scripts/apply_schema.py      # Windows; .venv/bin/python elsewhere
.venv/Scripts/uvicorn app.main:app --reload --port 8000
.venv/Scripts/python -m app.worker --loop          # second terminal
```

Frontend: `cd frontend && npm install && npm run dev` (reads `VITE_API_BASE_URL`, default `http://localhost:8000`).

The worker and the compose tests need **ffmpeg with libass** on PATH (the Docker image and CI install Debian/Ubuntu's `ffmpeg`; on Windows the gyan.dev "full" build works).

### Music beds

The five 30-second beds in `backend/app/music/` are cut from CC0 tracks (sources and licence: [MUSIC.md](MUSIC.md)). To recut them, download the five tracks from their Free Music Archive pages (free login) into a folder outside the repo and run `.venv/Scripts/python scripts/make_music_beds.py <folder>`. The originals are not committed.

### Voice previews

The four short voice previews in `backend/app/voices/` were made once with `.venv/Scripts/python scripts/make_voice_samples.py` (real voice model, paid: about 0.006 EUR; needs `OPENAI_API_KEY` in `backend/.env`). Run it again only to change the sample line or the voices.

## Tests

```bash
docker run -d --name ugc-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=ugc_test -p 55432:5432 pgvector/pgvector:pg18
cd backend
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/ugc_test .venv/Scripts/python -m pytest
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

Tests always run on mock providers with every key blanked and non-local network blocked ([D15](../DECISIONS.md)). Without `TEST_DATABASE_URL` the database tests are skipped locally; in CI they must run.

## Settings

Every setting is listed by name in [backend/.env.example](../backend/.env.example) and [frontend/.env.example](../frontend/.env.example). Money settings are in EUR. Frontend `VITE_` values are public: never put a secret there.

## Database (Neon)

Project `ugc-ad-builder`, AWS Europe Central 1 (Frankfurt), database `neondb`. The API and worker use the pooled URL (`DATABASE_URL`); schema changes use the direct URL (`DATABASE_URL_DIRECT`):

```bash
cd backend && .venv/Scripts/python scripts/apply_schema.py
```

The schema file is idempotent; run it after every change to `db/schema.sql`.

## Deploy (Google Cloud Run + Vercel)

Project `ugc-ad-builder`, region `europe-west4`. No service-account key files: `gcloud auth login` locally, service accounts on Cloud Run ([D16](../DECISIONS.md), [D19](../DECISIONS.md)). These are the commands that were run on 18 Nov 2026.

gcloud is installed per user in `%LOCALAPPDATA%\google-cloud-sdk` (on PATH). If gcloud fails with `NO_CERTIFICATE_OR_CRL_FOUND`, check for a `CURL_CA_BUNDLE` environment variable pointing to an empty file: Python's `requests` uses it as its only CA bundle (one was set to `NUL` on this machine and has been removed).

```bash
gcloud config set project ugc-ad-builder
gcloud config set run/region europe-west4
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com   iamcredentials.googleapis.com storage.googleapis.com iam.googleapis.com

# Image registry; keep only the last 5 images
gcloud artifacts repositories create ugc --repository-format=docker --location=europe-west4
gcloud artifacts repositories set-cleanup-policies ugc --location=europe-west4   --policy=deploy/gcp/ar-cleanup-policy.json --no-dry-run
gcloud auth configure-docker europe-west4-docker.pkg.dev

# Service accounts; each may sign URLs only as itself (IAM signBlob, no key files)
for sa in ugc-api ugc-worker; do
  gcloud iam service-accounts create $sa
  gcloud iam service-accounts add-iam-policy-binding $sa@ugc-ad-builder.iam.gserviceaccount.com     --member=serviceAccount:$sa@ugc-ad-builder.iam.gserviceaccount.com --role=roles/iam.serviceAccountTokenCreator
done

# Private bucket in the EU; jobs/* deleted after 30 days (RETENTION_DAYS)
gcloud storage buckets create gs://ugc-ad-builder-media --location=europe-west4   --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://ugc-ad-builder-media --lifecycle-file=deploy/gcp/bucket-lifecycle.json
for sa in ugc-api ugc-worker; do
  gcloud storage buckets add-iam-policy-binding gs://ugc-ad-builder-media     --member=serviceAccount:$sa@ugc-ad-builder.iam.gserviceaccount.com --role=roles/storage.objectAdmin
done

# Secrets from backend/.env (values piped on stdin, never printed), stored in europe-west4
python backend/scripts/put_secrets.py
# Each service account can read only what it needs:
#   ugc-worker: fal-key, database-url      ugc-api: openai-api-key, database-url, access-codes
gcloud secrets add-iam-policy-binding fal-key   --member=serviceAccount:ugc-worker@ugc-ad-builder.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
# (same for the other four pairs)

# Image
TAG=$(git rev-parse --short HEAD)
IMAGE=europe-west4-docker.pkg.dev/ugc-ad-builder/ugc/backend:$TAG
docker build -f backend/Dockerfile -t $IMAGE . && docker push $IMAGE

# Worker job: 45-minute task timeout, 1 retry, one task
gcloud run jobs deploy ugc-worker --image=$IMAGE --command=python --args=-m,app.worker   --tasks=1 --parallelism=1 --task-timeout=45m --max-retries=1 --memory=1Gi --cpu=1   --service-account=ugc-worker@ugc-ad-builder.iam.gserviceaccount.com   --env-vars-file=deploy/gcp/worker.env.yaml   --set-secrets=FAL_KEY=fal-key:latest,DATABASE_URL=database-url:latest

# API service: scales to zero, at most 2 instances; no fal key (it never renders)
gcloud run deploy ugc-api --image=$IMAGE --allow-unauthenticated   --min-instances=0 --max-instances=2 --memory=1Gi --cpu=1 --timeout=300   --service-account=ugc-api@ugc-ad-builder.iam.gserviceaccount.com   --env-vars-file=deploy/gcp/api.env.yaml   --set-secrets=OPENAI_API_KEY=openai-api-key:latest,DATABASE_URL=database-url:latest,ACCESS_CODES=access-codes:latest

# The API may start the worker job, without overrides, and nothing else
gcloud run jobs add-iam-policy-binding ugc-worker   --member=serviceAccount:ugc-api@ugc-ad-builder.iam.gserviceaccount.com --role=roles/run.jobsExecutor
```

Non-secret settings live in `deploy/gcp/api.env.yaml` and `deploy/gcp/worker.env.yaml`. Use those files rather than `--set-env-vars`: on Windows gcloud runs through `cmd`, which eats the `^` in gcloud's custom-delimiter syntax.

A new release: build and push a new tag, then `gcloud run jobs update ugc-worker --image=$IMAGE` and `gcloud run deploy ugc-api --image=$IMAGE`.

API: https://ugc-api-1002867777166.europe-west4.run.app (docs at `/docs`).

Frontend: the Vercel project `ugc-creator` (root directory `frontend`, Vite). Settings as of 19 Nov 2026:
- `VITE_API_BASE_URL` = the API URL, set for **Production** and for **Preview on the `v2` branch**. `VITE_` values are baked in at build time: after changing one, redeploy without build cache.
- `VITE_N8N_WEBHOOK_URL` (v1) deleted in all environments.
- Vercel Authentication (deployment protection) is off, so previews are public; generation still needs the access code.
- Production: https://ugc-creator-delta.vercel.app. Stable `v2` preview: https://ugc-creator-git-v2-aimilios-projects-21450502.vercel.app.

Every site that calls the API must be listed in `CORS_ORIGINS` in `deploy/gcp/api.env.yaml` (today: production and the `v2` preview), then applied with `gcloud run services update ugc-api --env-vars-file=deploy/gcp/api.env.yaml` plus the same `--set-secrets` as above.

### M2 deploy (not run yet; each step with the owner's go)

1. Apply the schema to Neon (`scripts/apply_schema.py`): new tables `campaigns`, `brand_kits`, `variants`; new stage, asset and cache kinds (including the `continuity` and `shorten` stages, D30); `jobs.phase` (D27). Scene ids, notes, continuity and the start/end notes live in the storyboard JSON (no schema change).
2. The worker now makes the voiceover, so it needs the OpenAI key: grant `ugc-worker` `roles/secretmanager.secretAccessor` on `openai-api-key` and add `OPENAI_API_KEY=openai-api-key:latest` to the job's `--set-secrets` ([D26](../DECISIONS.md)).
3. Set `RENDER_SCENES: "5"` in both `deploy/gcp/*.env.yaml` (the most scenes rendered, D28; pinned to 1 until then, [D25](../DECISIONS.md)), build the image (it now installs ffmpeg) and update the job and the service. The new API changes what the live site talks to (pictures, then video), so the M2 frontend goes live with it.
4. One paid smoke run of a full 3-scene ad (about 1.05 EUR), with the owner's go and limit.

### Rotate the access code
Never print or commit the code.
1. Generate a new random code and write it as `ACCESS_CODES=` in `backend/.env` (a script, not by hand on screen).
2. `python backend/scripts/put_secrets.py` adds it as a new version of the `access-codes` secret.
3. `gcloud run services update ugc-api --region=europe-west4 --update-secrets=ACCESS_CODES=access-codes:latest --revision-suffix=<new>` so the API reads the new version.
4. Check that `POST /access/check` accepts the new code and refuses the old one, then disable the old version: `gcloud secrets versions disable <old> --secret=access-codes`.

### v1 site
The v1 build stays online at https://ugc-creator-4a20yqpyc-aimilios-projects-21450502.vercel.app (tag `v1-final`; screenshots in `docs/before-after/v1/`).

## GitHub: CI and the ruleset on `main`

CI (`.github/workflows/ci.yml`) runs the jobs `frontend`, `backend` and `docker` on every push and PR, on a pinned `ubuntu-24.04` runner with `actions/checkout@v7`, `actions/setup-python@v7` and `actions/setup-node@v7` ([D23](../DECISIONS.md)). When GitHub announces a new runner image or action major, update them in one commit and check that the run has no annotations.

The ruleset "main protection" (id `27687215`, created 19 Nov 2026 with `gh api`, [D23](../DECISIONS.md)) applies to `refs/heads/main` only:
- force pushes blocked (`non_fast_forward`) and deletion blocked;
- required status checks `frontend`, `backend` and `docker` from GitHub Actions (integration id 15368), and the branch must be up to date before merging (strict);
- no required reviews and an empty bypass list, so it applies to the owner too.

It was created with:
```bash
gh api -X POST repos/Aimilios94/UGC-Creator/rulesets --input ruleset.json
```
where `ruleset.json` holds `name`, `target: branch`, `enforcement: active`, `conditions.ref_name.include: ["refs/heads/main"]`, `bypass_actors: []` and the three rules above. Check it with `gh api repos/Aimilios94/UGC-Creator/rules/branches/main`. A history rewrite on `main` needs the ruleset lifted first (`gh api -X PUT repos/Aimilios94/UGC-Creator/rulesets/27687215 -f enforcement=disabled`), only with the owner's explicit go, and turned back on afterwards.

## Scheduled jobs (from M2)

The cleanup and stale-job sweep run from a GitHub Actions cron every 15 minutes at an odd minute ([D6](../DECISIONS.md)). GitHub disables scheduled workflows in public repositories after 60 days without repository activity; re-enable it in the Actions tab if that happens.
