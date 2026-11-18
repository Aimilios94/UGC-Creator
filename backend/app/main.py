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
from .routers import assets, health, jobs

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="UGC Ad Builder API",
    version=__version__,
    description="One product photo and a short brief in; a ready-to-post UGC-style video ad out.",
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
app.include_router(assets.router)


@app.get("/", tags=["health"])
def root() -> dict:
    return {"app": "UGC Ad Builder", "version": __version__, "docs": "/docs", "health": "/health"}
