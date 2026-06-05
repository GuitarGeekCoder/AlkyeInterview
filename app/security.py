from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_secret(value: str, salt: str | None = None, iterations: int = 120_000) -> str:
    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        actual_salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${actual_salt}${digest.hex()}"


def verify_secret(value: str, stored_value: str) -> bool:
    algorithm, raw_iterations, salt, expected_digest = stored_value.split("$", 3)
    if algorithm != "pbkdf2_sha256":
        return False
    computed = hash_secret(value, salt=salt, iterations=int(raw_iterations))
    return hmac.compare_digest(computed, stored_value)


def generate_login_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def create_access_token(
    *,
    secret_key: str,
    user_id: str,
    email: str,
    role: str,
    expires_minutes: int,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"


def decode_access_token(token: str, secret_key: str) -> dict[str, str | int]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(_b64url_encode(expected_signature), encoded_signature):
        raise ValueError("Invalid token signature")
    payload = json.loads(_b64url_decode(encoded_payload))
    if int(payload["exp"]) < int(time.time()):
        raise ValueError("Token has expired")
    return payload
