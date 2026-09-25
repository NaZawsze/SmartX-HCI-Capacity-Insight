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
                    "scope": {"tower_id": tower_id, "cluster_id": cluster_id, "cluster_enabled": None},
                    "capacity_risk": {"level": "normal", "message": "当前所有集群暂无明显容量风险"},
                    "totals": {"towers": 1, "clusters": 1, "vms": 1},
                    "storage": {"used_bytes": 1, "total_bytes": 2, "used_ratio": 0.5},
                    "collection": None,
                    "day_fastest_growing_vms": [],
                    "day_new_vms": [],
                    "clusters": [],
                }

        class FakeVmService:
            trend_days: int | None = None

            def list_vms(self, tower_id=None, cluster_id=None):
                return [{"tower_id": tower_id, "cluster_id": cluster_id, "vm_id": "vm-1", "vm_name": "VM One", "used_bytes": 1}]

            def trend(self, *, vm_id, tower_id, cluster_id, days):
                self.trend_days = days
                return {"tower_id": tower_id, "cluster_id": cluster_id, "vm_id": vm_id, "vm_name": "VM One", "points": []}

            def detail(self, *, vm_id, tower_id, cluster_id):
                return {"tower_id": tower_id, "cluster_id": cluster_id, "vm_id": vm_id, "vm_name": "VM One", "used_bytes": 1}

            def volumes(self, *, vm_id, tower_id, cluster_id):
                return [{"volume_id": "vol-1", "name": "Root", "size_bytes": 100, "used_bytes": 60, "storage_policy": "Replica-2", "replica_num": 2}]

            def all_volumes(self, tower_id=None, cluster_id=None, page=None, page_size=200, sort=None, order=None):
                if page is None:
                    return [{"tower_id": 1, "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "VM One", "volumes": []}]
                return {"volumes": [{"tower_id": 1, "cluster_id": "cluster-a", "vm_id": "vm-1", "vm_name": "VM One", "volume_id": "vol-1"}], "total": 1, "page": page, "page_size": page_size}

            def usage_summary(self, tower_id=None, cluster_id=None):
                return [{"tower_id": 1, "cluster_id": "cluster-a", "vm_id": "vm-1", "used_bytes": 60.0, "provisioned_bytes": 100.0}]

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["SMARTX_DATA_ROOT"] = tmpdir
            os.environ["SMARTX_SECRET_KEY"] = "dashboard-api-secret"
            os.environ["SMARTX_ADMIN_PASSWORD"] = "password"
            try:
                vm_service = FakeVmService()
                app = create_app()
                app.dependency_overrides[get_dashboard_service] = lambda: FakeDashboardService()
                app.dependency_overrides[get_vm_service] = lambda: vm_service
                with TestClient(app) as client:
                    self.assertEqual(client.get("/api/dashboard/summary").status_code, 401)
                    token = client.post("/api/auth/login", json={"username": "admin", "password": "password"}).json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    summary = client.get("/api/dashboard/summary?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(summary.status_code, 200)
                    self.assertEqual(summary.json()["scope"], {"type": None, "label": None, "tower_id": 1, "cluster_id": "cluster-a", "cluster_enabled": None})

                    vms = client.get("/api/vms?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(vms.status_code, 200)
                    self.assertEqual(vms.json()[0]["vm_name"], "VM One")

                    missing_scope = client.get("/api/vms/vm-1/trend?tower_id=1", headers=headers)
                    self.assertEqual(missing_scope.status_code, 400)

                    trend = client.get("/api/vms/vm-1/trend?tower_id=1&cluster_id=cluster-a&days=7", headers=headers)
                    self.assertEqual(trend.status_code, 200)
                    self.assertEqual(trend.json()["vm_id"], "vm-1")

                    trend = client.get("/api/vms/vm-1/trend?tower_id=1&cluster_id=cluster-a&period_days=7", headers=headers)
                    self.assertEqual(trend.status_code, 200)
                    self.assertEqual(trend.json()["vm_id"], "vm-1")
                    self.assertEqual(vm_service.trend_days, 7)

                    detail = client.get("/api/vms/vm-1?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(detail.json()["vm_name"], "VM One")

                    missing_volume_scope = client.get("/api/vms/vm-1/volumes?tower_id=1", headers=headers)
                    self.assertEqual(missing_volume_scope.status_code, 400)
                    volumes = client.get("/api/vms/vm-1/volumes?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(volumes.status_code, 200)
                    self.assertEqual(volumes.json()[0]["volume_id"], "vol-1")

                    grouped_volumes = client.get("/api/vm-volumes?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(grouped_volumes.status_code, 200)
                    self.assertIsInstance(grouped_volumes.json(), list)

                    paged_volumes = client.get("/api/vm-volumes?tower_id=1&page=2&page_size=50&sort=used&order=desc", headers=headers)
                    self.assertEqual(paged_volumes.status_code, 200)
                    payload = paged_volumes.json()
                    self.assertEqual(payload["page"], 2)
                    self.assertEqual(payload["page_size"], 50)
                    self.assertEqual(payload["total"], 1)

                    self.assertEqual(client.get("/api/vm-volumes?page=0", headers=headers).status_code, 400)
                    self.assertEqual(client.get("/api/vm-volumes?page=1&page_size=1001", headers=headers).status_code, 400)
                    self.assertEqual(client.get("/api/vm-volumes?page=1&sort=name", headers=headers).status_code, 400)
                    self.assertEqual(client.get("/api/vm-volumes?page=1&order=up", headers=headers).status_code, 400)

                    usage_summary = client.get("/api/vm-volumes/usage-summary?tower_id=1&cluster_id=cluster-a", headers=headers)
                    self.assertEqual(usage_summary.status_code, 200)
                    self.assertEqual(usage_summary.json()["usages"][0]["vm_id"], "vm-1")

                    missing_summary_scope = client.get("/api/vm-volumes/usage-summary?cluster_id=cluster-a", headers=headers)
                    self.assertEqual(missing_summary_scope.status_code, 400)
            finally:
                os.environ.pop("SMARTX_DATA_ROOT", None)
                os.environ.pop("SMARTX_SECRET_KEY", None)
                os.environ.pop("SMARTX_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
