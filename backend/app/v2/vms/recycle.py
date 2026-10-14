"""回收站 VM 的**权威判据**（#36/#37 ②）。

口径（2026-10-14 定）：
- 权威来源 = `vm_latest.in_recycle_bin`（采集侧 49-47 写入，`.3` 实测与名字前缀一致）；
- 名字前缀 `in-recycle-bin-<uuid>` **仅作兜底**（兼容历史行、Tower 改名约定变化前的数据）；
- 所有展示/统计过滤都走本模块，**不要各处再写一套前缀判定**——
  这正是 #37 要收掉的"两套实现"（series 路径曾只用前缀，与展示层的标记口径不一致）。

注意：本模块只回答"哪些 VM 在回收站"，**不改变任何统计口径**
（已使用/已分配/容量预测仍含回收站，用户 2026-10-03 口径，见 pending #75/#77）。
"""

from __future__ import annotations

from typing import Any

from app.v2.cloudtower.client import RECYCLE_BIN_VM_PREFIX

RecycledVmKey = tuple[int, str, str]


def is_recycled_row(name: Any, in_recycle_bin: Any) -> bool:
    """单行判据：权威标记优先，名字前缀兜底。"""
    if int(in_recycle_bin or 0):
        return True
    return str(name or "").startswith(RECYCLE_BIN_VM_PREFIX)


def recycled_vm_keys(database: Any) -> set[RecycledVmKey]:
    """当前处于回收站的 VM 三元组集合 `(tower_id, cluster_id, vm_id)`。

    读取失败返回空集（展示/统计不应因探测失败而报错；此时退化为"不额外过滤"，
    与旧行为一致——名字前缀判定在各调用点仍保留为兜底）。
    """
    try:
        with database.connection() as conn:
            rows = conn.execute(
                "SELECT tower_id, cluster_id, vm_id, name, in_recycle_bin FROM vm_latest"
            ).fetchall()
    except Exception:  # noqa: BLE001 - 探测失败不应让列表/报表整体报错
        return set()
    keys: set[RecycledVmKey] = set()
    for row in rows:
        if is_recycled_row(row["name"], row["in_recycle_bin"]):
            keys.add((int(row["tower_id"]), str(row["cluster_id"]), str(row["vm_id"])))
    return keys


def is_recycled_key(key: Any, recycled_keys: set[RecycledVmKey] | None) -> bool:
    """按三元组判回收站（`recycled_keys=None` ⇒ 视为"未提供"，返回 False）。"""
    if not recycled_keys or key is None:
        return False
    try:
        return tuple(key) in recycled_keys
    except TypeError:
        return False
