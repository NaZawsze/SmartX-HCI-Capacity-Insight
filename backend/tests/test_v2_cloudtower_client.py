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


if __name__ == "__main__":
    unittest.main()
