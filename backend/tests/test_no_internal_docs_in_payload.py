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
            ("docs/deployment.zh-CN.md", False),
            ("scripts/verify_release_docs_safe.py", False),
        ]
        for rel, expected in cases:
            with self.subTest(rel=rel):
                self.assertEqual(self.builder._is_internal_doc(Path(rel)), expected, rel)

    def test_payload_excludes_internal_docs(self) -> None:
        files = self.builder.collect_project_files("v0.5.4", check_version_metadata=False)
        leaked = [f for f in files if self.builder._is_internal_doc(Path(f))]
        self.assertEqual(leaked, [], f"内部开发记录不得进包：{leaked}")

    def test_payload_ships_only_runtime_essentials(self) -> None:
        """升级包只带运行期必需的 project 文件，**一个 .md 都不带**（2026-10-21 用户令）。

        历史：曾是 `PROJECT_DIRS = ["docs", "scripts"]` → 182 个文件里 144 个 .md，
        运行期一个都不读；现场升级后 `project/docs/` 落 154 个文件纯属噪音，
        且内部交接文档（含测试机密码）随包分发。
        """
        files = self.builder.collect_project_files("v0.5.4", check_version_metadata=False)
        # `release-notes.md` 是**包内说明**（manifest `notes` 字段声明、升级中心展示位），
        # 属包语义而非开发记录；除此之外不得出现任何 .md。
        docs = [f for f in files if f.endswith(".md")]
        self.assertEqual(docs, [], f"project/ 载荷不得携带任何 .md 文档：{docs}")
        for required in (
            "docker-compose.offline.yml",
            "docker-compose.online.yml",
            "docker-compose.dev.yml",
            "prometheus/prometheus.yml",
            "pre_install.sh",
            "compose-guard.sh",
            "scripts/bind-mount-recover.sh",
            "scripts/verify_site_acceptance.sh",
        ):
            self.assertIn(required, files, f"运行期/运维必需文件缺失：{required}")
        self.assertLessEqual(len(files), 12, f"入包文件过多（疑似又收进了整个目录）：{len(files)}")

    def test_payload_secret_scan_rejects_credentials(self) -> None:
        """含明文凭据的文件进包时必须拒绝（直接测扫描函数，不依赖 docs/ 是否在清单里）。"""
        victim = ROOT / "scripts" / "LEAKPROBE-xyz.sh"
        # 用拼接构造，避免本测试文件自身触发凭据扫描（门禁扫全仓已跟踪文件）
        secret = "sshpass " + "-p " + "'RealSecret123' scp x y\n"
        victim.write_text(secret, encoding="utf-8")
        try:
            with self.assertRaises(SystemExit) as ctx:
                self.builder.assert_no_secret_in_payload(["scripts/LEAKPROBE-xyz.sh"])
            self.assertIn("硬凭据", str(ctx.exception))
        finally:
            victim.unlink(missing_ok=True)

    def test_payload_secret_scan_allows_clean_file(self) -> None:
        """正常运维脚本不应被误拦。"""
        self.builder.assert_no_secret_in_payload(list(self.builder.PROJECT_SCRIPTS))


if __name__ == "__main__":
    unittest.main()
