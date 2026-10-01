"""upgrade.sh 包路径解析门禁（2026-09-30 `.14` 实测修）。

背景：交付包 `README.md` 与 `usage` 里写的是相对路径
    bash upgrade/upgrade.sh --with-runner packages/smartx-upgrade-runner-v0.3.2.tar.gz
该相对路径原本按**调用者当前目录**解析，于是只有「恰好 cd 到 upgrade/」时成立。
在别的目录调用（`/root`、`/tmp`、运维随手敲的绝对路径场景）时报
「runner 组件包不存在，跳过：…」——**照文档做却静默不升级**，属最难查的一类问题。

本测试真实执行 upgrade.sh 的参数解析段，验证三种调用位置下都能定位到同一个包。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPGRADE = ROOT / "delivery" / "upgrade" / "upgrade.sh"
RUNNER_TAR = "smartx-upgrade-runner-v0.3.2.tar.gz"
PLATFORM_TAR = "smartx-capacity-insight-upgrade-v0.5.3.tar.gz"


class PathNormalisationSourceTest(unittest.TestCase):
    """静态门禁：归一化必须发生在「使用之前」，且两种包都覆盖。"""

    def setUp(self) -> None:
        self.text = UPGRADE.read_text(encoding="utf-8")

    def test_both_packages_are_normalised(self) -> None:
        for var in ("PACKAGE", "RUNNER_PACKAGE"):
            self.assertRegex(
                self.text,
                rf'{var}="\$\(_normalize_pkg_path "\${var}"\)"',
                f"{var} 必须走 _normalize_pkg_path 归一化"
                "（.14 实测：照文档调用却静默跳过）",
            )

    def test_candidate_order_puts_script_dir_first(self) -> None:
        """候选顺序：脚本同级 → 交付根 → 调用者 cwd。

        顺序不能反：README 的标准写法是 `packages/...`（相对脚本目录），
        旧写法是 `upgrade/packages/...`（相对交付根），两者都要能用。
        """
        m = re.search(r'_normalize_pkg_path\(\) \{(.*?)\n\}', self.text, re.S)
        self.assertIsNotNone(m, "未找到 _normalize_pkg_path 定义")
        body = m.group(1)
        # 按整行匹配，避免 '"$_np_in"' 命中 '"$SCRIPT_DIR/$_np_in"' 的尾部
        order = [
            '"$SCRIPT_DIR/$_np_in"',
            '"$SCRIPT_DIR/../$_np_in"',
            '"$_np_in"',
        ]
        # 候选写在 for 列表里，行尾带续行反斜杠（"..."\），要剥掉再比对
        probe_lines = [
            ln.strip().rstrip(chr(92)).strip().removesuffix("; do").strip().removesuffix(";").strip()
            for ln in body.splitlines()
        ]
        positions = []
        for token in order:
            self.assertIn(token, probe_lines, f"候选缺少 {token}")
            positions.append(probe_lines.index(token))
        self.assertEqual(
            positions, sorted(positions),
            f"候选顺序必须脚本同级优先，实际顺序 {positions}",
        )

    def test_normalisation_precedes_use(self) -> None:
        """归一化必须早于 `[ -f ]` 判定与上传，否则修了也不生效。"""
        norm = self.text.index('_normalize_pkg_path()')
        first_use = self.text.index('[ ! -f "$RUNNER_PACKAGE" ]')
        self.assertLess(norm, first_use, "路径归一化必须早于文件存在性判定")

    def test_absolute_paths_untouched(self) -> None:
        """绝对路径必须原样保留，不能被拼上 SCRIPT_DIR。"""
        self.assertRegex(
            self.text,
            r'/\*\)\s*printf\s+.*?return 0',
            "必须有 /* 分支让绝对路径原样通过",
        )


class PathResolutionBehaviourTest(unittest.TestCase):
    """行为门禁：在不同调用目录下，参数解析得到同一个绝对路径。

    只跑 upgrade.sh 的参数解析段（到「前置检查」之前），不碰网络与 API。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.upgrade_dir = Path(self.tmp.name) / "offline-delivery" / "upgrade"
        (self.upgrade_dir / "packages").mkdir(parents=True)
        self.script = self.upgrade_dir / "upgrade.sh"
        shutil.copy2(UPGRADE, self.script)
        # 造出两个真实的包文件
        (self.upgrade_dir / "packages" / RUNNER_TAR).write_bytes(b"x")
        (self.upgrade_dir / "packages" / PLATFORM_TAR).write_bytes(b"x")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _normalize(self, arg: str, cwd: Path) -> str:
        """在 cwd 下执行真实的 _normalize_pkg_path，返回归一化结果。

        直接抽出该函数执行，而不是截断整个脚本——截断要跨越 usage() 的
        heredoc、守卫加载的 if/fi 等多处结构边界，切在哪一头都会留下
        未闭合结构而报语法错误。函数本身是纯路径计算、无副作用，
        单独执行与在脚本里执行等价。
        """
        lines = UPGRADE.read_text(encoding="utf-8").splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.startswith("_normalize_pkg_path()"))
        end = next(i for i, ln in enumerate(lines[start + 1 :], start + 1) if ln == "}")
        func = "\n".join(lines[start:end + 1])
        probe = self.upgrade_dir / "_probe_norm.sh"
        probe.write_text(
            f'SCRIPT_DIR="{self.upgrade_dir}"\n{func}\n'
            f'_normalize_pkg_path "$1"\n',
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["bash", str(probe), arg],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(cwd),
        )
        self.assertEqual(completed.returncode, 0, f"归一化失败：{completed.stderr}")
        return completed.stdout.strip()

    def test_relative_arg_resolves_against_script_dir(self) -> None:
        """从任意目录调用，相对路径都应解析到脚本同级的 packages/。"""
        expected = str(self.upgrade_dir / "packages" / RUNNER_TAR)
        for cwd in (self.upgrade_dir, self.upgrade_dir.parent, Path("/")):
            with self.subTest(cwd=cwd):
                got = self._normalize(f"packages/{RUNNER_TAR}", cwd)
                self.assertEqual(
                    got, expected,
                    f"从 {cwd} 调用应解析到 {expected}，实际 {got}",
                )

    def test_legacy_upgrade_prefixed_form_still_works(self) -> None:
        """旧 README 写法 `upgrade/packages/...`（相对交付根）仍要能用。"""
        delivery_root = self.upgrade_dir.parent
        expected = str(self.upgrade_dir / "packages" / RUNNER_TAR)
        got = self._normalize(f"upgrade/{'packages'}/{RUNNER_TAR}", Path("/"))
        self.assertEqual(
            got, expected,
            "旧写法 upgrade/packages/... 应解析到同一个包（文档历史写法不能失效）",
        )

    def test_absolute_arg_unchanged(self) -> None:
        absolute = "/opt/custom/my-runner.tar.gz"
        got = self._normalize(absolute, Path("/"))
        self.assertEqual(got, absolute, "绝对路径必须原样保留")


