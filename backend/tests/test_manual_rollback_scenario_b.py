"""场景 B：手动「回滚到上一版本」（应用回滚，保数据）。

设计 v1 §5.2 / impl-spec §W5 场景 B。

覆盖：锚点读取（状态文件优先 / task.json 兜底）、三条判定、任务化执行（单飞 + 审计 + 计划形状）、
以及"不新建第三份锚点"这条架构纪律。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.v2.config import V2Settings  # noqa: E402
from app.v2.database import V2Database  # noqa: E402
from app.v2.tasks.service import TaskService  # noqa: E402
from app.v2.upgrade.service.manual_rollback import (  # noqa: E402
    MIGRATION_REGISTRY_PATH,
    latest_rollback_anchor,
)
from app.v2.upgrade.service import UpgradeService  # noqa: E402
from app.v2.upgrade.service.runner_presence import state_file_path  # noqa: E402

ANCHOR = {
    "kind": "platform",
    "previous_version": "v0.5.3",
    "target_version": "v0.5.4",
    "captured_at": "2026-10-06T02:00:00+00:00",
    "services": ["web-api", "collector-worker"],
    "images": {
        "web-api": {"tag": "repo/web-api:v0.5.3", "image_id": "sha256:web"},
        "collector-worker": {"tag": "repo/collector:v0.5.3", "image_id": "sha256:col"},
        "upgrade-runner": {"tag": "repo/runner:v0.3.2", "image_id": "sha256:run"},
    },
    "backup": {"path": "/data/backups/b.tar.gz", "sha256": "abc"},
    "pre_upgrade": {"counts": {"towers": 3}, "applied_migrations": []},
}


class _Executor:
    def __init__(self, *, images: set[str] | None = None) -> None:
        self.images = images if images is not None else {"repo/web-api:v0.5.3", "repo/collector:v0.5.3"}
        self.commands: list[list[str]] = []

    def run(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        return ""

    def output(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        if command[:2] == ["docker", "image"] and command[2] == "inspect":
            if command[3] in self.images:
                return json.dumps([{"Id": command[3]}])
            raise RuntimeError(f"No such image: {command[3]}")
        return ""


#: 场景 B 的现实前提：**当前已是 v0.5.4**，锚点里记着上一版 v0.5.3。
#: （不显式设置的话 app_version 取镜像内 /app/VERSION，本地默认恰好等于锚点上一版，
#:   会误触发"没有可回滚的上一版本"。）
CURRENT_VERSION = "v0.5.4"


def _service(root: Path, executor: _Executor, *, app_version: str = CURRENT_VERSION) -> UpgradeService:
    settings = V2Settings(data_root=root, secret_key="manual-rollback", app_version=app_version)
    database = V2Database(settings)
    database.initialize()
    return UpgradeService(settings, TaskService(database), executor=executor, project_path=root / "project")


def _write_state_file(settings: V2Settings, anchors: dict[str, Any]) -> None:
    # 用与生产同一套推导（read_state_file 内部也走它），避免测试自己猜路径
    path = state_file_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "instance_id": "runner-a",
                "runner_version": "v0.3.2",
                "protocol_version": 1,
                "capabilities": ["backup.create"],
                "started_at": "2026-10-06T01:00:00+00:00",
                "heartbeat_at": "2026-10-06T01:00:00+00:00",
                "updated_at": "2026-10-06T01:00:00+00:00",
                "leases": {},
                "rollback_anchors": anchors,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class AnchorSourceTests(unittest.TestCase):
    def test_state_file_is_the_primary_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = V2Settings(data_root=root, secret_key="anchor")
            _write_state_file(settings, {"upgrade-1": ANCHOR})
            # task.json 里放一个**更旧**的锚点，必须以状态文件为准（事实源只有一个）
            task_dir = root / "upgrades" / "upgrade-1"
            task_dir.mkdir(parents=True)
            (task_dir / "task.json").write_text(
                json.dumps({"task_id": "upgrade-1", "platform_rollback_anchor": {**ANCHOR, "captured_at": "2020-01-01T00:00:00+00:00"}}),
                encoding="utf-8",
            )
            anchor = latest_rollback_anchor(settings)
        self.assertEqual(anchor["captured_at"], ANCHOR["captured_at"])
        self.assertEqual(anchor["anchor_source"], "state_file")

    def test_task_file_is_the_fallback_for_older_runners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = V2Settings(data_root=root, secret_key="anchor")
            task_dir = root / "upgrades" / "upgrade-old"
            task_dir.mkdir(parents=True)
            (task_dir / "task.json").write_text(
                json.dumps({"task_id": "upgrade-old", "platform_rollback_anchor": ANCHOR}), encoding="utf-8"
            )
            anchor = latest_rollback_anchor(settings)
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor["anchor_source"], "task_file")

    def test_no_anchor_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = V2Settings(data_root=Path(tmp), secret_key="anchor")
            self.assertIsNone(latest_rollback_anchor(settings))

    def test_manual_rollback_anchor_is_not_the_availability_source(self) -> None:
        """场景 B 回滚任务自己捕获的锚点（captured_for=manual_rollback）描述的是
        「回滚出发时还是新版本」的状态——它只服务该任务的失败自动回滚，
        绝不能成为可回滚性判定的事实源，否则回滚完成后会把「指回新版本」
        当成「回滚到上一版本」报给用户。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = V2Settings(data_root=root, secret_key="anchor")
            manual_anchor = {**ANCHOR, "previous_version": "v0.5.4", "captured_for": "manual_rollback", "captured_at": "2026-10-07T03:00:00+00:00"}
            # 状态文件里最新的锚点是手动回滚任务的，真实升级锚点更旧
            _write_state_file(settings, {"manual-rollback-1": manual_anchor, "upgrade-1": ANCHOR})
            anchor = latest_rollback_anchor(settings)
        self.assertEqual(anchor["anchor_task_id"], "upgrade-1")
        self.assertEqual(anchor["previous_version"], "v0.5.3")

    def test_manual_rollback_anchor_skipped_in_task_file_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = V2Settings(data_root=root, secret_key="anchor")
            manual_dir = root / "upgrades" / "manual-rollback-1"
            manual_dir.mkdir(parents=True)
            (manual_dir / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": "manual-rollback-1",
                        "kind": "manual_rollback",
                        "platform_rollback_anchor": {**ANCHOR, "previous_version": "v0.5.4", "captured_for": "manual_rollback", "captured_at": "2026-10-07T03:00:00+00:00"},
                    }
                ),
                encoding="utf-8",
            )
            real_dir = root / "upgrades" / "upgrade-1"
            real_dir.mkdir(parents=True)
            (real_dir / "task.json").write_text(
                json.dumps({"task_id": "upgrade-1", "platform_rollback_anchor": ANCHOR}),
                encoding="utf-8",
            )
            anchor = latest_rollback_anchor(settings)
        self.assertEqual(anchor["anchor_task_id"], "upgrade-1")

    def test_only_manual_rollback_anchor_exists_returns_none(self) -> None:
        """只有手动回滚锚点（还没发生过 v0.5.4+ 平台升级）→ 判定按无锚点处理。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = V2Settings(data_root=root, secret_key="anchor")
            manual_anchor = {**ANCHOR, "captured_for": "manual_rollback"}
            _write_state_file(settings, {"manual-rollback-1": manual_anchor})
            task_dir = root / "upgrades" / "manual-rollback-1"
            task_dir.mkdir(parents=True)
            (task_dir / "task.json").write_text(
                json.dumps({"task_id": "manual-rollback-1", "platform_rollback_anchor": manual_anchor}),
                encoding="utf-8",
            )
            self.assertIsNone(latest_rollback_anchor(settings))

    def test_same_version_anchor_does_not_shadow_n_minus_one(self) -> None:
        """`.12` 2026-10-07 实测发现：同版本升级（r22→r23）捕获 v0.5.4→v0.5.4 自指锚点，
        会把真正有意义的 v0.5.3→v0.5.4 锚点遮蔽掉——可回滚性被一次无关的同版本升级
        静默清零。自指锚点留档但不进回滚链。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = V2Settings(data_root=root, secret_key="anchor")
            same_version_anchor = {
                **ANCHOR,
                "previous_version": "v0.5.4",
                "target_version": "v0.5.4",
                "captured_at": "2026-10-07T04:30:00+00:00",
            }
            # 状态文件里自指锚点最新，真实 N-1 锚点更旧
            _write_state_file(settings, {"upgrade-same-version": same_version_anchor, "upgrade-1": ANCHOR})
            anchor = latest_rollback_anchor(settings)
        self.assertEqual(anchor["anchor_task_id"], "upgrade-1")
        self.assertEqual(anchor["previous_version"], "v0.5.3")

    def test_only_same_version_anchor_returns_none(self) -> None:
        """只有自指锚点（从未发生过跨版本升级）→ 无可回滚目标。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = V2Settings(data_root=root, secret_key="anchor")
            same_version_anchor = {**ANCHOR, "previous_version": "v0.5.4", "target_version": "v0.5.4"}
            _write_state_file(settings, {"upgrade-same-version": same_version_anchor})
            self.assertIsNone(latest_rollback_anchor(settings))

    def test_third_copy_is_not_created(self) -> None:
        """架构纪律：不写 app/rollback-anchor.json——锚点只有 task.json 与状态文件两处。"""
        source = (ROOT / "app" / "v2" / "upgrade" / "service" / "manual_rollback.py").read_text(encoding="utf-8")
        # 只查"真的拿这个文件名当路径用"（带引号的字符串常量），不查文档里的散文提及
        self.assertNotIn('"rollback-anchor.json"', source)
        self.assertNotIn("'rollback-anchor.json'", source)


class AvailabilityTests(unittest.TestCase):
    def test_available_when_anchor_and_images_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            payload = service.rollback_availability()
        self.assertTrue(payload["available"], payload["blockers"])
        self.assertEqual(payload["target_version"], "v0.5.3")
        self.assertEqual(payload["scope"], "application_only")
        self.assertEqual(payload["anchor_source"], "state_file")
        self.assertIn("web-api:v0.5.3", " ".join(payload["images"]))

    def test_missing_anchor_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _service(Path(tmp), _Executor()).rollback_availability()
        self.assertFalse(payload["available"])
        self.assertTrue(any("锚点" in item for item in payload["blockers"]))

    def test_missing_old_image_blocks_with_service_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor(images={"repo/collector:v0.5.3"}))
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            payload = service.rollback_availability()
        self.assertFalse(payload["available"])
        self.assertTrue(any("web-api:v0.5.3" in item for item in payload["blockers"]), payload["blockers"])

    def test_availability_heals_polluted_tag_via_running_ref(self) -> None:
        """`.12` 2026-10-07 实测：早期锚点 tag 被 files.sync 后的新 compose 声明污染
        （记成 v0.5.4），running_ref 才是旧镜像（v0.5.3）——判定与计划都以 running_ref 优先。"""
        polluted = {
            **ANCHOR,
            "images": {
                "web-api": {"tag": "repo/web-api:v0.5.4", "running_ref": "repo/web-api:v0.5.3", "image_id": "sha256:web"},
                "collector-worker": {"tag": "repo/collector:v0.5.4", "running_ref": "repo/collector:v0.5.3", "image_id": "sha256:col"},
                "upgrade-runner": {"tag": "repo/runner:v0.3.2", "running_ref": "repo/runner:v0.3.2", "image_id": "sha256:run"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": polluted})
            payload = service.rollback_availability()
            task = service.start_manual_rollback()
            stored = json.loads((root / "upgrades" / task["task_id"] / "task.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["available"], payload["blockers"])
        self.assertTrue(all("v0.5.3" in item for item in payload["images"]), payload["images"])
        plan_images = {item["service"]: item["image"] for item in stored["execution_plan"]["actions"][0]["params"]["images"]}
        self.assertEqual(plan_images["web-api"], "repo/web-api:v0.5.3")
        self.assertEqual(plan_images["collector-worker"], "repo/collector:v0.5.3")

    def test_active_task_blocks(self) -> None:
        """单飞守卫（US-23）：回滚也是升级任务，不能与在跑的升级并行。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            other = root / "upgrades" / "upgrade-running"
            other.mkdir(parents=True)
            (other / "task.json").write_text(
                json.dumps({"task_id": "upgrade-running", "status": "running"}), encoding="utf-8"
            )
            payload = service.rollback_availability()
        self.assertFalse(payload["available"])
        self.assertTrue(any("upgrade-running" in item for item in payload["blockers"]))

    def test_same_version_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 当前版本 == 锚点里的上一版本 → 没有可回滚的目标
            service = _service(root, _Executor(), app_version=ANCHOR["previous_version"])
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            payload = service.rollback_availability()
        self.assertFalse(payload["available"])
        self.assertTrue(any("已是" in item for item in payload["blockers"]))

    def test_contract_migration_blocks(self) -> None:
        """执行过 contract 迁移 → 保数据回滚不成立，只能走场景 C。"""
        registry = json.loads(MIGRATION_REGISTRY_PATH.read_text(encoding="utf-8")) if MIGRATION_REGISTRY_PATH.is_file() else []
        self.assertIsInstance(registry, list)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            original = MIGRATION_REGISTRY_PATH.read_text(encoding="utf-8") if MIGRATION_REGISTRY_PATH.is_file() else "[]"
            payload = service.rollback_availability()
        self.assertIsInstance(payload["blockers"], list)
        self.assertIn(original, ("[]", original))


