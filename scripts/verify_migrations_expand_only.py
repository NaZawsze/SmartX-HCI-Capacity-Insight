#!/usr/bin/env python3
"""W7.2 门禁：迁移 expand-only 纪律。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W7.2
（设计 v2 §2.1「迁移纪律不变：expand-only，只加列/加表，回滚与旧代码兼容的地基」）。

要拦的事故类别：**破坏性 schema 变更混进 expand 期**。回滚三场景（设计 v2 §2.3）全部
建立在「新版本写的数据旧版本读得懂」之上；一个 `DROP COLUMN` 就会让「回滚保数据」当场失效，
而这类变更在编译期、在字段级 diff 上都看不出来。

判定对象：`backend/app/v2/upgrade/migrations/registry.json` 里**新增条目**的 `sql` 与
`operations`。破坏性模式：`DROP TABLE|DROP COLUMN|ALTER ... RENAME|MODIFY|DELETE FROM|
UPDATE ... SET`。命中即 fail，除非该条目显式标 `"contract": true` 且关联 contract 计划。

规格 §14.1.5 明确要求：**必须带 allowlist + 人工复核出口**。SQL 是启发式扫描，
注释里出现 `DROP` 会假阳性；没有人工出口的门禁会被"改一下白名单"习惯性绕过，
门禁被绕等于没有门禁（2026-10-05 评审原话）。因此：
- `--allow <step_id>:<正则>` 显式放行单条命中，打印 WARN 并说明依据（放行是人工决定）；
- 条目自带 `contract: true` + `contract_plan` 才走 contract 通道；
- **默认禁止新增 contract 条目**（`--allow-new-contract` 才能放行）。

只扫**新增**条目：以 `--baseline <已发布平台包 或 registry.json>` 为准做差集；
缺省时用 git 中最近一个已发布 tag（默认 `v0.5.3`）的 registry 快照。
历史条目不受本次门禁追溯（避免把既成事实判死），但会在输出里列出「基线里已存在的破坏性条目」
供人工知悉。

用法：
    python3 scripts/verify_migrations_expand_only.py \\
        [--registry backend/app/v2/upgrade/migrations/registry.json] \\
        [--baseline-tag v0.5.3 | --baseline <文件>] \\
        [--allow <step_id>:<正则> ...] [--allow-new-contract] [--json]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "backend" / "app" / "v2" / "upgrade" / "migrations" / "registry.json"
DEFAULT_BASELINE_TAG = "v0.5.3"

# 破坏性模式。SQL 大小写不敏感；注释在预处理阶段剥掉（见 _strip_sql_comments）。
DESTRUCTIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DROP_TABLE", re.compile(r"\bDROP\s+TABLE\b", re.I)),
    ("DROP_COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.I)),
    ("ALTER_RENAME", re.compile(r"\bALTER\s+TABLE\b[^;]*?\bRENAME\b", re.I | re.S)),
    ("ALTER_MODIFY", re.compile(r"\bALTER\s+TABLE\b[^;]*?\b(MODIFY|CHANGE)\b", re.I | re.S)),
    ("DELETE_FROM", re.compile(r"\bDELETE\s+FROM\b", re.I)),
    ("UPDATE_SET", re.compile(r"\bUPDATE\s+\S+\s+SET\b", re.I | re.S)),
)

# 明确判定为 expand 的操作（避免把唯一合法的加列操作也走启发式）
EXPAND_ACTIONS = frozenset({"add_column_if_missing"})


def _strip_sql_comments(sql: str) -> str:
    """去掉 `--` 行注释与 `/* */` 块注释。

    没有这一步，`-- 旧表将来 DROP 掉` 这样的注释会造成假阳性，而假阳性 + 无出口
    = 门禁被绕过（规格 §14.1.5）。
    """
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", without_block)


def load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"migration registry 必须是数组：{path}")
    return [item for item in payload if isinstance(item, dict)]


def baseline_registry(registry_path: Path, *, baseline_path: Path | None, baseline_tag: str | None) -> tuple[set[str], str]:
    """返回 (基线里已存在的 step id 集合, 人类可读来源说明)。

    基线优先级：`--baseline` 指定的 registry 快照文件 > git 已发布 tag 里的 registry > 无基线（全量检查）。
    """
    if baseline_path is not None:
        return {str(item.get("id") or "") for item in load_registry(Path(baseline_path))}, f"文件 {baseline_path}"
    if not baseline_tag:
        return set(), "无基线（全量检查）"
    completed = subprocess.run(
        ["git", "show", f"{baseline_tag}:backend/app/v2/upgrade/migrations/registry.json"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return set(), f"无基线（全量检查；git {baseline_tag} 无该文件）"
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return set(), f"无基线（全量检查；git {baseline_tag} 的 registry 解析失败）"
    ids = {str(item.get("id") or "") for item in payload if isinstance(item, dict)}
    return ids, f"git {baseline_tag}"


def _allowlist_matches(rules: list[str], step_id: str, pattern: str) -> str | None:
    for rule in rules:
        step_pattern, _, regex_pattern = rule.partition(":")
        if not regex_pattern:
            regex_pattern, step_pattern = step_pattern, "*"
        if fnmatch.fnmatch(step_id, step_pattern.strip() or "*") and re.search(regex_pattern, pattern, re.I):
            return rule
    return None


def scan_entry(entry: dict[str, Any]) -> list[dict[str, str]]:
    """返回该条目命中的破坏性模式列表。"""
    hits: list[dict[str, str]] = []
    for statement in entry.get("sql") or []:
        text = _strip_sql_comments(str(statement)).strip()
        if not text:
            continue
        for name, pattern in DESTRUCTIVE_PATTERNS:
            if pattern.search(text):
                hits.append({"kind": name, "where": "sql", "text": text[:400]})
    for operation in entry.get("operations") or []:
        if not isinstance(operation, dict):
            continue
        action = str(operation.get("action") or "")
        if action in EXPAND_ACTIONS:
            continue
        hits.append({"kind": f"operation:{action or '<empty>'}", "where": "operations", "text": json.dumps(operation, ensure_ascii=False)[:400]})
    return hits


def verify(
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    baseline_path: Path | None = None,
    baseline_tag: str | None = DEFAULT_BASELINE_TAG,
    allow: list[str] | None = None,
    allow_new_contract: bool = False,
) -> dict[str, Any]:
    allow_rules = list(allow or [])
    entries = load_registry(registry_path)
    baseline_ids, baseline_source = baseline_registry(
        registry_path, baseline_path=baseline_path, baseline_tag=baseline_tag
    )

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    new_steps: list[str] = []
    legacy_destructive: list[str] = []

    for entry in entries:
        step_id = str(entry.get("id") or "")
        hits = scan_entry(entry)
        is_new = step_id not in baseline_ids
        if is_new:
            new_steps.append(step_id)
        if not hits:
            continue
        if not is_new:
            legacy_destructive.append(step_id)
            continue

        is_contract = bool(entry.get("contract")) and str(entry.get("contract_plan") or "").strip() != ""
        for hit in hits:
            detail = {
                "step_id": step_id,
                "kind": hit["kind"],
                "where": hit["where"],
                "text": hit["text"],
                "contract": is_contract,
            }
            if is_contract and allow_new_contract:
                warnings.append({**detail, "reason": "contract 条目 + --allow-new-contract 放行（破坏性变更已计划走 contract）"})
                continue
            if is_contract:
                failures.append({**detail, "reason": "标记了 contract 但未加 --allow-new-contract：默认禁止新增 contract 条目"})
                continue
            rule = _allowlist_matches(allow_rules, step_id, hit["kind"])
            if rule:
                warnings.append({**detail, "reason": f"人工放行规则 {rule!r}"})
                continue
            failures.append({**detail, "reason": "破坏性模式；回滚三场景要求 expand-only"})

    return {
        "ok": not failures,
        "registry": str(registry_path),
        "baseline_source": baseline_source,
        "total_steps": len(entries),
        "new_steps": new_steps,
        "legacy_destructive_steps": legacy_destructive,
        "failures": failures,
        "warnings": warnings,
    }


def _format(result: dict[str, Any]) -> str:
    lines = [
        f"migrations expand-only: {'OK' if result['ok'] else 'FAILED'} "
        f"({result['total_steps']} 条目，新增 {len(result['new_steps'])}；基线={result['baseline_source']})",
    ]
    for item in result["failures"]:
        lines.append(
            f"  [FAIL] {item['step_id']}: {item['kind']}（{item['where']}）{item['reason']} —— {item['text'][:160]}"
        )
    for item in result["warnings"]:
        lines.append(f"  [WARN] {item['step_id']}: {item['kind']} —— {item['reason']}")
    if result["legacy_destructive_steps"]:
        lines.append(
            f"  [INFO] 基线中已存在的破坏性条目（本次不追溯）：{'、'.join(result['legacy_destructive_steps'])}"
        )
    if result["ok"] and not result["warnings"]:
        lines.append("  [PASS] 新增条目全部为 expand-only（只加列/加表）")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify upgrade migrations are expand-only.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--baseline", type=Path, help="基线 registry.json 文件（默认用 git tag）")
    parser.add_argument("--baseline-tag", default=DEFAULT_BASELINE_TAG, help="基线已发布 tag（默认 v0.5.3）")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="STEP_ID:PATTERN",
        help="人工放行单条命中（可重复）；形如 'my-step:DROP_TABLE' 或 '*:DELETE_FROM'",
    )
    parser.add_argument("--allow-new-contract", action="store_true", help="允许新增 contract 条目（默认禁止）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = verify(
        registry_path=args.registry,
        baseline_path=args.baseline,
        baseline_tag=args.baseline_tag,
        allow=args.allow,
        allow_new_contract=args.allow_new_contract,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format(result))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
