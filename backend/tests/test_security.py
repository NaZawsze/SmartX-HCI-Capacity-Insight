from app.core.security import create_token, decode_token, hash_password, verify_password


def test_password_hash_round_trip() -> None:
    stored = hash_password("secret")
    assert verify_password("secret", stored)
    assert not verify_password("wrong", stored)


def test_token_round_trip() -> None:
    token = create_token("admin", ttl_minutes=1)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "admin"

