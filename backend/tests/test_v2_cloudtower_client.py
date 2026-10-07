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
        self.requests.append({"method": "POST", "path": path, "json": json or {}, "headers": headers or {}})
        if not self.responses:
            raise AssertionError("No fake response configured.")
        return self.responses.pop(0)

    def get(self, path, headers=None):
        self.requests.append({"method": "GET", "path": path, "headers": headers or {}})
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
            {
                "used_bytes": 1024,
                "total_bytes": 4096,
                "allocated_bytes": int(2 * 1024 ** 4),
                # #84：容量来源随 payload 返回，便于运维判读（此例走容量端点）
                "capacity_source": "cluster-storage-info",
            },
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


    def test_normalize_vm_extracts_owner_and_folder(self) -> None:
        """Phase 69：所有者来自 labels 的 system.cloudtower/owner；虚拟机组来自 folder.name。

        `.3` 只读账号实测形状（设计 §2/§3）：值已是用户名；无标签/空值 → None（不猜不填充）。
        """
        from app.v2.cloudtower.client import _normalize_vm

        vm = _normalize_vm(
            {
                "id": "cm-owner",
                "name": "Test1",
                "used_size": 0,
                "labels": [
                    {"id": "l1", "key": "other/key", "value": "x"},
                    {"id": "l2", "key": "system.cloudtower/owner", "value": "root"},
                ],
                "folder": {"id": "f1", "name": "研发组"},
            }
        )
        self.assertEqual(vm["owner"], "root")
        self.assertEqual(vm["folder_name"], "研发组")

    def test_normalize_vm_owner_edge_cases(self) -> None:
        from app.v2.cloudtower.client import _normalize_vm

        cases = [
            # 无 labels / labels 非数组 → owner None
            ({"id": "a", "name": "n"}, None, None),
            ({"id": "b", "name": "n", "labels": "oops"}, None, None),
            # 有 labels 但无 owner 标签 → None
            ({"id": "c", "name": "n", "labels": [{"key": "other", "value": "y"}]}, None, None),
            # owner 标签值为空/空白 → None
            ({"id": "d", "name": "n", "labels": [{"key": "system.cloudtower/owner", "value": "  "}]}, None, None),
            # 多条同 key → 取第一条
            (
                {
                    "id": "e",
                    "name": "n",
                    "labels": [
                        {"key": "system.cloudtower/owner", "value": "first"},
                        {"key": "system.cloudtower/owner", "value": "second"},
                    ],
                },
                "first",
                None,
            ),
            # 值非字符串 → str() 化
            ({"id": "f", "name": "n", "labels": [{"key": "system.cloudtower/owner", "value": 42}]}, "42", None),
            # folder 缺 name / 非对象 → None
            ({"id": "g", "name": "n", "folder": {"id": "f"}}, None, None),
            ({"id": "h", "name": "n", "folder": "oops"}, None, None),
        ]
        for payload, expected_owner, expected_folder in cases:
            normalized = _normalize_vm(payload)
            self.assertIsNotNone(normalized, payload)
            self.assertEqual(normalized["owner"], expected_owner, payload)
            self.assertEqual(normalized["folder_name"], expected_folder, payload)

    def test_normalize_volume_treats_negative_usage_as_unreported(self) -> None:
        """2026-10-07 `.3` 实测：CloudTower 对无用量数据的卷返回 used_size=-1（哨兵），
        原样落库会导致页面显示「实际使用空间 -1 B / 实际占用 -2 B」。负值一律视为未上报 → None。"""
        from app.v2.cloudtower.client import _normalize_volume

        sentinel = _normalize_volume({"id": "vol-1", "name": "vol-1", "used_size": -1, "size": 2199023255552, "replica_num": 2})
        self.assertIsNone(sentinel["used_bytes"])
        self.assertEqual(sentinel["size_bytes"], 2199023255552)

        normal = _normalize_volume({"id": "vol-2", "name": "vol-2", "used_size": 1024, "size": -1})
        self.assertEqual(normal["used_bytes"], 1024)
        self.assertIsNone(normal["size_bytes"])

    def test_normalize_volume_derives_replica_from_storage_policy_string(self) -> None:
        """2026-10-07 `.3` 实测：新版卷响应只给策略串（`REPLICA_2_THIN_PROVISION`），
        没有 `elf_storage_policy_replica_num` 等扁平字段。若 replica_num 落成 None，
        采集侧「已分配 = Σ size × replica_num」恒乘 0——Test 集群已分配永远是 0。
        缺失扁平字段时按策略串推导（老式 `Replica-2` 串同样兼容）。"""
        from app.v2.cloudtower.client import _normalize_volume

        # 新式串：REPLICA_2_THIN_PROVISION（.3 只读账号实测原样）
        derived = _normalize_volume({"id": "vol-1", "size": 42949672960, "elf_storage_policy": "REPLICA_2_THIN_PROVISION"})
        self.assertEqual(derived["replica_num"], 2)
        self.assertIs(derived["thin_provision"], True)

        # 老式串：Replica-3（连字符/大小写混排）
        legacy = _normalize_volume({"id": "vol-2", "size": 1024, "elf_storage_policy": "Replica-3"})
        self.assertEqual(legacy["replica_num"], 3)

        # 显式扁平字段优先于策略串
        explicit = _normalize_volume(
            {"id": "vol-3", "size": 1024, "elf_storage_policy": "REPLICA_3_THIN_PROVISION", "elf_storage_policy_replica_num": 2}
        )
        self.assertEqual(explicit["replica_num"], 2)

        # 认不出的策略串不猜：保持 None（该卷按 0 计，与修前一致）
        unknown = _normalize_volume({"id": "vol-4", "size": 1024, "elf_storage_policy": "WHATEVER"})
        self.assertIsNone(unknown["replica_num"])
        self.assertIsNone(unknown["thin_provision"])

    def test_collect_cluster_allocated_uses_policy_string_replica(self) -> None:
        """回归：策略串-only 的塔（只读测试塔实测形态）也要算出已分配。

        4 台 VM 各 1 个 40GiB 卷、REPLICA_2 → 已分配 = 4 × 40GiB × 2 = 320GiB（修前为 0）。"""
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        size = 42949672960  # 40 GiB
        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(200, {"data": {"used_data_space": 262144, "total_data_capacity": 1052266987520}}),
                FakeResponse(200, {"data": {"items": [{"id": f"vm-{index}", "name": f"Test{index}"} for index in range(1, 5)]}}),
                *[
                    FakeResponse(
                        200,
                        {"data": [{"id": f"vol-{index}", "name": f"Test{index}-1", "size": size, "elf_storage_policy": "REPLICA_2_THIN_PROVISION"}]},
                    )
                    for index in range(1, 5)
                ],
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        payload = client.collect_cluster("cluster-a")

        self.assertEqual(payload["cluster"]["allocated_bytes"], 4 * size * 2)
        self.assertEqual([vm["volumes"][0]["replica_num"] for vm in payload["vms"]], [2, 2, 2, 2])

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


