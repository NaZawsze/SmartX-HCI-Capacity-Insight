"""A5：平台升级回滚机制（设计 v1 §5.0 / impl-spec §W5 场景 A）。

覆盖面：
1. 开关与触发面判定（`rollback_on_failure` 缺省 false、触发面严格化）；
2. 锚点四要素捕获（previous_version / 旧镜像 tag+ID / backup 路径+SHA / 迁移与计数快照）
   + 落 checkpoint sink；
3. 回滚子流程：override 旧 tag → compose.apply → 健康门 → 业务计数守卫，全部复用现有动作；
4. 引擎接线：apply 前捕获锚点、失败分流（rolled_back / rollback_failed / failed 不滚）。
"""
from __future__ import annotations

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

from app.upgrade_runner.rollback import (  # noqa: E402
    ROLLBACK_TRIGGER_ACTIONS,
    anchor_rollback_override_images,
    business_count_guard,
    capture_platform_rollback_anchor,
    is_rollback_trigger,
    rollback_on_failure_enabled,
)

PROJECT = "smartx-hci-capacity-insight"
RUNNER = "upgrade-runner"


class _Executor:
    """按脚本回答 docker 事实查询的假执行器。"""

    def __init__(
        self,
        *,
        containers: dict[tuple[str, str], dict[str, str]] | None = None,
        compose_images: dict[str, str] | None = None,
        image_ids: dict[str, str] | None = None,
    ) -> None:
        self.containers = containers or {}
        self.compose_images = compose_images or {}
        self.image_ids = image_ids or {}
        self.calls: list[list[str]] = []

    def run(self, command: list[str], **_: Any) -> str:
        self.calls.append(list(command))
        return ""

    def output(self, command: list[str], **_: Any) -> str:
        self.calls.append(list(command))
        joined = " ".join(command)
        if joined.startswith("docker ps"):
            service = ""
            project = ""
            for part in command:
                if part.startswith("label=com.docker.compose.service="):
                    service = part.split("=", 2)[2]
                if part.startswith("label=com.docker.compose.project="):
                    project = part.split("=", 2)[2]
            facts = self.containers.get((project, service))
            if not facts:
                return ""
            return f"{facts.get('container_id','')} {project}\n"
        if joined.startswith("docker inspect") and "{{.Image}}" in joined:
            return self._for_container(command[-1], "image_id")
        if joined.startswith("docker inspect") and "{{.Config.Image}}" in joined:
            return self._for_container(command[-1], "image_ref")
        if joined.startswith("docker image inspect"):
            image = command[-1]
            return self.image_ids.get(image, "sha256:unknown")
        if joined.startswith("docker exec"):
            container = command[2]
            facts = self._facts_of_container(container)
            return facts.get("version_file", "")
        return ""

    def _facts_of_container(self, container_id: str) -> dict[str, str]:
        for facts in self.containers.values():
            if facts.get("container_id") == container_id:
                return facts
        return {}

    def _for_container(self, container_id: str, key: str) -> str:
        return self._facts_of_container(container_id).get(key, "")


