"""An ad with no product photo (strategy plan A6, phase 6): the photo is optional, nothing is read
from it, the pictures are made from the brief's words, the ad's first picture is the product's
reference for the later ones, and the clips say "product as described", never "as in the photo"."""

from __future__ import annotations

import pytest

from app import worker
from app.models import Scene
from app.services.image_gen import FROM_FIRST, plan_scene_image
from app.services.providers.media import InputImage
from conftest import BRIEF
from helpers import create_job, separate_shots, to_video

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

MUG = {
    **BRIEF,
    "product_name": "Lumo travel mug",
    "description": "Matte green steel travel mug with a leak-proof lid. Keeps coffee hot for 12 hours.",
    "story": (
        "A woman in a yellow raincoat waits at a bus stop at dawn. She sips from her matte green travel mug.\n\n"
        "Close-up of the mug in her hand, steam rising from the open lid.\n\n"
        "She steps onto the bus, mug in hand."
    ),
}


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


def test_the_picture_prompt_with_no_photo_describes_the_product_and_then_follows_the_first_picture():
    sc = Scene(role="demo", description="A mug on a bench", image_prompt="A mug on a bench at dawn", motion_prompt="")
    kw = dict(model="edit", text_model="text", aspect_ratio="9:16", seed=1, scene=sc,
              product_text="Lumo travel mug: matte green steel")  # fmt: skip
    first = plan_scene_image(product=None, product_sha256="", **kw)
    assert first.request.model == "text" and first.request.input_image is None
    prompt = first.request.arguments["prompt"]
    assert "exactly as described: Lumo travel mug: matte green steel" in prompt
    assert "reference photo" not in prompt.lower() and "as in the photo" not in prompt
    face = InputImage(data=b"f", content_type="image/jpeg")
    ignored = plan_scene_image(product=None, product_sha256="", people=[("P1", face, "f")], in_photo=["P1"], **kw)
    assert not ignored.request.extra_images and "Reference photo" not in ignored.request.arguments["prompt"]
    pic = InputImage(data=b"p", content_type="image/jpeg")
    later = plan_scene_image(product=pic, product_sha256="p1", product_from="picture", **kw)
    assert later.request.model == "edit" and later.request.input_image is pic
    assert "this ad's first picture: keep the product exactly as it is there" in later.request.arguments["prompt"]
    assert FROM_FIRST.format(product="x").count("{") == 0


def test_an_ad_with_no_photo_is_made_from_the_brief(client, ctx, session_id):
    r = create_job(client, session_id, None, brief=MUG)
    assert r.status_code == 201, r.text
    job = r.json()
    if job["storyboard"] is None:  # the quick questions: let the AI decide
        job = client.post(f"/jobs/{job['id']}/answers", json={"skip": True}, headers=_h(session_id)).json()
    assert job["has_photo"] is False and job["analysis"] is None
    assert not any(s["stage"] == "analyze" for s in job["stages"])  # nothing to read, nothing paid
    structure = job["storyboard"]["structure"]
    assert structure["has_photo"] is False and "matte green steel" in structure["sheet"]["product"]["value"].lower()
    assert all("as in the photo" not in c["text"] for c in job["clips"])
    assert any("product as described above" in c["text"] for c in job["clips"])

    board = job["storyboard"]
    board["scenes"][0]["image_source"] = "product"  # there is no product photo to use
    bad = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=_h(session_id))
    assert bad.status_code == 422 and "no product photo" in bad.json()["detail"]
    board["scenes"][0]["image_source"] = "generate"

    separate_shots(client, session_id, job)  # every shot its own picture
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    assert done["status"] == "done", done.get("last_error")
    pictures = [r for r in ctx.media.submits if r.kind == "image"]
    first, later = pictures[0], pictures[1:]
    assert first.model == ctx.settings.text_image_model and first.input_image is None
    assert later and all(r.model == ctx.settings.image_model and r.input_image is not None for r in later)
    assert all("this ad's first picture" in r.arguments["prompt"] for r in later)
    assert not any("as in the photo" in r.arguments["prompt"] for r in pictures)


def test_with_no_photo_a_short_brief_is_refused(client, session_id):
    r = create_job(client, session_id, None, brief={**BRIEF, "description": "          "})
    assert r.status_code == 422
