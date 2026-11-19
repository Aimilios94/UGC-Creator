"""Signed, expiring file URLs for local storage. (GCS serves its own signed URLs.)"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ..deps import get_ctx
from ..services.pipeline import Context, content_type_for
from ..services.providers.storage import LocalStorage

router = APIRouter(tags=["assets"])


@router.get("/assets/{key:path}")
def get_asset(key: str, exp: int, sig: str, ctx: Context = Depends(get_ctx)) -> Response:
    storage = ctx.storage
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status_code=404)
    try:
        valid = storage.verify(key, exp, sig)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=403, detail="This link has expired or is not valid.")
    try:
        data = storage.get(key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404) from None
    return Response(content=data, media_type=content_type_for(key), headers={"Cache-Control": "private, max-age=60"})
