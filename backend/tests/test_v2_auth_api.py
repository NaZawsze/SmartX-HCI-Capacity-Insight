import os
import tempfile
import unittest


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2AuthApiTest(unittest.TestCase):
    def test_login_me_and_password_change_api_flow(self) -> None:
        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "api-test-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                with TestClient(create_app()) as client:
                    self.assertEqual(client.get("/api/me").status_code, 401)

                    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
                    self.assertEqual(login.status_code, 200)
                    token = login.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    me = client.get("/api/me", headers=headers)
                    self.assertEqual(me.status_code, 200)
                    self.assertEqual(me.json(), {"username": "admin", "is_admin": True})

                    mismatch = client.put(
                        "/api/me/password",
                        json={"current_password": "password", "new_password": "new-password", "confirm_password": "other"},
                        headers=headers,
                    )
                    self.assertEqual(mismatch.status_code, 400)

                    changed = client.put(
                        "/api/me/password",
                        json={"current_password": "password", "new_password": "new-password", "confirm_password": "new-password"},
                        headers=headers,
                    )
                    self.assertEqual(changed.status_code, 200)
                    self.assertEqual(changed.json(), {"ok": True})

                    old_login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
                    self.assertEqual(old_login.status_code, 401)
                    new_login = client.post("/api/auth/login", json={"username": "admin", "password": "new-password"})
                    self.assertEqual(new_login.status_code, 200)
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
