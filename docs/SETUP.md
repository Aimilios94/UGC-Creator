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

Project `ugc-ad-builder`, region `europe-west4`. No service-account key files: `gcloud auth login` locally, service accounts on Cloud Run ([D16](../DECISIONS.md)). These commands are run once in M1 and are checked when they run.

```bash
gcloud config set project ugc-ad-builder
gcloud config set run/region europe-west4
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  iamcredentials.googleapis.com storage.googleapis.com

# Image registry
gcloud artifacts repositories create ugc --repository-format=docker --location=europe-west4
gcloud auth configure-docker europe-west4-docker.pkg.dev

# Service accounts: the API may only start the job; both sign URLs via IAM (no keys)
gcloud iam service-accounts create ugc-api
gcloud iam service-accounts create ugc-worker
for sa in ugc-api ugc-worker; do
  gcloud iam service-accounts add-iam-policy-binding $sa@ugc-ad-builder.iam.gserviceaccount.com \
    --member=serviceAccount:$sa@ugc-ad-builder.iam.gserviceaccount.com --role=roles/iam.serviceAccountTokenCreator
done

# Private bucket in the EU
gcloud storage buckets create gs://ugc-ad-builder-media --location=europe-west4 \
  --uniform-bucket-level-access --public-access-prevention
for sa in ugc-api ugc-worker; do
  gcloud storage buckets add-iam-policy-binding gs://ugc-ad-builder-media \
    --member=serviceAccount:$sa@ugc-ad-builder.iam.gserviceaccount.com --role=roles/storage.objectAdmin
done

# Secrets (values are read from backend/.env by a script, never typed or echoed):
#   fal-key, openai-api-key, database-url, access-codes
# each granted roles/secretmanager.secretAccessor for the service account that needs it.

# Image
TAG=$(git rev-parse --short HEAD)
IMAGE=europe-west4-docker.pkg.dev/ugc-ad-builder/ugc/backend:$TAG
docker build -f backend/Dockerfile -t $IMAGE . && docker push $IMAGE

# Worker job: 45-minute task timeout, 1 retry
gcloud run jobs deploy ugc-worker --image=$IMAGE --command=python --args=-m,app.worker \
  --task-timeout=45m --max-retries=1 --service-account=ugc-worker@ugc-ad-builder.iam.gserviceaccount.com \
  --set-env-vars=APP_ENV=prod,STORAGE_PROVIDER=gcs,GCS_BUCKET=ugc-ad-builder-media,LLM_PROVIDER=openai,MEDIA_PROVIDER=fal \
  --set-secrets=FAL_KEY=fal-key:latest,OPENAI_API_KEY=openai-api-key:latest,DATABASE_URL=database-url:latest

# API service
gcloud run deploy ugc-api --image=$IMAGE --allow-unauthenticated \
  --service-account=ugc-api@ugc-ad-builder.iam.gserviceaccount.com \
  --set-env-vars=APP_ENV=prod,JOB_RUNNER=cloudrun,CLOUD_RUN_JOB_NAME=ugc-worker,STORAGE_PROVIDER=gcs,GCS_BUCKET=ugc-ad-builder-media,CORS_ORIGINS=https://ugc-creator-delta.vercel.app \
  --set-secrets=OPENAI_API_KEY=openai-api-key:latest,DATABASE_URL=database-url:latest,ACCESS_CODES=access-codes:latest

# The API may start the worker job, without overrides, and nothing else
gcloud run jobs add-iam-policy-binding ugc-worker \
  --member=serviceAccount:ugc-api@ugc-ad-builder.iam.gserviceaccount.com --role=roles/run.jobsExecutor
```

Frontend: the existing Vercel project `ugc-creator` (root directory `frontend`) with `VITE_API_BASE_URL` set to the Cloud Run API URL.

## Scheduled jobs (from M2)

The cleanup and stale-job sweep run from a GitHub Actions cron every 15 minutes at an odd minute ([D6](../DECISIONS.md)). GitHub disables scheduled workflows in public repositories after 60 days without repository activity; re-enable it in the Actions tab if that happens.