def _write_compose(root: Path, images: dict[str, str]) -> Path:
    project = root / "project"
    project.mkdir(parents=True, exist_ok=True)
    lines = ["services:"]
    for service, image in images.items():
        lines.extend([f"  {service}:", f"    image: {image}", '    command: ["sleep", "infinity"]'])
    path = project / "docker-compose.yml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_db(root: Path, *, towers: int = 3, clusters: int = 2, vms: int = 10, volumes: int = 20) -> Path:
    database = root / "smartx.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE towers (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("CREATE TABLE clusters (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("CREATE TABLE vms (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("CREATE TABLE volumes (id INTEGER PRIMARY KEY, name TEXT)")
        for index in range(towers):
            connection.execute("INSERT INTO towers (name) VALUES (?)", (f"t{index}",))
        for index in range(clusters):
            connection.execute("INSERT INTO clusters (name) VALUES (?)", (f"c{index}",))
        for index in range(vms):
            connection.execute("INSERT INTO vms (name) VALUES (?)", (f"v{index}",))
        for index in range(volumes):
            connection.execute("INSERT INTO volumes (name) VALUES (?)", (f"d{index}",))
    return database


def _context(root: Path, executor: Any) -> Any:
    from app.upgrade_runner.actions import ActionContext

    return ActionContext(
        package_path=root / "package",
        project_path=root / "project",
        data_path=root,
        upgrades_path=root / "upgrades",
        backups_path=root / "backups",
        exports_path=root / "exports",
        compose_runtime_path=root / "compose-runtime",
        prometheus_path=root / "prometheus",
        compose_file="docker-compose.yml",
        compose_project=PROJECT,
        executor=executor,
        task_id="upgrade-a5",
        target_version="v0.5.4",
    )


def _platform_task(*, rollback_on_failure: bool | None = True, backup: bool = True) -> dict[str, Any]:
    actions: list[dict[str, Any]] = [
        {
            "id": "backup",
            "type": "backup.create",
            "params": {"scope": "platform"},
            "status": "succeeded" if backup else "pending",
            "attempt": 1,
            "checkpoint": {},
            "result": (
                {"path": "/data/backups/upgrade-v0.5.4-before-20260101.tar.gz", "sha256": "abc123", "scope": "platform"}
                if backup
                else {}
            ),
        },
        {
            "id": "write-compose-override",
            "type": "compose.override",
            "params": {
                "services": ["web-api", "collector-worker"],
                "images": [
                    {"service": "web-api", "image": "repo/web-api:v0.5.4"},
                    {"service": "collector-worker", "image": "repo/collector:v0.5.4"},
                ],
            },
            "status": "pending",
            "attempt": 0,
            "checkpoint": {},
            "result": {},
        },
        {
            "id": "apply-compose",
            "type": "compose.apply",
            "params": {"services": ["web-api", "collector-worker"]},
            "status": "pending",
            "attempt": 0,
            "checkpoint": {},
            "result": {},
        },
        {
            "id": "health-platform",
            "type": "health.http",
            "params": {"url": "http://web-api:8000/api/health", "attempts": 1, "delay_seconds": 0},
            "status": "pending",
            "attempt": 0,
            "checkpoint": {},
            "result": {},
        },
    ]
    manifest: dict[str, Any] = {"version": "v0.5.4", "components": ["platform"]}
    if rollback_on_failure is not None:
        manifest["rollback_on_failure"] = rollback_on_failure
    return {
        "task_id": "upgrade-a5",
        "status": "pending",
        "target_version": "v0.5.4",
        "manifest": manifest,
        "execution_plan": {"protocol_version": 1, "required_capabilities": [], "actions": actions},
    }


def _executor_with_containers(root_images: dict[str, str]) -> _Executor:
    containers: dict[tuple[str, str], dict[str, str]] = {}
    if "web-api" in root_images:
        containers[(PROJECT, "web-api")] = {
            "container_id": "web1",
            "image_ref": root_images["web-api"],
            "image_id": "sha256:web-old",
            "version_file": "v0.5.3\n",
        }
    if "collector-worker" in root_images:
        containers[(PROJECT, "collector-worker")] = {
            "container_id": "col1",
            "image_ref": root_images["collector-worker"],
            "image_id": "sha256:col-old",
            "version_file": "",
        }
    containers[(PROJECT, RUNNER)] = {
        "container_id": "run1",
        "image_ref": "repo/runner:v0.3.2",
        "image_id": "sha256:run",
    }
    return _Executor(containers=containers, image_ids={value: "sha256:by-tag" for value in root_images.values()})


class SwitchAndTriggerTests(unittest.TestCase):
    def test_rollback_on_failure_defaults_to_false(self) -> None:
        self.assertFalse(rollback_on_failure_enabled({}))
        self.assertFalse(rollback_on_failure_enabled({"manifest": None}))
        self.assertFalse(rollback_on_failure_enabled({"manifest": {"version": "v0.5.3"}}))
        self.assertTrue(rollback_on_failure_enabled({"manifest": {"rollback_on_failure": True}}))

    def test_trigger_surface_is_strict(self) -> None:
        for kind in ("compose.apply", "health.http", "health.prometheus", "post_upgrade.schedule_collection"):
            self.assertTrue(is_rollback_trigger(kind), kind)
        for kind in ("image.load", "backup.create", "files.sync", "filesystem.prepare", "compose.override"):
            self.assertFalse(is_rollback_trigger(kind), kind)

    def test_trigger_set_is_declared_explicitly(self) -> None:
        self.assertEqual(
            ROLLBACK_TRIGGER_ACTIONS,
            frozenset({"compose.apply", "health.http", "health.prometheus"}),
        )


class AnchorCaptureTests(unittest.TestCase):
    def test_anchor_carries_all_four_elements(self) -> None:
        root_images = {"web-api": "repo/web-api:v0.5.3", "collector-worker": "repo/collector:v0.5.3"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, root_images)
            _write_db(root)
            executor = _executor_with_containers(root_images)
            sinks: list[tuple[str, dict[str, Any]]] = []
            anchor = capture_platform_rollback_anchor(
                _context(root, executor),
                _platform_task(),
                executor=executor,
                target_version="v0.5.4",
                checkpoint_sink=lambda task_id, payload: sinks.append((task_id, payload)),
            )
        # ① previous_version
        self.assertEqual(anchor["previous_version"], "v0.5.3")
        self.assertEqual(anchor["kind"], "platform")
        # ② 旧镜像 tag + 不可变镜像 ID
        self.assertEqual(anchor["images"]["web-api"]["tag"], "repo/web-api:v0.5.3")
        self.assertEqual(anchor["images"]["web-api"]["image_id"], "sha256:web-old")
        self.assertEqual(anchor["images"]["collector-worker"]["container_id"], "col1")
        # ③ backup 路径 + SHA
        self.assertEqual(anchor["backup"]["sha256"], "abc123")
        self.assertTrue(anchor["backup"]["path"].endswith(".tar.gz"))
        # ④ 升级前计数 + 迁移快照
        self.assertEqual(anchor["pre_upgrade"]["counts"]["towers"], 3)
        self.assertEqual(anchor["pre_upgrade"]["counts"]["volumes"], 20)
        self.assertEqual(anchor["pre_upgrade"]["applied_migrations"], [])
        # 期望镜像（回滚时用来判别 apply 结果）也在锚点里
        self.assertEqual(anchor["expected_images"]["web-api"], "repo/web-api:v0.5.4")
        # 落 checkpoint sink（状态文件）
        self.assertEqual(len(sinks), 1)
        self.assertEqual(sinks[0][0], "upgrade-a5")
        self.assertEqual(sinks[0][1]["platform_rollback_anchor"]["previous_version"], "v0.5.3")

    def test_anchor_is_scoped_to_compose_project(self) -> None:
        """别的 project 的容器不能被当成锚点来源（与 W3 组件锚点同一纪律）。"""
        root_images = {"web-api": "repo/web-api:v0.5.3"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, root_images)
            executor = _executor_with_containers(root_images)
            # 把 web-api 容器挪到别的 project
            executor.containers[("other-project", "web-api")] = executor.containers.pop((PROJECT, "web-api"))
            anchor = capture_platform_rollback_anchor(
                _context(root, executor), _platform_task(), executor=executor, target_version="v0.5.4"
            )
        self.assertEqual(anchor["previous_version"], "")
        self.assertEqual(anchor["images"]["web-api"]["container_id"], "")

    def test_incomplete_anchor_is_returned_not_raised(self) -> None:
        """没有 backup、没有运行容器时也要留下锚点骨架（缺项只影响回滚能力）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, {"web-api": "repo/web-api:v0.5.3"})
            executor = _Executor()
            with self.assertLogs("app.upgrade_runner.rollback", level="WARNING") as captured:
                anchor = capture_platform_rollback_anchor(
                    _context(root, executor),
                    _platform_task(backup=False),
                    executor=executor,
                    target_version="v0.5.4",
                )
        self.assertEqual(anchor["kind"], "platform")
        self.assertEqual(anchor["backup"], {})
        self.assertTrue(any("锚点不完整" in message for message in captured.output))

    def test_checkpoint_sink_failure_does_not_break_capture(self) -> None:
        root_images = {"web-api": "repo/web-api:v0.5.3"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, root_images)
            executor = _executor_with_containers(root_images)

            def broken(_task_id: str, _payload: dict[str, Any]) -> None:
                raise RuntimeError("状态文件不可写")

            with self.assertLogs("app.upgrade_runner.rollback", level="ERROR"):
                anchor = capture_platform_rollback_anchor(
                    _context(root, executor),
                    _platform_task(),
                    executor=executor,
                    target_version="v0.5.4",
                    checkpoint_sink=broken,
                )
        self.assertEqual(anchor["previous_version"], "v0.5.3")

    def test_override_images_skip_services_without_tag(self) -> None:
        anchor = {
            "images": {
                "web-api": {"tag": "repo/web-api:v0.5.3"},
                "collector-worker": {"tag": ""},
            }
        }
        self.assertEqual(
            anchor_rollback_override_images(anchor),
            [{"service": "web-api", "image": "repo/web-api:v0.5.3"}],
        )


class BusinessCountGuardTests(unittest.TestCase):
    def test_growth_is_allowed_and_shrink_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_db(root, towers=3, volumes=20)
            database = root / "smartx.db"
            anchor = {"pre_upgrade": {"counts": {"towers": 3, "volumes": 20}}}
            healthy = business_count_guard(anchor, database)
            self.assertTrue(healthy["ok"], healthy)

            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO towers (name) VALUES ('t-new')")
            grown = business_count_guard(anchor, database)
            self.assertTrue(grown["ok"])
            self.assertEqual(grown["after"]["towers"], 4)

            with sqlite3.connect(database) as connection:
                connection.execute("DELETE FROM volumes WHERE name = 'd0'")
                connection.execute("DELETE FROM volumes WHERE name = 'd1'")
            shrunk = business_count_guard(anchor, database)
            self.assertFalse(shrunk["ok"])
            self.assertEqual(shrunk["regressions"]["volumes"], {"before": 20, "after": 18})

    def test_missing_database_is_treated_as_empty_not_pass(self) -> None:
        anchor = {"pre_upgrade": {"counts": {"towers": 3}}}
        verdict = business_count_guard(anchor, Path("/nonexistent/smartx.db"))
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["regressions"]["towers"], {"before": 3, "after": 0})


class _EngineCase(unittest.TestCase):
    """引擎接线用例的公共脚手架。

    `failing` 的语义很重要：`{"health.http": 1}` 表示**第一次**调用失败、之后成功
    ——这正是"新版本起不健康、回滚后旧版本健康"的形态；`-1` 表示永远失败。
    """

    def _engine(self, root: Path, handlers: dict[str, Any], task: dict[str, Any], *, executor: Any = None):
        from app.upgrade_runner.actions import ActionContext
        from app.upgrade_runner.engine import UpgradeEngine
        from app.upgrade_runner.store import TaskStore

        executor = executor or _Executor()
        task_dir = root / "upgrades" / task["task_id"]
        TaskStore(task_dir).save(task)
        context = ActionContext(
            package_path=task_dir / "package",
            project_path=root / "project",
            data_path=root,
            upgrades_path=root / "upgrades",
            backups_path=root / "backups",
            exports_path=root / "exports",
            compose_runtime_path=root / "compose-runtime",
            prometheus_path=root / "prometheus",
            compose_file="docker-compose.yml",
            compose_project=PROJECT,
            executor=executor,
            task_id=task["task_id"],
            target_version=str(task.get("target_version") or ""),
        )
        sinks: list[tuple[str, dict[str, Any]]] = []
        engine = UpgradeEngine(
            TaskStore(task_dir),
            handlers=handlers,
            context=context.as_dict(),
            checkpoint_sink=lambda task_id, payload: sinks.append((task_id, payload)),
        )
        return engine, TaskStore(task_dir), sinks, executor

    def _handlers(self, failing: dict[str, int] | None = None) -> dict[str, Any]:
        remaining = dict(failing or {})

        def make(kind: str):
            def handler(action, _context):
                left = remaining.get(kind, 0)
                if left != 0:
                    remaining[kind] = left - 1 if left > 0 else left
                    raise RuntimeError(f"{kind} 失败（注入）")
                return {"action": action["id"], "checkpoint": {"ok": True}}

            return handler

        return {
            kind: make(kind)
            for kind in ("backup.create", "compose.override", "compose.apply", "health.http")
        }


def _health_only_task() -> dict[str, Any]:
    return {
        "task_id": "upgrade-a5-legacy",
        "status": "pending",
        "target_version": "v0.5.4",
        "manifest": {"version": "v0.5.4", "components": ["platform"], "rollback_on_failure": True},
        "execution_plan": {
            "protocol_version": 1,
            "required_capabilities": [],
            "actions": [
                {
                    "id": "health-platform",
                    "type": "health.http",
                    "params": {"url": "http://web-api:8000/api/health", "attempts": 1, "delay_seconds": 0},
                    "status": "pending",
                    "attempt": 0,
                    "checkpoint": {},
                    "result": {},
                }
            ],
        },
    }


class EngineAnchorTests(_EngineCase):
    def test_anchor_is_captured_before_first_compose_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, {"web-api": "repo/web-api:v0.5.3"})
            _write_db(root)
            root_images = {"web-api": "repo/web-api:v0.5.3"}
            executor = _executor_with_containers(root_images)
            handlers = self._handlers()
            seen: list[bool] = []
            base_apply = handlers["compose.apply"]

            def apply(action, context):
                seen.append(bool(context["task"].get("platform_rollback_anchor")))
                return base_apply(action, context)

            handlers["compose.apply"] = apply
            engine, store, sinks, _ = self._engine(root, handlers, _platform_task(), executor=executor)
            result = engine.run()
        self.assertEqual(result["status"], "success")
        self.assertEqual(seen, [True], "compose.apply 执行时锚点必须已经在 task 里")
        self.assertEqual(result["platform_rollback_anchor"]["previous_version"], "v0.5.3")
        self.assertEqual(len(sinks), 1, "锚点必须写一次状态文件 checkpoint")

    def test_existing_anchor_is_not_recaptured(self) -> None:
        """崩溃重入（同一 task 再次被 runner 捡起）不得覆盖已有锚点、也不重复写 checkpoint。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, {"web-api": "repo/web-api:v0.5.3"})
            _write_db(root)
            executor = _executor_with_containers({"web-api": "repo/web-api:v0.5.3"})
            task = _platform_task()
            task["platform_rollback_anchor"] = {
                "kind": "platform",
                "previous_version": "v0.5.2",
                "images": {"web-api": {"tag": "repo/web-api:v0.5.2"}},
                "backup": {"path": "/data/backups/earlier.tar.gz", "sha256": "zzz"},
                "pre_upgrade": {"counts": {"towers": 9}},
                "captured_at": "2026-01-01T00:00:00+00:00",
            }
            engine, store, sinks, _ = self._engine(root, self._handlers(), task, executor=executor)
            result = engine.run()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["platform_rollback_anchor"]["captured_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(result["platform_rollback_anchor"]["previous_version"], "v0.5.2")
        self.assertEqual(sinks, [], "已有锚点时不应再写状态文件 checkpoint")


class EngineRollbackFlowTests(_EngineCase):
    def test_health_failure_rolls_back_to_old_tags_with_count_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, {"web-api": "repo/web-api:v0.5.3", "collector-worker": "repo/collector:v0.5.3"})
            _write_db(root)
            executor = _executor_with_containers(
                {"web-api": "repo/web-api:v0.5.3", "collector-worker": "repo/collector:v0.5.3"}
            )
            handlers = self._handlers({"health.http": 1})
            engine, store, _sinks, _ = self._engine(root, handlers, _platform_task(), executor=executor)
            result = engine.run()
        self.assertEqual(result["status"], "rolled_back")
        record = result["automatic_rollback"]
        self.assertEqual(record["mode"], "anchor_apply")
        self.assertEqual([step["step"] for step in record["steps"]], ["compose.override", "compose.apply", "health.http", "business_count_guard"])
        self.assertEqual(
            record["images"],
            [
                {"service": "web-api", "image": "repo/web-api:v0.5.3"},
                {"service": "collector-worker", "image": "repo/collector:v0.5.3"},
            ],
        )
        self.assertTrue(record["steps"][-1]["result"]["ok"])
        # 失败证据保留（US-09：宁留记录）
        self.assertIn("失败", result["error"])

    def test_rollback_override_writes_old_tags_through_existing_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, {"web-api": "repo/web-api:v0.5.3"})
            _write_db(root)
            executor = _executor_with_containers({"web-api": "repo/web-api:v0.5.3"})
            calls: list[dict[str, Any]] = []
            handlers = self._handlers({"health.http": 1})
            base_override = handlers["compose.override"]

            def override(action, context):
                calls.append(dict(action["params"]))
                return base_override(action, context)

            handlers["compose.override"] = override
            engine, _store, _sinks, _ = self._engine(root, handlers, _platform_task(), executor=executor)
            engine.run()
        rollback_call = [item for item in calls if item.get("images") and item["images"][0]["image"].endswith("v0.5.3")]
        self.assertEqual(len(rollback_call), 1, rollback_call)

    def test_apply_failure_rolls_back_only_when_manifest_opts_in(self) -> None:
        for rollback_on_failure, expected in ((True, "rolled_back"), (None, "failed"), (False, "failed")):
            with self.subTest(rollback_on_failure=rollback_on_failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_compose(root, {"web-api": "repo/web-api:v0.5.3"})
                _write_db(root)
                executor = _executor_with_containers({"web-api": "repo/web-api:v0.5.3"})
                # apply 只失败第一次（真实形态：首次 apply 出问题，回滚指向旧镜像成功）
                handlers = self._handlers({"compose.apply": 1})
                engine, _store, _sinks, _ = self._engine(
                    root, handlers, _platform_task(rollback_on_failure=rollback_on_failure), executor=executor
                )
                result = engine.run()
                self.assertEqual(result["status"], expected, result.get("error"))
                if expected == "rolled_back":
                    self.assertEqual(result["automatic_rollback"]["mode"], "anchor_apply")

    def test_health_failure_without_anchor_uses_legacy_restore(self) -> None:
        """老任务/组件任务没有平台锚点时，仍走既有 rollback.restore（行为不回退）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_db(root)
            restored: list[dict[str, Any]] = []

            def restore(action, _context):
                restored.append(dict(action["params"]))
                return {"checkpoint": {"restored": True}}

            handlers = {
                "health.http": self._handlers({"health.http": 1})["health.http"],
                "rollback.restore": restore,
            }
            engine, store, _sinks, _ = self._engine(root, handlers, _health_only_task())
            result = engine.run()
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(len(restored), 1)
        self.assertNotIn("mode", result["automatic_rollback"])

    def test_apply_triggered_rollback_uses_its_own_health_params(self) -> None:
        """回归：apply 失败触发的回滚必须**自造**健康动作。

        沙箱 `w3c` case-a3 实测的缺陷：早先 copy 失败动作再改 type，把 compose.apply 的
        params（没有 url）当健康检查参数传下去 → `url=None` → 健康门必然失败 →
        每次 apply 触发的回滚都以 rollback_failed 收场。
        """
        seen: list[dict[str, Any]] = []

        def health(action, _context):
            seen.append(dict(action.get("params") or {}))
            return {"status": 200, "checkpoint": {"healthy": True}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, {"web-api": "repo/web-api:v0.5.3"})
            _write_db(root)
            executor = _executor_with_containers({"web-api": "repo/web-api:v0.5.3"})
            handlers = self._handlers({"compose.apply": 1})
            handlers["health.http"] = health
            engine, _store, _sinks, _ = self._engine(
                root, handlers, _platform_task(rollback_on_failure=True), executor=executor
            )
            result = engine.run()
        self.assertEqual(result["status"], "rolled_back", result.get("error"))
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].get("url"), f"健康动作必须自带 url：{seen[0]}")
        self.assertEqual(seen[0]["url"], "http://web-api:8000/api/system/health")

    def test_count_guard_regression_marks_rollback_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_compose(root, {"web-api": "repo/web-api:v0.5.3"})
            database = _write_db(root, towers=3)
            executor = _executor_with_containers({"web-api": "repo/web-api:v0.5.3"})
            handlers = self._handlers({"health.http": 1})
            base_health = handlers["health.http"]

            def health(action, context):
                # 模拟回滚动作把数据弄少了（真实原因不重要，守卫必须拦住）
                with sqlite3.connect(database) as connection:
                    connection.execute("DELETE FROM towers")
                return base_health(action, context)

            handlers["health.http"] = health
            engine, _store, _sinks, _ = self._engine(root, handlers, _platform_task(), executor=executor)
            result = engine.run()
        self.assertEqual(result["status"], "rollback_failed")
        self.assertEqual(result["recovery_status"], "recovery_required")
        self.assertIn("计数守卫未通过", result["error"])
        self.assertEqual(result["available_recovery_actions"], ["rollback", "fail"])

    def test_rollback_without_old_tags_fails_loudly(self) -> None:
        """锚点里一个旧 tag 都没有时必须判 rollback_failed，而不是拿空 override 去 apply。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # compose 里没有任何 image 声明 + 没有运行容器 → 锚点无旧 tag
            (root / "project").mkdir(parents=True)
            (root / "project" / "docker-compose.yml").write_text(
                "services:\n  web-api:\n    command: [\"sleep\", \"infinity\"]\n", encoding="utf-8"
            )
            _write_db(root)
            executor = _Executor()
            engine, _store, _sinks, _ = self._engine(
                root, self._handlers({"health.http": 1}), _platform_task(), executor=executor
            )
            result = engine.run()
        self.assertEqual(result["status"], "rollback_failed")
        self.assertIn("没有旧镜像 tag", result["error"])


class RollbackVocabularyTests(unittest.TestCase):
    def test_no_new_plan_actions_introduced(self) -> None:
        """A5 只复用现有动作实现，不新增计划词汇（W7 动作冻结的前提）。"""
        from app.upgrade_runner.actions import default_handlers

        handlers = default_handlers()
        self.assertIn("compose.override", handlers)
        self.assertIn("compose.apply", handlers)
        for forbidden in ("rollback.apply_anchor", "rollback.count_guard", "rollback.*"):
            self.assertNotIn(forbidden, handlers)

    def test_rollback_module_does_not_import_new_verbs(self) -> None:
        source = (ROOT / "app" / "upgrade_runner" / "rollback.py").read_text(encoding="utf-8")
        self.assertNotIn("docker compose down", source)
        self.assertIn("rollback_on_failure", source)
        self.assertIn("expand-only", source)


if __name__ == "__main__":
    unittest.main()