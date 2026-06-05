from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

try:
    import redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - exercised via cache factory tests
    redis = None
    RedisError = Exception


class CacheBackend(Protocol):
    backend_name: str

    def get(self, key: str) -> Any | None:
        ...

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ...

    def delete(self, key: str) -> None:
        ...

    def clear(self) -> None:
        ...

@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class InMemoryCache:
    backend_name = "memory"

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._store: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at <= datetime.utcnow():
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or self.default_ttl_seconds
        self._store[key] = CacheEntry(
            value=value,
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
        )

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class RedisCache:
    backend_name = "redis"

    def __init__(
        self,
        client: Any,
        default_ttl_seconds: int = 300,
        key_prefix: str = "fastapi_assignment:",
    ) -> None:
        self.client = client
        self.default_ttl_seconds = default_ttl_seconds
        self.key_prefix = key_prefix

    def _key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def get(self, key: str) -> Any | None:
        value = self.client.get(self._key(key))
        if value is None:
            return None
        return json.loads(value)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or self.default_ttl_seconds
        self.client.set(self._key(key), json.dumps(value), ex=ttl)

    def delete(self, key: str) -> None:
        self.client.delete(self._key(key))

    def clear(self) -> None:
        pattern = f"{self.key_prefix}*"
        keys = list(self.client.scan_iter(match=pattern))
        if keys:
            self.client.delete(*keys)


def create_cache(
    *,
    cache_backend: str,
    default_ttl_seconds: int,
    redis_url: str,
    redis_key_prefix: str,
    redis_timeout_seconds: float,
) -> CacheBackend:
    normalized_backend = cache_backend.lower()
    if normalized_backend not in {"auto", "memory", "redis"}:
        raise ValueError(f"Unsupported cache backend: {cache_backend}")

    if normalized_backend == "memory":
        return InMemoryCache(default_ttl_seconds=default_ttl_seconds)

    if redis is None:
        if normalized_backend == "redis":
            raise RuntimeError(
                "Redis cache backend requested but the 'redis' package is not installed."
            )
        return InMemoryCache(default_ttl_seconds=default_ttl_seconds)

    try:
        client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=redis_timeout_seconds,
            socket_timeout=redis_timeout_seconds,
        )
        client.ping()
    except RedisError as exc:
        if normalized_backend == "redis":
            raise RuntimeError(
                f"Redis cache backend requested but Redis is unavailable at {redis_url}."
            ) from exc
        return InMemoryCache(default_ttl_seconds=default_ttl_seconds)

    return RedisCache(
        client=client,
        default_ttl_seconds=default_ttl_seconds,
        key_prefix=redis_key_prefix,
    )
