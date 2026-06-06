import os
import tempfile
import unittest


try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local host may not have web deps.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed.")
class V2DashboardVmApiTest(unittest.TestCase):
    def test_dashboard_and_vm_api_require_auth_and_return_data(self) -> None:
        from app.v2.api import get_dashboard_service, get_vm_service
        from app.v2.main import create_app

        class FakeDashboardService:
            def summary(self, tower_id=None, cluster_id=None):
                return {
                    "scope": {"tower_id": tower_id, "cluster_id": cluster_id},
                    "capacity_risk": {"level": "normal", "message": "当前所有集群暂无明显容量风险"},
                    "totals": {"towers": 1, "clusters": 1, "vms": 1},
                    "storage": {"used_bytes": 1, "total_bytes": 2, "used_ratio": 0.5},
                    "collection": None,
                    "day_fastest_growing_vms": [],
                    "day_new_vms": [],
                    "clusters": [],
                }

        class FakeVmService:
            def list_vms(self, tower_id=None, cluster_id=None):
                return [{"tower_id": tower_id, "cluster_id": cluster_id, "vm_id": "vm-1", "vm_name": "VM One", "used_bytes": 1}]

            def trend(self, *, vm_id, tower_id, cluster_id, days):
                return {"tower_id": tower_id, "cluster_id": cluster_id, "vm_id": vm_id, "vm_name": "VM One", "points": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "dashboard-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                app = create_app()
                app.dependency_overrides[get_dashboard_service] = lambda: FakeDashboardService()
                app.dependency_overrides[get_vm_service] = lambda: FakeVmService()
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/dashboard/summary").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    summary = client.get("/api/dashboard/summary?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(summary.status_code, 200)
                    self.assertEqual(summary.json()["scope"], {"tower_id": 1, "cluster_id": "cluster-a"})

                    vms = client.get("/api/vms?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(vms.status_code, 200)
                    self.assertEqual(vms.json()[0]["vm_name"], "VM One")

                    missing_scope = client.get("/api/vms/vm-1/trend?tower_id=1", headers=headers)
                    self.assertEqual(missing_scope.status_code, 400)

                    trend = client.get("/api/vms/vm-1/trend?tower_id=1&cluster_id=cluster-a&days=7", headers=headers)
                    self.assertEqual(trend.status_code, 200)
                    self.assertEqual(trend.json()["vm_id"], "vm-1")
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
