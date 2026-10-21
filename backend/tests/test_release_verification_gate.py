"""内部发布验证记录门禁（`scripts/verify_release_verification.py`）的回归锁。

分工（用户 2026-10-21）：`CHANGELOG.md` 面向使用者（只写修复/新增/优化/已知问题）；
包 SHA、任务 ID、验证机器等内部细节写在 `docs/releases/release-verification-<版本>.md`。
这里锁住内部记录的**灵敏度**——包换了轮次而内部记录没跟、或证据缺失，必须 FAIL。
"""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "scripts" / "verify_release_verification.py"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DOC = ROOT / "docs" / "releases" / f"release-verification-{VERSION}.md"


def _load_gate():
    spec = importlib.util.spec_from_file_location("verify_release_verification", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ReleaseVerificationGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 内部验证记录 2026-10-21 起不入公开仓库（仓库只放代码）；
        # 本地开发机上仍在时跑完整回归，干净 clone 下跳过。
        if not DOC.is_file():
            raise unittest.SkipTest(f"{DOC.name} 属内部记录，公开仓库不含")
        cls.gate = _load_gate()
        cls.original = DOC.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        DOC.write_text(self.original, encoding="utf-8")

    def _failed(self, text: str) -> set[str]:
        """把文本写进真实路径后跑门禁（门禁按固定路径读取）。"""
        DOC.write_text(text, encoding="utf-8")
        import subprocess

        result = subprocess.run(
            ["python3", str(GATE_PATH), "--version", VERSION, "--json"],
            cwd=ROOT, capture_output=True, text=True,
        )
        import json

        payload = json.loads(result.stdout)
        return {c["name"] for c in payload["checks"] if not c["ok"]}

    def test_current_doc_passes(self) -> None:
        self.assertEqual(self._failed(self.original), set())

    def test_detects_stale_platform_sha(self) -> None:
        """包换了轮次而内部记录没跟（历史真实问题）。"""
        sha = re.search(r"`([0-9a-f]{64})`", self.original)
        self.assertIsNotNone(sha, "夹具失效：文档里没有 SHA")
        mutated = self.original.replace(sha.group(1), "0" * 64, 1)
        self.assertIn("platform_sha_matches_ledger", self._failed(mutated))

    def test_detects_missing_task_ids(self) -> None:
        """缺升级任务 ID → 无法复核。"""
        mutated = re.sub(r"upgrade-[0-9a-f]{8,}", "TASK", self.original)
        self.assertIn("task_ids_present", self._failed(mutated))

    def test_detects_missing_data_comparison(self) -> None:
        """缺数据比对结果（N PASS）。"""
        mutated = re.sub(r"\d+\s*PASS", "通过", self.original)
        self.assertIn("data_comparison_present", self._failed(mutated))

    def test_detects_missing_runner_sha(self) -> None:
        """缺 runner 组件包 SHA（把该行 SHA 挖掉）。"""
        mutated = re.sub(
            r"(runner 组件包[^\n]*`)[0-9a-f]{64}(`)",
            r"\1(未记录)\2",
            self.original,
        )
        self.assertNotEqual(mutated, self.original, "夹具失效：未找到 runner 组件包 SHA 行")
        self.assertIn("runner_sha_present", self._failed(mutated))

    def test_detects_missing_release_status(self) -> None:
        """未写明发布状态。"""
        mutated = re.sub(r"未发布|已发布", "待定", self.original)
        self.assertIn("release_status_stated", self._failed(mutated))

    def test_gate_is_wired_into_release_script(self) -> None:
        script = (ROOT / "scripts" / "build_release_delivery.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/verify_release_verification.py", script)


if __name__ == "__main__":
    unittest.main()
