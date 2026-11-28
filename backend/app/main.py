"""UGC Ad Builder API.

Run locally (from backend/):
    uvicorn app.main:app --reload --port 8000
Docs at http://localhost:8000/docs
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .routers import assets, brand_kit, campaigns, health, jobs, library
from .services.monitoring import init_monitoring

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
init_monitoring(settings, "api")

app = FastAPI(
    title="UGC Ad Builder API",
    version=__version__,
    description=(
        "A short brief (and, if you have one, a product photo) in; a ready-to-post UGC-style video ad out.\n\n"
        "**How to call it.** There are no accounts. Send a random `X-Session-Id` header (22 to 128 letters, "
        "digits, `-` or `_`) with every request: a job can only be read from the session that created it. "
        "The live site also needs an "
        "`X-Access-Code` header. A job runs in two steps: `POST /jobs` writes the storyboard, then "
        "`POST /jobs/{id}/approve` makes the pictures and the video. Poll `GET /jobs/{id}` for progress.\n\n"
        "**Cost.** Every job has a cost cap and the app a daily limit; a job that would pass them is refused "
        "before any paid call."
    ),
    openapi_tags=[
        {"name": "jobs", "description": "Create an ad, answer its questions, approve its storyboard, follow it."},
        {"name": "campaigns", "description": "Campaign briefs that several ads can share."},
        {"name": "brand kit", "description": "Logo, colours, font and tone, kept per browser session."},
        {"name": "library", "description": "Themes, voices and music to choose from."},
        {"name": "assets", "description": "Signed links to the pictures, clips and finished videos."},
        {"name": "health", "description": "Is the API up, and can it reach its database."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Session-Id", "X-Access-Code"],
)

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(campaigns.router)
app.include_router(brand_kit.router)
app.include_router(library.router)
app.include_router(assets.router)


@app.get("/", tags=["health"])
def root() -> dict:
    return {"app": "UGC Ad Builder", "version": __version__, "docs": "/docs", "health": "/health"}
