#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REQUIRED_RUNNER_CAPABILITIES = {
    "backup.create",
    "checkpoint.write",
    "compose.apply",
    "compose.override",
    "files.sync",
    "health.http",
    "health.prometheus",
    "image.load",
    "rollback.restore",
    "script.sandbox.v1",
}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def load_json_url(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        fail(f"cannot request {url}: {exc}")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        fail(f"{url} did not return JSON: {exc}")
    raise AssertionError("unreachable")


def check_health(base_url: str, expected_version: str, expected_runner_version: str) -> None:
    health = load_json_url(f"{base_url.rstrip('/')}/api/system/health")
    if not health.get("ok"):
        fail(f"system health is not ok: {health}")
    if health.get("version") != expected_version:
        fail(f"expected platform {expected_version}, got {health.get('version')}")
    if health.get("runner_version") != expected_runner_version:
        fail(f"expected runner {expected_runner_version}, got {health.get('runner_version')}")
    ok(f"health reports platform={expected_version}, runner={expected_runner_version}")


def check_runner_state(db_path: Path, expected_runner_version: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM upgrade_runner_state WHERE id = 1").fetchone()
    if row is None:
        fail("upgrade_runner_state is missing")
    capabilities = set(json.loads(row["capabilities_json"] or "[]"))
    missing = sorted(REQUIRED_RUNNER_CAPABILITIES - capabilities)
    if row["runner_version"] != expected_runner_version:
        fail(f"runner state version mismatch: {row['runner_version']}")
    if int(row["protocol_version"] or 0) < 1:
        fail(f"runner protocol too old: {row['protocol_version']}")
    if missing:
        fail(f"runner capabilities missing: {missing}")
    ok(f"runner heartbeat present with {len(capabilities)} capabilities at {row['heartbeat_at']}")


def check_success_task_steps(db_path: Path) -> None:
    bad: list[tuple[str, str, str]] = []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, status, steps_json
            FROM tasks
            WHERE type = 'upgrade' AND status = 'success'
            ORDER BY updated_at DESC
            """
        ).fetchall()
    for row in rows:
        steps = json.loads(row["steps_json"] or "[]")
        for step in steps:
            if step.get("status") in {"running", "pending"}:
                bad.append((row["id"], str(step.get("key")), str(step.get("status"))))
    if bad:
        preview = ", ".join(f"{task_id}:{key}={status}" for task_id, key, status in bad[:10])
        fail(f"successful upgrade tasks contain unfinished steps: {preview}")
    ok(f"{len(rows)} successful upgrade task projections have no running/pending steps")


def check_task_files(upgrades_dir: Path) -> None:
    bad: list[str] = []
    checked = 0
    for task_file in upgrades_dir.glob("*/task.json"):
        task = json.loads(task_file.read_text(encoding="utf-8"))
        if task.get("status") != "success":
            continue
        checked += 1
        for step in task.get("steps") or []:
            if step.get("status") in {"running", "pending"}:
                bad.append(f"{task.get('task_id') or task_file.parent.name}:{step.get('key')}={step.get('status')}")
    if bad:
        fail("successful task.json files contain unfinished steps: " + ", ".join(bad[:10]))
    ok(f"{checked} successful task.json files have no running/pending steps")


def check_platform_package(package_path: Path, expected_version: str) -> None:
    if not package_path.exists():
        fail(f"package does not exist: {package_path}")
    with tarfile.open(package_path, "r:gz") as tar:
        names = tar.getnames()
        manifest_file = tar.extractfile("manifest.json")
        if manifest_file is None:
            fail("package missing manifest.json")
        manifest = json.load(manifest_file)
    if manifest.get("version") != expected_version:
        fail(f"package version mismatch: {manifest.get('version')}")
    if manifest.get("database_migration") is not False:
        fail(f"v0.5.0 package should have database_migration=false: {manifest.get('database_migration')}")
    forbidden = {
        "migration": "manifest migration",
        "migration_steps": "manifest migration_steps",
    }
    for key, label in forbidden.items():
        if key in manifest:
            fail(f"v0.5.0 package unexpectedly contains {label}")
    if "script.sandbox.v1" in set(manifest.get("required_capabilities") or []):
        fail("v0.5.0 package without schema migration must not require script.sandbox.v1")
    migration_members = [name for name in names if name.startswith("migrations/") or name == "scripts/migrate.sh"]
    if migration_members:
        fail(f"v0.5.0 package unexpectedly contains migration files: {migration_members}")
    for required in ["images/web-api.tar", "images/collector-worker.tar", "images/frontend.tar"]:
        if required not in names:
            fail(f"package missing {required}")
    ok(f"platform package {package_path.name} has no migration payload and contains platform images")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify v0.5.0 upgrade-center release gates.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--db-path", default="/data/smartx.db")
    parser.add_argument("--upgrades-dir", default="/data/upgrades")
    parser.add_argument("--platform-package")
    parser.add_argument("--expected-version", default="v0.5.0")
    parser.add_argument("--expected-runner-version", default="v0.3.0")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        fail(f"database does not exist: {db_path}")

    check_health(args.base_url, args.expected_version, args.expected_runner_version)
    check_runner_state(db_path, args.expected_runner_version)
    check_success_task_steps(db_path)
    check_task_files(Path(args.upgrades_dir))
    if args.platform_package:
        check_platform_package(Path(args.platform_package), args.expected_version)
    ok("v0.5.0 upgrade-center verification gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

