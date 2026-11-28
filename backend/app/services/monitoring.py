"""Sentry error monitoring (plan §6, M2 item 5), on only when SENTRY_DSN is set.

Privacy first (PRIVACY.md): Sentry gets the error type, the stack trace and IDs, never what a
user typed or uploaded. SDK 3 collects personal data by default, so every category is switched
off here, and `scrub_event` is a second layer that runs on every event before it leaves:
- the request keeps only its method and path (no body, headers, cookies or query string);
- emails, web addresses and the app's own secret values are replaced in every text;
- long texts are cut short, and Pydantic's echo of the input ("input_value=...") is removed,
  because a brief or a story can appear inside an error message.
No tracing, logs or replays are sent: errors only, which also keeps the free plan.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .. import __version__
from ..config import Settings

log = logging.getLogger(__name__)

MAX_TEXT = 300
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?|gs|s3|ftp)://[^\s'\"<>]+|\bwww\.[^\s'\"<>]+", re.I)
_INPUT_ECHO = re.compile(r"input_value=(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\{.*?\}|\[.*?\]|\S+)", re.S)
# Code locations are kept as they are: they never hold user text, and Sentry needs them.
_KEEP = {"filename", "abs_path", "module", "function", "package", "platform", "type", "mechanism",
         "event_id", "timestamp", "level", "logger", "release", "environment", "server_name", "category"}  # fmt: skip

# What the SDK may collect on its own: nothing personal (Sentry Python SDK 3 `data_collection`).
DATA_COLLECTION: dict[str, Any] = {
    "user_info": False,
    "cookies": {"mode": "off"},
    "http_headers": {"request": {"mode": "off"}},
    "http_bodies": [],
    "url_query_params": {"mode": "off"},
    "gen_ai": {"inputs": False, "outputs": False},
    "mcp": {"inputs": False, "outputs": False},
    "database_query_data": False,
    "queues": False,
    "stack_frame_variables": False,
    "frame_context_lines": 5,  # our own source code around the error, never user data
}


def _secret_values(settings: Settings) -> list[str]:
    names = ("openai_api_key", "anthropic_api_key", "fal_key", "asset_signing_secret", "admin_token",
             "batch_token", "ip_hash_secret", "sentry_dsn", "database_url")  # fmt: skip
    values = [str(getattr(settings, n, "") or "") for n in names] + settings.access_code_list
    return sorted({v for v in values if len(v) >= 4}, key=len, reverse=True)


def scrub_text(text: str, secrets: list[str] = ()) -> str:
    for s in secrets:
        text = text.replace(s, "[secret]")
    text = _INPUT_ECHO.sub("input_value=[removed]", text)
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub("[url]", text)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…[cut]"


def _walk(value: Any, secrets: list[str], key: str = "") -> Any:
    if isinstance(value, str):
        return value if key in _KEEP else scrub_text(value, secrets)
    if isinstance(value, dict):
        return {k: _walk(v, secrets, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, secrets, key) for v in value]
    return value


def scrub_event(event: dict[str, Any], secrets: list[str] = ()) -> dict[str, Any]:
    """Everything that could hold user data is dropped or masked; IDs and code locations stay."""
    request = event.get("request")
    if isinstance(request, dict):
        url = str(request.get("url") or "")
        path = re.sub(r"^[a-z]+://[^/]+", "", url).split("?")[0]
        event["request"] = {"method": request.get("method"), "url": path}
    event.pop("user", None)
    event.pop("extra", None)
    for frame_holder in _frames(event):
        frame_holder.pop("vars", None)
    return _walk(event, list(secrets))


def _frames(event: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for exc in (event.get("exception") or {}).get("values") or []:
        out += (exc.get("stacktrace") or {}).get("frames") or []
    for thread in (event.get("threads") or {}).get("values") or []:
        out += (thread.get("stacktrace") or {}).get("frames") or []
    return out


def init_monitoring(settings: Settings, component: str) -> bool:
    """Start Sentry for the API or the worker. Returns False (and does nothing) without a DSN."""
    if not settings.sentry_dsn:
        return False
    import sentry_sdk

    secrets = _secret_values(settings)
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        release=f"ugc-api@{__version__}",
        environment=settings.app_env,
        data_collection=DATA_COLLECTION,
        before_send=lambda event, hint: scrub_event(event, secrets),
        before_breadcrumb=lambda crumb, hint: _walk(crumb, secrets),
        max_breadcrumbs=30,
        traces_sample_rate=0.0,
    )
    sentry_sdk.set_tag("component", component)
    log.info("error monitoring on (%s)", component)
    return True