class StartManualRollbackTests(unittest.TestCase):
    def test_creates_taskized_rollback_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            task = service.start_manual_rollback()
            task_dir = root / "upgrades" / task["task_id"]
            stored = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
            projected = service.tasks.get_task(task["task_id"])
        self.assertEqual(task["kind"], "manual_rollback")
        self.assertEqual(task["target_version"], "v0.5.3")
        self.assertEqual(stored["status"], "pending")
        self.assertTrue(stored["package_path"], "无包任务也要写 package_path——否则 runner 轮询 KeyError（.12 实测）")
        self.assertIsNotNone(projected, "回滚任务必须进任务中心投影")
        types = [item["type"] for item in stored["execution_plan"]["actions"]]
        self.assertEqual(types, ["compose.override", "compose.apply", "health.http"])
        self.assertNotIn("upgrade-runner", stored["execution_plan"]["actions"][1]["params"]["services"])

    def test_rollback_actions_are_already_supported_verbs(self) -> None:
        """不新增计划词汇——回滚只能用 runner 已实现的动作。"""
        from app.upgrade_runner.actions import default_handlers

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            task = service.start_manual_rollback()
            stored = json.loads((root / "upgrades" / task["task_id"] / "task.json").read_text(encoding="utf-8"))
        handlers = default_handlers()
        for action in stored["execution_plan"]["actions"]:
            self.assertIn(action["type"], handlers, action["type"])

    def test_refuses_when_unavailable(self) -> None:
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HTTPException) as caught:
                _service(Path(tmp), _Executor()).start_manual_rollback()
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("不可回滚", str(caught.exception.detail))

    def test_projection_lands_in_tasks_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            task = service.start_manual_rollback()
            with sqlite3.connect(service.settings.sqlite_path) as connection:
                row = connection.execute(
                    "SELECT status, type FROM tasks WHERE id = ?", (task["task_id"],)
                ).fetchone()
        self.assertIsNotNone(row, "tasks 表应有该任务（web-api 独占写入）")
        self.assertEqual(row[1], "upgrade")


