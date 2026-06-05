import os
import tempfile
import unittest


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2InventoryApiTest(unittest.TestCase):
    def test_tower_api_requires_auth_and_does_not_return_credentials(self) -> None:
        from app.v2.main import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "inventory-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                with TestClient(create_app()) as client:
                    self.assertEqual(client.get("/api/towers").status_code, 401)
                    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
                    token = login.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    created = client.post(
                        "/api/towers",
                        json={
                            "name": "Tower A",
                            "base_url": "https://tower.example.com",
                            "username": "admin",
                            "password": "secret-password",
                            "api_token": "secret-token",
                            "verify_tls": False,
                            "enabled": True,
                        },
                        headers=headers,
                    )
                    self.assertEqual(created.status_code, 200)
                    payload = created.json()
                    self.assertEqual(payload["name"], "Tower A")
                    self.assertNotIn("password", payload)
                    self.assertNotIn("api_token", payload)

                    tower_id = payload["id"]
                    synced = client.post(
                        f"/api/towers/{tower_id}/clusters/sync",
                        json=[{"cluster_id": "cluster-a", "name": "Cluster A", "enabled": True}],
                        headers=headers,
                    )
                    self.assertEqual(synced.status_code, 200)
                    self.assertEqual(synced.json()[0]["cluster_id"], "cluster-a")

                    cluster = client.put(
                        f"/api/towers/{tower_id}/clusters/cluster-a",
                        json={"enabled": False, "name": "Cluster A Disabled"},
                        headers=headers,
                    )
                    self.assertEqual(cluster.status_code, 200)
                    self.assertFalse(cluster.json()["enabled"])

                    towers = client.get("/api/towers", headers=headers)
                    self.assertEqual(towers.status_code, 200)
                    self.assertEqual(towers.json()[0]["clusters"][0]["name"], "Cluster A Disabled")
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
