from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return f"pbkdf2_sha256${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = _unb64url(digest_b64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64url(salt_b64), 260_000)
    return hmac.compare_digest(actual, expected)


def create_token(subject: str, secret_key: str, ttl_minutes: int) -> str:
    now = int(time.time())
    payload = {"sub": subject, "iat": now, "exp": now + ttl_minutes * 60}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url(signature)}"


def decode_token(token: str, secret_key: str) -> dict[str, Any] | None:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64url(signature), expected):
            return None
        payload = json.loads(_unb64url(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload
