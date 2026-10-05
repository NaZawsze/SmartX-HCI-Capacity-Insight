"""W3b：宿主/容器路径混用的系统性修复。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W3b
决策：用户 2026-10-05 批准**方案 A**——runner 内部一律用容器路径，
仅在 `docker run -v` / `docker compose -f` 边界用 `docker_host_path` 翻译成宿主路径。
（否决方案 B：给 runner 补挂真实宿主路径 = 改 compose = 动 config-hash = 正面撞
US-26/US-37 热点，且要同步四个交付面。）

## 缺陷本体（.3 交付实例实测取证）

runner 在容器内用宿主风格路径 `/data/smartx-storage-forecast/compose-runtime` 写文件，
该路径穿过 `app` 那个 bind，落到 **UPG-050 载体目录**
`app/smartx-storage-forecast/compose-runtime/`；辅助容器挂载的却是**真实目录**。
`.3` 上两处各有一份内容不同的同名文件：

| 位置 | 时间 | image | compose |
| --- | --- | --- | --- |
| 载体（runner 实际写入处） | 2026-10-03 | v0.3.2 | offline |
| 真实目录（辅助容器实际读取处） | 2026-08-12 | v0.3.1 | release |

⇒ 自 2026-08-12 起，handoff 新写的配置**从未生效**。平台升级 handoff「实测通过」
只是因为旧文件恰好描述了当时正确的目标（老链路基线正是 v0.3.1）——属潜伏，
但自换走的正是这条配置传递链，必须先修。

## 本模块的判定纪律（唯一不变量）

**辅助容器挂载的宿主文件，必须就是 runner 刚写下的那个文件。**
一切路径选择都服务于这一条；写点与挂载点需要不同路径时（容器内写 vs 宿主挂载），
二者必须成对翻译并互相印证。

另外两条硬纪律（impl-spec §W3b 要求 1）：
- 容器内的文件写一律用容器路径；
- 宿主路径只允许出现在 `-v` 字符串与写进 `SMARTX_HOST_*` env 的值里。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.upgrade_runner.actions import (  # noqa: E402
    ActionContext,
    CommandExecutor,
    _container_runtime_paths,
    _runner_runtime_paths,
    _write_runner_runtime_compose,
)

COMPOSE_NAME = "docker-compose.runner-upgrade.yml"


class _Executor:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        return ""

    def output(self, command: list[str], **_: Any) -> str:
        self.commands.append(list(command))
        return ""


def _realistic_context(root: Path, executor: Any) -> ActionContext:
    """构造与 `.3` 交付实例一致的上下文：容器路径与宿主路径是**两套不同目录**。

    真实布局（`docker inspect` 实测）：
        宿主 /data/smartx-storage-forecast/app           → 容器 /data
        宿主 /data/smartx-storage-forecast/upgrades       → 容器 /data/upgrades
        宿主 /data/smartx-storage-forecast/compose-runtime → 容器 /data/compose-runtime
        宿主 /data/smartx-storage-forecast/project        → 容器 /data/smartx-storage-forecast/project
    宿主 app 目录下还有一个**载体目录** `app/smartx-storage-forecast/`，
    它会让「容器内用宿主路径」悄悄写进错误位置——本模块的核心风险。
    """
    container_data = root / "mnt" / "data"
    container_upgrades = root / "mnt" / "data" / "upgrades"
    container_backups = root / "mnt" / "data" / "backups"
    container_exports = root / "mnt" / "data" / "exports"
    container_runtime = root / "mnt" / "data" / "compose-runtime"
    container_prometheus = root / "mnt" / "prometheus-data"
    container_project = root / "mnt" / "data" / "smartx-storage-forecast" / "project"

    host_root = root / "host" / "data" / "smartx-storage-forecast"
    context = ActionContext(
        package_path=container_upgrades / "upgrade-1" / "package",
        project_path=container_project,
        data_path=container_data,
        upgrades_path=container_upgrades,
        backups_path=container_backups,
        exports_path=container_exports,
        compose_runtime_path=container_runtime,
        prometheus_path=container_prometheus,
        compose_file="docker-compose.offline.yml",
        compose_project="smartx-hci-capacity-insight",
        executor=executor,
        task_id="upgrade-1",
        target_version="v0.3.3",
        host_project_path=host_root / "project",
        host_data_path=host_root / "app",
        host_upgrades_path=host_root / "upgrades",
        host_backups_path=host_root / "backups",
        host_exports_path=host_root / "exports",
        host_compose_runtime_path=host_root / "compose-runtime",
        host_prometheus_path=host_root / "prometheus",
    )
    return context


class DoubleViewRuntimeComposeTests(unittest.TestCase):
    """W3b 要求 3：构造「app 载体 vs 真实目录」双视图，断言写入落在真实目录。"""

    def _carrier_and_real(self, root: Path, context: ActionContext) -> tuple[Path, Path]:
        """造出双视图：宿主真实目录 + app bind 下的同名载体目录。"""
        real = Path(context.host_compose_runtime_path)
        real.mkdir(parents=True, exist_ok=True)
        # 容器内 /data = 宿主 app 目录；宿主风格路径 /data/smartx-storage-forecast/...
        # 在容器内解析为 <host app>/data/smartx-storage-forecast/... → 载体
        carrier = Path(context.host_data_path) / "data" / "smartx-storage-forecast" / "compose-runtime"
        carrier.mkdir(parents=True, exist_ok=True)
        return real, carrier

    def _params(self) -> dict[str, Any]:
        return {
            "image": "repo/upgrade-runner:v0.3.3",
            "compose_project": "smartx-hci-capacity-insight",
            "network_name": "smartx-hci-capacity-insight-net",
        }

    def test_write_lands_in_container_path_not_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _realistic_context(root, _Executor())
            real, carrier = self._carrier_and_real(root, context)
            Path(context.compose_runtime_path).mkdir(parents=True, exist_ok=True)

            runtime = _write_runner_runtime_compose(context, self._params())

            container_write = Path(context.compose_runtime_path) / COMPOSE_NAME
            self.assertTrue(container_write.is_file(), "必须写到容器可见的 compose-runtime")
            self.assertEqual(
                list(carrier.iterdir()),
                [],
                f"UPG-050 载体目录不得被写入任何文件（实际：{list(carrier.iterdir())}）",
            )
            self.assertEqual(list(real.iterdir()), [], "真实目录此时也应是空的（本测试只验写点）")
            self.assertEqual(str(runtime["compose_file_container"]), str(container_write))

    def test_returned_compose_file_is_host_path_of_what_was_written(self) -> None:
        """不变量：辅助容器挂载的宿主文件 == runner 刚写下的那个文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _realistic_context(root, _Executor())
            real, _carrier = self._carrier_and_real(root, context)
            Path(context.compose_runtime_path).mkdir(parents=True, exist_ok=True)

            runtime = _write_runner_runtime_compose(context, self._params())
            host_path = Path(runtime["compose_file"])

            self.assertEqual(
                context.docker_host_path(Path(runtime["compose_file_container"])),
                host_path,
                "compose_file 必须是 compose_file_container 经 docker_host_path 的翻译结果",
            )
            self.assertEqual(
                host_path.parent,
                real,
                f"宿主路径必须指向真实 compose-runtime（{real}），而不是 app bind 下的载体",
            )

    def test_compose_content_keeps_host_paths(self) -> None:
        """内容仍必须是宿主路径——这段 compose 由宿主 dockerd 消费。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _realistic_context(root, _Executor())
            self._carrier_and_real(root, context)
            Path(context.compose_runtime_path).mkdir(parents=True, exist_ok=True)
            _write_runner_runtime_compose(context, self._params())
            content = (Path(context.compose_runtime_path) / COMPOSE_NAME).read_text(encoding="utf-8")
        self.assertIn(f"SMARTX_HOST_UPGRADES_PATH: {context.host_upgrades_path}", content)
        self.assertIn(f"SMARTX_HOST_COMPOSE_RUNTIME_PATH: {context.host_compose_runtime_path}", content)
        self.assertIn(f"- {context.host_data_path}:/data", content)
        self.assertIn(f"- {context.host_compose_runtime_path}:/data/compose-runtime", content)
        # 容器内常量路径不应被误写成宿主路径
        self.assertIn("SMARTX_COMPOSE_RUNTIME_PATH: /data/compose-runtime", content)


class ContainerPathTranslationTests(unittest.TestCase):
    def test_all_runtime_paths_translate_to_container_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _realistic_context(root, _Executor())
            host_paths = _runner_runtime_paths(context, {})
            container_paths = _container_runtime_paths(context, host_paths)
        self.assertEqual(container_paths["compose_runtime_path"], context.compose_runtime_path)
        self.assertEqual(container_paths["upgrades_path"], context.upgrades_path)
        self.assertEqual(container_paths["backups_path"], context.backups_path)
        self.assertEqual(container_paths["exports_path"], context.exports_path)
        self.assertEqual(container_paths["prometheus_path"], context.prometheus_path)
        self.assertEqual(container_paths["data_path"], context.data_path)
        self.assertEqual(container_paths["project_path"], context.project_path)
        # 宿主路径绝不能出现在翻译结果里
        for key, value in container_paths.items():
            self.assertNotIn(
                str(context.host_compose_runtime_path),
                str(value),
                f"{key} 仍指向宿主路径",
            )

    def test_nested_relative_path_is_preserved(self) -> None:
        """`compose-runtime` 之外的嵌套（如 exports/子目录）也要按相对结构映射。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _realistic_context(root, _Executor())
            host_paths = dict(_runner_runtime_paths(context, {}))
            host_paths["exports_path"] = Path(context.host_exports_path) / "reports" / "2026"
            container_paths = _container_runtime_paths(context, host_paths)
        self.assertEqual(
            container_paths["exports_path"],
            Path(context.exports_path) / "reports" / "2026",
        )

    def test_missing_host_field_falls_back_to_container_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = _realistic_context(root, _Executor())
            context.host_prometheus_path = None
            host_paths = dict(_runner_runtime_paths(context, {}))
            container_paths = _container_runtime_paths(context, host_paths)
        self.assertEqual(container_paths["prometheus_path"], context.prometheus_path)


