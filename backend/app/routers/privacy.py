"""Delete my data (plan §11, M2 item 6, D34): everything this browser session made, at once.

No access code is needed: deleting your own data is never gated. Only the session that made
the data can delete it, and another session's data is never touched.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_ctx, session_hash
from ..models import DeletedData
from ..services.cleanup import SessionBusy, delete_my_data
from ..services.pipeline import Context

router = APIRouter(tags=["privacy"])


@router.delete("/my-data", response_model=DeletedData)
def delete_my_data_endpoint(ctx: Context = Depends(get_ctx), sess: str = Depends(session_hash)) -> DeletedData:
    """Delete this browser's ads (with every picture, clip and video), brand kit, logo and campaigns.
    Refused with 409 while one of its ads is being made: wait for it to finish, then delete."""
    try:
        out = delete_my_data(ctx, sess)
    except SessionBusy:
        raise HTTPException(
            status_code=409,
            detail="One of your ads is being made. Wait until it is finished, then delete your data.",
        ) from None
    return DeletedData(**out)
