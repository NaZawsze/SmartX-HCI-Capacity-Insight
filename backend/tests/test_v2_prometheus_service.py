import unittest


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="OK") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.requests = []

    def get(self, path, params=None):
        self.requests.append({"path": path, "params": params or {}})
        if not self.responses:
            raise AssertionError("No fake response configured.")
        return self.responses.pop(0)

    def close(self):
        pass


class V2PrometheusServiceTest(unittest.TestCase):
    def test_health_checks_ready_endpoint(self) -> None:
        from app.v2.metrics.prometheus import PrometheusService

        http = FakeHttpClient([FakeResponse(200, text="Ready")])
        result = PrometheusService("http://prometheus:9090", http_client=http).health()

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "Prometheus ready.")
        self.assertEqual(http.requests[0]["path"], "/-/ready")

    def test_query_and_query_range_return_result_arrays(self) -> None:
        from app.v2.metrics.prometheus import PrometheusService

        http = FakeHttpClient(
            [
                FakeResponse(200, {"status": "success", "data": {"result": [{"metric": {"vm_id": "vm-1"}, "value": [1, "42"]}]}}),
                FakeResponse(200, {"status": "success", "data": {"result": [{"metric": {"vm_id": "vm-1"}, "values": [[1, "40"], [2, "42"]]}]}}),
            ]
        )
        service = PrometheusService("http://prometheus:9090", http_client=http)

        instant = service.instant("smartx_vm_storage_used_bytes")
        ranged = service.range("smartx_vm_storage_used_bytes", start=100, end=200, step="1h")

        self.assertEqual(instant[0]["metric"]["vm_id"], "vm-1")
        self.assertEqual(ranged[0]["values"][1], [2, "42"])
        self.assertEqual(http.requests[0]["path"], "/api/v1/query")
        self.assertEqual(http.requests[0]["params"]["query"], "smartx_vm_storage_used_bytes")
        self.assertEqual(http.requests[1]["path"], "/api/v1/query_range")
        self.assertEqual(http.requests[1]["params"], {"query": "smartx_vm_storage_used_bytes", "start": 100, "end": 200, "step": "1h"})

    def test_health_reports_permission_style_error(self) -> None:
        from app.v2.metrics.prometheus import PrometheusService

        http = FakeHttpClient([FakeResponse(503, text="permission denied")])
        result = PrometheusService("http://prometheus:9090", http_client=http).health()

        self.assertFalse(result.ok)
        self.assertIn("permission denied", result.message)


if __name__ == "__main__":
    unittest.main()
