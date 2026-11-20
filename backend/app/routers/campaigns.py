"""Campaigns: a campaign brief groups ads (plan §11). Private to the browser session.

A campaign is created with the first ad's brief (POST /jobs without `campaign_id`);
later ads pass `campaign_id` to join it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import repository as repo
from ..deps import get_ctx, session_hash
from ..models import CampaignView
from ..services.pipeline import Context

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def campaign_view(row: dict) -> CampaignView:
    return CampaignView(
        id=str(row["id"]),
        name=row["name"],
        goal=row["goal"],
        audience=row["audience"],
        offer=row["offer"],
        landing_url=row["landing_url"],
        ads=int(row.get("ads") or 0),
        created_at=row["created_at"].isoformat(),
    )


@router.get("")
def list_campaigns(sess: str = Depends(session_hash), ctx: Context = Depends(get_ctx)) -> list[CampaignView]:
    return [campaign_view(r) for r in repo.list_campaigns(ctx.db, sess)]