class VersionInfoTest(unittest.TestCase):
    """2026-10-07 需求：读 Tower 版本号（平台走 GET /v2/api/get-version，节点走 get-clusters）。"""

    def test_get_version_uses_get_and_returns_plain_text(self) -> None:
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                # get-version 返回纯文本（实测 v4.5.0），不是 JSON
                FakeResponse(200, None, text="v4.5.0\n"),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        version = client.get_version()

        self.assertEqual(version, "v4.5.0")
        # POST 同路径会 405，必须确认真的是 GET
        self.assertEqual(http.requests[-1]["method"], "GET")
        self.assertEqual(http.requests[-1]["path"], "/v2/api/get-version")

    def test_get_version_empty_body_returns_none(self) -> None:
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient([FakeResponse(200, {"data": {"token": "token-1"}}), FakeResponse(200, None, text="  ")])
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        self.assertIsNone(client.get_version())

    def test_version_info_reads_platform_and_cluster_versions(self) -> None:
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(200, None, text="v4.5.0"),  # get-version
                FakeResponse(
                    200,
                    {"data": [{"id": "cluster-a", "name": "CA", "version": "6.1.1"}, {"id": "cluster-b", "name": "CB"}]},
                ),  # get-clusters（cluster-b 无 version → 不记录）
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        info = client.version_info()

        self.assertEqual(info["platform"], "v4.5.0")
        self.assertEqual(info["clusters"], {"cluster-a": "6.1.1"})


if __name__ == "__main__":
    unittest.main()


