"""Campaign brief and brand kit (plan §9, §11): private to the browser session, the brief's
goal/theme/ad type validated, and each ad keeps a snapshot of the brand kit."""

from __future__ import annotations

import io

from PIL import Image

from app.services.providers.llm import LlmHandle, build_llm, mock_storyboard
from conftest import BRIEF, new_session
from helpers import approve, create_job


def _h(session_id: str, code: str | None = None) -> dict:
    h = {"X-Session-Id": session_id}
    if code:
        h["X-Access-Code"] = code
    return h


def _png_with_alpha() -> bytes:
    img = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    img.paste((255, 200, 0, 255), (20, 20, 280, 100))
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=_pnginfo())
    return buf.getvalue()


def _pnginfo():
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Author", "someone@example.com")
    return info


# --- brief fields -------------------------------------------------------------------
def test_goal_theme_and_ad_type_are_stored_and_validated(client, session_id, photo_bytes):
    brief = {**BRIEF, "goal": "sales", "theme": "sport", "ad_type": "product_demo"}
    job = create_job(client, session_id, photo_bytes, brief=brief).json()
    assert (job["brief"]["goal"], job["brief"]["theme"], job["brief"]["ad_type"]) == ("sales", "sport", "product_demo")
    bad = create_job(client, session_id, photo_bytes, brief={**BRIEF, "theme": "cars"})
    assert bad.status_code == 422


# --- campaigns ----------------------------------------------------------------------
def test_the_first_ad_creates_a_campaign_and_later_ads_join_it(client, session_id, photo_bytes):
    brief = {**BRIEF, "goal": "traffic"}
    first = create_job(client, session_id, photo_bytes, brief=brief, extra={"campaign_name": "Spring kit"}).json()
    cid = first["campaign_id"]
    assert cid
    second = create_job(client, session_id, photo_bytes, extra={"campaign_id": cid}).json()
    assert second["campaign_id"] == cid
    listed = client.get("/campaigns", headers=_h(session_id)).json()
    assert len(listed) == 1
    c = listed[0]
    assert (c["name"], c["goal"], c["offer"], c["ads"]) == ("Spring kit", "traffic", BRIEF["offer"], 2)
    assert c["landing_url"] == BRIEF["landing_url"]


def test_a_campaign_is_named_after_the_product_by_default(client, session_id, photo_bytes):
    create_job(client, session_id, photo_bytes)
    assert client.get("/campaigns", headers=_h(session_id)).json()[0]["name"] == BRIEF["product_name"]


def test_another_session_cannot_see_or_use_a_campaign(client, session_id, photo_bytes):
    cid = create_job(client, session_id, photo_bytes).json()["campaign_id"]
    other = new_session()
    assert client.get("/campaigns", headers=_h(other)).json() == []
    r = create_job(client, other, photo_bytes, extra={"campaign_id": cid})
    assert r.status_code == 404
    assert create_job(client, other, photo_bytes, extra={"campaign_id": "not-a-uuid"}).status_code == 404


# --- brand kit ----------------------------------------------------------------------
KIT = {
    "tone": "energetic",
    "colors": {"primary": "#ff6600", "secondary": "#111111", "background": "#ffffff"},
    "font": "Bebas Neue",
}


def test_brand_kit_is_saved_once_per_session(client, session_id):
    assert client.get("/brand-kit", headers=_h(session_id)).json() is None
    saved = client.put("/brand-kit", json=KIT, headers=_h(session_id)).json()
    assert (saved["tone"], saved["font"], saved["colors"]["primary"]) == ("energetic", "Bebas Neue", "#ff6600")
    again = client.put("/brand-kit", json={**KIT, "tone": "calm"}, headers=_h(session_id)).json()
    assert again["tone"] == "calm"
    assert client.get("/brand-kit", headers=_h(session_id)).json()["tone"] == "calm"
    assert client.get("/brand-kit", headers=_h(new_session())).json() is None  # private to the session


def test_brand_kit_values_are_validated(client, session_id):
    assert (
        client.put("/brand-kit", json={**KIT, "colors": {"primary": "red"}}, headers=_h(session_id)).status_code == 422
    )
    assert client.put("/brand-kit", json={**KIT, "font": "Comic Sans"}, headers=_h(session_id)).status_code == 422
    assert client.put("/brand-kit", json={**KIT, "tone": "angry"}, headers=_h(session_id)).status_code == 422


def test_logo_upload_keeps_transparency_and_strips_metadata(client, ctx, session_id):
    r = client.post(
        "/brand-kit/logo", files={"logo": ("logo.png", _png_with_alpha(), "image/png")}, headers=_h(session_id)
    )
    assert r.status_code == 200, r.text
    kit = repo_kit(ctx, session_id)
    assert kit["logo_key"].startswith("brand/") and kit["logo_key"].endswith(".png")
    data = ctx.storage.get(kit["logo_key"])
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0
        assert "Author" not in im.info
    assert r.json()["logo_url"]
    bad = client.post("/brand-kit/logo", files={"logo": ("x.svg", b"<svg/>", "image/svg+xml")}, headers=_h(session_id))
    assert bad.status_code == 422


def repo_kit(ctx, session_id):
    import hashlib

    from app import repository as repo

    return repo.get_brand_kit(ctx.db, hashlib.sha256(session_id.encode()).hexdigest())


def test_saving_the_brand_kit_needs_the_access_code_when_codes_are_set(client, ctx, session_id):
    ctx.settings = ctx.settings.model_copy(update={"access_codes": "letmein-2026"})
    assert client.put("/brand-kit", json=KIT, headers=_h(session_id)).status_code == 403
    logo = {"logo": ("logo.png", _png_with_alpha(), "image/png")}
    assert client.post("/brand-kit/logo", files=logo, headers=_h(session_id)).status_code == 403
    assert client.put("/brand-kit", json=KIT, headers=_h(session_id, "letmein-2026")).status_code == 200
    assert client.get("/brand-kit", headers=_h(session_id)).status_code == 200  # reading needs no code


def test_an_ad_keeps_a_snapshot_of_the_brand_kit_and_uses_its_tone(client, ctx, session_id, photo_bytes):
    client.put("/brand-kit", json=KIT, headers=_h(session_id))
    prompts: list[str] = []
    real = build_llm(ctx.settings, "storyboard")

    from pydantic_ai import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def respond(messages, info):
        prompts.append("\n".join(str(getattr(p, "content", "")) for m in messages for p in getattr(m, "parts", [])))
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=mock_storyboard(BRIEF))])

    handle = LlmHandle(model=FunctionModel(respond), provider="mock", model_name=real.model_name, settings={})
    ctx.llm_factory = lambda task: handle if task == "storyboard" else build_llm(ctx.settings, task)

    job = create_job(client, session_id, photo_bytes, extra={"use_brand_kit": "true"}).json()
    assert job["brand"]["tone"] == "energetic" and job["brand"]["font"] == "Bebas Neue"
    assert "logo_key" not in job["brand"]  # storage keys are not exposed
    assert '<brand>{"tone_of_voice": "energetic"}</brand>' in prompts[0]

    client.put("/brand-kit", json={**KIT, "tone": "calm"}, headers=_h(session_id))
    after = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    assert after["brand"]["tone"] == "energetic"  # a later edit never changes a planned ad

    plain = create_job(client, session_id, photo_bytes).json()
    assert plain["brand"] is None  # the kit is applied only when asked
    assert approve(client, session_id, job["id"]).status_code == 202
