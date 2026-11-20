"""Brand kit: logo, colours, font and tone, set once per browser session and reused (plan §9).

Each ad takes a snapshot of the kit when its brief is sent, so editing the kit never
changes an ad already planned. Saving needs the access code on the public deployment,
like generation, so the bucket cannot be used as free file hosting.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import repository as repo
from ..deps import get_ctx, require_access_code, session_hash
from ..errors import UploadRejected
from ..models import BrandKit, BrandKitView
from ..services.pipeline import Context
from ..services.uploads import sanitise_image

router = APIRouter(prefix="/brand-kit", tags=["brand kit"])

LOGO_MAX_SIDE_PX = 1024


def brand_kit_view(ctx: Context, row: dict) -> BrandKitView:
    ttl = ctx.settings.signed_url_ttl_seconds
    return BrandKitView(
        tone=row["tone"],
        colors=row["colors"] or {},
        font=row["font"],
        logo_url=ctx.storage.signed_url(row["logo_key"], ttl) if row["logo_key"] else None,
        updated_at=row["updated_at"].isoformat(),
    )


@router.get("")
def get_brand_kit(sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> BrandKitView | None:
    row = repo.get_brand_kit(ctx.db, sess)
    return brand_kit_view(ctx, row) if row else None


@router.put("", dependencies=[Depends(require_access_code)])
def save_brand_kit(kit: BrandKit, sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> BrandKitView:
    row = repo.save_brand_kit(ctx.db, sess, tone=kit.tone, colors=kit.colors.model_dump(mode="json"), font=kit.font)
    return brand_kit_view(ctx, row)


@router.post("/logo", dependencies=[Depends(require_access_code)])
def upload_logo(
    logo: UploadFile = File(...), sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)
) -> BrandKitView:
    """PNG (transparency kept), JPEG or WebP; metadata stripped like product photos.

    A replaced logo file is kept, because ads already planned point to it; retention
    cleanup and "delete my data" remove it."""
    s = ctx.settings
    raw = logo.file.read(s.max_upload_bytes + 1)
    try:
        clean = sanitise_image(raw, max_bytes=s.max_upload_bytes, max_side=LOGO_MAX_SIDE_PX)
    except UploadRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    key = f"brand/{sess}/logo-{uuid.uuid4().hex[:12]}.{clean.ext}"
    ctx.storage.put(key, clean.data, clean.content_type)
    return brand_kit_view(ctx, repo.set_brand_logo(ctx.db, sess, key))
