# One image for the API (Cloud Run service) and the worker (Cloud Run Job).
# Build from the repo root:  docker build -f backend/Dockerfile -t ugc-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY db/schema.sql /db/schema.sql

# Non-root; /data is the local-storage folder in Compose (Cloud Run uses GCS).
RUN useradd --uid 10001 --no-create-home app && mkdir -p /data && chown app /data
USER app

# API by default. The worker runs the same image with: python -m app.worker
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
