"""The scheduled cleanup and stale-job sweep (plan §8, M2 item 6, D6, D34).

Called by the GitHub Actions cron every 15 minutes with the secret token in `X-Admin-Token`.
Without the token configured on the server the endpoint is off (503); a wrong or missing token
is refused (401), compared in constant time.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from ..deps import get_ctx
from ..models import CleanupResult
from ..services.cleanup import run_cleanup
from ..services.pipeline import Context

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/cleanup", response_model=CleanupResult)
def cleanup(ctx: Context = Depends(get_ctx), x_admin_token: str | None = Header(default=None)) -> CleanupResult:
    """Sweep stale jobs, delete ads past the retention period and unused brand data."""
    expected = ctx.settings.admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="Cleanup is not configured on this server.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="A valid X-Admin-Token header is required.")
    return CleanupResult(**run_cleanup(ctx))
