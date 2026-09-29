"""49-56 步骤 1：`build_offline_delivery.py` 的单元测试。

用**小的假包**构造，不依赖真实的几百 MB 交付物，因此本地/`.3` 都能秒级跑完。
真包路径由 `.3`/`.12` 上的实测覆盖（见 progress.md）。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.build_offline_delivery import (
    FORBIDDEN_DIR_HINTS,
    extract_member,
    render_offline_compose,
    scan_forbidden,
    write_sha256sums,
)


def _make_tar_gz(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class ExtractMemberTest(unittest.TestCase):
    def test_extracts_by_exact_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "pkg.tar.gz"
            _make_tar_gz(archive, {"images/web-api.tar": b"web-api-bytes", "manifest.json": b"{}"})
            out = extract_member(archive, "images/web-api.tar", Path(tmpdir) / "out" / "web-api.tar")
            self.assertEqual(out.read_bytes(), b"web-api-bytes")

    def test_extracts_by_suffix_for_nested_layout(self) -> None:
        """OCI/多层布局下成员名可能带前缀，按后缀也要能取到。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "pkg.tar.gz"
            _make_tar_gz(archive, {"top/dir/images/frontend.tar": b"frontend-bytes"})
            out = extract_member(archive, "images/frontend.tar", Path(tmpdir) / "frontend.tar")
            self.assertEqual(out.read_bytes(), b"frontend-bytes")

    def test_missing_member_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "pkg.tar.gz"
            _make_tar_gz(archive, {"manifest.json": b"{}"})
            with self.assertRaises(SystemExit):
                extract_member(archive, "images/web-api.tar", Path(tmpdir) / "x.tar")


class RenderOfflineComposeTest(unittest.TestCase):
    def _compose(self, tmpdir: str) -> Path:
        path = Path(tmpdir) / "docker-compose.offline.yml"
        path.write_text(
            "services:\n"
            "  web-api:\n"
            "    image: repo/web-api:v0.5.3\n"
            "    pull_policy: never\n"
            "  upgrade-runner:\n"
            "    build:\n"
            "      context: .\n"
            "    image: nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2\n"
            "    env_file:\n"
            "      - .env\n"
            "  prometheus:\n"
            "    image: prom/prometheus:v2.55.1\n",
            encoding="utf-8",
        )
        return path

    def test_renders_published_baseline(self) -> None:
        """交付 compose 必须落已发布基线，而不是源码 compose 的开发线 tag。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = self._compose(tmpdir)
            target = Path(tmpdir) / "out.yml"
            render_offline_compose(source, target, "v0.3.1")
            text = target.read_text(encoding="utf-8")
            self.assertIn("upgrade-runner:v0.3.1", text)
            self.assertNotIn("upgrade-runner:v0.3.2", text)
            # 其它服务与键不得被改动
            self.assertIn("image: repo/web-api:v0.5.3", text)
            self.assertIn("image: prom/prometheus:v2.55.1", text)
            self.assertIn("    build:\n", text)
            self.assertIn("      - .env\n", text)

    def test_raises_when_runner_image_line_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "compose.yml"
            source.write_text("services:\n  web-api:\n    image: repo/web-api:v0.5.3\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                render_offline_compose(source, Path(tmpdir) / "out.yml", "v0.3.1")


class Sha256SumsTest(unittest.TestCase):
    def test_writes_verifiable_sums(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "a.tar").write_bytes(b"aaa")
            (directory / "b.tar").write_bytes(b"bb")
            target = write_sha256sums(directory, ["a.tar", "b.tar"])
            lines = target.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            # 格式必须是 `sha256sum -c` 能直接吃的两空格分隔
            for line in lines:
                self.assertRegex(line, r"^[0-9a-f]{64}  \S+$")

    def test_sorted_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            for name in ("z.tar", "a.tar"):
                (directory / name).write_bytes(b"x")
            target = write_sha256sums(directory, ["z.tar", "a.tar"])
            names = [line.split("  ", 1)[1] for line in target.read_text(encoding="utf-8").strip().splitlines()]
            self.assertEqual(names, ["a.tar", "z.tar"], "输出必须排序，保证两次构建结果一致")


class ScanForbiddenTest(unittest.TestCase):
    def test_clean_delivery_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "install" / "images").mkdir(parents=True)
            (root / "install" / "images" / "web-api.tar").write_bytes(b"x")
            (root / "install" / ".env.template").write_text("SMARTX_SECRET_KEY=__GENERATE__", encoding="utf-8")
            (root / "upgrade" / "packages").mkdir(parents=True)
            (root / "upgrade" / "packages" / "pkg.tar.gz").write_bytes(b"x")
            self.assertEqual(scan_forbidden(root), [])

    def test_detects_real_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "install").mkdir(parents=True)
            (root / "install" / ".env").write_text("SMARTX_SECRET_KEY=real", encoding="utf-8")
            self.assertIn("install/.env", scan_forbidden(root))

    def test_detects_database_and_backup_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app").mkdir(parents=True)
            (root / "app" / "smartx.db").write_bytes(b"x")
            hint = FORBIDDEN_DIR_HINTS[0]
            (root / hint).mkdir(parents=True)
            (root / hint / "upgrade-x.tar.gz").write_bytes(b"x")
            hits = scan_forbidden(root)
            self.assertIn("app/smartx.db", hits)
            self.assertTrue(any(h.startswith(hint) for h in hits))

    def test_env_template_is_allowed(self) -> None:
        """.env.template 是交付物必需的（脚本据此生成），不能被禁含规则误伤。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env.template").write_text("SMARTX_SECRET_KEY=__GENERATE__", encoding="utf-8")
            self.assertEqual(scan_forbidden(root), [])


