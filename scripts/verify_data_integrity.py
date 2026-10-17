#!/usr/bin/env python3
"""数据完整性快照与比对（升级验证用，见 docs/test-process-and-scope.md §4）。

用法：
    # 采样（升级前 / 每跳后 / 终态）
    python3 scripts/verify_data_integrity.py snapshot --out /data/diag/t0.json
    # 比对（任一次采样 vs 基线；退出码 0=PASS，1=FAIL）
    python3 scripts/verify_data_integrity.py compare --before /data/diag/t0.json --after /data/diag/t1.json

设计要点（都是踩过的坑）：
- **禁止 `SELECT *`**：升级会 expand-only 加列，`SELECT *` 会假报不一致 → 每表用固定「稳定列」。
- **可增长表**（tasks/collection_runs/metric_snapshots）只要求「升级前已有行不变 + 行数不减」，
  用主键边界内的指纹判定，不能要求 count 相等。
- **凭据列必须参与指纹**（`towers.password_encrypted` 等）：否则"凭据被清空"测不出来。
- **`.env` 只记录 key 与规范化 sha256，绝不回显值**。
- **宿主直读 DB**（容器内 `/run/smartx-runtime.env` 可能异常，`docker cp` 会挂）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DB_CANDIDATES = (
    "/data/smartx-storage-forecast/app/smartx.db",
    "/data/smartx-capacity-insight-data/app/smartx.db",
    "/data/smartx.db",
)
ENV_CANDIDATES = (
    "/data/smartx-storage-forecast/project/.env",
    "/opt/smartx-storage-forecast/.env",
)
COMPOSE_CANDIDATES = (
    "/data/smartx-storage-forecast/project/docker-compose.offline.yml",
    "/opt/smartx-storage-forecast/docker-compose.release.yml",
)

#: 业务表：**任何变化都是 FAIL**。凭据列必须参与（"凭据被清空"必须测得出）。
STRICT_TABLES: dict[str, list[str]] = {
    "towers": ["id", "name", "url", "username", "password_encrypted", "api_token_encrypted"],
    "clusters": ["tower_id", "cluster_id", "name"],
    "vm_latest": ["tower_id", "cluster_id", "vm_id", "name", "used_bytes"],
    "vm_volumes": ["tower_id", "cluster_id", "vm_id", "volume_id", "name", "used_bytes"],
    "users": ["id", "username", "password_hash"],
}
#: 运行表：允许新增，已有行不得变化（用主键边界判定）。
#: 注意：稳定列只选**升级过程中不会变**的字段。
#: `tasks` 的 `status` / `updated_at` 会随任务推进而变化（running→succeeded 是正常业务语义），
#: 纳入稳定列会把正常状态推进误报成"数据被改"（2026-10-18 L3-c 实测踩到）。
GROWABLE_TABLES: dict[str, list[str]] = {
    "tasks": ["id", "type", "created_at"],
    "collection_runs": ["id", "started_at"],
    "metric_snapshots": ["id", "tower_id", "collected_at"],
}
#: 迁移表：只增。
APPEND_ONLY_TABLES: dict[str, list[str]] = {
    "schema_migrations": ["version", "applied_at"],
}
#: 运行时表：任意变化，不作判据（仅记录行数便于排障）。
VOLATILE_TABLES = ("upgrade_runner_state", "upgrade_task_leases")

PROM_METRICS = (
    "smartx_cluster_storage_used_bytes",
    "smartx_cluster_storage_total_bytes",
    "smartx_cluster_storage_allocated_bytes",
    "smartx_vm_storage_used_bytes",
)


# ── 通用工具 ────────────────────────────────────────────────────────────
def sha16(rows: list[tuple]) -> str:
    return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()[:16]


def detect(candidates: tuple[str, ...], explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    for item in candidates:
        if os.path.exists(item):
            return Path(item)
    return None


def table_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str, int]]:
    return [(str(r[1]), str(r[2] or ""), int(r[5] or 0)) for r in conn.execute(f"PRAGMA table_info({table})")]


def primary_key(conn: sqlite3.Connection, table: str) -> str | None:
    for name, _type, pk in table_columns(conn, table):
        if pk == 1:
            return name
    return None


def digest_table(conn: sqlite3.Connection, table: str, columns: list[str], *, max_pk: Any = None) -> dict[str, Any]:
    present = [name for name, _t, _p in table_columns(conn, table)]
    if not present:
        return {"error": "table-missing"}
    use = [c for c in columns if c in present]
    if not use:
        return {"error": "no-stable-columns", "present": present}
    pk = primary_key(conn, table)
    sql = f"SELECT {', '.join(use)} FROM {table}"
    params: tuple = ()
    if max_pk is not None and pk:
        sql += f" WHERE {pk} <= ?"
        params = (max_pk,)
    rows = [tuple(r) for r in conn.execute(sql, params)]
    result: dict[str, Any] = {"count": len(rows), "digest": sha16(rows), "columns": use}
    if pk:
        result["pk"] = pk
        result["max_pk"] = conn.execute(f"SELECT MAX({pk}) FROM {table}").fetchone()[0]
    return result


def env_snapshot(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"path": str(path) if path else None, "exists": False}
    keys: list[str] = []
    pairs: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        keys.append(key)
        # 只对"键=值"做哈希（值不回显）；按 key 排序 → 行顺序变化不算变化
        pairs.append(f"{key}={value}")
    normalized = "\n".join(sorted(pairs))
    return {
        "path": str(path),
        "exists": True,
        "keys": sorted(keys),
        "key_count": len(keys),
        "sha256": hashlib.sha256(normalized.encode()).hexdigest(),
        "secret_present": bool(next((p for p in pairs if p.startswith("SMARTX_SECRET_KEY=") and len(p) > 20), "")),
        "credential_present": bool(
            next((p for p in pairs if p.startswith("SMARTX_CREDENTIAL_KEY=") and len(p) > 20), "")
        ),
    }


def file_sha(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"path": str(path) if path else None, "exists": False}
    return {"path": str(path), "exists": True, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def prom_query(base: str, query: str, timeout: int = 15) -> dict[str, Any]:
    url = f"{base.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode({"query": query})
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def prom_range(base: str, query: str, start: float, end: float, step: int, timeout: int = 30) -> dict[str, Any]:
    url = f"{base.rstrip('/')}/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": step}
    )
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def prom_snapshot(base: str | None, window_hours: float = 6.0, step: int = 300) -> dict[str, Any]:
    if not base:
        return {"url": None, "error": "prometheus-url-not-provided"}
    end = time.time()
    start = end - window_hours * 3600
    out: dict[str, Any] = {"url": base, "window": {"start": int(start), "end": int(end), "step": step}, "metrics": {}}
    try:
        series = prom_query(base, 'count({__name__=~"smartx_.*"})')
        result = series.get("data", {}).get("result") or []
        out["series"] = int(float(result[0]["value"][1])) if result else 0
    except Exception as exc:  # noqa: BLE001 - 探测失败要如实记录，不能假装通过
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    for metric in PROM_METRICS:
        try:
            data = prom_range(base, metric, start, end, step)
            results = data.get("data", {}).get("result") or []
            points = [tuple(point) for series_item in results for point in series_item.get("values") or []]
            out["metrics"][metric] = {"series": len(results), "points": len(points), "digest": sha16(points)}
        except Exception as exc:  # noqa: BLE001
            out["metrics"][metric] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def snapshot(args: argparse.Namespace) -> int:
    db_path = detect(DB_CANDIDATES, args.db)
    env_path = detect(ENV_CANDIDATES, args.env)
    compose_path = detect(COMPOSE_CANDIDATES, args.compose)
    payload: dict[str, Any] = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "label": args.label or "",
        "db": {"path": str(db_path) if db_path else None},
        "env": env_snapshot(env_path),
        "compose": file_sha(compose_path),
        "prometheus": prom_snapshot(args.prom),
    }

    if db_path is None or not db_path.is_file():
        payload["db"]["error"] = "db-not-found"
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            payload["db"]["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            payload["db"]["foreign_key_violations"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
            tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            payload["db"]["tables"] = {}
            for table, columns in STRICT_TABLES.items():
                if table in tables:
                    payload["db"]["tables"][table] = {**digest_table(conn, table, columns), "kind": "strict"}
            for table, columns in GROWABLE_TABLES.items():
                if table in tables:
                    payload["db"]["tables"][table] = {**digest_table(conn, table, columns), "kind": "growable"}
            for table, columns in APPEND_ONLY_TABLES.items():
                if table in tables:
                    payload["db"]["tables"][table] = {**digest_table(conn, table, columns), "kind": "append_only"}
            for table in VOLATILE_TABLES:
                if table in tables:
                    payload["db"]["tables"][table] = {
                        "count": conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                        "kind": "volatile",
                    }
            payload["db"]["schema"] = {
                table: [{"name": name, "type": type_, "pk": pk} for name, type_, pk in table_columns(conn, table)]
                for table in sorted(tables)
            }
            payload["db"]["references"] = _reference_violations(conn, tables)
            payload["db"]["aggregates"] = _aggregates(conn, tables)
        finally:
            conn.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[snapshot] {out}  db={payload['db'].get('path')}  label={payload.get('label')}")
    return 0


def _reference_violations(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    checks = {
        "clusters.tower_id->towers.id": "SELECT COUNT(*) FROM clusters c LEFT JOIN towers t ON t.id=c.tower_id WHERE t.id IS NULL",
        "vm_latest.cluster_id->clusters.cluster_id": "SELECT COUNT(*) FROM vm_latest v LEFT JOIN clusters c ON c.cluster_id=v.cluster_id WHERE c.cluster_id IS NULL",
        "vm_latest.tower_id->towers.id": "SELECT COUNT(*) FROM vm_latest v LEFT JOIN towers t ON t.id=v.tower_id WHERE t.id IS NULL",
        "vm_volumes.vm_id->vm_latest.vm_id": "SELECT COUNT(*) FROM vm_volumes o LEFT JOIN vm_latest v ON v.vm_id=o.vm_id WHERE v.vm_id IS NULL",
    }
    out: dict[str, int] = {}
    for name, sql in checks.items():
        need = {item.split(".")[0] for item in name.split("->")}
        if not need.issubset(tables):
            continue
        try:
            out[name] = int(conn.execute(sql).fetchone()[0])
        except sqlite3.Error:
            continue
    return out


def _aggregates(conn: sqlite3.Connection, tables: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        if "vm_latest" in tables:
            out["vm_count"] = conn.execute("SELECT COUNT(*) FROM vm_latest").fetchone()[0]
            out["vm_used_bytes_sum"] = conn.execute("SELECT COALESCE(SUM(used_bytes),0) FROM vm_latest").fetchone()[0]
        if "vm_volumes" in tables:
            out["volume_count"] = conn.execute("SELECT COUNT(*) FROM vm_volumes").fetchone()[0]
    except sqlite3.Error:
        pass
    return out


# ── 比对 ────────────────────────────────────────────────────────────────
class Report:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str]] = []

    def add(self, status: str, check: str, detail: str = "") -> None:
        self.lines.append((status, check, detail))

    def emit(self) -> int:
        for status, check, detail in self.lines:
            print(f"{status:5s} {check}" + (f"  {detail}" if detail else ""))
        failed = sum(1 for status, _, _ in self.lines if status == "FAIL")
        warned = sum(1 for status, _, _ in self.lines if status == "WARN")
        print(f"\n汇总：PASS={sum(1 for s, _, _ in self.lines if s == 'PASS')} FAIL={failed} WARN={warned}")
        return 0 if failed == 0 else 1


def compare(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    report = Report()

    # 1) DB 完整性
    integrity = after.get("db", {}).get("integrity")
    report.add("PASS" if integrity == "ok" else "FAIL", "db.integrity_check", str(integrity))
    fk = after.get("db", {}).get("foreign_key_violations")
    report.add("PASS" if fk == 0 else "FAIL", "db.foreign_key_check", f"violations={fk}")

    # 1.5) 数据前置：空库上的"数据检验"是空过，必须判 FAIL（2026-10-17 用户令）
    before_agg_probe = (before.get("db", {}).get("aggregates") or {})
    vm_count_t0 = int(before_agg_probe.get("vm_count") or 0)
    report.add(
        "PASS" if vm_count_t0 > 0 else "FAIL",
        "data.present",
        f"T0 vm_count={vm_count_t0}" + ("" if vm_count_t0 > 0 else "（空库，数据检验无效：先注入标准数据集）"),
    )

    # 2) 表级比对
    before_tables = before.get("db", {}).get("tables", {})
    after_tables = after.get("db", {}).get("tables", {})
    for table, spec in before_tables.items():
        kind = spec.get("kind")
        current = after_tables.get(table) or {}
        if kind == "volatile":
            report.add("PASS", f"table.{table}", "运行时表，不作判据")
            continue
        if not current:
            report.add("FAIL", f"table.{table}", "升级后表不存在")
            continue
        if kind == "strict":
            same = spec.get("digest") == current.get("digest") and spec.get("count") == current.get("count")
            report.add(
                "PASS" if same else "FAIL",
                f"table.{table}",
                f"count {spec.get('count')}->{current.get('count')} digest {spec.get('digest')}->{current.get('digest')}",
            )
        elif kind == "append_only":
            grew = int(current.get("count") or 0) >= int(spec.get("count") or 0)
            report.add(
                "PASS" if grew else "FAIL",
                f"table.{table}",
                f"count {spec.get('count')}->{current.get('count')}（只增）",
            )
        elif kind == "growable":
            max_pk = spec.get("max_pk")
            pk = spec.get("pk")
            if pk and max_pk is not None:
                # 用「升级前主键边界内」的指纹重算：新增行不影响，旧行变化会被抓到
                db_path = after.get("db", {}).get("path")
                digest_now = _digest_at_boundary(db_path, table, spec.get("columns") or [], pk, max_pk)
                same = digest_now == spec.get("digest")
                report.add(
                    "PASS" if same else "FAIL",
                    f"table.{table}",
                    f"旧行指纹 {spec.get('digest')}->{digest_now}（count {spec.get('count')}->{current.get('count')}）",
                )
            else:
                grew = int(current.get("count") or 0) >= int(spec.get("count") or 0)
                report.add("PASS" if grew else "FAIL", f"table.{table}", f"仅比较行数 {spec.get('count')}->{current.get('count')}")

    # 3) 表结构：不得删列/改类型
    before_schema = before.get("db", {}).get("schema", {})
    after_schema = after.get("db", {}).get("schema", {})
    for table, columns in before_schema.items():
        now = {c["name"]: c["type"] for c in after_schema.get(table) or []}
        if not now:
            report.add("FAIL", f"schema.{table}", "表被删除")
            continue
        missing = [c["name"] for c in columns if c["name"] not in now]
        retyped = [c["name"] for c in columns if c["name"] in now and now[c["name"]] != c["type"]]
        ok = not missing and not retyped
        report.add("PASS" if ok else "FAIL", f"schema.{table}", f"缺失列={missing} 类型变化={retyped}")

    # 4) 引用完整性
    for name, count in (after.get("db", {}).get("references") or {}).items():
        report.add("PASS" if count == 0 else "FAIL", f"refs.{name}", f"orphans={count}")

    # 5) 聚合口径（VM 数/容量合计）
    before_agg = before.get("db", {}).get("aggregates") or {}
    after_agg = after.get("db", {}).get("aggregates") or {}
    for key, value in before_agg.items():
        report.add(
            "PASS" if after_agg.get(key) == value else "FAIL",
            f"aggregate.{key}",
            f"{value}->{after_agg.get(key)}",
        )

    # 6) .env：键集合与密钥
    before_env = before.get("env") or {}
    after_env = after.get("env") or {}
    if before_env.get("exists"):
        missing = sorted(set(before_env.get("keys") or []) - set(after_env.get("keys") or []))
        report.add("PASS" if not missing else "FAIL", "env.keys", f"missing={missing}")
        report.add(
            "PASS" if before_env.get("sha256") == after_env.get("sha256") else "FAIL",
            "env.values",
            "密钥/配置值未变" if before_env.get("sha256") == after_env.get("sha256") else "值发生变化（可能是密钥被换）",
        )
        report.add(
            "PASS" if after_env.get("secret_present") and after_env.get("credential_present") else "FAIL",
            "env.secret_pair",
            "两枚密钥均在" if after_env.get("secret_present") and after_env.get("credential_present") else "密钥缺失",
        )

    # 7) Prometheus 历史窗口
    before_prom = before.get("prometheus") or {}
    after_prom = after.get("prometheus") or {}
    if before_prom.get("error") or after_prom.get("error"):
        report.add("WARN", "prometheus", f"不可达：{(after_prom.get('error') or before_prom.get('error'))}")
    else:
        window = before_prom.get("window") or {}
        base = after_prom.get("url") or before_prom.get("url")
        for metric, spec in (before_prom.get("metrics") or {}).items():
            if spec.get("error"):
                report.add("WARN", f"prom.{metric}", str(spec["error"])[:120])
                continue
            if not spec.get("points"):
                # 基线窗口里一个样本都没有 → 这个检查是**空过**，不能算 PASS
                report.add("WARN", f"prom.{metric}", "基线窗口内无样本（升级前需先完成一次采集）")
                continue
            try:
                data = prom_range(base, metric, window["start"], window["end"], window.get("step", 300))
                results = data.get("data", {}).get("result") or []
                points = [tuple(p) for s in results for p in s.get("values") or []]
                now_digest = sha16(points)
            except Exception as exc:  # noqa: BLE001
                report.add("WARN", f"prom.{metric}", f"重查失败：{exc}")
                continue
            same = now_digest == spec.get("digest")
            report.add(
                "PASS" if same else "FAIL",
                f"prom.{metric}",
                f"历史窗口 points {spec.get('points')}->{len(points)} digest {spec.get('digest')}->{now_digest}",
            )

    return report.emit()


def _digest_at_boundary(db_path: str | None, table: str, columns: list[str], pk: str, max_pk: Any) -> str | None:
    if not db_path or not Path(db_path).is_file():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = [tuple(r) for r in conn.execute(f"SELECT {', '.join(columns)} FROM {table} WHERE {pk} <= ?", (max_pk,))]
        return sha16(rows)
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="升级数据完整性快照/比对")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="采集一次快照")
    snap.add_argument("--db", help="SQLite 路径（默认按布局自动探测）")
    snap.add_argument("--env", help=".env 路径（默认按布局自动探测）")
    snap.add_argument("--compose", help="compose 路径（默认按布局自动探测）")
    snap.add_argument("--prom", help="Prometheus 地址，如 http://127.0.0.1:9090")
    snap.add_argument("--label", help="标注（如 t0/t1/final）")
    snap.add_argument("--out", required=True, help="输出 JSON 路径")
    snap.set_defaults(func=snapshot)

    cmp_ = sub.add_parser("compare", help="比对两次快照")
    cmp_.add_argument("--before", required=True)
    cmp_.add_argument("--after", required=True)
    cmp_.set_defaults(func=compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
