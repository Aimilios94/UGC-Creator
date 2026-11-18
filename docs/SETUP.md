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

On this Windows machine the user environment sets `CURL_CA_BUNDLE=NUL`, which leaves gcloud's Python with no CA certificates. Run gcloud with that variable cleared (Git Bash: `env -u CURL_CA_BUNDLE gcloud ...`; PowerShell: `$env:CURL_CA_BUNDLE = $null`). gcloud is installed per user in `%LOCALAPPDATA%\google-cloud-sdk`.

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

Frontend: the Vercel project `ugc-creator` (root directory `frontend`) with `VITE_API_BASE_URL` set to the API URL. Every site that calls the API must be listed in `CORS_ORIGINS` in `deploy/gcp/api.env.yaml`.

## Scheduled jobs (from M2)

The cleanup and stale-job sweep run from a GitHub Actions cron every 15 minutes at an odd minute ([D6](../DECISIONS.md)). GitHub disables scheduled workflows in public repositories after 60 days without repository activity; re-enable it in the Actions tab if that happens.
