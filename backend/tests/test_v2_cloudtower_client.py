import unittest


class FakeResponse:
    def __init__(self, status_code, payload=None, text="") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.requests = []

    def post(self, path, json=None, headers=None):
        self.requests.append({"path": path, "json": json or {}, "headers": headers or {}})
        if not self.responses:
            raise AssertionError("No fake response configured.")
        return self.responses.pop(0)

    def close(self):
        pass


class V2CloudTowerClientTest(unittest.TestCase):
    def test_client_logs_in_pages_clusters_and_normalizes_cluster_inputs(self) -> None:
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(200, {"data": [{"id": "cluster-a", "name": "Cluster A"}]}),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret", verify_tls=False),
            http_client=http,
        )

        clusters = client.get_clusters()

        self.assertEqual([(cluster.cluster_id, cluster.name) for cluster in clusters], [("cluster-a", "Cluster A")])
        self.assertEqual(http.requests[0]["path"], "/v2/api/login")
        self.assertEqual(http.requests[1]["headers"]["Authorization"], "token-1")

    def test_collect_cluster_normalizes_capacity_and_vm_identity(self) -> None:
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(200, {"data": {"used_data_space": 1024, "total_data_capacity": 4096}}),
                FakeResponse(200, {"data": {"items": [{"id": "vm-1", "name": "VM One", "used_size": 512}]}}),
                FakeResponse(
                    200,
                    {
                        "data": [
                            {
                                "id": "vol-1",
                                "name": "Root",
                                "path": "/root",
                                "size": 1000,
                                "used_size": 600,
                                "elf_storage_policy": "Replica-2",
                                "elf_storage_policy_replica_num": 2,
                                "elf_storage_policy_thin_provision": True,
                            }
                        ]
                    },
                ),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        payload = client.collect_cluster("cluster-a")

        self.assertEqual(payload["cluster"], {"used_bytes": 1024, "total_bytes": 4096})
        self.assertEqual(payload["vms"][0]["vm_id"], "vm-1")
        self.assertEqual(payload["vms"][0]["name"], "VM One")
        self.assertEqual(payload["vms"][0]["used_bytes"], 512)
        self.assertEqual(
            payload["vms"][0]["volumes"],
            [
                {
                    "volume_id": "vol-1",
                    "name": "Root",
                    "path": "/root",
                    "size_bytes": 1000,
                    "used_bytes": 600,
                    "storage_policy": "Replica-2",
                    "replica_num": 2,
                    "thin_provision": True,
                    "ec_k": None,
                    "ec_m": None,
                }
            ],
        )

    def test_client_uses_api_token_without_password_login(self) -> None:
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient([FakeResponse(200, {"data": []})])
        client = CloudTowerClient(CloudTowerCredentials(base_url="https://tower.example.com", api_token="api-token"), http_client=http)

        self.assertEqual(client.get_clusters(), [])
        self.assertEqual(http.requests[0]["path"], "/v2/api/get-clusters")
        self.assertEqual(http.requests[0]["headers"]["Authorization"], "api-token")


    def test_get_cluster_allocations_reads_perf_allocated_data_space_and_defaults_to_zero(self) -> None:
        """49-36：已分配容量取 get-clusters 的 perf_allocated_data_space，缺失/null 记 0。"""
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(
                    200,
                    {
                        "data": [
                            {"id": "cluster-a", "perf_allocated_data_space": 270},
                            {"id": "cluster-b"},
                            {"id": "cluster-c", "perf_allocated_data_space": None},
                        ]
                    },
                ),
            ]
        )
        client = CloudTowerClient(CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"), http_client=http)

        allocations = client.get_cluster_allocations(["cluster-a", "cluster-b", "cluster-c"])

        self.assertEqual(allocations, {"cluster-a": 270, "cluster-b": 0, "cluster-c": 0})
        self.assertEqual(http.requests[1]["path"], "/v2/api/get-clusters")
        self.assertEqual(http.requests[1]["json"]["where"], {"id_in": ["cluster-a", "cluster-b", "cluster-c"]})

    def test_get_cluster_allocations_skips_request_without_cluster_ids(self) -> None:
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient([])
        client = CloudTowerClient(CloudTowerCredentials(base_url="https://tower.example.com", api_token="api-token"), http_client=http)

        self.assertEqual(client.get_cluster_allocations([]), {})
        self.assertEqual(http.requests, [])


    def test_normalize_vm_records_recycle_bin_fields(self) -> None:
        """49-47：回收站 VM 不再丢弃，记录 in_recycle_bin/original_name/deleted_at。"""
        from app.v2.cloudtower.client import _normalize_vm

        recycled = _normalize_vm(
            {
                "id": "cm1",
                "name": "in-recycle-bin-abc",
                "used_size": 100,
                "in_recycle_bin": True,
                "original_name": "my-vm",
                "deleted_at": "2026-09-01T10:00:00+08:00",
            }
        )
        self.assertIsNotNone(recycled)
        self.assertEqual(recycled["vm_id"], "cm1")
        self.assertEqual(recycled["name"], "in-recycle-bin-abc")
        self.assertTrue(recycled["in_recycle_bin"])
        self.assertEqual(recycled["original_name"], "my-vm")
        self.assertEqual(recycled["deleted_at"], "2026-09-01T10:00:00+08:00")
        self.assertEqual(recycled["used_bytes"], 100)

        alive = _normalize_vm({"id": "cm2", "name": "live-vm", "used_size": 5, "in_recycle_bin": False, "original_name": "x", "deleted_at": "y"})
        self.assertIsNotNone(alive)
        self.assertFalse(alive["in_recycle_bin"])
        self.assertIsNone(alive["original_name"])
        self.assertIsNone(alive["deleted_at"])


if __name__ == "__main__":
    unittest.main()
