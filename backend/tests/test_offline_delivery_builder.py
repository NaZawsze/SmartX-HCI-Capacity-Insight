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

    def test_precheck_produces_no_shell_errors(self) -> None:
        """前置检查全程不得有任何 shell 报错输出。

        `.3` 实测踩到：`$(( ... ))` 少一个右括号，`bash -n` 查不出来（它只查语法结构，
        不查算术展开），只有真跑才报 `[: missing ']'`。
        """
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        result = self._run("--install-root", "/nonexistent-smartx-install-root-for-test")
        combined = result.stdout + result.stderr
        for pattern in ("missing `]'", "unbound variable", "syntax error", "integer expression expected"):
            self.assertNotIn(pattern, combined, f"前置检查出现 shell 报错：{combined}")

    def test_disk_check_line_is_valid_arithmetic(self) -> None:
        """直接抽出磁盘比较那行做算术求值，确保括号配平。"""
        import re

        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["install/install.sh"].read_text(encoding="utf-8")
        match = re.search(r"if \[ \"\$AVAIL_BYTES\" -lt \$\(\((.*?)\)\)\s*\]; then", text)
        self.assertIsNotNone(match, "找不到磁盘比较语句（格式可能变了）")
        expression = match.group(1)
        # 能被 bash 正确求值即括号配平
        result = subprocess.run(
            ["bash", "-c", f"NEED_GIB=1; echo $(( {expression} ))"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"算术表达式有问题：{expression} → {result.stderr}")
        self.assertTrue(result.stdout.strip().isdigit(), result.stdout)


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


class DeliveryReadmeTest(unittest.TestCase):
    """交付 README 的内容门禁：必备章节齐全，且不得漏掉两条关键警告。"""

    def _readme(self) -> str:
        from scripts.build_offline_delivery import ROOT

        path = ROOT / "delivery" / "README.md"
        self.assertTrue(path.is_file(), "缺少交付 README 源文件")
        return path.read_text(encoding="utf-8")

    def test_required_sections_present(self) -> None:
        text = self._readme()
        for heading in (
            "前置条件",
            "目录结构",
            "首次安装",
            "离线升级",
            "自检",
            "常见失败与处理",
            "卸载",
            "安全建议",
        ):
            self.assertIn(heading, text, f"README 缺少章节：{heading}")

    def test_warns_to_change_default_password(self) -> None:
        """默认口令是公开的，README 必须明确要求首登改密。"""
        text = self._readme()
        self.assertIn("password", text)
        self.assertTrue(
            "修改管理员口令" in text or "改密" in text,
            "README 必须提示首次登录后修改管理员口令",
        )
        self.assertIn("公开", text)

    def test_warns_uninstall_is_irreversible(self) -> None:
        """卸载会删数据，README 必须警告不可恢复。"""
        text = self._readme()
        self.assertIn("不可恢复", text)
        self.assertIn("rm -rf /data/smartx-storage-forecast", text)

    def test_documents_upgrade_order(self) -> None:
        """必须写清"先平台、后 runner"，否则客户容易顺序颠倒导致升级中断。"""
        text = self._readme()
        self.assertIn("升级顺序", text)
        self.assertTrue("成功之后" in text or "成功之后" in text)
        self.assertIn("--with-runner", text)

    def test_explains_why_upgrade_must_use_api(self) -> None:
        """必须解释为什么不能自己 docker load 改环境（避免客户绕过脚本）。"""
        text = self._readme()
        self.assertIn("docker load", text)
        self.assertIn("API", text)
        for keyword in ("并发", "清理", "留痕", "锁死"):
            self.assertIn(keyword, text, f"README 解释绕过 API 的后果时缺少：{keyword}")

    def test_readme_is_release_doc_scanned(self) -> None:
        """README 随包发给客户，必须纳入对外文档脱敏扫描。"""
        from scripts.verify_release_docs_safe import PUBLIC_DOCS

        self.assertIn("delivery/README.md", PUBLIC_DOCS)

    def test_readme_passes_release_docs_scan(self) -> None:
        from scripts.verify_release_docs_safe import scan_file
        from scripts.build_offline_delivery import ROOT

        violations = scan_file(ROOT / "delivery" / "README.md")
        self.assertEqual(violations, [], "交付 README 触发脱敏门禁")

    def test_readme_commands_use_placeholder_not_real_host(self) -> None:
        """不得出现具体内网 IP（客户环境不同），统一用 <本机IP> 占位。"""
        import re

        text = self._readme()
        self.assertIn("<本机IP>", text)
        for match in re.finditer(r"\b10\.(?!249\.)\d{1,3}\.\d{1,3}\.\d{1,3}\b", text):
            self.fail(f"README 含内网 IP：{match.group(0)}")

    def test_documented_verification_state_is_honest(self) -> None:
        """README 必须如实标注各条命令的验证状态，不得把"计划中"写成"已验证"。

        设计 §7 场景 7 要求"每条命令都在实测中跑过"。当前进度：完整安装与离线升级
        仍待**干净 VM 实测**（步骤 6），因此这里用显式清单锁住口径，后续实测完成时
        再更新——避免文档长期给出未经验证的结论。
        """
        import re

        from scripts.build_offline_delivery import ROOT

        marker = ROOT / "delivery" / "README.verified.md"
        self.assertTrue(
            marker.is_file(),
            "缺少 delivery/README.verified.md（各命令验证状态清单）——"
            "禁止在无清单的情况下宣称 README 命令已验证",
        )
        text = marker.read_text(encoding="utf-8")
        self.assertIn("干净 VM", text)
        # 清单里必须同时出现"已验证"与"未验证"两类状态，避免全绿幻觉
        self.assertRegex(text, r"已验证")
        self.assertRegex(text, r"未验证|待实测")
        # 交付 README 正文里必须带上这份清单的指引
        readme = self._readme()
        self.assertIn("验证", readme)

        def normalize(value: str) -> str:
            """归一化：去掉 sudo/bash 前缀、路径、换行；保留脚本名与长选项。"""
            value = value.replace("sudo ", "").replace("bash ", "").replace("./", "")
            return re.sub(r"\s+", " ", value).strip()

        readme_norm = normalize(readme)
        for command, state in re.findall(r"^\| `([^`]+)` \| (\S+?) \|", text, re.M):
            self.assertIn(state, ("已验证", "未验证", "待实测"), f"未知状态：{state}")
            normalized = normalize(command)
            script = normalized.split()[0].split("/")[-1] if normalized.split() else ""
            # 脚本名必须在 README 里出现
            self.assertIn(script, readme_norm, f"README 里找不到脚本 {script}（清单条目：{command}）")
            # 命令里出现的每个长选项也必须在 README 里出现
            for option in (t for t in normalized.split() if t.startswith("--")):
                self.assertIn(
                    option, readme_norm,
                    f"README 里找不到选项 {option}（清单条目：{command}）",
                )


if __name__ == "__main__":
    unittest.main()


class InstallRunnerBaselineTest(unittest.TestCase):
    """US-33：安装用 runner 镜像必须与 install compose 声明的 baseline 同 tag。

    `.14` 干净 VM 实测暴露的缺陷：交付包把 install compose 的 runner tag 渲染成
    **已发布基线** v0.3.1（AGENTS §8 版本治理要求），却把组件包里"当前版本"的
    v0.3.2 镜像塞进 `install/images/` —— 干净 VM 上 `install.sh` 必然在
    「镜像 tag 与 compose 声明不匹配」这一步失败。

    这个缺陷在 `.3` 上被掩盖了：`.3` 本地恰好同时存在 v0.3.1 与 v0.3.2。
    """

    def _source(self) -> str:
        from scripts.build_offline_delivery import ROOT

        return (ROOT / "scripts" / "build_offline_delivery.py").read_text(encoding="utf-8")

    def test_install_runner_image_comes_from_baseline_not_component_package(self) -> None:
        """安装镜像必须 docker save baseline tag，而不是从组件包解包。"""
        source = self._source()
        self.assertIn(
            "docker_save(baseline_image, images_dir / \"upgrade-runner.tar\")",
            source,
            "安装用 runner 镜像必须按 baseline tag 导出",
        )
        # 旧的错误来源：从组件包提取当前版本镜像
        self.assertNotIn(
            'extract_member(runner_package, "images/upgrade-runner.tar", images_dir / "upgrade-runner.tar")',
            source,
            "不得再把组件包的当前版本镜像当作安装镜像（US-33 根因）",
        )

    def test_baseline_image_name_is_built_from_runner_baseline(self) -> None:
        source = self._source()
        self.assertIn(
            'baseline_image = f"nazawsze/smartx-hci-capacity-insight-upgrade-runner:{args.runner_baseline}"',
            source,
            "baseline 镜像名必须由 --runner-baseline 拼出，保证与 compose 一致",
        )

    def test_missing_baseline_image_fails_at_build_time(self) -> None:
        """本地没有 baseline 镜像时必须**构建即失败**，而不是留给客户安装时炸。"""
        source = self._source()
        self.assertIn('["docker", "image", "inspect", baseline_image]', source)
        self.assertIn("本地没有安装用 runner 镜像", source)
        self.assertIn("raise SystemExit", source)

    def test_install_sh_rejects_tag_mismatch(self) -> None:
        """install.sh 必须真的校验 tag（这也是当初拦下 US-33 的那道关）。"""
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["install/install.sh"].read_text(encoding="utf-8")
        self.assertIn("EXPECTED_IMAGES", text)
        self.assertIn("docker image inspect", text)
        self.assertIn("镜像 tag 与 compose 声明不匹配", text)


if __name__ == "__main__":
    unittest.main()


class ShellQuotingTest(unittest.TestCase):
    """shell 单引号内不得再出现单引号（会提前闭合、后续被当命令执行）。

    `.14` 实测踩到：`upgrade.sh` 预检查格式化里写了 `check.get('name')`，
    而整个 python 代码是用 shell 单引号包裹的 —— 单引号提前闭合导致格式化失效，
    预检查结果把整段 JSON 原样打给用户（`.14` 离线升级实测）。
    """

    def _python_blocks(self, script: Path) -> list[str]:
        import re

        text = script.read_text(encoding="utf-8")
        return [match.group(1) for match in re.finditer(r"python3? -c '(.*?)'", text, re.S)]

    def test_no_single_quote_inside_single_quoted_python(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        for relative, source in SCRIPT_SOURCES.items():
            for index, block in enumerate(self._python_blocks(source), start=1):
                for number, line in enumerate(block.splitlines(), start=1):
                    self.assertNotIn(
                        "'", line,
                        f"{relative} 第 {index} 个内嵌 python 块第 {number} 行含单引号，"
                        f"会提前闭合 shell 引号：{line.strip()[:80]}",
                    )

    def test_upgrade_script_precheck_is_formatted(self) -> None:
        """预检查必须逐项打印（含 OK/FAIL 标记），而不是原样 JSON。"""
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        text = SCRIPT_SOURCES["upgrade/upgrade.sh"].read_text(encoding="utf-8")
        self.assertIn("预检查结果", text)
        self.assertIn('print("     [" + mark + "] "', text)
        self.assertIn('mark = "OK  " if check.get("ok") else "FAIL"', text)
        # python3 缺失时要有可读的兜底，而不是崩溃
        self.assertIn("系统无 python3", text)


class DeliveryBundleSelfConsistencyTest(unittest.TestCase):
    """US-33 防线 A：交付物必须在**构建期**自洽，无需干净机器即可断言。

    做法：解包 `images/*.tar` 读出镜像的**真实 tag**，与 install compose 的声明逐一比对。
    OCI 格式从 `index.json` 的 `io.containerd.image.name` 注解取，旧格式从
    `manifest.json` 的 `RepoTags` 取。
    """

    def test_reads_tags_from_oci_archive(self) -> None:
        import io as _io
        import json as _json
        import tarfile as _tarfile

        from scripts.build_offline_delivery import image_tags_in_archive

        index = _json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "annotations": {
                            "io.containerd.image.name": "docker.io/nazawsze/repo:v0.3.1"
                        }
                    }
                ],
            }
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "img.tar"
            with _tarfile.open(archive, "w") as tar:
                info = _tarfile.TarInfo("index.json")
                info.size = len(index)
                tar.addfile(info, _io.BytesIO(index))
            self.assertEqual(image_tags_in_archive(archive), {"nazawsze/repo:v0.3.1"})

    def test_reads_tags_from_legacy_archive(self) -> None:
        import io as _io
        import json as _json
        import tarfile as _tarfile

        from scripts.build_offline_delivery import image_tags_in_archive

        manifest = _json.dumps([{"RepoTags": ["nazawsze/repo:v0.3.2", "nazawsze/repo:latest"]}]).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "legacy.tar"
            with _tarfile.open(archive, "w") as tar:
                info = _tarfile.TarInfo("manifest.json")
                info.size = len(manifest)
                tar.addfile(info, _io.BytesIO(manifest))
            self.assertEqual(
                image_tags_in_archive(archive),
                {"nazawsze/repo:v0.3.2", "nazawsze/repo:latest"},
            )

    def test_declared_images_parsed_from_compose(self) -> None:
        from scripts.build_offline_delivery import declared_images_from_compose

        with tempfile.TemporaryDirectory() as tmpdir:
            compose = Path(tmpdir) / "docker-compose.offline.yml"
            compose.write_text(
                "services:\n"
                "  web-api:\n"
                "    image: repo/web-api:v0.5.3\n"
                "  upgrade-runner:\n"
                "    build:\n"
                "      context: .\n"
                "    image: repo/upgrade-runner:v0.3.1\n"
                "    # image: repo/ignored:v0\n",
                encoding="utf-8",
            )
            declared = declared_images_from_compose(compose)
            self.assertIn("repo/web-api:v0.5.3", declared)
            self.assertIn("repo/upgrade-runner:v0.3.1", declared)
            self.assertNotIn("repo/ignored:v0", declared, "注释里的 image 不得算作声明")

    def test_comparison_logic_matches_tags_not_filenames(self) -> None:
        """判别：比对必须用**真实 tag 集合**，不能用归档文件名集合。

        曾经的 bug：`set(provided)` 取到的是 `{'web-api.tar', ...}` 这类**文件名**，
        与 compose 声明的 tag 集合永不相交 → 即使每个 tag 都正确也报"不自洽"。
        .3 真实构建当场暴露（5 个 tag 全对却报不自洽）。
        """
        import io as _io
        import json as _json
        import tarfile as _tarfile

        from scripts.build_offline_delivery import (
            declared_images_from_compose,
            image_tags_in_archive,
        )

        # 造两个归档，tag 集合恰好覆盖 compose 声明
        archives = {"web-api.tar": {"nazawsze/web-api:v0.5.3"},
                    "upgrade-runner.tar": {"nazawsze/upgrade-runner:v0.3.1"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir)
            for name, tags in archives.items():
                index = _json.dumps(
                    {"manifests": [{"annotations": {
                        "io.containerd.image.name": f"docker.io/{next(iter(tags))}"}}]}
                ).encode("utf-8")
                with _tarfile.open(images_dir / name, "w") as tar:
                    info = _tarfile.TarInfo("index.json")
                    info.size = len(index)
                    tar.addfile(info, _io.BytesIO(index))

            compose = Path(tmpdir) / "docker-compose.yml"
            compose.write_text(
                "services:\n  web-api:\n    image: nazawsze/web-api:v0.5.3\n"
                "  upgrade-runner:\n    image: nazawsze/upgrade-runner:v0.3.1\n",
                encoding="utf-8",
            )

            declared = declared_images_from_compose(compose)
            available: set[str] = set()
            for tar_path in sorted(images_dir.glob("*.tar")):
                available |= image_tags_in_archive(tar_path)

            self.assertEqual(declared - available, set(), "tag 全部匹配时不得报告缺失")
            # 关键：available 必须是 tag，不能是文件名
            self.assertNotIn("web-api.tar", available)

    def test_comparison_detects_real_mismatch(self) -> None:
        """US-33 判别：compose 要 v0.3.1、归档里是 v0.3.2 → 必须报缺失。"""
        import io as _io
        import json as _json
        import tarfile as _tarfile

        from scripts.build_offline_delivery import (
            declared_images_from_compose,
            image_tags_in_archive,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            images_dir = Path(tmpdir)
            index = _json.dumps(
                {"manifests": [{"annotations": {
                    "io.containerd.image.name": "docker.io/nazawsze/upgrade-runner:v0.3.2"}}]}
            ).encode("utf-8")
            with _tarfile.open(images_dir / "upgrade-runner.tar", "w") as tar:
                info = _tarfile.TarInfo("index.json")
                info.size = len(index)
                tar.addfile(info, _io.BytesIO(index))

            compose = Path(tmpdir) / "docker-compose.yml"
            compose.write_text(
                "services:\n  upgrade-runner:\n    image: nazawsze/upgrade-runner:v0.3.1\n",
                encoding="utf-8",
            )
            declared = declared_images_from_compose(compose)
            available: set[str] = set()
            for tar_path in sorted(images_dir.glob("*.tar")):
                available |= image_tags_in_archive(tar_path)
            self.assertEqual(declared - available, {"nazawsze/upgrade-runner:v0.3.1"})

    def test_builder_runs_self_consistency_gate(self) -> None:
        """构建流程必须真的调用这道门禁。"""
        from scripts.build_offline_delivery import ROOT

        source = (ROOT / "scripts" / "build_offline_delivery.py").read_text(encoding="utf-8")
        self.assertIn("image_tags_in_archive(", source)
        self.assertIn("declared_images_from_compose(", source)
        self.assertIn("交付物不自洽", source)
        self.assertIn("US-33", source)
        # 门禁必须在写 SHA256SUMS 之前跑（否则清单先于失败产出）
        self.assertLess(
            source.index("交付物不自洽"),
            source.index("install_sums = write_sha256sums"),
            "自洽门禁应早于 SHA256SUMS 生成",
        )


class CriticalCommandVisibilityTest(unittest.TestCase):
    """US-34 防线 B：关键命令失败不得被静默吞掉。

    US-34 里 `python3 -c '...'` 的格式化失败被 `2>/dev/null` 吞掉，脚本照常往下走、
    把整段 JSON 原样打给用户却毫无提示。

    判定"关键命令"：health 探测、登录、上传、预检查、start、status 这些
    **决定脚本分支走向**的调用——它们失败必须走 `|| true` 之外的显式错误分支。
    探测类（`df` / `ss` / `find`）失败是正常分支，保留 `2>/dev/null` 合理。
    """

    CRITICAL = (
        "api/auth/login",
        "api/admin/upgrade/upload",
        "api/admin/upgrade/precheck",
        "api/admin/upgrade/start",
        "api/admin/upgrade/status",
        "api/system/health",
    )

    def test_no_critical_call_swallows_stderr_silently(self) -> None:
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        for relative, source in SCRIPT_SOURCES.items():
            for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
                if not any(endpoint in line for endpoint in self.CRITICAL):
                    continue
                if "2>/dev/null" not in line:
                    continue
                # 捕获变量并配 `|| true` 是允许的（失败会被后续的分支判定接住）
                if "|| true" in line or "=$(" in line or "-s " in line:
                    continue
                self.fail(
                    f"{relative}:{number} 关键调用静默吞掉 stderr，且无显式失败分支：{line.strip()[:90]}"
                )

    def test_scripts_report_when_probe_fails(self) -> None:
        """健康探测失败时必须有可读提示，而不是只有空变量。"""
        from scripts.build_offline_delivery import SCRIPT_SOURCES

        upgrade = SCRIPT_SOURCES["upgrade/upgrade.sh"].read_text(encoding="utf-8")
        self.assertIn("平台不可达", upgrade, "health 失败必须给出可读原因")
        install = SCRIPT_SOURCES["install/install.sh"].read_text(encoding="utf-8")
        self.assertIn("服务未在超时内达到健康状态", install, "健康检查失败必须给出诊断与补救")
        # install.sh 装了 ERR 陷阱，任何未预期失败都有行号可查
        self.assertIn("BASH_LINENO", install)