class WritePointInventoryTests(unittest.TestCase):
    """W3b 要求 1 的清单固化（允许写进测试注释，故以断言形式留档）。

    规则：`actions.py` / `main.py` 中，**任何文件写操作**都不得以 `host_*_path` 为基址；
    宿主路径只允许出现在 `-v` 字符串与 `SMARTX_HOST_*` env 里。
    本测试做源码级静态检查——这类纪律靠人记不住，必须机器可查。
    """

    HOST_ATTRS = (
        "host_project_path",
        "host_data_path",
        "host_upgrades_path",
        "host_backups_path",
        "host_exports_path",
        "host_compose_runtime_path",
        "host_prometheus_path",
    )

    WRITE_TOKENS = (
        ".write_text(",
        ".write_bytes(",
        ".mkdir(",
        "os.replace(",
        "shutil.copy2(",
        "shutil.copytree(",
        "shutil.rmtree(",
        "sqlite3.connect(",
    )

    def test_no_write_call_uses_a_host_path_attribute_directly(self) -> None:
        offenders: list[str] = []
        for name in ("actions.py", "main.py", "engine.py", "store.py", "statefile.py", "lease.py", "sandbox.py"):
            path = Path(__file__).resolve().parents[1] / "app" / "upgrade_runner" / name
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("*"):
                    continue
                if not any(token in stripped for token in self.WRITE_TOKENS):
                    continue
                if any(attr in stripped for attr in self.HOST_ATTRS):
                    offenders.append(f"{name}:{number}: {stripped}")
        self.assertEqual(
            offenders,
            [],
            "容器内写操作不得直接以 host_* 路径为基址（会落进 app bind 下的 UPG-050 载体）",
        )

    def test_helper_mount_no_longer_bypasses_translation(self) -> None:
        """回归锁：辅助容器挂载源不得再直接取 `paths[...]`（宿主路径未翻译）。

        修 W3b 之前，辅助容器挂载写的是 `f"{paths['compose_runtime_path']}:/runner-cutover/runtime:ro"`，
        而 runner 实际把文件写到了容器路径落不到的那处（载体目录）——两者不一致。
        修法是挂载源改为 `runtime["compose_file"]`（= 写点的 `docker_host_path` 翻译结果）。
        """
        path = Path(__file__).resolve().parents[1] / "app" / "upgrade_runner" / "actions.py"
        source = path.read_text(encoding="utf-8")
        self.assertNotIn(
            "paths['compose_runtime_path']}:/runner-cutover/runtime:ro",
            source,
            "辅助容器 runtime 挂载不得直接用 paths[]（宿主路径未与写点配对）",
        )
        self.assertIn(
            "{runtime['compose_file'].parent}:/runner-cutover/runtime:ro",
            source,
            "辅助容器必须挂载 runner 刚写下的那个文件所在目录",
        )

    def test_container_path_is_the_only_write_base(self) -> None:
        """`_write_runner_runtime_compose` 的写点必须来自 `_container_runtime_paths`。"""
        path = Path(__file__).resolve().parents[1] / "app" / "upgrade_runner" / "actions.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn(
            'compose_path = container_paths["compose_runtime_path"] / "docker-compose.runner-upgrade.yml"',
            source,
            "写点必须用容器路径",
        )
        self.assertIn(
            "host_compose_path = context.docker_host_path(compose_path)",
            source,
            "返回值必须是把写点翻译回宿主路径的结果",
        )


if __name__ == "__main__":
    unittest.main()
