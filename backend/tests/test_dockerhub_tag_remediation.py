"""#88 DockerHub v0.5.1u2 tag 修复脚本门禁（2026-10-14）。

设计：docs/superpowers/specs/2026-10-14-dockerhub-v051u2-tag-remediation-design.md

锁死四件事：默认干跑、推送前必须校验 web-api /app/VERSION、推送需显式 --push、
凭据只走环境变量/stdin 不落代码。真机推送验证（T3）需用户凭据，不在自动测试范围。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fix_dockerhub_v051u2_tag.sh"
DESIGN = ROOT / "docs" / "superpowers" / "specs" / "2026-10-14-dockerhub-v051u2-tag-remediation-design.md"


class DockerHubTagRemediationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert SCRIPT.is_file(), f"修复脚本不存在：{SCRIPT}"
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_design_doc_exists(self):
        # 设计文档 2026-10-21 起不入公开仓库（仓库只放代码）；本地开发机上仍在时校验。
        if not DESIGN.is_file():
            self.skipTest("设计文档属内部记录，公开仓库不含")

    def test_default_is_dry_run(self):
        self.assertIn("PUSH=0", self.text, "默认必须是干跑")
        # 按行判定：干跑分支的 exit 0 必须出现在**实际推送命令**之前
        # （不能按字符串下标——usage/注释里也提到过 docker push）
        lines = self.text.splitlines()
        dry_run_line = next(i for i, line in enumerate(lines) if "干跑模式" in line)
        dry_exit = next(
            i for i in range(dry_run_line, len(lines)) if lines[i].strip() == "exit 0"
        )
        push_cmd = next(
            i for i, line in enumerate(lines) if line.strip().startswith("docker push")
        )
        self.assertLess(dry_exit, push_cmd, "干跑分支（exit 0）必须先于实际 docker push 命令")

    def test_push_requires_explicit_flag(self):
        self.assertIn("--push)", self.text)
        self.assertIn("[ \"$PUSH\" -eq 0 ]", self.text)

    def test_web_api_version_is_verified_before_push(self):
        lines = self.text.splitlines()
        verify = next(
            i
            for i, line in enumerate(lines)
            if "--entrypoint cat" in line and "/app/VERSION" in line
        )
        push_cmd = next(
            i for i, line in enumerate(lines) if line.strip().startswith("docker push")
        )
        self.assertLess(verify, push_cmd, "必须先校验 /app/VERSION 再推送")
        self.assertIn("拒绝打 tag/推送", self.text)

    def test_expected_version_is_pinned(self):
        self.assertIn('EXPECT_VERSION="v0.5.1u2"', self.text)

    def test_all_three_platform_images_are_handled(self):
        for name in ("web-api", "collector-worker", "frontend"):
            self.assertIn(name, self.text)

    def test_credentials_never_hardcoded(self):
        # 只允许环境变量/stdin，禁止字面凭据
        self.assertIn("--password-stdin", self.text)
        self.assertIn("DOCKERHUB_TOKEN", self.text)
        for bad in ("p@ssw0rd", "ghp_", "dckr_pat_"):
            self.assertNotIn(bad, self.text)

    def test_script_bash_syntax(self):
        import subprocess

        proc = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(proc.returncode, 0, f"bash 语法错误：{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
