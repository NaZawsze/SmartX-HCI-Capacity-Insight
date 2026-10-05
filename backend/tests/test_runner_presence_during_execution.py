from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.upgrade_protocol.constants import RUNNER_CAPABILITIES  # noqa: E402
from app.v2.config import V2Settings  # noqa: E402
from app.v2.database import V2Database  # noqa: E402
from app.v2.system.health import RUNNER_NOT_DETECTED, _active_runner_version  # noqa: E402
from app.v2.tasks.service import TaskService  # noqa: E402
from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService  # noqa: E402
from app.v2.upgrade.service.runner_presence import (  # noqa: E402
    HEARTBEAT_SOURCE,
    TASK_LEASE_SOURCE,
    active_task_lease_is_fresh,
    instance_heartbeat_is_fresh,
    presence_source,
)

# 这些时间戳**必须在每个用例里现算**，不能钉在模块导入时刻。
# `RUNNER_HEARTBEAT_STALE_SECONDS = 30`：导入到执行之间一旦超过 30 秒（本项目全量约 6 分钟），
# "新鲜心跳"就变成过期心跳 → 两例必然失败。钉在模块级时它们单跑绿、全量红，
# 会把"环境/顺序问题"混进回归基线，掩盖真正的回归（2026-10-06 全量首次撞上）。


def _stale() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()


