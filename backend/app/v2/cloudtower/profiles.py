"""Tower（CloudTower）API 版本画像：按平台版本选择不同的 API 行为（#84）。

**证据来源**：官方文档站按版本发布的 OpenAPI 规范
（`https://code-site.smartx.com/specs/<version>-swagger.json`），
用 `scripts/probe_cloudtower_api_versions.py --all` 生成差异矩阵（2026-10-07 实测，
只覆盖 4.4.0+，见下）。矩阵结论：

| 差异 | 版本边界 | 应对 |
| --- | --- | --- |
| `get-cluster-storage-info` 端点 | 4.5.0+ 有；4.4.x **无** | 4.4.x 从 `get-clusters` 的 `Cluster.used_data_space/total_data_capacity` 取容量 |
| 卷扁平字段 `elf_storage_policy_replica_num/_thin_provision/_ec_k/_ec_m` | 4.7.0+ 有；≤4.6 **无** | 无则按策略串推导（`REPLICA_2_THIN_PROVISION` → 2 副本 / 精简） |
| `Vm.used_size` / `VmVolume.used_size` | 4.6.0+ 有；≤4.5 **无** | 无则按「未上报」处理（None → 页面显示 `-`），不得当 0 参与增长计算 |
| `GET /v2/api/get-version` | 4.4.0+ 全有 | 版本探测本身在支持面内始终可用 |

**运行时规则**（本模块只做「版本 → 画像」的纯函数选择，不含 I/O）：
1. 版本可解析 → 取该版本对应的画像；
2. 版本未知（塔不可达/尚未采集/字符串不可解析）→ **最新画像**，并由调用方
   叠加「字段探测兜底」（端点失败/字段缺失时走旧形态路径），保证不会因为读不到
   版本而退化成不可用；
3. 低于支持下限（4.4.0）不阻断，只按 4.4.0 画像处理（顺带留日志给运维排查）。

实测旁证（2026-10-07）：`.3` 可达测试塔 = v4.5.0，其卷响应确实**没有**扁平副本字段
（与「4.7.0+ 才有」一致）；生产塔返回扁平字段 → 预测其平台版本 ≥ 4.7.0（塔可达后可用
`GET /v2/api/get-version` 验证）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 支持下限（2026-10-07 用户口径：按版本选 API 只需管 4.4.0 及以上）。
MIN_SUPPORTED_VERSION = (4, 4, 0)

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(value: str | None) -> tuple[int, ...] | None:
    """把 `v4.5.0` / `4.5` / `4` 解析成可比较元组；解析不出返回 None。"""
    if not value:
        return None
    match = _VERSION_RE.search(str(value).strip())
    if not match:
        return None
    parts = [int(part) for part in match.groups() if part is not None]
    return tuple(parts) if parts else None


@dataclass(frozen=True)
class ApiProfile:
    """一个版本区间的 API 行为画像（@dataclass 冻结，便于测试与比较）。"""

    #: 版本下限（含），用于表格排序与诊断输出
    version_floor: tuple[int, ...]
    #: `POST /v2/api/get-cluster-storage-info` 是否可用（4.4.x 没有 → 用集群记录容量兜底）
    cluster_storage_info_endpoint: bool
    #: 卷是否返回扁平策略字段 `elf_storage_policy_replica_num/_thin_provision/_ec_k/_ec_m`（4.7.0+）
    volume_flat_policy_fields: bool
    #: 卷是否返回 `used_size`（4.6.0+）
    volume_used_size: bool
    #: VM 是否返回 `used_size`（4.6.0+）
    vm_used_size: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "version_floor": ".".join(str(part) for part in self.version_floor),
            "cluster_storage_info_endpoint": self.cluster_storage_info_endpoint,
            "volume_flat_policy_fields": self.volume_flat_policy_fields,
            "volume_used_size": self.volume_used_size,
            "vm_used_size": self.vm_used_size,
        }


#: 版本画像表：按 version_floor 从新到旧排列，取第一个 `version >= floor` 的画像。
PROFILES: tuple[ApiProfile, ...] = (
    ApiProfile((4, 7, 0), cluster_storage_info_endpoint=True, volume_flat_policy_fields=True, volume_used_size=True, vm_used_size=True),
    ApiProfile((4, 6, 0), cluster_storage_info_endpoint=True, volume_flat_policy_fields=False, volume_used_size=True, vm_used_size=True),
    ApiProfile((4, 5, 0), cluster_storage_info_endpoint=True, volume_flat_policy_fields=False, volume_used_size=False, vm_used_size=False),
    ApiProfile(MIN_SUPPORTED_VERSION, cluster_storage_info_endpoint=False, volume_flat_policy_fields=False, volume_used_size=False, vm_used_size=False),
)

#: 版本未知时使用（最新画像 + 调用方的字段探测兜底）
NEWEST_PROFILE = PROFILES[0]


def profile_for_version(version: str | None) -> ApiProfile:
    """按平台版本选择画像；未知/放不下/低于下限一律回退（见模块 docstring 规则 2、3）。"""
    parsed = parse_version(version)
    if parsed is None:
        return NEWEST_PROFILE
    for profile in PROFILES:
        if parsed >= profile.version_floor:
            return profile
    return PROFILES[-1]
