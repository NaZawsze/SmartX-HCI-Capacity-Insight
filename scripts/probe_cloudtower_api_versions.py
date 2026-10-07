#!/usr/bin/env python3
"""CloudTower API 版本差异探针（#84「按 Tower 版本选择 API」的证据源）。

数据来源 = 官方开发者文档站按版本发布的 OpenAPI 规范（浏览器实测的加载地址）：

    https://code-site.smartx.com/specs/<version>-swagger.json

本脚本只做只读抓取 + 结构比对，回答两个问题：
  1. 我们实际调用的 6 个接口，在哪些版本里存在（有没有端点级差异）；
  2. 我们从响应里消费的字段，在哪些版本里存在（字段级差异在哪一刀）。

用法：

    python3 scripts/probe_cloudtower_api_versions.py --versions 4.9.0,4.5.0,4.0.0
    python3 scripts/probe_cloudtower_api_versions.py --all
    python3 scripts/probe_cloudtower_api_versions.py --all --json /tmp/cloudtower-api-matrix.json

缓存：默认写 `.cache/cloudtower-specs/`（仓库已忽略），重复运行不重复下载。
退出码：0 = 全部版本抓到；2 = 有版本抓取失败（矩阵仍打印，失败版本标明）。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SPEC_URL = "https://code-site.smartx.com/specs/{version}-swagger.json"
#: 只覆盖 4.4.0 及以上（2026-10-07 用户口径：按 Tower 版本选 API 只需管 4.4.0+）。
#: 低于 4.4.0 的版本不在支持面内，探测它们的意义有限。
DEFAULT_SPEC_VERSIONS = [
    "4.9.0", "4.8.1", "4.8.0", "4.7.2", "4.7.1", "4.7.0", "4.6.2", "4.6.1", "4.6.0",
    "4.5.0", "4.4.2", "4.4.1", "4.4.0",
]
#: 平台实际调用的端点（spec 里路径不带 /v2/api 前缀，比对时按末段匹配）
OUR_ENDPOINTS = (
    "login",
    "get-version",
    "get-clusters",
    "get-vms",
    "get-vm-volumes",
    "get-cluster-storage-info",
)
#: 我们从响应里消费的字段（schema 名 → 字段名列表）
CONSUMED_FIELDS: dict[str, tuple[str, ...]] = {
    "Cluster": (
        "id", "name", "version",
        # 容量兜底来源：4.4.x 没有 get-cluster-storage-info 端点，容量只能从集群记录读
        "used_data_space", "total_data_capacity",
    ),
    "Vm": ("id", "name", "used_size", "in_recycle_bin", "original_name", "deleted_at", "labels", "folder"),
    "VmVolume": (
        "id", "name", "path", "size", "used_size",
        "elf_storage_policy", "elf_storage_policy_replica_num", "elf_storage_policy_thin_provision",
        "elf_storage_policy_ec_k", "elf_storage_policy_ec_m", "replica_num",
    ),
    "ClusterStorageInfo": ("used_data_space", "total_data_capacity"),
}


def fetch_spec(version: str, cache_dir: Path) -> dict | None:
    cache_file = cache_dir / f"{version}-swagger.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_file.unlink()
    url = SPEC_URL.format(version=version)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - 固定官方文档站
            payload = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[warn] {version}: 抓取失败 {exc}", file=sys.stderr)
        return None
    # 实测：部分版本（4.7.1 / 4.6.2 / 4.6.1）该目录下没有规范文件，站点返回 200 + 一段 HTML。
    if not payload.lstrip()[:1] == "{":
        print(f"[warn] {version}: 该版本无规范文件（返回非 JSON，{len(payload)} 字节）", file=sys.stderr)
        return None
    try:
        spec = json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"[warn] {version}: 规范不是合法 JSON：{exc}", file=sys.stderr)
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(payload, encoding="utf-8")
    return spec


def schema_properties(spec: dict, name: str, seen: set[str] | None = None) -> dict:
    """合并 allOf/$ref 后的属性字典（OpenAPI 3 的 components.schemas）。"""
    schemas = (spec.get("components") or {}).get("schemas") or {}
    node = schemas.get(name)
    if not isinstance(node, dict):
        return {}
    seen = seen or set()
    if name in seen:
        return {}
    seen.add(name)
    props: dict = dict(node.get("properties") or {})
    for part in node.get("allOf") or []:
        ref = part.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            props.update(schema_properties(spec, ref.rsplit("/", 1)[-1], seen))
        else:
            props.update(part.get("properties") or {})
    return props


def endpoint_presence(spec: dict) -> dict[str, bool]:
    tails = {path.rstrip("/").rsplit("/", 1)[-1] for path in (spec.get("paths") or {})}
    return {endpoint: endpoint in tails for endpoint in OUR_ENDPOINTS}


def field_presence(spec: dict) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    for schema, fields in CONSUMED_FIELDS.items():
        props = schema_properties(spec, schema)
        if not props:
            result[schema] = {field: False for field in fields}
            continue
        result[schema] = {field: field in props for field in fields}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--versions", help="逗号分隔的版本号，如 4.9.0,4.5.0")
    parser.add_argument("--all", action="store_true", help=f"文档站全量版本（{len(DEFAULT_SPEC_VERSIONS)} 个）")
    parser.add_argument("--cache-dir", default=".cache/cloudtower-specs", help="规范缓存目录")
    parser.add_argument("--json", help="把完整矩阵写到该 JSON 文件")
    args = parser.parse_args()

    versions = DEFAULT_SPEC_VERSIONS if args.all else [item.strip() for item in (args.versions or "").split(",") if item.strip()]
    if not versions:
        parser.error("需要 --versions 或 --all")

    cache_dir = Path(args.cache_dir)
    failures: list[str] = []
    matrix: dict[str, dict] = {}
    for version in versions:
        spec = fetch_spec(version, cache_dir)
        if spec is None:
            failures.append(version)
            continue
        matrix[version] = {
            "endpoints": endpoint_presence(spec),
            "fields": field_presence(spec),
        }

    # 端点级差异：按「端点 → 缺失的版本」报告
    print("== 端点存在性 ==")
    for endpoint in OUR_ENDPOINTS:
        missing = [version for version in versions if version in matrix and not matrix[version]["endpoints"][endpoint]]
        if missing:
            print(f"  {endpoint}: 缺失于 {', '.join(missing)}")
    if all(matrix[v]["endpoints"][endpoint] for v in matrix for endpoint in OUR_ENDPOINTS):
        print("  6 个端点在所有已抓版本中均存在")

    # 字段级差异：按「schema.字段 → 缺失/出现版本」报告
    print("\n== 消费字段存在性 ==")
    for schema, fields in CONSUMED_FIELDS.items():
        for field in fields:
            present = [v for v in versions if v in matrix and matrix[v]["fields"][schema][field]]
            missing = [v for v in versions if v in matrix and not matrix[v]["fields"][schema][field]]
            if missing and present:
                print(f"  {schema}.{field}: 出现于 {', '.join(present)}")
                print(f"      └ 缺失于 {', '.join(missing)}")
            elif not present:
                print(f"  {schema}.{field}: 所有已抓版本均无该字段")

    if args.json:
        Path(args.json).write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n矩阵已写入 {args.json}")

    if failures:
        print(f"\n[warn] {len(failures)} 个版本抓取失败：{', '.join(failures)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