def _fresh() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunnerPresenceTest(unittest.TestCase):
    def setUp(self):
        self.stale = _stale()
        self.fresh = _fresh()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = V2Settings(data_root=Path(self.tmp.name), secret_key="upgrade-secret", app_version="v0.5.3")
        self.database = V2Database(self.settings)
        self.database.initialize()
        self.tasks = TaskService(self.database)
        self.project_path = Path(self.tmp.name) / "project"

    def _service(self) -> UpgradeService:
        class FakeExecutor(UpgradeCommandExecutor):
            def run(self, command, *, cwd=None):  # pragma: no cover
                return None

            def output(self, command, *, cwd=None):  # pragma: no cover
                return ""

        return UpgradeService(self.settings, self.tasks, executor=FakeExecutor(), project_path=self.project_path)

    def _set_instance_heartbeat(self, value: str) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO upgrade_runner_state
                    (id, instance_id, runner_version, protocol_version, capabilities_json, heartbeat_at, updated_at)
                VALUES (1, 'runner-a', 'v0.3.1', 1, ?, ?, ?)
                """,
                (json.dumps(sorted(RUNNER_CAPABILITIES)), value, value),
            )

    def _add_lease(self, *, task_id: str = "upgrade-x", expires_delta_seconds: int, heartbeat: str) -> None:
        expires = (datetime.now(timezone.utc) + timedelta(seconds=expires_delta_seconds)).isoformat()
        with self.database.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO upgrade_task_leases (task_id, lease_owner, lease_expires_at, heartbeat_at, revision)"
                " VALUES (?, 'runner-a', ?, ?, 0)",
                (task_id, expires, heartbeat),
            )

    # ---- 纯判定 ----------------------------------------------------------
    def test_fresh_instance_heartbeat_is_heartbeat_source(self):
        self._set_instance_heartbeat(self.fresh)
        self.assertEqual(presence_source(self.database, {"heartbeat_at": self.fresh}), HEARTBEAT_SOURCE)
        self.assertTrue(instance_heartbeat_is_fresh({"heartbeat_at": self.fresh}))

    def test_stale_instance_heartbeat_alone_is_not_present(self):
        self._set_instance_heartbeat(self.stale)
        self.assertIsNone(presence_source(self.database, {"heartbeat_at": self.stale}))
        self.assertFalse(active_task_lease_is_fresh(self.database))

    def test_live_lease_makes_runner_present_despite_stale_instance_heartbeat(self):
        self._set_instance_heartbeat(self.stale)
        self._add_lease(expires_delta_seconds=25, heartbeat=self.fresh)
        self.assertTrue(active_task_lease_is_fresh(self.database))
        self.assertEqual(presence_source(self.database, {"heartbeat_at": self.stale}), TASK_LEASE_SOURCE)

    def test_recent_lease_heartbeat_is_enough_even_if_expires_field_is_old(self):
        self._set_instance_heartbeat(self.stale)
        self._add_lease(expires_delta_seconds=-5, heartbeat=self.fresh)
        self.assertTrue(active_task_lease_is_fresh(self.database))

    def test_expired_lease_with_old_heartbeat_is_not_present(self):
        self._set_instance_heartbeat(self.stale)
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self._add_lease(expires_delta_seconds=-60, heartbeat=old)
        self.assertFalse(active_task_lease_is_fresh(self.database))
        self.assertIsNone(presence_source(self.database, {"heartbeat_at": self.stale}))

    def test_missing_state_is_not_present(self):
        self.assertIsNone(presence_source(self.database, None))
        self.assertIsNone(presence_source(self.database, {}))

    def test_lease_query_failure_is_not_present(self):
        with mock.patch.object(V2Database, "connection", side_effect=RuntimeError("db down")):
            self.assertFalse(active_task_lease_is_fresh(self.database))

    # ---- web-api 消费点 ---------------------------------------------------
    def test_active_runner_version_resolves_during_execution(self):
        self._set_instance_heartbeat(self.stale)
        self._add_lease(expires_delta_seconds=25, heartbeat=self.fresh)
        service = self._service()
        with mock.patch.object(UpgradeService, "_active_runner_state_from_docker", return_value=None):
            self.assertEqual(service._active_runner_version(), "v0.3.1")
            self.assertEqual(service._active_runner_state().get("source"), TASK_LEASE_SOURCE)

    def test_active_runner_version_reports_not_detected_without_both_channels(self):
        self._set_instance_heartbeat(self.stale)
        service = self._service()
        with mock.patch.object(UpgradeService, "_active_runner_state_from_docker", return_value=None):
            self.assertEqual(service._active_runner_version(), RUNNER_NOT_DETECTED)

    def test_runner_protocol_check_accepts_task_lease_source(self):
        self._set_instance_heartbeat(self.stale)
        self._add_lease(expires_delta_seconds=25, heartbeat=self.fresh)
        service = self._service()
        manifest = {
            "schema_version": "3",
            "minimum_runner_protocol": 1,
            "minimum_runner_version": "v0.3.1",
            "required_capabilities": sorted(RUNNER_CAPABILITIES),
            "components": [{"type": "platform", "services": ["web-api"], "images": []}],
        }
        with mock.patch.object(UpgradeService, "_active_runner_state_from_docker", return_value=None):
            check = service._check_runner_protocol(manifest)
        self.assertTrue(check["ok"], check)

    def test_component_catalog_is_compatible_with_task_lease_source(self):
        self._set_instance_heartbeat(self.stale)
        self._add_lease(expires_delta_seconds=25, heartbeat=self.fresh)
        service = self._service()
        with mock.patch.object(UpgradeService, "_active_runner_state_from_docker", return_value=None), \
             mock.patch.object(UpgradeService, "_inspect_service_by_name", return_value={}):
            catalog = service.component_catalog()
        runner = next(item for item in catalog["components"] if item["type"] == "runner")
        self.assertEqual(runner["version"], "v0.3.1")
        self.assertTrue(runner["compatible"], runner)

    def test_health_runner_version_uses_task_lease(self):
        self._set_instance_heartbeat(self.stale)
        self._add_lease(expires_delta_seconds=25, heartbeat=self.fresh)
        self.assertEqual(_active_runner_version(self.settings, self.database, runner_probe=lambda: ""), "v0.3.1")

    def test_health_runner_version_falls_back_to_probe_without_lease(self):
        self._set_instance_heartbeat(self.stale)
        self.assertEqual(_active_runner_version(self.settings, self.database, runner_probe=lambda: ""), RUNNER_NOT_DETECTED)
        self.assertEqual(_active_runner_version(self.settings, self.database, runner_probe=lambda: "v0.3.1"), "v0.3.1")


if __name__ == "__main__":
    unittest.main()
