"""CloudTower API 版本矩阵文档 ↔ 版本画像表一致性门禁（#84）。

`docs/cloudtower-api-version-matrix.md` 是长期维护件（随 CloudTower 新版本更新），
同时是**本测试的夹具**：改了文档里的矩阵或画像表就必须同步 `profiles.py`，反之亦然。

解析范围（标记块之间）：

    <!-- API-MATRIX-TABLE-START ... -->

断言两条：
1. 每版一行表覆盖文档声明支持的版本区间（4.4.0+），且断点两侧取值正确
   （4.7.0+ 全 ✅；4.6.0 无扁平策略字段；4.5.0 无 used_size；4.4.x 无容量端点）；
2. 表里出现的每一档 floor 与 `profiles.py` 的画像逐字段一致（文档漂移即失败）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "cloudtower-api-version-matrix.md"
BLOCK_RE = re.compile(r"<!-- API-MATRIX-TABLE-START.*?-->(?P<body>.*?)<!-- API-MATRIX-TABLE-END", re.S)
ROW_RE = re.compile(r"^\|\s*([0-9]+\.[0-9]+\.[0-9]+)\s*\|(?P<cells>.+)\|\s*$", re.M)
FLAG = {"✅": True, "—": False}


def _parse_matrix(path: Path) -> dict[tuple[int, ...], tuple[bool, bool, bool, bool]]:
    text = path.read_text(encoding="utf-8")
    match = BLOCK_RE.search(text)
    if match is None:
        raise AssertionError("cloudtower-api-version-matrix.md 缺少 API-MATRIX-TABLE 标记块")
    table: dict[tuple[int, ...], tuple[bool, bool, bool, bool]] = {}
    for row in ROW_RE.finditer(match.group("body")):
        version = tuple(int(part) for part in row.group(1).split("."))
        cells = []
        for cell in row.group("cells").split("|"):
            token = cell.strip()
            if token == "":
                continue
            if token not in FLAG:
                raise AssertionError(f"{row.group(1)} 行出现未识别的取值：{token!r}")
            cells.append(FLAG[token])
        if len(cells) != 4:
            raise AssertionError(f"{row.group(1)} 行应有 4 列，实际 {len(cells)}")
        table[version] = tuple(cells)  # type: ignore[assignment]
    if not table:
        raise AssertionError("矩阵表为空")
    return table


class CloudTowerApiVersionMatrixTest(unittest.TestCase):
    def test_document_matrix_matches_profile_table(self) -> None:
        from app.v2.cloudtower import profiles

        table = _parse_matrix(DOC_PATH)

        # ② 文档里每个断点值必须与画像表逐字段一致（画像按 floor 向下取）
        for version, (capacity, policy_fields, volume_used, vm_used) in table.items():
            text = ".".join(str(part) for part in version)
            profile = profiles.profile_for_version(text)
            self.assertEqual(
                (capacity, policy_fields, volume_used, vm_used),
                (
                    profile.cluster_storage_info_endpoint,
                    profile.volume_flat_policy_fields,
                    profile.volume_used_size,
                    profile.vm_used_size,
                ),
                f"文档矩阵与 profiles.py 不一致：{text}",
            )

        # ① 断点两侧必须按实测结论取值（防止两边一起改错）
        self.assertTrue(all(table[(4, 9, 0)]), "最新版本应四项全支持")
        self.assertTrue(all(table[(4, 7, 0)]), "4.7.0 起卷扁平策略字段应可用")
        self.assertEqual(table[(4, 6, 0)][1], False, "4.6.0 无卷扁平策略字段")
        self.assertTrue(table[(4, 6, 0)][2], "4.6.0 起卷 used_size 可用")
        self.assertEqual(table[(4, 5, 0)], (True, False, False, False), "4.5.0：有容量端点、无 used_size")
        self.assertEqual(table[(4, 4, 1)][0], False, "4.4.x 无容量端点")
        self.assertEqual(table[(4, 4, 0)], (False, False, False, False), "4.4.0 四项全无（支持下限）")

        # 支持下限必须写明并至少覆盖 4.4.0
        self.assertIn((4, 4, 0), table, "矩阵必须覆盖支持下限 4.4.0")

    def test_document_lists_all_integrated_endpoints(self) -> None:
        """§1 清单必须列出我们实际调用的 6 个端点（新增对接端点时同步文档）。"""
        text = DOC_PATH.read_text(encoding="utf-8")
        for endpoint in (
            "/v2/api/login",
            "/v2/api/get-version",
            "/v2/api/get-clusters",
            "/v2/api/get-vms",
            "/v2/api/get-vm-volumes",
            "/v2/api/get-cluster-storage-info",
        ):
            self.assertIn(endpoint, text, f"矩阵文档缺少端点 {endpoint}")