class DocumentedCommandMatchesBehaviourTest(unittest.TestCase):
    """文档里给的示例命令必须真能工作（文档与实现不许脱节）。"""

    def setUp(self) -> None:
        self.readme = (ROOT / "delivery" / "README.md").read_text(encoding="utf-8")

    def test_readme_example_is_a_supported_relative_form(self) -> None:
        """README 给的相对写法必须是归一化支持的两种之一。"""
        examples = [
            m.group(1) for m in re.finditer(r"--with-runner\s+(\S+)", self.readme)
            if not m.group(1).startswith("<")
        ]
        self.assertTrue(examples, "README 应给出 --with-runner 示例")
        arg = examples[0]
        self.assertTrue(
            arg.startswith("packages/") or arg.startswith("upgrade/packages/"),
            f"README 示例应为受支持的相对写法，实际 {arg}",
        )

    def test_script_usage_shows_same_form(self) -> None:
        text = UPGRADE.read_text(encoding="utf-8")
        # 跳过参数说明里的占位符 `<组件包>`，只取真实示例行
        examples = [
            m.group(1) for m in re.finditer(r"--with-runner\s+(\S+)", text)
            if not m.group(1).startswith("<")
        ]
        self.assertTrue(examples, "usage 里应给出 --with-runner 的真实示例")
        arg = examples[0]
        self.assertTrue(
            arg.startswith("packages/") or arg.startswith("upgrade/packages/"),
            f"usage 示例应为受支持的相对写法，实际 {arg}",
        )


if __name__ == "__main__":
    unittest.main()