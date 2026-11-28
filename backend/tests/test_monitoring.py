"""Sentry (M2 item 5): off without a DSN, and nothing a user typed or uploaded ever leaves. DB-free."""

from __future__ import annotations

import json

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from app.config import Settings
from app.services import monitoring
from app.services.monitoring import MAX_TEXT, init_monitoring, scrub_event, scrub_text

BRIEF = "My secret sneaker launch for jane.doe@example.com, see https://shop.example.com/launch?code=42"


def test_off_without_a_dsn():
    assert init_monitoring(Settings(sentry_dsn=""), "api") is False


def test_text_loses_emails_urls_secrets_and_pydantic_echoes():
    out = scrub_text(f"bad brief: input_value='{BRIEF}' code ACCESS-1234 at www.example.com", ["ACCESS-1234"])
    assert "example.com" not in out and "jane" not in out and "ACCESS-1234" not in out
    assert "input_value=[removed]" in out and "[secret]" in out and "[url]" in out
    assert len(scrub_text("x" * 5000)) <= MAX_TEXT + len("…[cut]")


def test_event_keeps_ids_and_code_but_drops_the_request_data():
    event = {
        "event_id": "abc",
        "request": {
            "method": "POST",
            "url": "https://api.example.com/jobs/1881f435?x=1",
            "data": {"story": BRIEF},
            "headers": {"X-Access-Code": "ACCESS-1234", "X-Session-Id": "s1"},
            "cookies": {"a": "b"},
            "query_string": "x=1",
        },
        "user": {"ip_address": "1.2.3.4"},
        "extra": {"brief": BRIEF},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": f"job 1881f435 failed: {BRIEF}",
                    "stacktrace": {"frames": [{"filename": "app/services/pipeline.py", "vars": {"brief": BRIEF}}]},
                }
            ]
        },
        "breadcrumbs": {"values": [{"category": "app", "message": "mail to jane.doe@example.com"}]},
    }
    out = json.dumps(scrub_event(event, ["ACCESS-1234"]))
    for leak in ("jane.doe", "shop.example.com", "ACCESS-1234", "1.2.3.4", "s1", '"x=1"', "cookies", "vars"):
        assert leak not in out, leak
    sent = json.loads(out)
    assert sent["request"] == {"method": "POST", "url": "/jobs/1881f435"}
    assert sent["exception"]["values"][0]["type"] == "ValueError"
    assert "job 1881f435 failed" in sent["exception"]["values"][0]["value"]
    assert sent["exception"]["values"][0]["stacktrace"]["frames"][0]["filename"] == "app/services/pipeline.py"


class _Capture(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def captured(monkeypatch):
    transport = _Capture()
    real_init = sentry_sdk.init
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: real_init(transport=transport, **kw))
    yield transport
    sentry_sdk.get_client().close()
    real_init(dsn="")  # switch the SDK off again for the other tests


def test_a_real_error_goes_out_scrubbed(captured):
    settings = Settings(sentry_dsn="https://public@o1.ingest.de.sentry.io/1", access_codes="ACCESS-1234")
    assert init_monitoring(settings, "worker") is True
    brief = BRIEF  # a local variable that must not be sent

    try:
        raise RuntimeError(f"writer failed on {brief} with ACCESS-1234")
    except RuntimeError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()

    assert len(captured.events) == 1
    out = json.dumps(captured.events[0])
    assert "RuntimeError" in out and "writer failed" in out
    for leak in ("jane.doe", "shop.example.com", "ACCESS-1234", "public@o1"):
        assert leak not in out, leak
    assert captured.events[0]["tags"]["component"] == "worker"
    assert monitoring.DATA_COLLECTION["user_info"] is False
