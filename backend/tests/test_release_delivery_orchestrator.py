"""49-56 补充：`build_release_delivery.sh` 编排器的静态与行为门禁。

动机：此前"从源码到可交付物"分散在 5 个脚本里，路径与顺序全靠人工记忆，
runner 交付一致性门禁就差点漏跑。本测试锁定链条完整性——**门禁不能被跳过**。
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ORCHESTRATOR = REPO_ROOT / "scripts" / "build_release_delivery.sh"


class OrchestratorContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(ORCHESTRATOR.is_file(), "缺少编排器 build_release_delivery.sh")
        self.text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.code = "\n".join(
            line for line in self.text.splitlines() if not line.strip().startswith("#")
        )

    def test_orchestrator_is_executable_and_valid(self) -> None:
        self.assertTrue(ORCHESTRATOR.stat().st_mode & 0o111, "编排器必须带可执行位")
        result = subprocess.run(["bash", "-n", str(ORCHESTRATOR)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_orchestrator_wires_every_step_in_order(self) -> None:
        """链条必须完整且有序，缺一步就会漏门禁。"""
        ordered = [
            "build_upgrade_package.py --check-version",
            "build_upgrade_package.py",
            "verify_upgrade_package_identity.py",
            "build_runner_component_package.py",
            "verify_runner_delivery_consistency.py",
            "build_offline_delivery.py",
        ]
        positions = []
        for step in ordered:
            index = self.code.find(step)
            self.assertNotEqual(index, -1, f"编排器缺少步骤：{step}")
            positions.append(index)
        self.assertEqual(positions, sorted(positions), f"步骤顺序不对：{ordered}")

    def test_every_gate_can_abort_the_build(self) -> None:
        """任一门禁失败都必须中止，绝不能继续产出"看起来完整"的交付物。

        注意：必须**逐行**判断"门禁调用后的同一逻辑块内出现 exit 1"。
        两种错法都实测过：
          · 用 `gate.*?exit 1` 跨行正则 → 会一路匹配到脚本后面别的 `exit 1`（假阳性）
          · 固定行数窗口（6/7 行）→ 多行 `|| { ... }` 块会被切断（仍假阳性）
        因此这里按"下一个 phase/if/fi 块结束前必须出现 exit 1"来判定。
        """
        lines = [line for line in self.text.splitlines() if not line.strip().startswith("#")]
        gates = (
            "build_upgrade_package.py --check-version",
            "verify_upgrade_package_identity.py",
            "verify_runner_delivery_consistency.py",
        )
        for gate in gates:
            hits = [i for i, line in enumerate(lines) if gate in line]
            self.assertTrue(hits, f"编排器缺少门禁调用：{gate}")
            for index in hits:
                # 从门禁调用行起，直到下一个 phase 标记或 15 行为止，
                # 这段就是该门禁的处理块；块内必须能中止
                window: list[str] = []
                for line in lines[index : index + 15]:
                    if window and line.strip().startswith("phase "):
                        break
                    window.append(line)
                self.assertIn(
                    "exit 1", "\n".join(window),
                    f"{gate}（第 {index + 1} 行）之后没有中止逻辑，"
                    "门禁失败仍会继续构建",
                )

    def test_uses_strict_mode_so_no_silent_failures(self) -> None:
        self.assertIn("set -Eeuo pipefail", self.text)

    def test_requires_runner_baseline_for_delivery(self) -> None:
        """交付物安装 compose 必须落**已发布** runner 基线，不能用源码开发线 tag。"""
        self.assertIn("runner-baseline", self.text)
        self.assertIn("已发布", self.text)
        # 缺基线时必须拒绝（而不是默认用仓库 RUNNER_VERSION）
        self.assertRegex(self.code, r"SKIP_DELIVERY.*-eq 0.*-z.*RUNNER_BASELINE")

    def test_supports_skip_and_reuse_paths(self) -> None:
        for option in ("--skip-delivery", "--platform-package", "--runner-package", "--reuse-images"):
            self.assertIn(option, self.text, f"缺少 {option}")

    def test_writes_sha256_manifest(self) -> None:
        """产物必须留下可登记的 SHA 清单。"""
        self.assertIn("sha256sum", self.code)
        self.assertIn("SHA256SUMS", self.text)
        self.assertIn("upgrade-package-ledger.md", self.text)

    def test_help_works(self) -> None:
        result = subprocess.run(
            ["bash", str(ORCHESTRATOR), "--help"], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0)
        for option in ("--runner-baseline", "--output-root", "--check-dockerhub"):
            self.assertIn(option, result.stdout)

    def test_rejects_unknown_option(self) -> None:
        result = subprocess.run(
            ["bash", str(ORCHESTRATOR), "--no-such-option"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未知选项", result.stdout + result.stderr)

    def test_refuses_delivery_without_runner_baseline(self) -> None:
        """不加 --runner-baseline 且未 --skip-delivery 时必须拒绝，而不是猜一个 tag。"""
        result = subprocess.run(
            ["bash", str(ORCHESTRATOR), "--output-root", "/tmp/should-not-be-used"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("runner-baseline", combined)
        # 不得在拒绝前就创建产物目录
        self.assertFalse(
            Path("/tmp/should-not-be-used").exists(),
            "参数校验失败时不得留下产物目录",
        )

    def test_skip_delivery_does_not_require_baseline(self) -> None:
        """--skip-delivery 是"只想出包"的正当路径，不该被基线校验拦住。"""
        result = subprocess.run(
            [
                "bash",
                str(ORCHESTRATOR),
                "--skip-delivery",
                "--platform-package",
                "/nonexistent-platform.tar.gz",
                "--runner-package",
                "/nonexistent-runner.tar.gz",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined = result.stdout + result.stderr
        # 应因"包不存在"而失败，而不是因缺 runner-baseline
        self.assertNotIn("必须显式指定 --runner-baseline", combined, combined)


class BuildGuideTest(unittest.TestCase):
    """发版构建手册必须与编排器实际行为一致（文档漂移是最常见的坑）。"""

    def _guide(self) -> str:
        path = REPO_ROOT / "docs" / "release-build-guide.md"
        self.assertTrue(path.is_file(), "缺少 docs/release-build-guide.md")
        return path.read_text(encoding="utf-8")

    def test_guide_is_registered_in_doc_map(self) -> None:
        doc_map = (REPO_ROOT / "docs" / "doc-map.md").read_text(encoding="utf-8")
        self.assertIn("release-build-guide.md", doc_map, "新文档必须登记到 docs/doc-map.md")

    def test_guide_references_the_real_orchestrator(self) -> None:
        guide = self._guide()
        self.assertIn("scripts/build_release_delivery.sh", guide)
        self.assertTrue(ORCHESTRATOR.is_file(), "手册引用的编排器必须真实存在")

    def test_guide_options_all_exist_in_orchestrator(self) -> None:
        """手册参数表里**属于编排器**的每个选项都必须在编排器里真实支持。

        只校验参数表（`## 3. 常用参数` 到下一个 `##` 之间），否则会误伤正文里
        提到的 git / 下游脚本参数。表里属于**交付脚本**（upgrade.sh 的 --with-runner
        等）不在此列——它们由 `test_offline_delivery_builder.py` 负责。
        """
        import re

        guide = self._guide()
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        section = guide.split("## 3. 常用参数", 1)[1].split("\n## ", 1)[0]
        options = set(re.findall(r"`?(--[a-z][a-z-]+)", section))
        self.assertTrue(options, "手册参数表为空，解析可能失效")
        # 交付脚本自己的参数（由 upgrade.sh 支持，不是构建编排器）
        deliver_only = {"--with-runner"}
        for option in sorted(options - deliver_only):
            self.assertIn(option, text, f"手册参数表列出 {option}，但编排器不支持——文档漂移")
        # 反向：编排器支持的选项也应在手册里出现
        for option in sorted(set(re.findall(r"^    (--[a-z][a-z-]+)\)", text, re.M))):
            self.assertIn(option, section, f"编排器支持 {option}，但手册参数表没写")

    def test_guide_covers_required_topics(self) -> None:
        guide = self._guide()
        for topic in ("前置条件", "一条命令", "runner-baseline", "改版本号", "常见问题"):
            self.assertIn(topic, guide, f"手册缺少：{topic}")

    def test_guide_explains_baseline_vs_version_distinction(self) -> None:
        """这两个参数最容易混，必须讲清。"""
        guide = self._guide()
        self.assertIn("--runner-baseline", guide)
        self.assertIn("--runner-version", guide)
        self.assertIn("已发布", guide)
        self.assertTrue(
            "不必相同" in guide or "通常也不相同" in guide,
            "必须说明两者不必相同",
        )

    def test_guide_states_commit_before_archive(self) -> None:
        """"先提交再 archive"是踩过的坑，手册必须写明。"""
        guide = self._guide()
        self.assertIn("git archive", guide)
        self.assertIn("先提交再 archive", guide)


if __name__ == "__main__":
    unittest.main()