class TowerApiProfileTest(unittest.TestCase):
    """#84：按 Tower 版本选 API——画像表由官方 4.4.0+ 规范矩阵得出（findings.md 2026-10-07）。"""

    def test_parse_version_variants(self) -> None:
        from app.v2.cloudtower import profiles

        self.assertEqual(profiles.parse_version("v4.5.0"), (4, 5, 0))
        self.assertEqual(profiles.parse_version("4.7"), (4, 7))
        self.assertEqual(profiles.parse_version(" 4 "), (4,))
        self.assertIsNone(profiles.parse_version(None))
        self.assertIsNone(profiles.parse_version(""))
        self.assertIsNone(profiles.parse_version("unknown"))

    def test_profile_floor_selection(self) -> None:
        from app.v2.cloudtower import profiles

        # 4.7.0+：扁平策略字段齐备
        self.assertTrue(profiles.profile_for_version("v4.7.0").volume_flat_policy_fields)
        self.assertTrue(profiles.profile_for_version("v4.9.0").volume_flat_policy_fields)
        # 4.6.x：有 used_size，无扁平策略字段
        profile_46 = profiles.profile_for_version("v4.6.0")
        self.assertFalse(profile_46.volume_flat_policy_fields)
        self.assertTrue(profile_46.volume_used_size)
        # 4.5.x（=.3 测试塔实测版本）：无 used_size、无扁平字段，但容量端点可用
        profile_45 = profiles.profile_for_version("v4.5.0")
        self.assertFalse(profile_45.volume_used_size)
        self.assertFalse(profile_45.vm_used_size)
        self.assertTrue(profile_45.cluster_storage_info_endpoint)
        # 4.4.x：容量端点不存在 → 必须走集群记录兜底
        self.assertFalse(profiles.profile_for_version("v4.4.1").cluster_storage_info_endpoint)
        self.assertFalse(profiles.profile_for_version("v4.4.0").cluster_storage_info_endpoint)

    def test_unknown_or_lower_version_falls_back(self) -> None:
        from app.v2.cloudtower import profiles

        # 版本未知 → 最新画像（由客户端的能力探测兜底，不能因读不到版本而不可用）
        self.assertEqual(profiles.profile_for_version(None), profiles.NEWEST_PROFILE)
        self.assertEqual(profiles.profile_for_version(""), profiles.NEWEST_PROFILE)
        self.assertEqual(profiles.profile_for_version("oops"), profiles.NEWEST_PROFILE)
        # 低于支持下限（4.4.0）→ 按最旧画像处理（不阻断，只降级）
        self.assertEqual(profiles.profile_for_version("v4.0.0"), profiles.PROFILES[-1])

    def test_collect_cluster_uses_cluster_record_capacity_for_legacy_towers(self) -> None:
        """4.4.x 塔没有 get-cluster-storage-info：容量必须从 get-clusters 的集群记录读，且不得请求该端点。"""
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials
        from app.v2.cloudtower.profiles import profile_for_version

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                # 只有 get-clusters（容量兜底来源）与 get-vms；**没有** get-cluster-storage-info 的响应
                FakeResponse(
                    200,
                    {"data": [{"id": "cluster-a", "name": "CA", "version": "5.0.0", "used_data_space": 4096, "total_data_capacity": 8192}]},
                ),
                FakeResponse(200, {"data": {"items": []}}),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        payload = client.collect_cluster("cluster-a", profile=profile_for_version("v4.4.0"))

        self.assertEqual(payload["cluster"]["used_bytes"], 4096)
        self.assertEqual(payload["cluster"]["total_bytes"], 8192)
        self.assertEqual(payload["cluster"]["capacity_source"], "cluster-record")
        paths = [request["path"] for request in http.requests]
        self.assertNotIn("/v2/api/get-cluster-storage-info", paths, "4.4.x 不得请求不存在的容量端点")

    def test_unknown_version_probes_capacity_endpoint_with_fallback(self) -> None:
        """版本未知：先试容量端点，端点报错则回退集群记录（能力探测兜底）。"""
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                # 端点不存在 → 404
                FakeResponse(404, {"message": "not found"}, text="not found"),
                # 回退：get-clusters 带容量
                FakeResponse(
                    200,
                    {"data": [{"id": "cluster-a", "name": "CA", "used_data_space": 100, "total_data_capacity": 200}]},
                ),
                FakeResponse(200, {"data": {"items": []}}),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        payload = client.collect_cluster("cluster-a")  # profile=None → 最新画像 + 探测

        self.assertEqual(payload["cluster"]["used_bytes"], 100)
        self.assertEqual(payload["cluster"]["total_bytes"], 200)
        self.assertEqual(payload["cluster"]["capacity_source"], "cluster-record")

    def test_known_version_endpoint_failure_is_not_silently_swallowed(self) -> None:
        """画像明确端点可用（4.5.0+）时，端点失败必须报错——不能静默换成集群记录掩盖问题。"""
        from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials, CloudTowerError
        from app.v2.cloudtower.profiles import profile_for_version

        http = FakeHttpClient(
            [
                FakeResponse(200, {"data": {"token": "token-1"}}),
                FakeResponse(500, {"message": "boom"}, text="boom"),
            ]
        )
        client = CloudTowerClient(
            CloudTowerCredentials(base_url="https://tower.example.com", username="admin", password="secret"),
            http_client=http,
        )

        with self.assertRaises(CloudTowerError):
            client.collect_cluster("cluster-a", profile=profile_for_version("v4.5.0"))
