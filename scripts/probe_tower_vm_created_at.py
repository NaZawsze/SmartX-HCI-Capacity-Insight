#!/usr/bin/env python3
"""Tower VM「真实创建时间 / 回收站标记」可读性探针（#36/#37，只读诊断）。

用途：核对 CloudTower 的 `get-vms` 到底返回哪些字段，为「新建 VM 口径升级」提供实测依据：
  ① 真实创建时间字段（候选 `local_created_at` / `created_at` / …）是否存在、格式如何；
  ② 权威回收站标记 `in_recycle_bin` 是否存在、`original_name` / `deleted_at` 形态；
  ③ `where` 能否**服务端过滤** `in_recycle_bin`（决定采集侧能否直接过滤，而不是全量拉回来再筛）。

两种运行方式（都不落任何凭据）：
  A) 只读账号（任意能访问 Tower 的机器）：
       TOWER_URL=https://<tower>:<port> TOWER_USER=... TOWER_PASSWORD=... \
       python3 scripts/probe_tower_vm_created_at.py [--sample 5]
  B) 用产品库里已配置的 Tower（**在 .3 的 web-api 容器内运行**，凭据不出容器）：
       docker exec -i <web-api 容器> python - < scripts/probe_tower_vm_created_at.py --configured

只读：仅 login + get-vms（含带 where 的探测调用），不写任何数据。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

#: 创建时间候选字段（不同 CloudTower 版本命名可能不同，逐个探测）
CREATION_CANDIDATES = (
    "local_created_at",
    "created_at",
    "create_time",
    "createdAt",
    "local_created_time",
)
RECYCLE_FIELDS = ("in_recycle_bin", "original_name", "deleted_at")


def _truncate(value: object, limit: int = 60) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def _probe_where_filter(client: Any) -> dict[str, Any]:
    """探测 `where` 能否服务端过滤 `in_recycle_bin`。"""
    report: dict[str, Any] = {}
    for label, where in (
        ("in_recycle_bin=true", {"in_recycle_bin": True}),
        ("in_recycle_bin=false", {"in_recycle_bin": False}),
    ):
        try:
            items = client.paged_post("/v2/api/get-vms", {"where": where})
            report[label] = f"OK，返回 {len(items)} 台"
            names = [str(item.get("name") or "") for item in items[:3]]
            report[label + " 样例"] = names
        except Exception as exc:  # noqa: BLE001 - 探测失败要如实呈现（不同版本可能不支持）
            report[label] = f"失败：{type(exc).__name__}: {exc}"
    return report


def _dump(client: Any, *, sample: int) -> dict[str, Any]:
    raw = client.paged_post("/v2/api/get-vms", {"where": {}})
    total = len(raw)
    print(f"[probe] get-vms 返回 {total} 台 VM")
    if not raw:
        return {"conclusion": "Tower 未返回任何 VM（环境/权限问题，无法得出结论）"}

    first = raw[0]
    print(f"[probe] 单台 VM 顶层字段共 {len(first)} 个：")
    print("        " + ", ".join(sorted(first.keys())))

    creation_hits = [field for field in CREATION_CANDIDATES if field in first]
    recycle_hits = [field for field in RECYCLE_FIELDS if field in first]
    print(f"[probe] 创建时间候选字段命中：{creation_hits or '（无）'}")
    print(f"[probe] 回收站相关字段命中：{recycle_hits or '（无）'}")

    print(f"[probe] 前 {min(sample, total)} 台样例：")
    for vm in raw[:sample]:
        row = {"id": vm.get("id"), "name": _truncate(vm.get("name"))}
        for field in CREATION_CANDIDATES + RECYCLE_FIELDS:
            if field in vm:
                row[field] = _truncate(vm.get(field))
        print("        " + json.dumps(row, ensure_ascii=False, default=str))

    # 创建时间字段的可用性：非空率 + 是否全同（全同=常量/未填）
    if creation_hits:
        field = creation_hits[0]
        values = [vm.get(field) for vm in raw]
        non_empty = [v for v in values if v not in (None, "", 0)]
        distinct = {str(v) for v in non_empty}
        print(
            f"[probe] `{field}` 非空 {len(non_empty)}/{total}，去重后 {len(distinct)} 个不同值"
            + ("（⚠ 只有一个值，疑似未填充）" if len(distinct) == 1 else "")
        )

    # 回收站标记形态
    if "in_recycle_bin" in first:
        recycled = [vm for vm in raw if vm.get("in_recycle_bin")]
        print(f"[probe] 标记为回收站的 VM：{len(recycled)} 台")
        for vm in recycled[:3]:
            print(
                "        "
                + json.dumps(
                    {
                        "name": _truncate(vm.get("name")),
                        "in_recycle_bin": vm.get("in_recycle_bin"),
                        "original_name": _truncate(vm.get("original_name")),
                        "deleted_at": _truncate(vm.get("deleted_at")),
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )

    print("[probe] where 过滤探测（服务端过滤能力）：")
    where_report = _probe_where_filter(client)
    for key, value in where_report.items():
        print(f"        {key}: {value}")

    conclusion = (
        f"创建时间字段={'/'.join(creation_hits) if creation_hits else '缺失'}；"
        f"回收站字段={'/'.join(recycle_hits) if recycle_hits else '缺失'}；"
        f"where(in_recycle_bin)={'可用' if str(where_report.get('in_recycle_bin=true', '')).startswith('OK') else '不可用/需确认'}"
    )
    return {"conclusion": conclusion, "where_report": where_report}


def _run_readonly_mode(args: argparse.Namespace) -> int:
    import os

    from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

    base_url = os.environ.get("TOWER_URL", "").strip()
    if not base_url:
        print("缺少 TOWER_URL 环境变量（模式 A）。", file=sys.stderr)
        return 2
    credentials = CloudTowerCredentials(
        base_url=base_url,
        username=os.environ.get("TOWER_USER"),
        password=os.environ.get("TOWER_PASSWORD"),
        api_token=os.environ.get("TOWER_API_TOKEN"),
        verify_tls=os.environ.get("TOWER_VERIFY_TLS", "0") not in {"0", "false", "False"},
    )
    client = CloudTowerClient(credentials)
    try:
        client.login()
        print("[probe] 登录成功（只读模式）")
        result = _dump(client, sample=args.sample)
    except Exception as exc:  # noqa: BLE001 - 探针把网络/权限问题如实翻译给人看
        print(f"[probe] Tower 不可达或调用失败：{exc}", file=sys.stderr)
        return 3
    finally:
        client.close()
    print(f"[probe] 结论：{result.get('conclusion', '见上')}")
    return 0


def _run_configured_mode(args: argparse.Namespace) -> int:
    from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials
    from app.v2.config import settings_from_environment
    from app.v2.database import V2Database
    from app.v2.inventory.service import InventoryService

    settings = settings_from_environment()
    database = V2Database(settings)
    # 兼容两代签名：v0.5.3 的 InventoryService(database, settings)；开发线单参数。
    try:
        inventory = InventoryService(database, settings)
    except TypeError:
        inventory = InventoryService(database)
    towers = inventory.list_towers()
    if not towers:
        print("产品库里没有已配置的 Tower。", file=sys.stderr)
        return 2
    if args.tower_id is not None:
        tower = next((t for t in towers if int(getattr(t, "id", 0)) == args.tower_id), None)
        if tower is None:
            print(f"未找到 tower id={args.tower_id}", file=sys.stderr)
            return 2
    else:
        tower = next((t for t in towers if getattr(t, "enabled", False)), towers[0])
    secrets = inventory.get_tower_secret_material(int(getattr(tower, "id", 0)))
    credentials = CloudTowerCredentials(
        base_url=str(getattr(tower, "base_url", "")),
        username=getattr(tower, "username", None),
        password=secrets.get("password"),
        api_token=secrets.get("api_token"),
        verify_tls=bool(getattr(tower, "verify_tls", True)),
    )
    client = CloudTowerClient(credentials)
    try:
        client.login()
        print(f"[probe] 已用现场配置的 Tower 登录（id={getattr(tower, 'id', '?')}，凭据不外显）")
        result = _dump(client, sample=args.sample)
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] Tower 不可达或调用失败：{exc}", file=sys.stderr)
        return 3
    finally:
        client.close()
    print(f"[probe] 结论：{result.get('conclusion', '见上')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tower VM 创建时间/回收站标记可读性探针（只读）")
    parser.add_argument("--configured", action="store_true", help="使用产品库中已配置的 Tower（容器内运行）")
    parser.add_argument("--tower-id", type=int, default=None, help="指定 tower id（默认取第一个启用的）")
    parser.add_argument("--sample", type=int, default=5, help="打印样例条数（默认 5）")
    args = parser.parse_args()
    return _run_configured_mode(args) if args.configured else _run_readonly_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
