"""FastAPI dependencies: settings, the pipeline context, the browser session and the access code.

No sign-in. A browser creates a random session ID once and sends it as X-Session-Id;
the server stores only its SHA-256, and a job is reachable only from that session.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from functools import lru_cache

from fastapi import Depends, Header, HTTPException

from .config import Settings, get_settings
from .repository import Database
from .services.pipeline import Context
from .services.providers.media import build_media
from .services.providers.storage import build_storage

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")


@lru_cache
def _context() -> Context:
    s = get_settings()
    db = Database(s.database_url, connect_timeout_s=s.db_connect_timeout_s, retries=s.db_connect_retries)
    return Context(settings=s, db=db, storage=build_storage(s), media=build_media(s))


def get_ctx() -> Context:
    return _context()


def session_hash(x_session_id: str | None = Header(default=None)) -> str:
    if not x_session_id or not SESSION_RE.match(x_session_id):
        raise HTTPException(status_code=400, detail="Missing or invalid X-Session-Id header.")
    return hashlib.sha256(x_session_id.encode()).hexdigest()


def access_ok(settings: Settings, code: str | None) -> bool:
    if not settings.access_code_required:
        return True
    if not code:
        return False
    return any(hmac.compare_digest(code.encode(), c.encode()) for c in settings.access_code_list)


def require_access_code(
    x_access_code: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Generation is access-code only on the public deployment (M1-M4)."""
    if not access_ok(settings, x_access_code):
        raise HTTPException(status_code=403, detail="Generation needs an access code.")
