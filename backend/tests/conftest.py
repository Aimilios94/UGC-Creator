"""Test setup: mock providers only, no real network, a throwaway Postgres.

Safety first, before the app is imported:
- every provider is forced to mock and every key/URL from backend/.env is blanked
  (environment variables override the .env file), so a test can never reach a paid API;
- a socket guard refuses any connection that is not to this machine;
- Pydantic AI's ALLOW_MODEL_REQUESTS is off.

Database tests need TEST_DATABASE_URL (CI sets it to its Postgres service container;
locally: docker run -p 55432:5432 pgvector/pgvector:pg18). Without it they are skipped.
"""

from __future__ import annotations

import os
import socket
import uuid

import pytest

_SAFE_ENV = {
    "APP_ENV": "local",
    "LLM_PROVIDER": "mock",
    "MEDIA_PROVIDER": "mock",
    "STORAGE_PROVIDER": "local",
    "JOB_RUNNER": "local",
    "OPENAI_API_KEY": "",
    "FAL_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "DATABASE_URL": "",
    "DATABASE_URL_DIRECT": "",
    "GCS_BUCKET": "",
    "ACCESS_CODES": "",
    "SENTRY_DSN": "",
    "LANGSMITH_TRACING": "false",
    "ASSET_SIGNING_SECRET": "test-signing-secret",
}
os.environ.update(_SAFE_ENV)

from pydantic_ai import models as pai_models  # noqa: E402

pai_models.ALLOW_MODEL_REQUESTS = False

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}
_real_connect = socket.socket.connect
_real_create_connection = socket.create_connection


class RealNetworkBlocked(RuntimeError):
    pass


def _host_of(address) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def _guarded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and _host_of(address) not in _LOCAL_HOSTS:
        raise RealNetworkBlocked(f"tests may not open network connections (to {_host_of(address)})")
    return _real_connect(self, address)


def _guarded_create_connection(address, *args, **kwargs):
    if _host_of(address) not in _LOCAL_HOSTS:
        raise RealNetworkBlocked(f"tests may not open network connections (to {_host_of(address)})")
    return _real_create_connection(address, *args, **kwargs)


socket.socket.connect = _guarded_connect
socket.create_connection = _guarded_create_connection

from app.config import Settings, get_settings  # noqa: E402
from app.repository import Database  # noqa: E402
from app.services.pipeline import Context  # noqa: E402
from app.services.providers.llm import build_llm  # noqa: E402
from app.services.providers.media import MockMedia  # noqa: E402
from app.services.providers.storage import LocalStorage  # noqa: E402

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
TABLES = ["llm_calls", "media_cache", "assets", "stage_runs", "scenes", "jobs"]


def make_settings(**overrides) -> Settings:
    base = dict(
        _env_file=None,
        app_env="local",
        llm_provider="mock",
        media_provider="mock",
        storage_provider="local",
        job_runner="local",
        asset_signing_secret="test-signing-secret",
        database_url=TEST_DB_URL,
        media_poll_interval_s=0,
        worker_poll_interval_s=0,
        db_connect_retries=2,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(scope="session")
def schema_applied():
    if not TEST_DB_URL:
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_URL must be set in CI: database tests may not be skipped")
        pytest.skip("TEST_DATABASE_URL not set")
    from scripts.apply_schema import apply

    apply(TEST_DB_URL)
    return True


@pytest.fixture
def db(schema_applied) -> Database:
    database = Database(TEST_DB_URL, retries=2, sleep=lambda s: None)
    with database.tx() as c:
        c.execute("truncate " + ", ".join(TABLES) + " cascade")
    return database


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "files", secret="test-signing-secret", public_base_url="http://testserver")


@pytest.fixture
def media() -> MockMedia:
    return MockMedia()


@pytest.fixture
def ctx(settings, db, storage, media) -> Context:
    return Context(
        settings=settings,
        db=db,
        storage=storage,
        media=media,
        llm_factory=lambda task: build_llm(settings, task),
        sleep=lambda s: None,
    )


@pytest.fixture
def client(ctx):
    from fastapi.testclient import TestClient

    from app.deps import get_ctx
    from app.main import app

    app.dependency_overrides[get_ctx] = lambda: ctx
    app.dependency_overrides[get_settings] = lambda: ctx.settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def new_session() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:8]


@pytest.fixture
def session_id() -> str:
    return new_session()


@pytest.fixture
def photo_bytes() -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", (800, 1000), (200, 40, 40))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


BRIEF = {
    "product_name": "Grip Socks Pro",
    "description": "Anti-slip football grip socks that keep your foot locked inside the boot.",
    "audience": "Amateur football players aged 16-35",
    "offer": "10% off with code KICK10",
    "landing_url": "https://example.com/grip-socks",
    "platform": "tiktok",
    "aspect_ratio": "9:16",
}
