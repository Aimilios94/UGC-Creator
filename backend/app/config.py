"""Environment-driven configuration (pattern adapted from Receipt-Ghostbuster).

Secrets live only in backend/.env (git-ignored) or in the deployment's secret store.
The app must import and run with no secret set: the health check, the mock
providers and the tests work without keys. Code that needs a secret checks the
matching `*_configured` property and fails with a clear message only when used.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]

PLATFORMS = ("tiktok", "instagram_reels", "youtube_shorts", "facebook")
ASPECT_RATIOS = ("9:16", "1:1", "4:5", "16:9")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: str = "local"  # local | prod
    log_level: str = "INFO"

    # --- Providers ---
    llm_provider: str = "openai"  # openai | anthropic | mock
    media_provider: str = "fal"  # fal | mock
    storage_provider: str = "local"  # local | gcs

    # --- Keys ---
    openai_api_key: str = ""
    fal_key: str = ""
    anthropic_api_key: str = ""

    # --- Models (a model is a config value) ---
    # A dated snapshot, so a model can't change under the evals without a config change.
    llm_model: str = "gpt-5-mini-2025-08-07"
    anthropic_model: str = ""
    image_model: str = "fal-ai/nano-banana/edit"
    video_model: str = "fal-ai/kling-video/v2.5-turbo/pro/image-to-video"
    llm_max_output_tokens: int = 8000
    video_duration_s: int = 5  # Kling accepts "5" or "10"
    render_scenes: int = 1  # M1 renders scene 1 only; M2 renders all three

    # --- Database ---
    database_url: str = ""
    database_url_direct: str = ""
    db_connect_timeout_s: int = 20
    db_connect_retries: int = 5

    # --- Storage ---
    storage_local_dir: str = "./data"
    gcs_bucket: str = ""
    gcp_project_id: str = "ugc-ad-builder"
    gcp_region: str = "europe-west4"
    signed_url_ttl_seconds: int = 900
    # Signs local asset URLs (HMAC). Local dev only; GCS signs its own URLs.
    asset_signing_secret: str = ""
    public_api_url: str = "http://localhost:8000"

    # --- Worker ---
    job_runner: str = "local"  # local (Compose worker loop) | cloudrun (Cloud Run Job)
    cloud_run_job_name: str = ""
    max_job_attempts: int = 2
    worker_poll_interval_s: float = 3.0
    media_poll_interval_s: float = 5.0
    media_timeout_s: int = 1500  # under the 45-minute task timeout
    fal_output_expiry_s: int = 3600  # fal keeps outputs forever by default; we copy them first

    # --- Money: everything the user sets or sees is in EUR ---
    job_cost_cap_eur: float = 1.75  # M2: a 3-scene ad plus one retry and 15% margin (D2)
    daily_spend_limit_eur: float = 4.0  # M2: two worst-case ads per day (D2)
    usd_to_eur_rate: float = 0.87
    display_currency: str = "EUR"  # EUR | USD
    demo_pot_eur: float = 0.0  # M4

    # --- Access and uploads ---
    access_codes: str = ""
    max_upload_mb: int = 10
    max_image_side_px: int = 2048
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Later milestones (read now so .env stays one file) ---
    retention_days: int = 30
    admin_token: str = ""
    batch_token: str = ""
    sentry_dsn: str = ""
    ip_hash_secret: str = ""

    # --- Derived ---
    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def access_code_list(self) -> list[str]:
        return [c.strip() for c in self.access_codes.split(",") if c.strip()]

    @property
    def access_code_required(self) -> bool:
        """Production always requires a code (fails closed when none is set).
        Local dev requires one only when codes are configured."""
        return self.is_prod or bool(self.access_code_list)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key and self.anthropic_model)
        return False

    @property
    def media_configured(self) -> bool:
        return self.media_provider == "mock" or bool(self.fal_key)

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def job_cost_cap_usd(self) -> float:
        return self.job_cost_cap_eur / self.usd_to_eur_rate

    @property
    def daily_spend_limit_usd(self) -> float:
        return self.daily_spend_limit_eur / self.usd_to_eur_rate

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