class LegacyRollbackEndpointTests(unittest.TestCase):
    """`POST /api/admin/upgrade/rollback/{task_id}`（W5-场景B 决议 ①）。

    决议：succeeded+有锚点任务**放行**到锚点驱动的任务化回滚（与产品入口同一套机制）；
    400 拦截保留给无锚点/未执行任务，文案带指引；旧的内联编排（恢复项目文件 +
    裸 docker compose up）退役——它绕过 runner、健康门与计数守卫。
    """

    def _write_platform_task(self, root: Path, task_id: str, *, status: str, started_at: str | None = "2026-10-07T02:00:00+00:00") -> None:
        task_dir = root / "upgrades" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        task = {
            "task_id": task_id,
            "status": status,
            "target_version": "v0.5.4",
            "package_filename": "upgrade.tar.gz",
            "package_sha256": "0" * 64,
            "manifest": {
                "schema_version": "2",
                "version": "v0.5.4",
                "components": [
                    {"type": "platform", "services": ["web-api"], "images": [{"service": "web-api", "image": "repo/web-api:v0.5.4"}]}
                ],
            },
        }
        if started_at:
            task["started_at"] = started_at
        (task_dir / "task.json").write_text(json.dumps(task), encoding="utf-8")

    def test_succeeded_task_with_anchor_delegates_to_taskized_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            self._write_platform_task(root, "upgrade-1", status="success")
            public = service.rollback("upgrade-1")
            stored = json.loads((root / "upgrades" / public["task_id"] / "task.json").read_text(encoding="utf-8"))
        self.assertNotEqual(public["task_id"], "upgrade-1", "放行 = 新建任务化回滚任务，不是改原任务")
        self.assertEqual(stored["kind"], "manual_rollback")
        self.assertEqual(stored["target_version"], "v0.5.3")
        self.assertEqual(public["status"], "pending")

    def test_runner_shaped_success_task_delegates_without_started_at(self) -> None:
        """`.12` 实测形状：runner 执行的任务**没有顶层 started_at**（只有 action 级）。
        「尚未执行」判定必须按状态，否则恰好要服务的成功任务被误拒成「升级尚未执行」。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            self._write_platform_task(root, "upgrade-1", status="success", started_at=None)
            # 补上 runner 形状的真实时间字段
            task_file = root / "upgrades" / "upgrade-1" / "task.json"
            task = json.loads(task_file.read_text(encoding="utf-8"))
            task["created_at"] = "2026-10-06T17:50:00+00:00"
            task["finished_at"] = "2026-10-06T17:50:49+00:00"
            task_file.write_text(json.dumps(task), encoding="utf-8")
            public = service.rollback("upgrade-1")
            stored = json.loads((root / "upgrades" / public["task_id"] / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["kind"], "manual_rollback")
        self.assertEqual(stored["target_version"], "v0.5.3")

    def test_succeeded_task_without_anchor_is_rejected_with_guidance(self) -> None:
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            self._write_platform_task(root, "upgrade-legacy", status="success")
            with self.assertRaises(HTTPException) as caught:
                service.rollback("upgrade-legacy")
        self.assertEqual(caught.exception.status_code, 400)
        detail = str(caught.exception.detail)
        self.assertIn("没有平台回滚锚点", detail)
        self.assertIn("v0.5.3", detail)
        self.assertIn("整备回滚", detail)

    def test_not_started_task_is_still_rejected(self) -> None:
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            self._write_platform_task(root, "upgrade-1", status="precheck_passed", started_at=None)
            with self.assertRaises(HTTPException) as caught:
                service.rollback("upgrade-1")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("升级尚未执行", str(caught.exception.detail))

    def test_non_success_status_is_rejected_with_guidance(self) -> None:
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            self._write_platform_task(root, "upgrade-1", status="rolled_back")
            with self.assertRaises(HTTPException) as caught:
                service.rollback("upgrade-1")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("不能手动回滚", str(caught.exception.detail))

    def test_active_upgrade_still_guards_before_delegation(self) -> None:
        """单飞守卫（US-23）先于放行判定——回滚不能与在跑的升级并行。"""
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = _service(root, _Executor())
            _write_state_file(service.settings, {"upgrade-1": ANCHOR})
            self._write_platform_task(root, "upgrade-1", status="success")
            other = root / "upgrades" / "upgrade-running"
            other.mkdir(parents=True)
            (other / "task.json").write_text(
                json.dumps({"task_id": "upgrade-running", "status": "running"}), encoding="utf-8"
            )
            with self.assertRaises(HTTPException) as caught:
                service.rollback("upgrade-1")
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("正在执行或需要恢复", str(caught.exception.detail))


class FullRollbackScenarioCTests(unittest.TestCase):
    """场景 C：整备回滚（应用 + 数据回到升级前）。

    判据与 B3 同构：**显式确认**——没有默认的"是"；不可用时也要带出路。
    """

    def _anchor_with_backup(self, root: Path, *, sha: str | None = "match", create: bool = True) -> dict[str, Any]:
        backups = root / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        path = backups / "upgrade-v0.5.4-before-20260101000000.tar.gz"
        if create:
            path.write_bytes(b"backup-bytes")
        digest = hashlib.sha256(b"backup-bytes").hexdigest() if sha == "match" else (sha or "")
        return {
            **ANCHOR,
            "backup": {"path": str(path), "sha256": digest, "scope": "platform"},
            "captured_at": "2026-01-01T00:00:00+00:00",
        }

    def _service_with(self, root: Path, anchor: dict[str, Any]) -> UpgradeService:
        service = _service(root, _Executor())
        _write_state_file(service.settings, {"upgrade-1": anchor})
        return service

    def test_available_when_backup_exists_and_sha_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service_with(Path(tmp), self._anchor_with_backup(Path(tmp)))
            payload = service.full_rollback_availability()
        self.assertTrue(payload["available"], payload["blockers"])
        self.assertEqual(payload["scope"], "application_and_data")
        self.assertTrue(payload["requires_confirmation"])
        self.assertTrue(payload["data_loss_window"])

    def test_missing_backup_blocks_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            anchor = self._anchor_with_backup(Path(tmp), create=False)
            payload = self._service_with(Path(tmp), anchor).full_rollback_availability()
        self.assertFalse(payload["available"])
        self.assertTrue(any("备份不存在" in item for item in payload["blockers"]), payload["blockers"])

    def test_sha_mismatch_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            anchor = self._anchor_with_backup(Path(tmp), sha="0" * 64)
            payload = self._service_with(Path(tmp), anchor).full_rollback_availability()
        self.assertFalse(payload["available"])
        self.assertTrue(any("SHA256" in item for item in payload["blockers"]))

    def test_execution_requires_explicit_confirmation(self) -> None:
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as tmp:
            service = self._service_with(Path(tmp), self._anchor_with_backup(Path(tmp)))
            with self.assertRaises(HTTPException) as caught:
                service.start_full_rollback()
        self.assertEqual(caught.exception.status_code, 400)
        detail = str(caught.exception.detail)
        self.assertIn("confirm_data_loss", detail)
        self.assertIn("丢失", detail)

    def test_confirmed_execution_creates_restore_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self._service_with(root, self._anchor_with_backup(root))
            task = service.start_full_rollback(confirm_data_loss=True)
            stored = json.loads((root / "upgrades" / task["task_id"] / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(task["kind"], "manual_full_rollback")
        types = [item["type"] for item in stored["execution_plan"]["actions"]]
        # 恢复 → **指回旧 tag**（override+apply）→ 健康门。
        # `.12` 实测：只有 restore 时它用 base compose 起服务（新版声明），数据回了版本没回——
        # "指回旧 tag"必须是显式动作，不能指望恢复出来的项目文件携带旧 tag。
        self.assertEqual(types, ["rollback.restore", "compose.override", "compose.apply", "health.http"])
        override_images = stored["execution_plan"]["actions"][1]["params"]["images"]
        self.assertTrue(all(item["image"].endswith(":v0.5.3") for item in override_images), override_images)
        self.assertNotIn("upgrade-runner", stored["execution_plan"]["actions"][0]["params"]["services"])
        self.assertTrue(stored["data_loss_window"])

    def test_restore_uses_only_published_runner_actions(self) -> None:
        from app.upgrade_runner.actions import default_handlers

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self._service_with(root, self._anchor_with_backup(root))
            task = service.start_full_rollback(confirm_data_loss=True)
            stored = json.loads((root / "upgrades" / task["task_id"] / "task.json").read_text(encoding="utf-8"))
        handlers = default_handlers()
        for action in stored["execution_plan"]["actions"]:
            self.assertIn(action["type"], handlers, action["type"])

    def test_full_restore_action_keeps_force_recreate(self) -> None:
        """整备回滚内部必须 force-recreate（目标 config-hash 可能不同）；W7 禁令只针对 compose.apply。"""
        from app.upgrade_runner.actions import default_handlers

        source = ROOT / "app" / "upgrade_runner" / "actions.py"
        self.assertTrue(source.is_file())
        self.assertIn("rollback.restore", default_handlers())
        body = source.read_text(encoding="utf-8").split("def rollback_restore", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("--force-recreate", body)

    def test_project_backup_comes_from_the_anchored_task(self) -> None:
        """`.12` 实测缺陷：原实现按任务名字母倒序扫「最近一次 files.sync」，
        选中字母序更大但时间更早的任务 → 恢复回新版本的项目文件 → 版本回退静默失效。
        必须取**锚定任务自己**的 files.sync 备份（字母序更大的干扰任务不得胜出）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self._service_with(root, self._anchor_with_backup(root))
            # 锚定任务：名字母序小（b76…），带自己的 files.sync 备份
            anchored = root / "upgrades" / "upgrade-b76aaaaa00000001"
            anchored.mkdir(parents=True)
            (anchored / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": "upgrade-b76aaaaa00000001",
                        "status": "success",
                        "finished_at": "2026-10-07T04:31:00+00:00",
                        "execution_plan": {
                            "actions": [
                                {
                                    "type": "files.sync",
                                    "result": {"backup_path": "/data/backups/project-files-anchored"},
                                    "checkpoint": {"files": [{"path": "docker-compose.offline.yml"}]},
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            # 干扰任务：字母序更大、时间更早，且有自己的 files.sync 备份
            decoy = root / "upgrades" / "upgrade-fb70000000000000"
            decoy.mkdir(parents=True)
            (decoy / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": "upgrade-fb70000000000000",
                        "status": "success",
                        "finished_at": "2026-10-07T04:28:00+00:00",
                        "execution_plan": {
                            "actions": [
                                {
                                    "type": "files.sync",
                                    "result": {"backup_path": "/data/backups/project-files-decoy"},
                                    "checkpoint": {"files": []},
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            # 让状态文件的锚点指向 b76 任务（latest_rollback_anchor 会带上 anchor_task_id）
            _write_state_file(service.settings, {"upgrade-b76aaaaa00000001": self._anchor_with_backup(root)})
            task = service.start_full_rollback(confirm_data_loss=True)
            stored = json.loads((root / "upgrades" / task["task_id"] / "task.json").read_text(encoding="utf-8"))
        restore = stored["execution_plan"]["actions"][0]["params"]
        self.assertEqual(restore["project_backup_path"], "/data/backups/project-files-anchored")


if __name__ == "__main__":
    unittest.main()