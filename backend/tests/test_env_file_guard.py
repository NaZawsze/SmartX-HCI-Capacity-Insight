"""`.env` 被 Docker bind 建成目录的防护（pending #93）。

来源：v0.5.4 候选（r37）全链路重测，`.12`/`.14` 两台机一致复现——v0.5.2 起的 compose 把
`project/.env` 当**绝对路径 bind 源**，工程目录不在默认新布局时该路径不存在，Docker 会把
宿主路径建成**空目录**；此后 `docker compose` 读 `env_file` 直接失败（`is a directory`），
平台升级的 restart 步骤退出码 14。判定实验见 findings.md 2026-10-16 节。

三层防护各自要有单测：
1. `_write_env_file`：目标是目录时先清掉再写（env 迁移自愈）；
2. `ensure_env_file`：compose 前守卫，能从运行中实例回填就修，修不了就**明确失败**；
3. `_check_env_file`：平台侧预检查，按执行器能力决定放行还是阻断（project 只读挂载，平台修不了）。
"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.upgrade_runner.actions import (
    ActionContext,
    _write_env_file,
    ensure_env_file,
)

WEB_API_CONTAINER_LINE = "abc123def456 repo/web-api:v0.5.4 deadbeef"
RUNTIME_ENV = "\n".join(
    [
        "TZ=Asia/Shanghai",
        "SMARTX_SECRET_KEY=secret-from-runtime",
        "SMARTX_CREDENTIAL_KEY=credential-from-runtime",
        "SMARTX_ADMIN_USER=admin",
        "SMARTX_ADMIN_PASSWORD=password",
        "SMARTX_DB_PATH=/data/smartx.db",
        # legacy 布局键：v0.5.1u2 时代 install.sh 写进 .env，如今已不在 .env.example
        # （2026-10-18 L4 实测：按白名单过滤会丢这几个键 → 自愈后 15 键变 11 键）
        "SMARTX_PROJECT_PATH=/data/smartx-storage-forecast/project",
        "SMARTX_COMPOSE_FILE=docker-compose.offline.yml",
        "SMARTX_COMPOSE_PROJECT_NAME=smartx-hci-capacity-insight",
        "SMARTX_PROMETHEUS_DATA_PATH=/prometheus-data",
    ]
)


class FakeExecutor:
    """只回放 docker 观测命令；任何写操作都不该在这里发生。"""

    def __init__(self, *, container: str = WEB_API_CONTAINER_LINE, env_text: str = RUNTIME_ENV) -> None:
        self.container = container
        self.env_text = env_text
        self.calls: list[list[str]] = []

    def run(self, command, *, cwd=None, timeout=None):  # noqa: ANN001 - 与 CommandExecutor 同形
        self.calls.append(list(command))
        return None

    def output(self, command, *, cwd=None):  # noqa: ANN001
        self.calls.append(list(command))
        if command[:2] == ["docker", "ps"]:
            return self.container + "\n" if self.container else ""
        if command[:2] == ["docker", "inspect"]:
            return self.env_text + "\n"
        return ""


class WriteEnvFileTests(unittest.TestCase):
    def test_directory_target_is_replaced_by_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.mkdir()  # Docker bind 留下的空目录
            _write_env_file(path, "SMARTX_ADMIN_USER=admin\n")

            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "SMARTX_ADMIN_USER=admin\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_file_target_is_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("OLD=1\n", encoding="utf-8")
            _write_env_file(path, "NEW=2\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "NEW=2\n")


class EnsureEnvFileTests(unittest.TestCase):
    def _context(self, tmp: str, executor: FakeExecutor) -> ActionContext:
        return ActionContext.minimal(Path(tmp), executor=executor)

    def test_regular_file_needs_no_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(tmp, FakeExecutor())
            (context.project_path / ".env").write_text("A=1\n", encoding="utf-8")
            self.assertIsNone(ensure_env_file(context))

    def test_directory_is_rebuilt_from_running_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(tmp, FakeExecutor())
            (context.project_path / ".env").mkdir()

            result = ensure_env_file(context)

            self.assertIsNotNone(result)
            self.assertTrue(result["repaired"])
            target = context.project_path / ".env"
            self.assertTrue(target.is_file())
            text = target.read_text(encoding="utf-8")
            # 密钥必须回填（否则 Tower 凭据解不开）
            self.assertIn("SMARTX_SECRET_KEY=secret-from-runtime", text)
            self.assertIn("SMARTX_CREDENTIAL_KEY=credential-from-runtime", text)
            # 2026-10-18 起：**全部 SMARTX_* 键**都回填（Config.Env 是 .env 的超集）。
            # legacy 布局键必须回来——丢它们等于丢 #99 撕裂态判定的依据（L4 实测 15→11 键）。
            self.assertIn("SMARTX_PROJECT_PATH=/data/smartx-storage-forecast/project", text)
            self.assertIn("SMARTX_COMPOSE_FILE=docker-compose.offline.yml", text)
            self.assertIn("SMARTX_COMPOSE_PROJECT_NAME=smartx-hci-capacity-insight", text)
            self.assertIn("SMARTX_PROMETHEUS_DATA_PATH=/prometheus-data", text)
            # 非 SMARTX_* 前缀的容器环境变量（TZ/PATH 等）不得污染 .env（按行首判断）
            lines = text.splitlines()
            self.assertFalse(any(line.startswith("TZ=") for line in lines))
            self.assertFalse(any(line.startswith("PATH=") for line in lines))
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_directory_without_runtime_source_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(tmp, FakeExecutor(container=""))
            (context.project_path / ".env").mkdir()

            with self.assertRaises(RuntimeError) as caught:
                ensure_env_file(context)
            self.assertIn("目录", str(caught.exception))
            self.assertIn("备份", str(caught.exception))

    def test_directory_without_keys_fails_loudly(self) -> None:
        """只有非密钥键时不能算恢复成功——缺密钥等于换个坏状态继续。"""
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(tmp, FakeExecutor(env_text="SMARTX_ADMIN_USER=admin"))
            (context.project_path / ".env").mkdir()

            with self.assertRaises(RuntimeError):
                ensure_env_file(context)

    def test_missing_file_is_left_to_compose(self) -> None:
        """缺失不是本缺陷：不凭空造无密钥的假 .env，交给 compose 报可读错误。"""
        with tempfile.TemporaryDirectory() as tmp:
            context = self._context(tmp, FakeExecutor())
            self.assertIsNone(ensure_env_file(context))
            self.assertFalse((context.project_path / ".env").exists())


class PrecheckEnvFileTests(unittest.TestCase):
    def _settings(self, path: Path) -> SimpleNamespace:
        return SimpleNamespace(env_file_path=path)

    def test_regular_file_passes(self) -> None:
        from app.v2.upgrade.service.precheck import _check_env_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("A=1\n", encoding="utf-8")
            check = _check_env_file(self._settings(path), "v0.3.2")
            self.assertTrue(check["ok"])
            self.assertEqual(check["name"], "env_file")

    def test_directory_passes_when_executor_can_self_heal(self) -> None:
        from app.v2.upgrade.service.precheck import _check_env_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.mkdir()
            check = _check_env_file(self._settings(path), "v0.3.3")
            self.assertTrue(check["ok"], check["message"])
            self.assertIn("目录", check["message"])

    def test_directory_blocks_when_executor_is_older(self) -> None:
        from app.v2.upgrade.service.precheck import _check_env_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.mkdir()
            check = _check_env_file(self._settings(path), "v0.3.2")
            self.assertFalse(check["ok"])
            self.assertIn("v0.3.3", check["message"])
            self.assertIn("备份", check["message"])

    def test_missing_env_does_not_block(self) -> None:
        """运行中的平台必然有 .env；缺失只可能是合成环境，不阻断（交给 compose）。"""
        from app.v2.upgrade.service.precheck import _check_env_file

        with tempfile.TemporaryDirectory() as tmp:
            check = _check_env_file(self._settings(Path(tmp) / ".env"), "v0.3.3")
            self.assertTrue(check["ok"])


class HeartbeatWindowTests(unittest.TestCase):
    def test_window_widened_and_env_overridable(self) -> None:
        from app.v2.upgrade.service import constants

        self.assertEqual(constants.RUNNER_HEARTBEAT_STALE_SECONDS, int(
            os.environ.get("SMARTX_RUNNER_HEARTBEAT_STALE_SECONDS", "90")
        ))
        self.assertGreaterEqual(constants.RUNNER_HEARTBEAT_STALE_SECONDS, 90)


class UpgradeScriptComponentGuardTests(unittest.TestCase):
    def test_component_upgrade_is_blocked_on_old_platform(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "delivery" / "upgrade" / "upgrade.sh").read_text(encoding="utf-8")
        self.assertIn("不支持先做 runner 组件升级", text)
        # 旧平台枚举必须覆盖会踩坑的全部版本（v0.5.2 及更早）
        for version in ("v0.5.0", "v0.5.1", "v0.5.1u1", "v0.5.1u2", "v0.5.2"):
            self.assertIn(version, text)


class RunnerVersionSingleSourceTests(unittest.TestCase):
    """runner 自报版本必须与仓库 `RUNNER_VERSION` 同源。

    2026-10-17 `.14` 实测：v0.3.3 的 runner 镜像 `/app/RUNNER_VERSION` 是 v0.3.3，
    但状态文件与 `/api/system/health` 报 v0.3.2——因为 `main.py` 里把 `"v0.3.2"` 写死了。
    后果是「执行器能力判定」按旧版本走：预检查把**能自愈 `.env` 的 runner 判成不能**。
    """

    def test_fallback_matches_repo_runner_version(self) -> None:
        from app.upgrade_runner.main import FALLBACK_RUNNER_VERSION

        root = Path(__file__).resolve().parents[2]
        repo_version = (root / "RUNNER_VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(FALLBACK_RUNNER_VERSION, repo_version)

    def test_version_file_wins_over_environment(self) -> None:
        import tempfile as _tempfile

        from app.upgrade_runner import main as runner_main

        with _tempfile.TemporaryDirectory() as tmp:
            version_file = Path(tmp) / "RUNNER_VERSION"
            version_file.write_text("v9.9.9\n", encoding="utf-8")
            original_file = runner_main.RUNNER_VERSION_FILE
            original_env = os.environ.get("SMARTX_RUNNER_VERSION")
            runner_main.RUNNER_VERSION_FILE = version_file
            os.environ["SMARTX_RUNNER_VERSION"] = "v0.0.1"
            try:
                self.assertEqual(runner_main.resolve_runner_version(), "v9.9.9")
            finally:
                runner_main.RUNNER_VERSION_FILE = original_file
                if original_env is None:
                    os.environ.pop("SMARTX_RUNNER_VERSION", None)
                else:
                    os.environ["SMARTX_RUNNER_VERSION"] = original_env


class RunnerRuntimeComposeHealthcheckTests(unittest.TestCase):
    """runner 自换的运行时 compose 必须带 healthcheck（pending #101）。

    2026-10-18 L4.2 实测：healthcheck 只加进了三份**交付** compose，没加
    `_write_runner_runtime_compose` 生成器 → 平台升级后 runner 由运行时 compose 重建，
    **永久失去 (unhealthy) 可见性**（`docker inspect` 无 Health 条目，pause 也测不出来）。
    """

    def test_generated_runtime_compose_has_healthcheck(self) -> None:
        from app.upgrade_runner.actions import _write_runner_runtime_compose

        with tempfile.TemporaryDirectory() as tmp:
            context = ActionContext.minimal(Path(tmp), executor=FakeExecutor())
            result = _write_runner_runtime_compose(
                context,
                {"image": "registry/upgrade-runner:v0.3.5", "compose_project": "smartx-hci-capacity-insight"},
            )
            compose_file = Path(result["compose_file"])
            self.assertTrue(compose_file.is_file())
            content = compose_file.read_text(encoding="utf-8")
            self.assertIn("healthcheck:", content)
            # 判定口径与交付 compose 一致：状态文件超 90s 未更新即不健康
            self.assertIn("upgrade-runner-state.json", content)
            self.assertIn("-lt 90", content)
            self.assertIn("interval: 30s", content)


class EnvFileKeyCoverageTests(unittest.TestCase):
    """自愈回填的键集合必须覆盖宿主 `.env` 的**全部**键。

    2026-10-17 P3 实测：`.env` 目录被自愈后从 16 键变 15 键，丢的是
    `SMARTX_COMPOSE_FILE_ACTIVE`（US-37 compose 变体标记）。这类"少一个键"不会让升级失败，
    却会让守卫失去依据——只有数据检验的 `env.keys` 能抓到。
    """

    def test_recoverable_keys_cover_host_only_markers(self) -> None:
        from app.upgrade_runner.actions import ENV_FILE_RECOVERABLE_KEYS

        for key in ("SMARTX_COMPOSE_FILE_ACTIVE", "SMARTX_ENV_FILE_SHA256"):
            self.assertIn(key, ENV_FILE_RECOVERABLE_KEYS, key)

    def test_recoverable_keys_cover_env_example(self) -> None:
        from app.upgrade_runner.actions import ENV_FILE_RECOVERABLE_KEYS

        root = Path(__file__).resolve().parents[2]
        keys = [
            line.split("=", 1)[0].strip()
            for line in (root / ".env.example").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.strip().startswith("#")
        ]
        missing = [key for key in keys if key not in ENV_FILE_RECOVERABLE_KEYS]
        self.assertEqual(missing, [], f"自愈会丢掉 .env.example 的键：{missing}")


if __name__ == "__main__":
    unittest.main()
