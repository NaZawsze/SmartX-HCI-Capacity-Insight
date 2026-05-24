import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


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
    salt = _unb64url(salt_b64)
    expected = _unb64url(digest_b64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return hmac.compare_digest(actual, expected)


def create_token(subject: str, ttl_minutes: int | None = None) -> str:
    settings = get_settings()
    now = int(time.time())
    expires_at = now + 60 * (ttl_minutes or settings.token_ttl_minutes)
    payload = {"sub": subject, "iat": now, "exp": expires_at}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(settings.secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url(signature)}"


def decode_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(settings.secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(_unb64url(signature), expected):
        return None
    payload = json.loads(_unb64url(body).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def _fernet() -> Fernet:
    settings = get_settings()
    seed = settings.credential_key or settings.secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None

