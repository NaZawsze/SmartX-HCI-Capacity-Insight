#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class Check:
    id: str
    status: str
    message: str
    details: dict[str, Any] | None = None


class SmokeClient:
    def __init__(self, base_url: str, *, token: str | None = None, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def json(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read()
        return json.loads(body.decode("utf-8")) if body else None


def http_status(url: str, *, timeout: int) -> int:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status)


def run_check(check_id: str, callback) -> Check:
    try:
        return callback()
    except urllib.error.HTTPError as exc:
        return Check(check_id, "critical", f"HTTP {exc.code}: {exc.reason}")
    except Exception as exc:  # noqa: BLE001 - CLI must keep running all checks.
        return Check(check_id, "critical", str(exc))


def ok(check_id: str, message: str, details: dict[str, Any] | None = None) -> Check:
    return Check(check_id, "ok", message, details)


def warning(check_id: str, message: str, details: dict[str, Any] | None = None) -> Check:
    return Check(check_id, "warning", message, details)


def critical(check_id: str, message: str, details: dict[str, Any] | None = None) -> Check:
    return Check(check_id, "critical", message, details)


def login(base_url: str, username: str, password: str, *, timeout: int) -> str:
    client = SmokeClient(base_url, timeout=timeout)
    payload = client.json("/api/auth/login", method="POST", payload={"username": username, "password": password})
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("login response does not contain access_token")
    return token


def vm_name_from_growth(item: dict[str, Any]) -> str:
    labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
    value = item.get("vm_name") or labels.get("vm") or labels.get("vm_name") or item.get("vm_id") or labels.get("vm_id") or ""
    return str(value).strip()


def build_checks(args: argparse.Namespace) -> list[Check]:
    checks: list[Check] = []
    client = SmokeClient(args.base_url, timeout=args.timeout)
    token: str | None = None

    checks.append(
        run_check(
            "frontend.http",
            lambda: ok("frontend.http", f"frontend returned HTTP {http_status(args.frontend_url, timeout=args.timeout)}"),
        )
    )
    checks.append(
        run_check(
            "prometheus.healthy",
            lambda: ok("prometheus.healthy", f"prometheus returned HTTP {http_status(args.prometheus_url.rstrip('/') + '/-/healthy', timeout=args.timeout)}"),
        )
    )

    def health_check() -> Check:
        payload = client.json("/api/system/health")
        version = str(payload.get("version") or "")
        runner = str(payload.get("runner_version") or "")
        if args.expected_version and version != args.expected_version:
            return critical("system.health", f"platform version mismatch: expected {args.expected_version}, got {version}", payload)
        if args.expected_runner_version and runner != args.expected_runner_version:
            return critical("system.health", f"runner version mismatch: expected {args.expected_runner_version}, got {runner}", payload)
        return ok("system.health", f"platform={version}, runner={runner}", payload)

    checks.append(run_check("system.health", health_check))

    if args.username or args.password:
        if not (args.username and args.password):
            checks.append(critical("auth.login", "username and password must be provided together"))
            return checks
        token_holder: dict[str, str] = {}

        def login_check() -> Check:
            token_holder["token"] = login(args.base_url, args.username, args.password, timeout=args.timeout)
            return ok("auth.login", "login succeeded", {"token": True})

        login_result = run_check("auth.login", login_check)
        checks.append(login_result)
        if login_result.status != "ok":
            return checks
        token = token_holder["token"]
        client = SmokeClient(args.base_url, token=token, timeout=args.timeout)

    if not token:
        checks.append(warning("auth.optional", "credentials not provided; authenticated smoke checks skipped"))
        return checks

    checks.append(run_check("tasks.list", lambda: ok("tasks.list", f"tasks={len(client.json('/api/tasks'))}")))

    def report_check() -> Check:
        report = client.json("/api/reports/latest")
        missing = []
        for key in ("day_fastest_growing_vms", "month_fastest_growing_vms"):
            for index, item in enumerate(report.get(key) or []):
                if not vm_name_from_growth(item):
                    missing.append(f"{key}[{index}]")
        if missing:
            return critical("reports.latest", "growth VM name missing: " + ", ".join(missing), {"missing": missing})
        return ok(
            "reports.latest",
            "report growth VM names are present",
            {
                "day_count": len(report.get("day_fastest_growing_vms") or []),
                "month_count": len(report.get("month_fastest_growing_vms") or []),
            },
        )

    checks.append(run_check("reports.latest", report_check))
    checks.append(
        run_check(
            "upgrade.version",
            lambda: ok("upgrade.version", f"upgrade version={client.json('/api/admin/upgrade/version').get('version')}"),
        )
    )
    checks.append(
        run_check(
            "component.runner_version",
            lambda: ok("component.runner_version", f"runner version={client.json('/api/admin/component-upgrade/version').get('version')}"),
        )
    )

    def components_check() -> Check:
        payload = client.json("/api/admin/component-upgrade/components")
        components = payload.get("components") or []
        prometheus = next((item for item in components if item.get("type") == "observability" or item.get("service") == "prometheus"), None)
        version = str((prometheus or {}).get("version") or "")
        if not prometheus:
            return critical("components.prometheus", "prometheus component not found", payload)
        if args.expected_prometheus_version and version != args.expected_prometheus_version:
            return critical("components.prometheus", f"prometheus version mismatch: expected {args.expected_prometheus_version}, got {version}", payload)
        return ok("components.prometheus", f"prometheus={version}", payload)

    checks.append(run_check("components.prometheus", components_check))

    def verification_check() -> Check:
        payload = client.json("/api/admin/upgrade/verification")
        project = str(payload.get("compose_project") or "")
        services = payload.get("services") or []
        service_names = {str(item.get("service") or "") for item in services if isinstance(item, dict)}
        expected_services = {"web-api", "collector-worker", "frontend", "prometheus", "upgrade-runner"}
        missing = sorted(expected_services - service_names)
        if args.expected_compose_project and project != args.expected_compose_project:
            return critical("upgrade.verification", f"compose project mismatch: expected {args.expected_compose_project}, got {project}", payload)
        if missing:
            return critical("upgrade.verification", "missing services: " + ", ".join(missing), payload)
        return ok("upgrade.verification", f"compose_project={project}, services={len(services)}", payload)

    checks.append(run_check("upgrade.verification", verification_check))
    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only release smoke checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--expected-version", default="v0.5.2")
    parser.add_argument("--expected-runner-version", default="v0.3.1")
    parser.add_argument("--expected-prometheus-version", default="v2.55.1")
    parser.add_argument("--expected-compose-project", default="smartx-storage-forecast")
    parser.add_argument("--expected-network", default="smartx-hci-capacity-insight-net")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = build_checks(args)
    critical_count = sum(1 for check in checks if check.status == "critical")
    warning_count = sum(1 for check in checks if check.status == "warning")
    payload = {
        "ok": critical_count == 0 and (warning_count == 0 or not args.fail_on_warning),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "checks": [check.__dict__ for check in checks],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Release smoke: critical={critical_count}, warning={warning_count}")
        for check in checks:
            print(f"[{check.status.upper()}] {check.id}: {check.message}")
    if critical_count:
        return 1
    if warning_count and args.fail_on_warning:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