class ScriptContractTest(unittest.TestCase):
    def test_script_requires_mandatory_args(self) -> None:
        """缺必填参数必须退出（而不是带着 None 往下跑）。"""
        from scripts.build_offline_delivery import main

        with mock.patch("sys.argv", ["build_offline_delivery.py"]), self.assertRaises(SystemExit):
            main()

    def test_platform_services_cover_offline_compose(self) -> None:
        """平台三件套必须与 offline compose 的服务一致，漏一个安装就起不来。"""
        from scripts.build_offline_delivery import PLATFORM_SERVICES

        compose = (Path(__file__).resolve().parent.parent.parent / "docker-compose.offline.yml").read_text(
            encoding="utf-8"
        )
        for service, _member in PLATFORM_SERVICES:
            self.assertIn(f"  {service}:", compose, f"offline compose 缺服务 {service}")
        self.assertIn("  upgrade-runner:", compose)
        self.assertIn("  prometheus:", compose)


class ProjectFilesLayoutTest(unittest.TestCase):
    """交付目录的 project/ 布局必须与 offline compose 的挂载路径对得上。"""

    def test_prometheus_yml_lands_where_compose_mounts_it(self) -> None:
        """compose 挂载 project/prometheus/prometheus.yml —— 放错位置 Prometheus 起不来。"""
        from scripts.build_offline_delivery import copy_project_files

        repo_root = Path(__file__).resolve().parent.parent.parent
        compose = (repo_root / "docker-compose.offline.yml").read_text(encoding="utf-8")
        self.assertIn("project/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml", compose)

        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "project"
            destination.mkdir(parents=True)
            copied = copy_project_files(destination)
            self.assertIn("prometheus/prometheus.yml", copied)
            self.assertTrue((destination / "prometheus" / "prometheus.yml").is_file())
            self.assertFalse((destination / "prometheus.yml").exists(), "不得再放 project 根下")

    def test_pre_install_script_is_delivered_and_executable(self) -> None:
        """安装脚本要复用 pre_install.sh 的目录/权限逻辑，必须随交付物一起发出。"""
        repo_root = Path(__file__).resolve().parent.parent.parent
        self.assertTrue((repo_root / "pre_install.sh").is_file())
        text = (repo_root / "pre_install.sh").read_text(encoding="utf-8")
        # 目录与权限逻辑必须齐全，安装脚本不再重复发明
        for marker in ("PROMETHEUS_UID", "PROMETHEUS_GID", "mkdir -p", "chown", "chmod"):
            self.assertIn(marker, text)


