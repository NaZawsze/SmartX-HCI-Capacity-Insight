#!/usr/bin/env python3
"""校验 docs/api.md 与后端 FastAPI 路由一致，防止接口文档漂移。

背景：2026-09-19 全仓文档盘点时发现 api.md 缺 6 个真实端点、
v2-api-contracts.md 记载了已不存在的 POST /api/reports/export。
本脚本把比对固化为可重复执行的门禁。

用法（仓库根目录执行）：

    python3 scripts/verify_api_docs.py                     # 双向校验 api.md
    python3 scripts/verify_api_docs.py --contract docs/v2-api-contracts.md
                                                           # 附加单向校验契约文档
                                                           #（契约只要求"记载的端点必须存在"）

规则：
- api.md 记载的端点（```http 代码块与 Markdown 表格行）必须存在于后端路由；
- 后端 `@router.<method>("path")` 声明的路由必须都被 api.md 记载；
- 查询串忽略（/path?x=y 按 /path 比对）；
- 白名单：`GET /metrics` 由 collector-worker :9108 暴露，不在 web-api 路由内。

退出码：0 一致；1 存在差异（逐条打印）。
"""

import argparse
import re
import sys
from pathlib import Path

ROUTE_RE = re.compile(r'@router\.(get|post|put|delete)\(\s*"([^"]+)"')
HTTP_BLOCK_RE = re.compile(r"^(GET|POST|PUT|DELETE)\s+(/\S*)", re.M)
TABLE_ROW_RE = re.compile(r"^\|\s*(GET|POST|PUT|DELETE)\s*\|\s*`([^`]+)`", re.M)
CONTRACT_HEADING_RE = re.compile(r"^###\s*`(GET|POST|PUT|DELETE)\s+([^`?]+)`", re.M)

# worker :9108 暴露的指标端点，不在 web-api 路由表内
WHITELIST = {"GET /metrics"}


def normalize(path: str) -> str:
    return path.split("?", 1)[0].rstrip("/")


def extract_code_routes(backend_root: Path) -> set:
    routes = set()
    for py_file in sorted(backend_root.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        for method, path in ROUTE_RE.findall(text):
            routes.add(f"{method.upper()} {path}")
    return routes


def extract_doc_routes(text: str) -> set:
    routes = set()
    for method, path in HTTP_BLOCK_RE.findall(text):
        routes.add(f"{method} {normalize(path)}")
    for method, path in TABLE_ROW_RE.findall(text):
        routes.add(f"{method} {normalize(path.strip())}")
    return routes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent),
                        help="仓库根目录（默认按脚本位置推断）")
    parser.add_argument("--api-doc", default="docs/api.md", help="API 文档路径（相对仓库根）")
    parser.add_argument("--contract", default=None,
                        help="契约文档路径（可选，单向校验：记载端点必须存在）")
    args = parser.parse_args()

    repo = Path(args.repo)
    backend_root = repo / "backend" / "app"
    api_doc = repo / args.api_doc
    if not backend_root.is_dir() or not api_doc.is_file():
        print(f"路径不存在：{backend_root} 或 {api_doc}", file=sys.stderr)
        return 2

    code_routes = extract_code_routes(backend_root)
    doc_routes = extract_doc_routes(api_doc.read_text(encoding="utf-8"))

    problems = []
    for route in sorted(doc_routes - code_routes - WHITELIST):
        problems.append(f"api.md 记载但后端不存在: {route}")
    for route in sorted(code_routes - doc_routes):
        problems.append(f"后端存在但 api.md 未记载: {route}")

    contract_note = ""
    if args.contract:
        contract_path = repo / args.contract
        if not contract_path.is_file():
            print(f"路径不存在：{contract_path}", file=sys.stderr)
            return 2
        contract_routes = extract_doc_routes(contract_path.read_text(encoding="utf-8"))
        contract_routes |= {
            f"{method} {normalize(path.strip())}"
            for method, path in CONTRACT_HEADING_RE.findall(
                contract_path.read_text(encoding="utf-8"))
        }
        missing = sorted(contract_routes - code_routes - WHITELIST)
        for route in missing:
            problems.append(f"契约记载但后端不存在: {route}")
        contract_note = f"；契约 {len(contract_routes)} 条校验通过"

    if problems:
        print(f"API 文档与路由不一致（{len(problems)} 处）：")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK: api.md {len(doc_routes)} 条（含 {len(doc_routes & WHITELIST)} 条白名单豁免）"
          f"与后端 {len(code_routes)} 条路由一致{contract_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
