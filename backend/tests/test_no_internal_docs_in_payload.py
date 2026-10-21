"""打包内容门禁：本地开发记录不得进升级包 + 包内不得含硬凭据。

**背景（2026-10-21 事故）**：已发布的 v0.5.4 平台包 `project/docs/` 里带着
`ai-handoff-2026-10-12.md`，其中含 `.3` 测试机明文密码——随 GitHub Release 资产对公众分发。
根因：`PROJECT_DIRS = ["docs", "scripts"]` 把**整个 docs/** 打进包，而当时的脱敏门禁
只扫 13 个公开文档白名单，这两类文件都不在范围。

本测试锁住两道防线：
1. `_is_internal_doc()` 能识别内部记录（progress/findings/task_plan/ai-handoff/test-handover/
   release-verification/archive 流水）；
2. `collect_project_files()` 的产物里不含内部记录，且 `assert_no_secret_in_payload()`
   对含密码的文件会拒绝打包。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "scripts" / "build_upgrade_package.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_upgrade_package_no_internal", BUILDER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    old_argv = sys.argv
    sys.argv = ["build_upgrade_package"]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = old_argv
    return module


class PackagePayloadHygieneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.builder = _load_builder()

    def test_internal_doc_detection(self) -> None:
        cases = [
            ("progress.md", True),
            ("findings.md", True),
            ("task_plan.md", True),
            ("docs/ai-handoff-2026-10-12.md", True),
            ("docs/ai-handoff-guide.md", True),
            ("docs/test-handover-20261019.md", True),
            ("docs/releases/release-verification-v0.5.4.md", True),
            ("docs/archive/progress-2026-07.md", True),
            # 客户可见文档不得被误排除
            ("docs/releases/CHANGELOG.md", False),
            ("docs/api.md", False),
            ("docs/deployment.md", False),
            ("scripts/verify_release_docs_safe.py", False),
        ]
        for rel, expected in cases:
            with self.subTest(rel=rel):
                self.assertEqual(self.builder._is_internal_doc(Path(rel)), expected, rel)

    def test_payload_excludes_internal_docs(self) -> None:
        files = self.builder.collect_project_files("v0.5.4", check_version_metadata=False)
        leaked = [f for f in files if self.builder._is_internal_doc(Path(f))]
        self.assertEqual(leaked, [], f"内部开发记录不得进包：{leaked}")

    def test_payload_still_ships_customer_docs(self) -> None:
        files = self.builder.collect_project_files("v0.5.4", check_version_metadata=False)
        for required in ("docs/releases/CHANGELOG.md", "docs/api.md", "docs/deployment.md"):
            self.assertIn(required, files, f"客户可见文档不得被误排除：{required}")

    def test_payload_secret_scan_rejects_credentials(self) -> None:
        """含明文凭据的文件进包时必须拒绝（文件名避开敏感路径规则，专测内容扫描）。"""
        victim = ROOT / "docs" / "LEAKPROBE-xyz.md"
        victim.write_text("sshpass -p 'RealSecret123' scp x y\n", encoding="utf-8")
        try:
            with self.assertRaises(SystemExit) as ctx:
                self.builder.collect_project_files("v0.5.4", check_version_metadata=False)
            self.assertIn("硬凭据", str(ctx.exception))
        finally:
            victim.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
