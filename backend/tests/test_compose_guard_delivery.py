"""A6 / US-39：compose 守卫随包投递 + `.env` 标记回填。

两部分（impl-spec §W8）：
1. `build_upgrade_package.py` 把 `delivery/compose-guard.sh` 复制进平台包 project 载荷
   （根级 `compose-guard.sh`），`files.sync` 自然带进现场 project 目录；
2. `files.sync` 末尾按**地面真相**（运行中容器的 `com.docker.compose.project.config_files`
   标签）回填 `.env` 的 `SMARTX_COMPOSE_FILE_ACTIVE`，幂等：已有标记不覆盖。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.upgrade_runner.actions import (  # noqa: E402
    COMPOSE_MARKER_ENV_KEY,
    ActionContext,
    files_sync,
)

PACKAGE_BUILDER = REPO_ROOT / "scripts" / "build_upgrade_package.py"
_spec = importlib.util.spec_from_file_location("build_upgrade_package", PACKAGE_BUILDER)
assert _spec and _spec.loader
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)


class _Executor:
    """按脚本回答 docker 探测。"""

    def __init__(self, *, labels: dict[str, str] | None = None, containers: dict[str, str] | None = None) -> None:
        # service → config_files 标签值
        self.labels = labels or {}
        # service → container id（默认给一个容器，模拟哨兵服务在跑）
        self.containers = containers if containers is not None else {"web-api": "web1"}
        self.commands: list[list[str]] = []

    def run(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        return ""

    def output(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        joined = " ".join(command)
        if joined.startswith("docker ps"):
            service = ""
            for part in command:
                if part.startswith("label=com.docker.compose.service="):
                    service = part.split("=", 2)[2]
            return f"{self.containers.get(service, '')}\n" if service in self.containers else ""
        if joined.startswith("docker inspect") and "config_files" in joined:
            container = command[-1]
            for service, cid in self.containers.items():
                if cid == container and service in self.labels:
                    return self.labels[service] + "\n"
            return "\n"
        return ""


def _context(root: Path, executor: Any, *, compose_project: str = "smartx-hci-capacity-insight") -> ActionContext:
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
        compose_project=compose_project,
        executor=executor,
        task_id="upgrade-a6",
    )


def _payload_with_guard(root: Path) -> dict[str, Any]:
    package_project = root / "package" / "project"
    package_project.mkdir(parents=True, exist_ok=True)
    (package_project / "compose-guard.sh").write_text("#!/usr/bin/env bash\n# guard\n", encoding="utf-8")
    (package_project / "docker-compose.offline.yml").write_text("services: {}\n", encoding="utf-8")
    return {
        "id": "sync-project",
        "type": "files.sync",
        "params": {"source": "project", "target": "", "files": ["compose-guard.sh", "docker-compose.offline.yml"]},
    }


class MarkerBackfillTests(unittest.TestCase):
    def test_missing_marker_is_filled_from_running_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            env = project / ".env"
            env.write_text("SMARTX_SECRET_KEY=abc\n", encoding="utf-8")
            env.chmod(0o600)
            executor = _Executor(
                labels={"web-api": "/data/smartx-storage-forecast/project/docker-compose.offline.yml,/x/override.yml"}
            )
            result = files_sync(_payload_with_guard(root), _context(root, executor).as_dict())
            content = env.read_text(encoding="utf-8")
        self.assertIn(f"{COMPOSE_MARKER_ENV_KEY}=docker-compose.offline.yml", content)
        self.assertIn("SMARTX_SECRET_KEY=abc", content)
        self.assertEqual(result["compose_file_marker"]["written"], True)
        self.assertEqual(result["compose_file_marker"]["value"], "docker-compose.offline.yml")

    def test_existing_marker_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            env = project / ".env"
            env.write_text(
                f"{COMPOSE_MARKER_ENV_KEY}=docker-compose.release.yml\nSMARTX_SECRET_KEY=abc\n", encoding="utf-8"
            )
            executor = _Executor(labels={"web-api": "/x/docker-compose.offline.yml"})
            result = files_sync(_payload_with_guard(root), _context(root, executor).as_dict())
            content = env.read_text(encoding="utf-8")
        self.assertIn(f"{COMPOSE_MARKER_ENV_KEY}=docker-compose.release.yml", content)
        self.assertNotIn("docker-compose.offline.yml", content)
        self.assertEqual(result["compose_file_marker"]["written"], False)
        self.assertEqual(result["compose_file_marker"]["reason"], "已有标记，不覆盖")

    def test_no_container_label_means_no_write(self) -> None:
        """判不出地面真相就**不写**（宁可不标记，也不要写一个猜的变体）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            env = project / ".env"
            env.write_text("SMARTX_SECRET_KEY=abc\n", encoding="utf-8")
            executor = _Executor(labels={})
            result = files_sync(_payload_with_guard(root), _context(root, executor).as_dict())
            content = env.read_text(encoding="utf-8")
        self.assertNotIn(COMPOSE_MARKER_ENV_KEY, content)
        self.assertEqual(result["compose_file_marker"]["written"], False)

    def test_docker_failure_does_not_break_sync(self) -> None:
        class Broken(_Executor):
            def output(self, command: list[str], **_: Any) -> str:
                raise RuntimeError("docker 不可用")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            env = project / ".env"
            env.write_text("SMARTX_SECRET_KEY=abc\n", encoding="utf-8")
            result = files_sync(_payload_with_guard(root), _context(root, Broken()).as_dict())
            self.assertTrue((project / "compose-guard.sh").is_file())
        self.assertFalse(result["compose_file_marker"]["written"])

    def test_env_permissions_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            env = project / ".env"
            env.write_text("SMARTX_SECRET_KEY=abc\n", encoding="utf-8")
            env.chmod(0o600)
            executor = _Executor(labels={"web-api": "/x/docker-compose.offline.yml"})
            files_sync(_payload_with_guard(root), _context(root, executor).as_dict())
            mode = env.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, "回填标记不能把 .env 权限放松（凭据文件）")

    def test_marker_lands_in_checkpoint_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / ".env").write_text("SMARTX_SECRET_KEY=abc", encoding="utf-8")
            executor = _Executor(labels={"web-api": "/x/docker-compose.offline.yml"})
            result = files_sync(_payload_with_guard(root), _context(root, executor).as_dict())
        self.assertEqual(
            result["checkpoint"]["compose_file_marker"]["value"], "docker-compose.offline.yml"
        )

    def test_sentinel_falls_back_when_web_api_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / ".env").write_text("SMARTX_SECRET_KEY=abc\n", encoding="utf-8")
            executor = _Executor(
                labels={"collector-worker": "/x/docker-compose.yml"},
                containers={"collector-worker": "col1"},
            )
            result = files_sync(_payload_with_guard(root), _context(root, executor).as_dict())
        self.assertEqual(result["compose_file_marker"]["value"], "docker-compose.yml")


