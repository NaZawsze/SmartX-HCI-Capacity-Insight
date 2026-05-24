from app.core.security import hash_password, verify_password
from app.db import get_conn, row_to_dict


def change_password(username: str, current_password: str, new_password: str) -> bool:
    with get_conn() as conn:
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
        if user is None or not verify_password(current_password, user["password_hash"]):
            return False
        conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(new_password), username))
    return True


def reset_password(username: str, new_password: str) -> bool:
    with get_conn() as conn:
        user = row_to_dict(conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone())
        if user is None:
            return False
        conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hash_password(new_password), username))
    return True
