"""File storage: a local folder in dev, a private GCS bucket when hosted.

Files are never public. The browser gets signed, expiring URLs; a provider (fal)
gets a short-lived URL to fetch an input image. Local URLs are signed with an HMAC
over (key, expiry) and served by GET /assets/...; GCS URLs are V4 signed URLs,
signed through the IAM signBlob API on Cloud Run (no key files).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from ...config import BACKEND_DIR, Settings
from ...errors import ProviderNotConfigured

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]{0,300}$")


def check_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in key or "//" in key:
        raise ValueError(f"invalid storage key: {key!r}")
    return key


class Storage(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, ttl_s: int) -> str: ...
    def provider_url(self, key: str, ttl_s: int) -> str | None:
        """A URL an outside provider can fetch, or None when the file is not reachable from outside."""
        ...


class LocalStorage:
    name = "local"

    def __init__(self, root: str | Path, *, secret: str, public_base_url: str, clock=time.time):
        root = Path(root)
        self.root = root if root.is_absolute() else (BACKEND_DIR / root).resolve()
        if not secret:
            raise ProviderNotConfigured("ASSET_SIGNING_SECRET is required for local storage")
        self._secret = secret.encode()
        self.public_base_url = public_base_url.rstrip("/")
        self._clock = clock

    def _path(self, key: str) -> Path:
        p = (self.root / check_key(key)).resolve()
        if self.root not in p.parents:
            raise ValueError("key escapes the storage root")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def sign(self, key: str, exp: int) -> str:
        return hmac.new(self._secret, f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()

    def verify(self, key: str, exp: int, sig: str) -> bool:
        if exp < int(self._clock()):
            return False
        return hmac.compare_digest(self.sign(key, exp), sig)

    def signed_url(self, key: str, ttl_s: int) -> str:
        exp = int(self._clock()) + ttl_s
        return f"{self.public_base_url}/assets/{quote(check_key(key))}?exp={exp}&sig={self.sign(key, exp)}"

    def provider_url(self, key: str, ttl_s: int) -> str | None:
        return None  # localhost is not reachable by fal; the media provider uploads the bytes instead


class GcsStorage:
    name = "gcs"

    def __init__(self, bucket: str):
        if not bucket:
            raise ProviderNotConfigured("GCS_BUCKET is required for gcs storage")
        from google.cloud import storage as gcs  # imported lazily: tests and local dev don't need it

        self._client = gcs.Client()
        self._bucket = self._client.bucket(bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._bucket.blob(check_key(key)).upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> bytes:
        return self._bucket.blob(check_key(key)).download_as_bytes()

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(check_key(key))
        if blob.exists():
            blob.delete()

    def signed_url(self, key: str, ttl_s: int) -> str:
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        # On Cloud Run there is no private key: sign through IAM signBlob with the
        # service account's own token (needs roles/iam.serviceAccountTokenCreator on itself).
        return self._bucket.blob(check_key(key)).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_s),
            method="GET",
            service_account_email=getattr(creds, "service_account_email", None),
            access_token=creds.token,
        )

    def provider_url(self, key: str, ttl_s: int) -> str | None:
        return self.signed_url(key, ttl_s)


def build_storage(settings: Settings) -> Storage:
    if settings.storage_provider == "gcs":
        return GcsStorage(settings.gcs_bucket)
    if settings.storage_provider == "local":
        return LocalStorage(
            settings.storage_local_dir, secret=settings.asset_signing_secret, public_base_url=settings.public_api_url
        )
    raise ProviderNotConfigured(f"unknown STORAGE_PROVIDER {settings.storage_provider!r}")