class DeliveryScriptsTest(unittest.TestCase):
    """交付脚本的静态门禁：存在、可执行、语法正确。"""

    def test_scripts_exist_and_are_executable(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        for relative, source in SCRIPT_SOURCES.items():
            self.assertTrue(source.is_file(), f"缺少交付脚本：{relative}（{source}）")
            self.assertTrue(source.stat().st_mode & 0o111, f"{relative} 必须带可执行位")

    def test_scripts_pass_bash_syntax_check(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        for relative, source in SCRIPT_SOURCES.items():
            result = subprocess.run(["bash", "-n", str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{relative} 语法错误：{result.stderr}")

    def test_install_script_never_prints_secrets(self) -> None:
        """密钥绝不能被直接送进输出（安装日志会被人看、被粘贴到工单）。

        判定"直接送进输出"：密钥变量出现在输出函数的**位置参数**里。
        `printf '%s' "$ENV_CONTENT" | awk -v sk="$SECRET_KEY"` 这种**传参给下游处理**不算泄露，
        但 `echo "$SECRET_KEY"` / `info "$SECRET_KEY"` 这类必须禁止。
        """
        import re

        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["install/install.sh"].read_text(encoding="utf-8")
        secret_vars = ("SECRET_KEY", "CREDENTIAL_KEY")
        # 允许的形态：变量出现在 `-v name=$VAR`（传给 awk）、赋值右侧、`unset`
        allowed_patterns = (
            re.compile(r"=\"?\$\{?(?:ENV_)?[A-Z_]*" + r"(SECRET_KEY|CREDENTIAL_KEY)\}?\"?"),
            re.compile(r"-v\s+\w+=\"?\$\{?(?:ENV_)?[A-Z_]*(SECRET_KEY|CREDENTIAL_KEY)\}?\"?"),
            re.compile(r"^unset\b"),
            re.compile(r"^#"),
        )
        offenders: list[str] = []
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not any(var in stripped for var in secret_vars):
                continue
            if any(pattern.search(stripped) for pattern in allowed_patterns):
                continue
            # 剩余情况：出现在输出函数的参数位置
            for output in ("echo", "printf", "info", "ok", "warn", "fail"):
                if re.search(rf"\b{output}\b[^\n]*\$\{{?(?:ENV_)?[A-Z_]*(?:SECRET_KEY|CREDENTIAL_KEY)", stripped):
                    offenders.append(f"第 {number} 行：{stripped}")
        self.assertEqual(offenders, [], "密钥不得直接进入输出：\n" + "\n".join(offenders))

        # 显式确认：随机密钥只经由 gen_secret 产生，且用完即清
        self.assertIn("gen_secret", text)
        self.assertIn("unset ENV_CONTENT SECRET_KEY CREDENTIAL_KEY", text)
        # 生成后必须自检：不得残留占位符、不得为空、两把必须不同
        self.assertIn("__GENERATE__", text)
        self.assertIn("两把密钥相同", text)

    def test_upgrade_script_only_calls_api(self) -> None:
        """升级脚本只调 API：**可执行代码**里不得出现 docker load / compose up / rm。

        注释里可以（而且应该）说明为什么不这么做，因此只看非注释行。
        """
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["upgrade/upgrade.sh"].read_text(encoding="utf-8")
        code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
        code = "\n".join(code_lines)
        for forbidden in ("docker load", "compose up", "rm -rf", "rm -f"):
            self.assertNotIn(forbidden, code, f"upgrade.sh 可执行代码不得包含 {forbidden}（必须只走 API）")
        # 必须真的在调 API
        for endpoint in ("/api/auth/login", "/api/admin/upgrade/upload",
                         "/api/admin/upgrade/precheck/", "/api/admin/upgrade/start/",
                         "/api/admin/upgrade/status/"):
            self.assertIn(endpoint, code, f"upgrade.sh 必须调用 {endpoint}")


    def test_install_script_has_no_silent_exit_traps(self) -> None:
        """set -e 下静默退出是最难排查的失败模式，必须有诊断。

        `.3` 实测踩过：`df -PB1 <尚未存在的 --install-root>` 返回空 → 后续算术比较
        在 set -e 下直接中止，脚本只打印了第一行就消失，用户完全看不到原因。
        """
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["install/install.sh"].read_text(encoding="utf-8")
        self.assertIn("set -Eeuo pipefail", text)
        # 必须装 ERR 陷阱打印行号与命令
        self.assertIn("trap", text)
        self.assertIn("BASH_LINENO", text)
        self.assertIn("BASH_COMMAND", text)
        # df 必须对"目录不存在"有兜底，而不是直接取空值
        self.assertIn("avail_bytes_of", text)
        self.assertIn('AVAIL_BYTES="$(avail_bytes_of', text)
        # 端口探测工具缺失时不得假装端口空闲
        self.assertIn("PORT_PROBE_TOOL", text)

    def test_install_script_does_not_source_env_file(self) -> None:
        """不得 source .env（会执行任意内容）；只能按键读取。"""
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["install/install.sh"].read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
        self.assertNotIn("source ", code)
        self.assertNotIn("set -a", code)
        self.assertNotIn(". \"$ENV_FILE\"", code)

    def test_upgrade_script_reads_env_without_sourcing(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["upgrade/upgrade.sh"].read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
        self.assertNotIn("source ", code)
        self.assertNotIn("set -a", code)
        self.assertIn("read_env_value", code)


class InstallScriptExecutionTest(unittest.TestCase):
    """**真实执行** install.sh 的前置检查，验证不会静默退出。

    只跑到磁盘/端口检查为止（非 root 环境会在这里退出），因此本机与 `.3` 都能跑。
    覆盖 `.3` 实测踩到的坑：`--install-root` 指向**尚不存在**的目录时，
    `set -u` 下未定义变量会让脚本以 1 退出且只打印第一行。
    """

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        return subprocess.run(
            ["bash", str(SCRIPT_SOURCES["install/install.sh"]), "--yes", *args],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_non_existent_install_root_does_not_crash(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        missing = "/nonexistent-smartx-install-root-for-test"
        self.assertFalse(Path(missing).exists())
        result = self._run("--install-root", missing)
        combined = result.stdout + result.stderr
        # 非 root 环境会在 root 检查处退出；关键是**不能**出现未定义变量错误，
        # 且必须给出可读原因而不是只打印一行就消失
        self.assertNotIn("unbound variable", combined, combined)
        if result.returncode != 0:
            self.assertTrue(
                any(marker in combined for marker in ("必须以 root", "root 运行", "磁盘", "端口", "内部错误")),
                f"失败时必须给出可读原因，实际输出：{combined}",
            )

    def test_non_root_exits_with_clear_reason(self) -> None:
        """非 root 时必须明确说明原因（而不是 trace 或静默）。"""
        if os.geteuid() == 0:
            self.skipTest("当前就是 root，跳过非 root 路径")
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        result = self._run()
        combined = result.stdout + result.stderr
        self.assertIn("root", combined)
        self.assertNotIn("unbound variable", combined)

    def test_help_exits_zero_without_touching_anything(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        result = subprocess.run(
            ["bash", str(SCRIPT_SOURCES["install/install.sh"]), "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("install-root", result.stdout)
        self.assertIn("force-env", result.stdout)

    def test_unknown_option_is_rejected(self) -> None:
        result = self._run("--no-such-option")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未知选项", result.stdout + result.stderr)


class UpgradeScriptExecutionTest(unittest.TestCase):
    """真实执行 upgrade.sh 的失败路径，确认它**不碰环境**且提示可读。"""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        return subprocess.run(
            ["bash", str(SCRIPT_SOURCES["upgrade/upgrade.sh"]), "--yes", *args],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_unreachable_platform_fails_cleanly(self) -> None:
        result = self._run("--base-url", "http://127.0.0.1:59999")
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("平台不可达", combined)
        # 必须说明"不会自行修改环境"
        self.assertIn("不会自行修改环境", combined)

    def test_help_exits_zero(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        result = subprocess.run(
            ["bash", str(SCRIPT_SOURCES["upgrade/upgrade.sh"]), "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("with-runner", result.stdout)


if __name__ == "__main__":
    unittest.main()
