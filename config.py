"""
config.py — Single source of truth for all environment-driven settings.

Every value here is read from environment variables (or .env for local dev).
To switch from local to cloud: set these same variables on your hosting
platform's dashboard — no code changes required.

    Railway  → railway.app   → Variables tab
    Render   → render.com    → Environment tab
    Heroku   → heroku.com    → Config Vars
    Fly.io   → fly.io        → fly secrets set KEY=value
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",       # loaded automatically; ignored in prod where real env vars are set
        extra="ignore",        # don't error on unrecognised env vars
        case_sensitive=False,
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str

    @field_validator("database_url")
    @classmethod
    def _fix_postgres_scheme(cls, v: str) -> str:
        # SQLAlchemy 2.x rejects the legacy 'postgres://' scheme used by some
        # cloud providers (older Heroku/Railway URLs). Fix it silently.
        return v.replace("postgres://", "postgresql://", 1) if v.startswith("postgres://") else v

    # ── Auth ──────────────────────────────────────────────────────────────────
    secret_key:                str = "change-me-before-deploying"
    access_token_ttl_minutes:  int = 60 * 24 * 7   # 7 days
    refresh_token_ttl_days:    int = 30

    # ── Email (SMTP) ──────────────────────────────────────────────────────────
    # Dev: leave smtp_host blank — codes print to the server console instead.
    # Prod: set these to your SMTP provider's values.
    smtp_host:     str  = ""
    smtp_port:     int  = 587
    smtp_tls:      bool = True
    smtp_username: str  = ""
    smtp_password: str  = ""
    smtp_from:     str  = "noreply@bazaar.app"

    # ── Image storage ─────────────────────────────────────────────────────────
    storage_backend:       str = "local"                  # "local" | "s3"
    local_base_url:        str = "http://localhost:8000"  # base URL for local file links
    s3_bucket_name:        str = ""
    s3_region:             str = "us-east-1"
    aws_access_key_id:     str = ""
    aws_secret_access_key: str = ""

    # ── Server ────────────────────────────────────────────────────────────────
    # Comma-separated allowed CORS origins, or "*" to allow any (dev only).
    # Example production value: "https://bazaar.app,https://www.bazaar.app"
    cors_origins: str = "*"

    # Set to True locally to get SQL query logging and detailed error pages.
    debug: bool = False


settings = Settings()
