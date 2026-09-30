"""CLI 工具链（task_plan #58 / pending-tasks #58）单测。

覆盖设计 §6.1 的提示规范与 §6.2 的退出码约定，以及"只提示不自动装"的纪律（Q5）。
这些是纯 shell 脚本，用桩命令（stub）构造环境来验证，不用真机。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "cli"
CHECK_DEPS = CLI / "check-deps.sh"
COMMON = CLI / "lib" / "common.sh"


class CliScriptPresenceTest(unittest.TestCase):
    """脚本存在、语法正确、入口齐全。"""

    def test_required_files_exist(self) -> None:
        for relative in ("README.md", "install.sh", "upgrade.sh", "package.sh", "check-deps.sh"):
            self.assertTrue((CLI / relative).is_file(), f"缺少 cli/{relative}")
        self.assertTrue(COMMON.is_file(), "缺少 cli/lib/common.sh")

    def test_all_scripts_pass_syntax_check(self) -> None:
        for script in sorted(CLI.rglob("*.sh")):
            completed = subprocess.run(
                ["bash", "-n", str(script)], capture_output=True, text=True, check=False
            )
            self.assertEqual(
                completed.returncode, 0, f"{script.relative_to(ROOT)} 语法错误：{completed.stderr}"
            )

    def test_scripts_are_executable(self) -> None:
        for name in ("install.sh", "upgrade.sh", "package.sh", "check-deps.sh"):
            path = CLI / name
            self.assertTrue(os.access(path, os.X_OK), f"cli/{name} 缺少可执行位")


class CliDependencyCheckTest(unittest.TestCase):
    """check-deps.sh 的退出码与提示规范（设计 §6.1 / §6.2）。"""

    def _stub_bin(self, directory: Path, stubs: dict[str, str]) -> Path:
        """造一个桩 PATH：stubs 是 命令名 -> 退出码(0 存在 / 127 不存在)。"""
        directory.mkdir(parents=True, exist_ok=True)
        for name, code in stubs.items():
            path = directory / name
            path.write_text(
                "#!/bin/sh\n"
                f"case \"$1\" in\n"
                f"  --version) echo '{name} 1.0.0' ;;\n"
                f"  --short) echo 'v1' ;;\n"
                f"esac\n"
                "exit %d\n" % code,
                encoding="utf-8",
            )
            path.chmod(0o755)
        return directory

    def _run(self, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["NO_COLOR"] = "1"
        # 强制低磁盘阈值，避开 CI 机器真实空间差异
        env.setdefault("CLI_MIN_DISK_GB", "1")
        if env_extra:
            env.update(env_extra)
        completed = subprocess.run(
            ["bash", str(CHECK_DEPS)],
            capture_output=True, env=env, check=False,
        )
        # 用 errors="replace"：脚本输出的字节流在非 UTF-8 locale 下可能夹带非法字节，
        # 断言看的是内容而非编码，不该因此炸在解码上。
        completed.stdout = completed.stdout.decode("utf-8", errors="replace")
        completed.stderr = completed.stderr.decode("utf-8", errors="replace")
        return completed

    def test_exits_2_when_docker_missing(self) -> None:
        """缺 Docker 时必须 exit 2（阻断），而不是继续。"""
        with tempfile.TemporaryDirectory() as raw:
            empty = Path(raw) / "empty-bin"
            empty.mkdir(parents=True, exist_ok=True)
            # PATH 只留系统基础命令，故意不含 docker
            result = self._run({"PATH": f"{empty}:/usr/bin:/bin"})
            self.assertEqual(
                result.returncode, 2, f"缺 docker 时应 exit 2，实际 {result.returncode}"
            )

    def test_missing_items_give_actionable_commands(self) -> None:
        """每项 MISSING 必须带可执行命令（设计 §6.1 文案规范）。"""
        with tempfile.TemporaryDirectory() as raw:
            empty = Path(raw) / "empty-bin"
            empty.mkdir(parents=True, exist_ok=True)
            result = self._run({"PATH": f"{empty}:/usr/bin:/bin"})
            output = result.stdout + result.stderr
            for expected in ("docker", "git", "python3"):
                self.assertIn(expected, output, f"缺 {expected} 时应在输出中说明")
            # 必须给出可直接执行的命令，而不是"请确保"这类无法执行的表述
            self.assertRegex(output, r"(yum install|apt-get install|get\.docker\.com|usermod)")
            for vague in ("请确保", "请检查是否安装"):
                self.assertNotIn(vague, output, f"提示不得使用无法执行的表述：{vague}")

    def test_never_auto_installs(self) -> None:
        """Q5 纪律：脚本内不得出现任何安装动作，只能提示。"""
        for script in sorted(CLI.rglob("*.sh")):
            text = script.read_text(encoding="utf-8")
            # 允许出现在 info/echo 的提示字符串里，但不允许作为真实命令执行
            offenders = [
                line
                for line in text.splitlines()
                if re.search(r"^\s*(sudo\s+)?(yum|apt-get|apt|dnf)\s+install", line)
            ]
            self.assertEqual(
                offenders, [], f"{script.relative_to(ROOT)} 不得自动安装依赖：{offenders}"
            )

    def test_exits_0_when_all_present(self) -> None:
        """桩出齐全的环境时应 exit 0。"""
        if not shutil.which("docker"):
            self.skipTest("本机无 docker，无法构造全齐环境")
        result = self._run()
        # 有 docker 但守护进程可能未运行；只要不是因缺命令而 exit 2 即可
        if result.returncode == 2 and "未检测到 docker 命令" in (result.stdout + result.stderr):
            self.fail("docker 存在时不应报'未检测到 docker 命令'")
        self.assertIn(result.returncode, (0, 2))


class CliCommonLibTest(unittest.TestCase):
    """共用库的退出码与确认逻辑。"""

    def test_die_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "t.sh"
            script.write_text(
                f'. "{COMMON}"\ndie "boom"\n', encoding="utf-8"
            )
            result = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True,
                env={**os.environ, "NO_COLOR": "1"}, check=False
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("boom", result.stderr)

    def test_confirm_requires_yes_when_not_interactive(self) -> None:
        """非交互且未给 --yes 时必须拒绝（不擅自替用户决定破坏性操作）。"""
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "t.sh"
            script.write_text(
                f'. "{COMMON}"\n'
                "unset ASSUME_YES\n"
                'if confirm "reset --hard"; then echo ALLOW; else echo DENY; fi\n',
                encoding="utf-8"
            )
            result = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "NO_COLOR": "1", "ASSUME_YES": ""}, check=False
            )
            self.assertIn("DENY", result.stdout, "非交互未确认时必须拒绝")

    def test_confirm_skips_when_assume_yes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "t.sh"
            script.write_text(
                f'. "{COMMON}"\n'
                'if confirm "reset --hard"; then echo ALLOW; else echo DENY; fi\n',
                encoding="utf-8"
            )
            result = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "NO_COLOR": "1", "ASSUME_YES": "1"}, check=False
            )
            self.assertIn("ALLOW", result.stdout)


class CliRepoRootTest(unittest.TestCase):
    """cli_repo_root 必须解析到仓库根（薄封装定位 delivery/ 靠它）。"""

    def test_repo_root_resolves_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "t.sh"
            script.write_text(
                f'. "{COMMON}"\ncli_repo_root\n', encoding="utf-8"
            )
            result = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True, check=False
            )
            self.assertEqual(
                result.stdout.strip(), str(ROOT), "cli_repo_root 必须解析到仓库根"
            )


class CliThinWrapperTest(unittest.TestCase):
    """install.sh / upgrade.sh 的转发逻辑（Q4）。

    2026-09-30 修正过一次设计错误：原实现直接 `exec ../delivery/install/install.sh`，
    但**仓库里 `delivery/install/` 只有 install.sh 本体**，没有 `images/`、`project/`——
    那些是 build_offline_delivery.py 打包时的产物（1.1G），不进 git。直接转发必然失败。
    现实现：先在几个候选位置找**自包含**的交付物料（含 images/+project/ 或 packages/），
    找到才转发；找不到则明确告知三条路径，不静默失败。
    """

    def test_wrappers_search_multiple_delivery_locations(self) -> None:
        for name, marker in (
            ("install.sh", '"$CANDIDATE/images"'),
            ("upgrade.sh", '"$CANDIDATE/packages"'),
        ):
            text = (CLI / name).read_text(encoding="utf-8")
            self.assertIn("for CANDIDATE in", text, f"cli/{name} 必须遍历候选交付目录")
            self.assertIn(
                marker, text,
                f"cli/{name} 必须校验交付物料完整性（{marker}），不能只看脚本存在",
            )
            self.assertIn("exec bash", text, f"cli/{name} 找到物料后必须 exec 转发")
            self.assertIn('"$@"', text, f"cli/{name} 必须原样透传参数")

    def test_wrappers_explain_repo_delivery_is_incomplete(self) -> None:
        """必须点明「仓库里的 delivery/ 不完整」，否则用户会以为脚本坏了。"""
        for name in ("install.sh", "upgrade.sh"):
            text = (CLI / name).read_text(encoding="utf-8")
            self.assertIn(
                "不是**给客户用的",
                text,
                f"cli/{name} 必须说明它不是给客户用的（避免与交付目录脚本混淆）",
            )
            self.assertIn(
                "不进 git",
                text,
                f"cli/{name} 必须解释交付物料为何不在仓库里",
            )

    def test_wrappers_fail_readably_without_delivery(self) -> None:
        """无交付物料时给可操作的三条路径，不是静默失败。"""
        with tempfile.TemporaryDirectory() as raw:
            fake_root = Path(raw)
            (fake_root / "cli" / "lib").mkdir(parents=True)
            shutil.copy2(COMMON, fake_root / "cli" / "lib" / "common.sh")
            for name in ("install.sh", "upgrade.sh"):
                shutil.copy2(CLI / name, fake_root / "cli" / name)
                result = subprocess.run(
                    ["bash", str(fake_root / "cli" / name)],
                    capture_output=True, text=True,
                    env={**os.environ, "NO_COLOR": "1"}, check=False
                )
                self.assertEqual(result.returncode, 2, f"{name} 应 exit 2")
                combined = result.stdout + result.stderr
                self.assertIn("找不到可用", combined, f"{name} 必须说明缺什么")
                self.assertIn(
                    "bash cli/package.sh", combined,
                    f"{name} 必须给出「先打包」这条路径",
                )
                self.assertIn(
                    "install/install.sh" if name == "install.sh" else "upgrade/upgrade.sh",
                    combined,
                    f"{name} 必须指出客户该用交付目录里的脚本",
                )

    def test_wrappers_do_not_modify_delivery(self) -> None:
        """入口不得改动 delivery/ 下任何文件。"""
        if not shutil.which("git"):
            self.skipTest("环境无 git（如容器内跑测试），无法用 git status 判定")
        if not (ROOT / ".git").exists():
            self.skipTest("当前不是 git 检出（测试机用 git archive 同步），无 git status 可用")
        completed = subprocess.run(
            ["git", "status", "--porcelain", "delivery/"],
            cwd=str(ROOT), capture_output=True, text=True, check=False
        )
        self.assertEqual(
            completed.stdout.strip(), "", "cli/ 实施不得改动 delivery/ 任何文件"
        )

    def test_delivery_scripts_untouched_by_content(self) -> None:
        """无 git 时的等价保证：交付态脚本必须存在且可执行。"""
        for relative in ("delivery/install/install.sh", "delivery/upgrade/upgrade.sh"):
            target = ROOT / relative
            self.assertTrue(target.is_file(), f"{relative} 必须存在")
            self.assertTrue(os.access(target, os.X_OK), f"{relative} 必须可执行")

    def test_repo_delivery_lacks_generated_artifacts(self) -> None:
        """锁定一个已确认的事实：仓库里的 delivery/install 没有 images/ 与 project/。

        这是 2026-09-30 发现的设计缺陷的根据——若哪天决定把镜像目录也纳入版本控制，
        本测试会失败，提醒同步更新 cli/install.sh 的定位逻辑与 README 文案。
        """
        install_dir = ROOT / "delivery" / "install"
        self.assertTrue((install_dir / "install.sh").is_file())
        self.assertFalse(
            (install_dir / "images").exists(),
            "仓库里不应存在 delivery/install/images/（1.1G 产物，不进 git）；"
            "若已纳入版本控制，请同步更新 cli/install.sh 与 cli/README.md",
        )



class CliPackageScriptTest(unittest.TestCase):
    """package.sh 的关键行为：分支默认、门禁、破坏性确认。"""

    def _text(self) -> str:
        return (CLI / "package.sh").read_text(encoding="utf-8")

    def test_default_branch_is_main(self) -> None:
        """Q1：默认必须是发布线 main，dev2 是开发线。"""
        text = self._text()
        self.assertIn('BRANCH="main"', text, "默认分支必须是 main（发布线）")
        self.assertIn("--branch", text, "必须支持 --branch 覆盖")

    def test_help_mentions_branch_risk(self) -> None:
        """帮助文本必须警告 dev2 是开发线（防止打错包发客户）。"""
        result = subprocess.run(
            ["bash", str(CLI / "package.sh"), "--help"],
            capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("dev2", result.stdout, "帮助必须点明 dev2 是开发线")

    def test_gates_are_enforced(self) -> None:
        """三道门禁必须都在，且失败即中止。"""
        text = self._text()
        self.assertIn("verify_upgrade_package_identity.py", text)
        self.assertIn("verify_runner_delivery_consistency.py", text)
        self.assertIn("敏感文件", text, "必须有敏感文件扫描")
        # 门禁失败必须 exit 2 而不是继续
        self.assertGreaterEqual(text.count("exit 2"), 5, "门禁/预检失败必须中止")

    def test_version_prefix_not_doubled(self) -> None:
        """VERSION 文件已带 v 前缀，路径不能再补一个 v（曾拼出 vv0.5.3 导致找不到包）。"""
        text = self._text()
        self.assertIn('${VER_RAW#v}', text, "必须去掉原始版本的前导 v 再归一化")
        self.assertIn('${RVER_RAW#v}', text)
        # 归一化后 VER/RVER 已含 v，路径里不得再写 v$VER（会变成 vv0.5.3）
        for bad in ("upgrade-v$VER.tar.gz", "构建平台包 v$VER"):
            self.assertNotIn(bad, text, f"版本号重复加 v：{bad}")
        # 正确的写法应是直接用归一化后的变量
        self.assertIn("upgrade-$VER.tar.gz", text)
        self.assertIn("smartx-upgrade-runner-$RVER.tar.gz", text)

    def test_dirty_tree_checked_even_with_no_fetch(self) -> None:
        """--no-fetch 也必须检查工作树脏状态。

        实测漏掉：脏检查被包在 `if [ -d .git ] && [ "$DO_FETCH" = 1 ]` 里，
        于是 --no-fetch 时完全不提示，而产物其实来自被改过的工作树。
        """
        text = self._text()
        # 脏检查必须在 fetch 判断之外
        dirty_at = text.index("git status --porcelain")
        guard_at = text.index('if [ -d "$ROOT/.git" ] && [ "$DO_FETCH" = "1" ]')
        self.assertLess(
            dirty_at, guard_at,
            "脏检查必须早于 fetch 分支判断（否则 --no-fetch 会跳过它）",
        )
        self.assertIn(
            "--no-fetch", text[dirty_at:guard_at],
            "--no-fetch 路径必须在脏检查处显式告警（产物含本地改动）",
        )

    def test_runner_baseline_is_tag_not_path(self) -> None:
        """--runner-baseline 收**tag**（v0.3.1），不是镜像 tar 路径。

        实测误传 tar 路径后，build_offline_delivery.py 拼出
        `upgrade-runner:/path/to/runner-baseline.tar` 而找不到镜像，直接失败。
        镜像导出由该脚本自己做，package.sh 不该插手。
        """
        text = self._text()
        self.assertIn('CLI_RUNNER_BASELINE_TAG:-v0.3.1', text, "基线必须是 tag 形式")
        self.assertIn('--runner-baseline "$BASELINE_TAG"', text,
                      "传给 build_offline_delivery 的必须是 tag，不是 tar 路径")
        self.assertNotIn('--runner-baseline "$BASELINE_TAR"', text,
                         "不得把 tar 路径当 --runner-baseline 传入")
        # 也不该自己 docker save（重复劳动且语义错位）——只查可执行代码行
        code_lines = [
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        ]
        self.assertNotIn(
            "docker save", "\n".join(code_lines),
            "镜像导出由 build_offline_delivery.py 负责，不该在 package.sh 里重复",
        )

    def test_no_build_flag_is_not_used(self) -> None:
        """禁止 --no-build：会复用带 v0.3.2 元数据的开发镜像导致 identity 门禁 FAIL。"""
        text = self._text()
        self.assertNotIn(
            "--no-build", text,
            "package.sh 不得使用 --no-build（会复用开发镜像，identity 门禁必 FAIL）",
        )

    def test_reset_hard_requires_confirmation(self) -> None:
        """破坏性操作必须确认，未确认则不改任何东西。"""
        text = self._text()
        self.assertIn("git reset --hard", text)
        self.assertIn("confirm ", text, "reset --hard 前必须交互确认")
        self.assertIn("已取消", text, "未确认时必须明确告知已取消且未做修改")

    def test_missing_baseline_image_is_reported_not_downloaded(self) -> None:
        """Q5 同源纪律：缺基线镜像必须提示，绝不自动联网下载。"""
        text = self._text()
        self.assertIn("已发布", text, "必须说明基线镜像是已发布产物")
        self.assertIn("--skip-offline", text, "必须提供跳过路径")
        for forbidden in ("curl -", "wget ", "docker pull"):
            self.assertNotIn(
                forbidden, text, f"package.sh 不得自动下载/拉取镜像（发现 {forbidden}）"
            )


class CliShellPitfallTest(unittest.TestCase):
    """锁住两个已实测踩到的 shell 陷阱（macOS/精简环境会复现）。"""

    def test_no_variable_glued_to_non_ascii(self) -> None:
        """`$VAR` 紧跟全角字符会被 shell 并入变量名 → `unbound variable` 且退出码退成 1。

        实测：`ok "git 仓库（$root）"` 使 bash 解析成变量 `root）`，
        在 set -u 下直接中断，脚本退成 exit 1 而不是约定的 exit 2。
        """
        pattern = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]")
        for script in sorted(CLI.rglob("*.sh")):
            text = script.read_text(encoding="utf-8")
            bad = [
                f"{i}: {line.strip()[:80]}"
                for i, line in enumerate(text.splitlines(), 1)
                if pattern.search(line)
            ]
            self.assertEqual(
                bad, [], f"{script.relative_to(ROOT)} 存在变量与全角字符粘连：{bad}"
            )

    def test_no_gnu_only_df_flags(self) -> None:
        """`df -BG` / `sort -V` 是 GNU 专有，BSD 与精简环境不支持 → 脚本会静默失效。"""
        for script in sorted(CLI.rglob("*.sh")):
            # 只看可执行代码行：注释里说明"为什么不用它"不算使用
            code_lines = [
                line for line in script.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            ]
            body = "\n".join(code_lines)
            for forbidden in ("df -BG", "sort -V", "--output=avail"):
                self.assertNotIn(
                    forbidden, body,
                    f"{script.relative_to(ROOT)} 用了 GNU 专有选项 {forbidden}（BSD/精简环境会失败）",
                )

    def test_exit_code_is_2_not_1_on_missing_deps(self) -> None:
        """有 MISSING 时必须 exit 2（设计的约定码），不能是 1 或 0。"""
        with tempfile.TemporaryDirectory() as raw:
            empty = Path(raw) / "empty-bin"
            empty.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "NO_COLOR": "1", "PATH": f"{empty}:/usr/bin:/bin"}
            completed = subprocess.run(
                ["bash", str(CHECK_DEPS)], capture_output=True, env=env, check=False
            )
            self.assertEqual(
                completed.returncode, 2,
                f"期望 exit 2，实际 {completed.returncode}；"
                f"输出尾：{completed.stderr.decode('utf-8', errors='replace')[-200:]}",
            )

    def test_local_vars_are_preassigned(self) -> None:
        """`local x` 后立刻被命令赋值，命令失败会在 set -u 下崩；必须先赋空值。"""
        pattern = re.compile(r"^\s*local\s+[A-Za-z_][A-Za-z0-9_]*\s*$")
        for script in sorted(CLI.rglob("*.sh")):
            text = script.read_text(encoding="utf-8")
            bad = [
                f"{i}: {line.strip()}"
                for i, line in enumerate(text.splitlines(), 1)
                if pattern.match(line)
            ]
            self.assertEqual(
                bad, [], f"{script.relative_to(ROOT)} 存在未预赋值的 local：{bad}"
            )


if __name__ == "__main__":
    unittest.main()
