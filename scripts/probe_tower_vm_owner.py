#!/usr/bin/env python3
"""Tower「VM 所有者」可读性探针 —— 虚拟机所有者可见性功能（Phase 69）的第一道门。

在不改产品代码的前提下回答四个问题：
1. `get-vms` 的**原始返回**里有没有所有者字段（键名与形态）；
2. 用**只读账号**调用时该字段是否可见（Mode A 传只读账号即可判定）；
3. 所有者是"用户 ID"还是"名字"——如是 ID，`get-users` 能否解析（需要相应读权限）；
4. 字段的稳定性（抽样多台 VM，看是否为空、类型是否一致）。

两种运行模式（都建议在 web-api 容器内跑，复用产品自带的 CloudTowerClient）：

  A. 只读账号测试（不碰产品库，凭据只经环境变量）：
     TOWER_URL=https://x.x.x.x:4433 TOWER_USER=ro-user TOWER_PASSWORD=... \
       python3 scripts/probe_tower_vm_owner.py [--sample 5] [--probe-users]

  B. 复用现场已配置的 Tower（凭据从产品库解密；**绝不打印凭据**）：
     python3 scripts/probe_tower_vm_owner.py --configured [--tower-id N] [--probe-users]

输出只包含：登录结果、VM 条目数、字段键清单、所有者相关字段的样例值（截断）、
get-users 试探结果。任何凭据/token 都不进入输出。

注意：本脚本是**诊断工具**，不属于升级链路，不改任何数据（只读调用）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

OWNER_KEY_PATTERN = re.compile(r"owner|user|creator|admin", re.IGNORECASE)


def _truncate(value: object, limit: int = 120) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _owner_like_fields(item: dict) -> dict:
    return {key: item.get(key) for key in item if OWNER_KEY_PATTERN.search(str(key))}


def _dump_get_vms(client, *, sample: int) -> dict:
    vms = client.get_vms()
    print(f"[probe] get-vms 条目数：{len(vms)}")
    if not vms:
        return {"items": 0}
    first = vms[0]
    if not isinstance(first, dict):
        print(f"[probe] 条目不是 dict，实际类型：{type(first)!r}")
        return {"items": len(vms)}
    print(f"[probe] 条目字段键（{len(first)} 个）：")
    print("        " + ", ".join(sorted(str(key) for key in first)))
    owner_fields_all: set[str] = set()
    for vm in vms[: max(1, sample)]:
        owner_fields_all.update(str(key) for key in _owner_like_fields(vm))
    if owner_fields_all:
        print(f"[probe] 所有者相关字段命中（样例前 {max(1, sample)} 台）：{', '.join(sorted(owner_fields_all))}")
        for vm in vms[: max(1, sample)]:
            name = str(vm.get("name") or vm.get("id") or "?")
            print(f"        - vm={name!r} → {json.dumps({k: _truncate(v) for k, v in _owner_like_fields(vm).items()}, ensure_ascii=False)}")
        conclusion = "get-vms 原始返回**包含**所有者相关字段——只读可见性由本次调用的账号权限决定（用只读账号跑 Mode A 即为结论）"
    else:
        print("[probe] get-vms 原始返回**未发现**所有者相关字段（owner/user/creator/admin）")
        conclusion = "get-vms 原始返回未含所有者字段——需要另找数据源（见设计文档「候选路径」）"
    return {"items": len(vms), "owner_fields": sorted(owner_fields_all), "conclusion": conclusion}


def _probe_users(client) -> None:
    """试探 get-users（端点名按 CloudTower v2 惯例猜，失败即如实报告）。"""
    print("[probe] 试探 /v2/api/get-users …")
    try:
        data = client.post("/v2/api/get-users", {"first": 3, "skip": 0})
    except Exception as exc:  # noqa: BLE001 - 探针如实报告失败
        print(f"[probe] get-users 不可用或无权：{exc}")
        return
    items = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else None)
    if not isinstance(items, list):
        print(f"[probe] get-users 返回形态未预期：{_truncate(data)}")
        return
    print(f"[probe] get-users 可用，条目数（本页）：{len(items)}")
    if items and isinstance(items[0], dict):
        print("        字段键：" + ", ".join(sorted(str(k) for k in items[0])))
        keys = [k for k in items[0] if re.search(r"name|username|display", str(k), re.IGNORECASE)]
        if keys:
            print("        名字类键样例：" + json.dumps({k: _truncate(items[0].get(k)) for k in keys}, ensure_ascii=False))


def _run_readonly_mode(args: argparse.Namespace) -> int:
    import os

    from app.v2.cloudtower.client import CloudTowerClient, CloudTowerCredentials

    base_url = os.environ.get("TOWER_URL", "").strip()
    if not base_url:
        print("缺少 TOWER_URL 环境变量（Mode A）。", file=sys.stderr)
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
        print(f"[probe] 登录成功（账号={'API token' if credentials.api_token else credentials.username!r}）")
        result = _dump_get_vms(client, sample=args.sample)
        if args.probe_users:
            _probe_users(client)
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
    inventory = InventoryService(database)
    towers = inventory.list_towers()
    if not towers:
        print("产品库里没有已配置的 Tower。", file=sys.stderr)
        return 2
    tower = None
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
        result = _dump_get_vms(client, sample=args.sample)
        if args.probe_users:
            _probe_users(client)
    finally:
        client.close()
    print(f"[probe] 结论：{result.get('conclusion', '见上')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tower VM 所有者可读性探针（只读诊断）")
    parser.add_argument("--configured", action="store_true", help="使用产品库中已配置的 Tower（容器内运行）")
    parser.add_argument("--tower-id", type=int, default=None, help="--configured 时指定 Tower id（默认第一个启用的）")
    parser.add_argument("--sample", type=int, default=5, help="打印所有者样例的 VM 台数（默认 5）")
    parser.add_argument("--probe-users", action="store_true", help="额外试探 get-users（用于所有者 ID→名字解析）")
    args = parser.parse_args()
    if args.configured:
        return _run_configured_mode(args)
    return _run_readonly_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