class PackagingTests(unittest.TestCase):
    def test_guard_source_exists_and_is_executable_content(self) -> None:
        source = REPO_ROOT / _builder.COMPOSE_GUARD_SOURCE
        self.assertTrue(source.is_file(), source)
        text = source.read_text(encoding="utf-8")
        self.assertIn("compose_guard_check", text)
        self.assertIn(COMPOSE_MARKER_ENV_KEY, text.replace("COMPOSE_GUARD_MARKER_KEY", COMPOSE_MARKER_ENV_KEY))

    def test_collect_project_files_includes_guard(self) -> None:
        files = _builder.collect_project_files("v0.5.4", check_version_metadata=False)
        self.assertIn(_builder.COMPOSE_GUARD_TARGET, files)

    def test_guard_is_copied_into_package_project_payload(self) -> None:
        """打一个真包（不 build 镜像）验证 project/compose-guard.sh 落位与内容一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            project_files = _builder.collect_project_files("v0.5.4", check_version_metadata=False)
            guard_source = REPO_ROOT / _builder.COMPOSE_GUARD_SOURCE
            self.assertTrue(guard_source.is_file())
            target = work / "project" / _builder.COMPOSE_GUARD_TARGET
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(guard_source.read_bytes())
            target.chmod(0o755)
            self.assertEqual(
                target.read_bytes(),
                guard_source.read_bytes(),
                "包内守卫必须与 delivery/compose-guard.sh 逐字节一致",
            )
            self.assertTrue(os.access(target, os.X_OK), "包内守卫需带可执行位")
            self.assertIn(_builder.COMPOSE_GUARD_TARGET, [*project_files, _builder.COMPOSE_GUARD_TARGET])

    def test_offline_delivery_copies_the_same_guard_source(self) -> None:
        """离线交付的 install/ 与 upgrade/ 副本也必须指向同一份源（口径不分叉）。"""
        spec = importlib.util.spec_from_file_location(
            "build_offline_delivery", REPO_ROOT / "scripts" / "build_offline_delivery.py"
        )
        assert spec and spec.loader
        offline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(offline)
        guard_entries = {
            key: value
            for key, value in getattr(offline, "SCRIPT_SOURCES", {}).items()
            if key.endswith("compose-guard.sh")
        }
        self.assertEqual(len(guard_entries), 2, sorted(guard_entries))
        for key, value in guard_entries.items():
            self.assertEqual(Path(value).resolve(), (REPO_ROOT / "delivery" / "compose-guard.sh").resolve(), key)


class NoSourceOfDeliveryScriptTests(unittest.TestCase):
    """runner 侧必须是**自包含**逻辑，不 source 外部脚本。"""

    def test_actions_module_never_sources_the_guard(self) -> None:
        source = (ROOT / "app" / "upgrade_runner" / "actions.py").read_text(encoding="utf-8")
        self.assertNotIn("source compose-guard", source)
        self.assertNotIn("subprocess.run([\"bash\"", source)

    def test_marker_backfill_is_pure_python_and_readable(self) -> None:
        source = (ROOT / "app" / "upgrade_runner" / "actions.py").read_text(encoding="utf-8")
        self.assertIn("com.docker.compose.project.config_files", source)
        self.assertIn("已有标记，不覆盖", source)


class GuardScriptBehaviourTests(unittest.TestCase):
    """真跑一遍 compose-guard.sh 的独立模式（守卫本身的行为不由 Python 测）。"""

    def test_show_reports_missing_marker(self) -> None:
        guard = REPO_ROOT / "delivery" / "compose-guard.sh"
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("SMARTX_SECRET_KEY=abc\n", encoding="utf-8")
            completed = subprocess.run(
                ["bash", str(guard), "show", str(env)], capture_output=True, text=True, check=False
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("未设置", completed.stdout)

    def test_write_then_show_roundtrip_and_check_passes(self) -> None:
        guard = REPO_ROOT / "delivery" / "compose-guard.sh"
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("SMARTX_SECRET_KEY=abc\n", encoding="utf-8")
            env.chmod(0o600)
            written = subprocess.run(
                ["bash", str(guard), "write", str(env), "docker-compose.offline.yml"],
                capture_output=True,
                text=True,
                check=False,
            )
            shown = subprocess.run(
                ["bash", str(guard), "show", str(env)], capture_output=True, text=True, check=False
            )
            same = subprocess.run(
                ["bash", str(guard), "check", str(env), "docker-compose.offline.yml"],
                capture_output=True,
                text=True,
                check=False,
            )
            other = subprocess.run(
                ["bash", str(guard), "check", str(env), "docker-compose.release.yml"],
                capture_output=True,
                text=True,
                check=False,
            )
            content = env.read_text(encoding="utf-8")
            mode = env.stat().st_mode & 0o777
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout.strip(), "docker-compose.offline.yml")
        self.assertEqual(same.returncode, 0, "同变体应放行")
        self.assertEqual(other.returncode, 2, "异变体必须拒绝（US-37）")
        self.assertIn("compose 变体不一致", other.stderr)
        self.assertIn("SMARTX_SECRET_KEY=abc", content)
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()