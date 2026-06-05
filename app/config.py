from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    app_name: str = "FastAPI Developer Assignment"
    database_url: str = "sqlite:///./app.db"
    secret_key: str = "change-me-for-production"
    access_token_expire_minutes: int = 60
    login_code_ttl_seconds: int = 300
    cache_ttl_seconds: int = 300
    cache_backend: str = "auto"
    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "fastapi_assignment:"
    redis_timeout_seconds: float = 0.25


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", Settings.database_url),
        secret_key=os.getenv("SECRET_KEY", Settings.secret_key),
        access_token_expire_minutes=int(
            os.getenv(
                "ACCESS_TOKEN_EXPIRE_MINUTES",
                str(Settings.access_token_expire_minutes),
            )
        ),
        login_code_ttl_seconds=int(
            os.getenv("LOGIN_CODE_TTL_SECONDS", str(Settings.login_code_ttl_seconds))
        ),
        cache_ttl_seconds=int(
            os.getenv("CACHE_TTL_SECONDS", str(Settings.cache_ttl_seconds))
        ),
        cache_backend=os.getenv("CACHE_BACKEND", Settings.cache_backend),
        redis_url=os.getenv("REDIS_URL", Settings.redis_url),
        redis_key_prefix=os.getenv("REDIS_KEY_PREFIX", Settings.redis_key_prefix),
        redis_timeout_seconds=float(
            os.getenv("REDIS_TIMEOUT_SECONDS", str(Settings.redis_timeout_seconds))
        ),
    )
