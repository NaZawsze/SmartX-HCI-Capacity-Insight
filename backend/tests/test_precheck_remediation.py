"""B3：precheck 的 remediation（拒绝必须带出路）。

口径（impl-spec §W6.1 + upgrade-chain.md §7.1）：
v0.5.4 只支持目标布局，≤v0.5.1u2 的源被拒绝时必须告诉客户**怎么走**：
「v0.5.4 不支持 ≤v0.5.1u2 源；请先升级 v0.5.3（链路已验证）再升 v0.5.4」。

两处落点：
1. 检查项的结构化字段 `remediation`（只在**失败**时出现）；
2. 该检查的 `message` 文案本身（前端老版本/纯文本场景也看得到）。

文案**由包携带**（`manifest.source_compatibility.remediation`，打包侧按实际支持矩阵生成），
precheck 只透传——不在后端写死版本号，否则文案会与包的真实支持范围脱节。
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(REPO_ROOT / "backend")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from app.v2.upgrade.service.precheck import _check_source_compatibility  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_upgrade_package", REPO_ROOT / "scripts" / "build_upgrade_package.py")
assert _spec and _spec.loader
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)

TARGET = "v0.5.4"
#: 用户 2026-10-06 定稿的那句，逐字断言。
APPROVED_REMEDIATION = "v0.5.4 不支持 ≤v0.5.1u2 源；请先升级 v0.5.3（链路已验证）再升 v0.5.4"


def _manifest_v054() -> dict[str, Any]:
    compatibility = _builder._source_compatibility(min_version="v0.5.0", target_version=TARGET)
    return {"version": TARGET, "source_compatibility": compatibility}


class PackagingEmitsRemediationTests(unittest.TestCase):
    """打包侧：文案跟着包走，且与实际支持矩阵一致。"""

    def test_remediation_text_is_the_approved_wording(self) -> None:
        self.assertEqual(
            _builder._source_remediation(min_version="v0.5.2", target_version=TARGET),
            APPROVED_REMEDIATION,
        )

    def test_source_compatibility_carries_remediation(self) -> None:
        payload = _builder._source_compatibility(min_version="v0.5.0", target_version=TARGET)
        self.assertEqual(payload["remediation"], APPROVED_REMEDIATION)

    def test_targets_that_still_support_legacy_carry_no_remediation(self) -> None:
        """v0.5.3 及更早仍支持 v0.5.0–v0.5.1u2 直升，不该出现引导文案。"""
        for target in ("v0.5.2", "v0.5.3"):
            self.assertEqual(_builder._source_remediation(min_version="v0.5.0", target_version=target), "")
            self.assertNotIn("remediation", _builder._source_compatibility(min_version="v0.5.0", target_version=target))

    def test_rejected_bound_tracks_the_actual_matrix(self) -> None:
        """被拒范围必须等于「布局下限之前最高的源版本」，不能写死。"""
        legacy = [
            version
            for version in _builder._supported_source_versions("v0.5.0", _builder.MINIMUM_SOURCE_VERSION)
            if version.startswith("v0.5.0")
            or version.startswith("v0.5.1")
        ]
        self.assertIn("v0.5.1u2", legacy)
        self.assertTrue(APPROVED_REMEDIATION.startswith(f"{TARGET} 不支持 ≤{max(legacy)} 源"))


class PrecheckSurfacesRemediationTests(unittest.TestCase):
    """precheck 侧：结构化字段 + message 文案两处都落。"""

    def test_blocked_source_gets_field_and_message(self) -> None:
        for source in ("v0.5.1u2", "v0.5.1u1", "v0.5.1", "v0.5.0"):
            with self.subTest(source=source):
                check = _check_source_compatibility(_manifest_v054(), source)
                self.assertFalse(check["ok"], source)
                self.assertEqual(check["remediation"], APPROVED_REMEDIATION)
                self.assertIn(APPROVED_REMEDIATION, check["message"])

    def test_supported_source_has_no_remediation_field(self) -> None:
        """通过的检查挂引导会变成噪音，也会让前端分不清提醒与错误。"""
        for source in ("v0.5.2", "v0.5.3", TARGET):
            with self.subTest(source=source):
                check = _check_source_compatibility(_manifest_v054(), source)
                self.assertTrue(check["ok"], source)
                self.assertIsNone(check.get("remediation"))
                self.assertNotIn(APPROVED_REMEDIATION, check["message"])

    def test_legacy_package_without_remediation_still_gets_a_next_step(self) -> None:
        """老包（无 remediation 字段）也要给下一步，不能只说"不支持"。"""
        legacy_manifest = {
            "version": "v0.5.3",
            "source_compatibility": {"min_version": "v0.5.0", "max_version_inclusive": "v0.5.3"},
        }
        check = _check_source_compatibility(legacy_manifest, "v0.5.9")
        self.assertFalse(check["ok"])
        self.assertTrue(check["remediation"])
        self.assertIn("请先升级", check["message"])
        self.assertIn("v0.5.0", check["remediation"])

    def test_message_keeps_the_range_fact_before_the_remediation(self) -> None:
        check = _check_source_compatibility(_manifest_v054(), "v0.5.1u2")
        self.assertTrue(check["message"].startswith("当前版本 v0.5.1u2 不在升级包兼容范围"))
        self.assertIn("v0.5.2 至 v0.5.4", check["message"])

    def test_check_shape_keeps_name_ok_message_detail(self) -> None:
        """结构化字段是**新增**，不改动既有键——老前端不受影响。"""
        check = _check_source_compatibility(_manifest_v054(), "v0.5.1u2")
        for key in ("name", "ok", "message", "detail"):
            self.assertIn(key, check)
        self.assertEqual(check["name"], "source_compatibility")
        self.assertEqual(check["detail"]["supported_versions"], ["v0.5.2", "v0.5.3", TARGET])


if __name__ == "__main__":
    unittest.main()