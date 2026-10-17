#!/usr/bin/env python3
"""标准测试数据集生成（**仅验证机**，见 docs/test-architecture.md §6）。

为什么要有：每次链路测试"随手 seed"会导致两轮结果不可比，且永远测不到编码/回收站/边界值。
本脚本按固定画像生成**确定性**数据（固定随机种子），两轮之间可直接比指纹。

画像：
- ≥2 塔、≥3 集群、120 VM、240 卷（可参数化）；
- 名字含**中文、空格、emoji**（编码损坏只能靠它暴露）；
- ≥3 台回收站 VM（`in_recycle_bin=1` + `in-recycle-bin-` 前缀 + `original_name`）；
- `local_created_at` 覆盖「本日 / 本月 / 历史 / 缺失」四段（#36/#37 回落口径）；
- 边界值：`used_bytes=0`、超大值（8 TiB）；
- **不造孤儿行**（引用完整性要求 0 孤儿）。

⚠️ 会写业务表：必须显式 `--db` 与 `--yes`；禁止对生产库执行。
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20261017
BIG_BYTES = 8 * 1024 ** 4


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def insert(conn: sqlite3.Connection, table: str, values: dict) -> None:
    have = table_columns(conn, table) & set(values)
    keys = sorted(have)
    if not keys:
        return
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
        [values[key] for key in keys],
    )


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def seed(
    db: Path,
    *,
    vms: int = 120,
    volumes_per_vm: int = 2,
    towers: int = 2,
    clusters: int = 3,
    recycle: int = 3,
) -> dict:
    rng = random.Random(SEED)
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(db)
    try:
        for index in range(1, towers + 1):
            insert(
                conn,
                "towers",
                {
                    "id": index,
                    "name": f"测试塔 {index:02d}",
                    "base_url": f"https://tower{index}.test.local",
                    "enabled": 1,
                    "collection_hour": 2,
                    "collection_minute": 10,
                    "created_at": iso(now - timedelta(days=400)),
                    "updated_at": iso(now),
                },
            )
        for index in range(1, clusters + 1):
            insert(
                conn,
                "clusters",
                {
                    "tower_id": (index - 1) % towers + 1,
                    "cluster_id": f"cluster-{index:02d}",
                    "name": f"集群 {index:02d}",
                    "enabled": 1,
                    "updated_at": iso(now),
                },
            )

        for index in range(vms):
            vm_id = f"e2e-vm-{index:03d}"
            cluster = f"cluster-{index % clusters + 1:02d}"
            tower = (index % clusters) % towers + 1
            # 字符集：中文 + 空格 + emoji（编码损坏只能靠它暴露）
            if index % 10 == 0:
                name = f"虚拟机 {index:03d} 🚀"
            else:
                name = f"vm-{index:03d} 测试 卷"
            if index == 5:
                used = 0                     # 边界：0
            elif index == 7:
                used = BIG_BYTES             # 边界：超大
            else:
                used = 1000 + rng.randint(0, 10_000)
            # 创建时间四段：本日 / 本月 / 历史 / 缺失（#36/#37 回落口径）
            if index % 4 == 0:
                created = iso(now - timedelta(hours=2))
            elif index % 4 == 1:
                created = iso(now - timedelta(days=3))
            elif index % 4 == 2:
                created = iso(now - timedelta(days=400))
            else:
                created = None
            recycle_flag = 1 if index >= vms - recycle else 0
            values = {
                "tower_id": tower,
                "cluster_id": cluster,
                "vm_id": vm_id,
                "name": f"in-recycle-bin-{name}" if recycle_flag else name,
                "original_name": name if recycle_flag else None,
                "used_bytes": used,
                "in_recycle_bin": recycle_flag,
                "deleted_at": iso(now - timedelta(days=1)) if recycle_flag else None,
                "local_created_at": created,
                "updated_at": iso(now),
                "owner": f"owner-{index % 3}",
                "folder_name": f"文件夹 {index % 4}",
            }
            insert(conn, "vm_latest", values)
            for volume in range(volumes_per_vm):
                insert(
                    conn,
                    "vm_volumes",
                    {
                        "tower_id": tower,
                        "cluster_id": cluster,
                        "vm_id": vm_id,
                        "volume_id": f"e2e-vol-{index:03d}-{volume}",
                        "name": f"卷 {index:03d}-{volume} 💾",
                        "path": "/e2e",
                        "size_bytes": used,
                        "used_bytes": used,
                        "storage_policy": "e2e",
                        "replica_num": 2,
                        "thin_provision": 0,
                        "ec_k": 0,
                        "ec_m": 0,
                        "updated_at": iso(now),
                    },
                )
        conn.commit()
        counts = {
            "towers": conn.execute("SELECT COUNT(*) FROM towers").fetchone()[0],
            "clusters": conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0],
            "vm_latest": conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0],
            "vm_volumes": conn.execute("SELECT COUNT(*) FROM vm_volumes").fetchone()[0],
            "recycle": conn.execute("SELECT COUNT(*) FROM vm_latest WHERE in_recycle_bin=1").fetchone()[0],
        }
        return counts
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成标准测试数据集（仅验证机）")
    parser.add_argument("--db", required=True, help="SQLite 路径（验证机，如 /data/smartx-storage-forecast/app/smartx.db）")
    parser.add_argument("--yes", action="store_true", help="确认这是验证机库，允许写入业务表")
    parser.add_argument("--vms", type=int, default=120)
    parser.add_argument("--volumes-per-vm", type=int, default=2)
    parser.add_argument("--towers", type=int, default=2)
    parser.add_argument("--clusters", type=int, default=3)
    parser.add_argument("--recycle", type=int, default=3)
    args = parser.parse_args(argv)

    if not args.yes:
        print("拒绝执行：会写入业务表。确认是验证机后加 --yes。", file=sys.stderr)
        return 2
    db = Path(args.db)
    if not db.is_file():
        print(f"数据库不存在：{db}", file=sys.stderr)
        return 2
    counts = seed(
        db,
        vms=args.vms,
        volumes_per_vm=args.volumes_per_vm,
        towers=args.towers,
        clusters=args.clusters,
        recycle=args.recycle,
    )
    print("SEEDED " + " ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
