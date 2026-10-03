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
                FakeResponse(200, {"data": {"items": [{"id": "vm-1", "name": "VM One", "used_size": 512}, {"id": "vm-r", "name": "in-recycle-bin-x", "used_size": 999, "in_recycle_bin": True}]}}),
                FakeResponse(
                    200,
                    {
                        "data": [
                            {
                                "id": "vol-1",
                                "name": "Root",
                                "path": "/root",
                                "size_bytes": 1099511627776,
                                "used_size": 600,
                                "elf_storage_policy": "Replica-2",
                                "elf_storage_policy_replica_num": 2,
                                "elf_storage_policy_thin_provision": True,
                            }
                        ]
                    },
                ),
                # 回收站 VM（vm-r）同样会走一次 get-vm-volumes
                # （口径 2026-10-03：回收站计入已分配，但仍记录其卷数据）
                FakeResponse(200, {"data": []}),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        payload = client.collect_cluster("cluster-a")

        # allocated 在采集时就地计算 = Σ(卷供给 1TiB × Replica-2) = 2TiB。
        # 口径（2026-10-03 用户决策）：回收站 VM 的卷**同样计入**已分配——
        # 它的物理块仍被占用，与「已使用」保持同口径。
        self.assertEqual(
            payload["cluster"],
            {"used_bytes": 1024, "total_bytes": 4096, "allocated_bytes": int(2 * 1024 ** 4)},
        )
        self.assertEqual(payload["vms"][-1]["vm_id"], "vm-r")
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
                    "size_bytes": 1099511627776,
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


    def test_recycle_bin_volumes_are_included_in_allocated(self) -> None:
        """口径（2026-10-03 用户决策）：回收站 VM 的卷**计入**已分配。

        背景：#75 初版把回收站排除在外，但那会让「已分配 < 已使用」——
        回收站卷的物理块仍被 Tower 计入 used_data_space。
        两个指标必须同口径，否则容量预测（基于已使用）也对不齐。
        """
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        one_tib = 1024 ** 4
        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(200, {"data": {"used_data_space": 1024, "total_data_capacity": 4096}}),
                FakeResponse(
                    200,
                    {
                        "data": {
                            "items": [
                                {"id": "vm-alive", "name": "Alive", "used_size": 1},
                                {"id": "vm-recycle", "name": "in-recycle-bin-x", "used_size": 2, "in_recycle_bin": True},
                            ]
                        }
                    },
                ),
                # 第一个 VM 的卷
                FakeResponse(
                    200,
                    {"data": [{"id": "vol-a", "name": "Root", "size_bytes": one_tib,
                               "elf_storage_policy": "Replica-2", "elf_storage_policy_replica_num": 2}]},
                ),
                # 第二个（回收站）VM 的卷——Replica-3
                FakeResponse(
                    200,
                    {"data": [{"id": "vol-b", "name": "Data", "size_bytes": one_tib,
                               "elf_storage_policy": "Replica-3", "elf_storage_policy_replica_num": 3}]},
                ),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        allocated = client.collect_cluster("cluster-a")["cluster"]["allocated_bytes"]

        # 1TiB×2 + 1TiB×3 = 5TiB。若回收站被排除，这里会是 2TiB。
        self.assertEqual(
            allocated, 5 * one_tib,
            "回收站 VM 的卷必须计入已分配（口径 2026-10-03）",
        )

    def test_recycle_bin_still_recorded_in_payload(self) -> None:
        """口径前提：计入已分配 ≠ 丢弃数据——回收站 VM 仍要出现在采集结果里。"""
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(200, {"data": {"used_data_space": 1024, "total_data_capacity": 4096}}),
                FakeResponse(
                    200,
                    {"data": {"items": [{"id": "vm-r", "name": "in-recycle-bin-x",
                                         "used_size": 9, "in_recycle_bin": True}]}},
                ),
                # 回收站 VM 同样会走一次 get-vm-volumes
                FakeResponse(200, {"data": []}),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        vms = client.collect_cluster("cluster-a")["vms"]

        self.assertEqual(len(vms), 1)
        self.assertTrue(vms[0]["in_recycle_bin"], "回收站标记必须保留，否则无法做回收站功能")
        self.assertEqual(vms[0]["vm_id"], "vm-r")


if __name__ == "__main__":
    unittest.main()
