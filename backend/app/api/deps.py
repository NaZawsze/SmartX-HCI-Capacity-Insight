from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.db import get_conn, row_to_dict


bearer = HTTPBearer(auto_error=False)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    with get_conn() as conn:
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE username = ?", (payload["sub"],)).fetchone())
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    return user
