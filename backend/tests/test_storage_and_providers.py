"""Storage signing, the fal provider's request shape (against a fake client), the worker trigger,
and the guardrail that tests run with mock providers and no real network."""

from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.errors import ProviderNotConfigured
from app.services import job_trigger
from app.services.providers.media import FalMedia, InputImage, MediaFailed, MediaRequest, build_media
from app.services.providers.storage import LocalStorage, check_key


# --- storage ---------------------------------------------------------------------------
def test_signed_url_verifies_until_it_expires(tmp_path):
    now = [1_000_000.0]
    s = LocalStorage(tmp_path, secret="k", public_base_url="http://api", clock=lambda: now[0])
    url = s.signed_url("jobs/a/upload.jpg", ttl_s=60)
    q = httpx.URL(url).params
    exp, sig = int(q["exp"]), q["sig"]
    assert s.verify("jobs/a/upload.jpg", exp, sig)
    assert not s.verify("jobs/b/upload.jpg", exp, sig)  # signature is bound to the key
    now[0] += 61
    assert not s.verify("jobs/a/upload.jpg", exp, sig)


def test_storage_keys_cannot_escape_the_root(tmp_path):
    for bad in ["../etc/passwd", "/abs", "a//b", "jobs/../../x", ""]:
        with pytest.raises(ValueError):
            check_key(bad)
    s = LocalStorage(tmp_path, secret="k", public_base_url="http://api")
    s.put("jobs/x/a.txt", b"hi", "text/plain")
    assert s.get("jobs/x/a.txt") == b"hi"
    assert s.provider_url("jobs/x/a.txt", 60) is None


def test_local_storage_needs_a_signing_secret(tmp_path):
    with pytest.raises(ProviderNotConfigured):
        LocalStorage(tmp_path, secret="", public_base_url="http://api")


# --- fal provider (fake client: no network) --------------------------------------------
class FakeFal:
    def __init__(self):
        self.submitted = []
        self.uploads = []

    def upload(self, data, content_type, lifecycle=None):
        self.uploads.append((len(data), content_type, lifecycle))
        return "https://v3.fal.media/files/fake/input.jpg"

    def submit(self, model, args, headers=None):
        self.submitted.append((model, args, headers))
        return SimpleNamespace(request_id="req-123")

    def status(self, model, request_id):
        import fal_client

        return fal_client.Completed(logs=None, metrics={}, error="NSFW", error_type="content_policy")

    def result(self, model, request_id):
        return {"images": [{"url": "https://v3.fal.media/files/out.jpg", "width": 720, "height": 1280}]}


def _req(field: str, url: str | None = None) -> MediaRequest:
    return MediaRequest(
        kind="image",
        model="fal-ai/nano-banana/edit",
        arguments={"prompt": "p"},
        input_image=InputImage(b"img", "image/jpeg", url=url),
        image_field=field,
    )


def test_fal_requests_turn_off_storage_and_expire_outputs():
    fake = FakeFal()
    fal = FalMedia("key-not-used", output_expiry_s=3600, client=fake)
    assert fal.submit(_req("image_urls")) == "req-123"
    model, args, headers = fake.submitted[0]
    assert headers["X-Fal-Store-IO"] == "0"
    assert json.loads(headers["X-Fal-Object-Lifecycle-Preference"]) == {"expiration_duration_seconds": 3600}
    assert args["image_urls"] == ["https://v3.fal.media/files/fake/input.jpg"]
    # local files go to fal's CDN with the same short expiry
    assert fake.uploads[0][2].expires_in == 3600


def test_fal_uses_a_given_url_without_uploading_and_single_image_field():
    fake = FakeFal()
    fal = FalMedia("k", client=fake)
    fal.submit(_req("image_url", url="https://storage.googleapis.com/signed"))
    assert fake.uploads == []
    assert fake.submitted[0][1]["image_url"] == "https://storage.googleapis.com/signed"


def test_fal_completed_with_error_is_a_hard_failure():
    fal = FalMedia("k", client=FakeFal())
    with pytest.raises(MediaFailed, match="content_policy"):
        fal.status("fal-ai/nano-banana/edit", "req-123")


def test_fal_result_parsing():
    r = FalMedia("k", client=FakeFal()).result("fal-ai/nano-banana/edit", "req-123", "image")
    assert r.url.endswith("out.jpg") and (r.width, r.height) == (720, 1280)


def test_api_without_a_fal_key_gets_a_media_stand_in_that_refuses_to_render():
    from app.services.providers.media import UnavailableMedia, build_media_or_unavailable

    m = build_media_or_unavailable(Settings(_env_file=None, media_provider="fal", fal_key=""))
    assert isinstance(m, UnavailableMedia)
    with pytest.raises(ProviderNotConfigured):
        m.submit(None)


def test_real_providers_refuse_to_start_without_keys():
    with pytest.raises(ProviderNotConfigured):
        build_media(Settings(_env_file=None, media_provider="fal", fal_key=""))
    from app.services.providers.llm import build_llm

    with pytest.raises(ProviderNotConfigured):
        build_llm(Settings(_env_file=None, llm_provider="openai", openai_api_key=""), "analyze")


# --- worker trigger ----------------------------------------------------------------------
def test_cloud_run_trigger_starts_the_job_with_no_overrides():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"name": "operations/x"})

    s = Settings(
        _env_file=None,
        job_runner="cloudrun",
        cloud_run_job_name="ugc-worker",
        gcp_project_id="ugc-ad-builder",
        gcp_region="europe-west4",
    )
    job_trigger.trigger_worker(s, http=httpx.Client(transport=httpx.MockTransport(handler)), token="tok")
    assert seen["url"] == (
        "https://run.googleapis.com/v2/projects/ugc-ad-builder/locations/europe-west4/jobs/ugc-worker:run"
    )
    assert json.loads(seen["body"]) == {}
    assert seen["auth"] == "Bearer tok"


def test_local_trigger_is_a_no_op():
    job_trigger.trigger_worker(Settings(_env_file=None, job_runner="local"))


# --- guardrail: CI runs with mock providers and makes no real provider calls -------------
def test_tests_run_on_mock_providers_with_no_keys():
    from app.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.llm_provider == "mock" and s.media_provider == "mock"
    assert s.openai_api_key == "" and s.fal_key == "" and s.anthropic_api_key == ""
    assert s.database_url == ""  # never the hosted database


def test_real_network_is_blocked():
    from conftest import RealNetworkBlocked

    with pytest.raises(RealNetworkBlocked):
        socket.create_connection(("api.openai.com", 443), timeout=1)
    with pytest.raises(RealNetworkBlocked):
        httpx.get("https://queue.fal.run/fal-ai/nano-banana/edit", timeout=1)


def test_pydantic_ai_model_requests_are_disabled():
    from pydantic_ai import models

    assert models.ALLOW_MODEL_REQUESTS is False
