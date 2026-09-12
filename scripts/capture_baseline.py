#!/usr/bin/env python3
"""Capture/verify a standard business baseline artifact.

标准业务基线 = SQLite 业务库（VACUUM INTO 一致性快照，无需停服）+ 配套 .env +（可选）Prometheus 数据目录。
产物带 SHA256SUMS 与 manifest.json（含库内行数），verify 模式可独立校验。

用法见 capture_baseline_parse_args --help。仅使用标准库，宿主机 python3 直接运行。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

COUNT_TABLES = ("users", "towers", "clusters", "vm_latest", "vm_volumes", "collection_runs")


def capture_baseline_parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="生成基线产物目录")
    capture.add_argument("--name", required=True, help="基线名称（产物目录名）")
    capture.add_argument("--db", required=True, help="源 SQLite 业务库路径")
    capture.add_argument("--env", required=True, help="源 .env 路径（配套凭据密钥）")
    capture.add_argument("--output", required=True, help="产物父目录")
    capture.add_argument("--prometheus", default=None, help="源 Prometheus 数据目录（默认尝试标准路径）")
    capture.add_argument("--skip-prometheus", action="store_true", help="不包含 Prometheus 数据")

    verify = sub.add_parser("verify", help="校验基线产物目录")
    verify.add_argument("--dir", required=True, help="基线产物目录")
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sha256sums(baseline_dir: Path) -> None:
    lines = []
    for path in sorted(baseline_dir.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        rel = path.relative_to(baseline_dir).as_posix()
        lines.append(f"{_sha256(path)}  {rel}")
    (baseline_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _db_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        counts = {}
        for table in COUNT_TABLES:
            try:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.OperationalError:
                counts[table] = -1
        return counts
    finally:
        conn.close()


def _check_integrity(db_path: Path) -> str:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def _vacuum_into(source: Path, target: Path) -> None:
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    finally:
        conn.close()


def capture(args: argparse.Namespace) -> int:
    source_db = Path(args.db)
    source_env = Path(args.env)
    if not source_db.is_file():
        raise SystemExit(f"source db not found: {source_db}")
    if not source_env.is_file():
        raise SystemExit(f"source env not found: {source_env}")

    baseline_dir = Path(args.output) / args.name
    if baseline_dir.exists():
        raise SystemExit(f"baseline dir already exists: {baseline_dir}")
    baseline_dir.mkdir(parents=True)

    snapshot = baseline_dir / "smartx.db"
    _vacuum_into(source_db, snapshot)

    tower_env = baseline_dir / "tower.env"
    shutil.copyfile(source_env, tower_env)
    os.chmod(tower_env, 0o600)

    prometheus_copy = "skipped"
    if not args.skip_prometheus:
        source_prom = Path(args.prometheus) if args.prometheus else Path("/data/smartx-storage-forecast/prometheus")
        if source_prom.is_dir():
            shutil.copytree(source_prom, baseline_dir / "prometheus")
            prometheus_copy = "live"
        else:
            print(f"[warn] prometheus dir not found, skipped: {source_prom}")

    counts = _db_counts(snapshot)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name": args.name,
        "sources": {"db": str(source_db), "env": str(source_env)},
        "prometheus_copy": prometheus_copy,
        "db_integrity": _check_integrity(snapshot),
        "db_counts": counts,
    }
    (baseline_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_sha256sums(baseline_dir)
    print(f"baseline captured: {baseline_dir}")
    print(json.dumps({"counts": counts, "integrity": manifest["db_integrity"], "prometheus": prometheus_copy}, ensure_ascii=False))
    return 0


def verify(args: argparse.Namespace) -> int:
    baseline_dir = Path(args.dir)
    sums_file = baseline_dir / "SHA256SUMS"
    manifest_file = baseline_dir / "manifest.json"
    db_file = baseline_dir / "smartx.db"
    for required in (sums_file, manifest_file, db_file):
        if not required.is_file():
            raise SystemExit(f"missing baseline file: {required}")

    for line in sums_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split("  ", 1)
        actual = _sha256(baseline_dir / rel)
        if actual != expected:
            raise SystemExit(f"sha mismatch: {rel}")

    integrity = _check_integrity(db_file)
    if integrity != "ok":
        raise SystemExit(f"integrity_check failed: {integrity}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    counts = _db_counts(db_file)
    for table, expected in manifest.get("db_counts", {}).items():
        if expected >= 0 and counts.get(table) != expected:
            raise SystemExit(f"count mismatch for {table}: manifest={expected} actual={counts.get(table)}")

    print("baseline ok")
    print(json.dumps({"counts": counts, "integrity": integrity}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = capture_baseline_parse_args(argv)
    if args.command == "capture":
        return capture(args)
    return verify(args)


if __name__ == "__main__":
    sys.exit(main())
