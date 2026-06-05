from __future__ import annotations

from dataclasses import dataclass

from app.v2.config import V2Settings
from app.v2.database import V2Database, row_to_dict
from app.v2.security import create_token, decode_token, hash_password, verify_password


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    username: str
    token_type: str = "bearer"


@dataclass(frozen=True)
class CurrentUser:
    username: str
    is_admin: bool


class AuthService:
    def __init__(self, database: V2Database, settings: V2Settings) -> None:
        self.database = database
        self.settings = settings

    def login(self, username: str, password: str) -> LoginResult | None:
        with self.database.connection() as conn:
            user = row_to_dict(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
        if user is None or not verify_password(password, user["password_hash"]):
            return None
        return LoginResult(
            access_token=create_token(username, self.settings.secret_key, self.settings.token_ttl_minutes),
            username=username,
        )

    def current_user(self, token: str) -> CurrentUser | None:
        payload = decode_token(token, self.settings.secret_key)
        if payload is None:
            return None
        username = str(payload.get("sub", ""))
        with self.database.connection() as conn:
            user = row_to_dict(conn.execute("SELECT username, is_admin FROM users WHERE username = ?", (username,)).fetchone())
        if user is None:
            return None
        return CurrentUser(username=user["username"], is_admin=bool(user["is_admin"]))

    def change_password(self, username: str, current_password: str, new_password: str) -> bool:
        with self.database.connection() as conn:
            user = row_to_dict(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
            if user is None or not verify_password(current_password, user["password_hash"]):
                return False
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                (hash_password(new_password), username),
            )
        return True
