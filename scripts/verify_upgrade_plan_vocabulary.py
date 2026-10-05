#!/usr/bin/env python3
"""W7.1 门禁：升级计划动作词汇冻结（计划动作集 ⊆ 已发布 runner 动作集）。

工程规格：docs/superpowers/specs/2026-10-05-upgrade-architecture-v054-impl-spec.md §W7.1。

要拦的事故类别：**平台包下发了现场 runner 不会做的动作**。这类事故不会在编译期暴露，
而是在升级跑到一半才失败（US-04 的 cutover 之后失败、49-50 的
`post_upgrade.schedule_collection` 都是这一类）。因此把「编译出来的动作集是否落在
已发布 runner 的真实能力内」做成一条可重复执行的命令。

三步检查（与规格一致）：

1. **manifest schema_version 与已发布线一致** —— 变更即 fail。老编译器必须能读新包，
   schema 变更属于跨版本契约变更，不能由单个平台包单方面推进。
2. **动作词汇**：用**候选包内编译器**（候选平台包里的 web-api 镜像，不是工作区源码）
   对 `source_compatibility.supported_versions` 的**每一个**源版本生成计划，
   断言动作集 ⊆ 已发布 runner 组件包镜像内的动作集。
3. **编译器变更提示**：`git diff <published-tag>..HEAD -- backend/app/v2/upgrade/compiler.py`
   非空时输出「编译器有变更，需人工核对偏斜矩阵」警告（不 fail，但必须出现在发版检查单）。

已发布 runner 的动作集**从组件包镜像归档内的 `upgrade_runner/actions.py` 静态解析**
（`default_handlers()` 的字典键，AST，不 import、不 load 镜像），即「客户手里那份
runner 真正实现的动作」，而不是仓库里正在开发的动作表。

默认完全离线（除第 2 步需要 docker 载入候选包的 web-api 镜像）。

用法：
    python3 scripts/verify_upgrade_plan_vocabulary.py <平台包.tar.gz> \\
        --runner-package <已发布 runner 组件包.tar.gz> [--published-tag v0.5.3] [--json]
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# 已发布线的 manifest schema_version（平台包 v0.5.2 / v0.5.3 与 runner 组件包均为 "3"）。
# 改动这个常量等于宣告 schema 契约变更，必须同时证明「所有仍在支持矩阵内的老编译器都读得懂」，
# 属于发布决策而不是构建门禁的自动判定，因此做成显式常量 + 可用 --released-platform-package 覆盖。
RELEASED_SCHEMA_VERSION = "3"

DEFAULT_PUBLISHED_TAG = "v0.5.3"
COMPILER_SOURCE = "backend/app/v2/upgrade/compiler.py"

# 计划里出现这些动作类型就必然需要更高版本 runner（人类可读的失败原因补充）
_NOTE_SOURCE_COMPILED_BELOW = "v0.5.3"


class GateError(Exception):
    """门禁判定失败（区别于脚本自身崩溃）。"""


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runner_consistency_module():
    """复用 runner 交付一致性门禁里已验证的「镜像归档内 actions.py 静态解析」实现。

    不复制第二份解析逻辑：两处对「已发布 runner 支持哪些动作」的判定一旦分叉，
    门禁就会自相矛盾（这正是 US-02 类事故的形态）。
    """
    return _load_module(ROOT / "scripts" / "verify_runner_delivery_consistency.py", "_runner_consistency")


# ── 包读取 ────────────────────────────────────────────────────────────────
def _safe_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        relative = Path(member.name)
        if relative.is_absolute() or ".." in relative.parts:
            raise GateError(f"包内存在不安全成员：{member.name}")


def read_platform_manifest(package: Path) -> dict[str, Any]:
    with tarfile.open(package, mode="r:gz") as archive:
        _safe_members(archive)
        handle = archive.extractfile("manifest.json")
        if handle is None:
            raise GateError(f"平台包缺少 manifest.json：{package}")
        payload = json.loads(handle.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise GateError("平台包 manifest.json 不是对象")
    return payload


def read_released_schema_version(released_package: Path | None) -> str:
    if released_package is None:
        return RELEASED_SCHEMA_VERSION
    try:
        manifest = read_platform_manifest(Path(released_package))
    except (OSError, tarfile.TarError) as exc:
        raise GateError(f"无法读取已发布平台包 {released_package}：{exc}") from exc
    return str(manifest.get("schema_version") or "")


def runner_package_actions(package: Path) -> set[str]:
    """从已发布 runner 组件包镜像归档里静态解析动作集（不 load 镜像）。"""
    module = _runner_consistency_module()
    manifest = module.read_package_manifest(Path(package))
    archive_rel, _sha, _image = module.package_image_entry(manifest)
    if not archive_rel:
        raise GateError(f"runner 组件包 manifest 没有镜像归档条目：{package}")
    payload = module.inspect_image_archive(module.read_image_archive_member(Path(package), archive_rel))
    actions = payload.get("actions") or []
    if not actions:
        raise GateError(f"无法从 runner 组件包镜像内解析动作表：{package}")
    return {str(item) for item in actions}


def web_api_archive(manifest: dict[str, Any]) -> str:
    for component in manifest.get("components") or []:
        for image in component.get("images") or []:
            if image.get("service") == "web-api" and image.get("archive"):
                return str(image["archive"])
    raise GateError("平台包 manifest 未声明归档化的 web-api 镜像")


# ── 用候选包内编译器生成计划 ───────────────────────────────────────────────
_COMPILE_SCRIPT = r'''
import json, sys

marker = "SMARTX_PLAN_VOCABULARY:"
payload = {"by_source": {}, "errors": []}
try:
    from app.v2.upgrade.compiler import compile_execution_plan
except Exception as exc:  # pragma: no cover - 候选镜像内编译器不可导入
    print(marker + json.dumps({"import_error": str(exc)}))
    raise SystemExit(0)

_raw = sys.stdin.read()
if not _raw.strip():
    print(marker + json.dumps({"import_error": "manifest stdin 为空：候选包 manifest 未传入容器"}))
    raise SystemExit(0)
try:
    manifest = json.loads(_raw)
except Exception as exc:
    print(marker + json.dumps({"import_error": f"manifest 解析失败: {exc}"}))
    raise SystemExit(0)
sources = list((manifest.get("source_compatibility") or {}).get("supported_versions") or [])
for source in sources:
    # 每个源版本编译一次：源版本决定老 web-api 的编译器与 source_compatibility 校验口径，
    # 计划里的动作集必须对**所有**受支持源版本都落在已发布 runner 能力内。
    scoped = json.loads(json.dumps(manifest))
    scoped.setdefault("source_compatibility", {})
    scoped["source_compatibility"]["min_version"] = source
    scoped["min_version"] = source
    try:
        plan = compile_execution_plan(scoped)
    except Exception as exc:
        payload["errors"].append({"source_version": source, "error": f"{type(exc).__name__}: {exc}"})
        continue
    actions = []
    for action in plan.actions:
        actions.append({"id": str(action.id), "type": str(action.type)})
    payload["by_source"][source] = actions
print(marker + json.dumps(payload))
'''


def _run(command: list[str], cwd: Path | None = None, *, stdin: str | None = None) -> str:
    # input 与 stdin 不能同时给（Python 3.13 起直接抛 ValueError），
    # 因此按是否需要喂 stdin 分别构造参数。
    extra: dict[str, Any] = (
        {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    )
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        **extra,
    )
    if completed.returncode != 0:
        raise GateError(f"命令失败（{completed.returncode}）：{' '.join(command)}\n{completed.stdout[-4000:]}")
    return completed.stdout


def _loaded_image_reference(output: str) -> str:
    for line in reversed(output.splitlines()):
        line = line.strip()
        for prefix in ("Loaded image: ", "Loaded image ID: "):
            if line.startswith(prefix):
                return line[len(prefix):].strip()
    raise GateError(f"docker load 输出里没有已载入镜像引用：{output[-1000:]}")


def compile_plans_from_package(package: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """载入候选包的 web-api 镜像，在**镜像内**用候选编译器对每个源版本编译计划。"""
    with tempfile.TemporaryDirectory(prefix="smartx-plan-vocabulary-") as tmpdir:
        root = Path(tmpdir)
        with tarfile.open(package, mode="r:gz") as archive:
            _safe_members(archive)
            try:
                archive.extractall(root, filter="data")
            except TypeError:  # Python < 3.12 无 extraction filter
                archive.extractall(root)
        archive_rel = web_api_archive(manifest)
        image_tar = root / archive_rel
        if not image_tar.is_file():
            raise GateError(f"平台包缺少 web-api 镜像归档：{archive_rel}")
        loaded = _loaded_image_reference(_run(["docker", "load", "-i", str(image_tar)]))
        temporary_tag = f"smartx-plan-vocabulary:{str(manifest.get('version') or 'unknown').lstrip('v').replace('.', '-')}-{uuid.uuid4().hex[:12]}"
        _run(["docker", "tag", loaded, temporary_tag])
        try:
            output = _run(
                ["docker", "run", "--rm", "--network=none", "-i", "--entrypoint", "python", temporary_tag, "-c", _COMPILE_SCRIPT],
                stdin=json.dumps(manifest, ensure_ascii=False),
            )
        finally:
            try:
                _run(["docker", "image", "rm", "-f", temporary_tag])
            except GateError:
                pass
    for line in output.splitlines():
        if line.startswith("SMARTX_PLAN_VOCABULARY:"):
            return json.loads(line[len("SMARTX_PLAN_VOCABULARY:"):])
    raise GateError(f"候选包编译器未返回计划结果：{output[-1000:]}")


# ── 第 3 步：编译器变更提示 ────────────────────────────────────────────────
def compiler_diff(published_tag: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "diff", f"{published_tag}..HEAD", "--", COMPILER_SOURCE],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        return {"available": False, "detail": completed.stdout.strip()[:500]}
    diff = completed.stdout
    return {"available": True, "changed": bool(diff.strip()), "lines": len(diff.splitlines())}


# ── 门禁主体 ──────────────────────────────────────────────────────────────
def verify(
    *,
    platform_package: Path,
    runner_package: Path,
    released_platform_package: Path | None = None,
    published_tag: str = DEFAULT_PUBLISHED_TAG,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def record(check_id: str, status: str, detail: str) -> None:
        checks.append({"id": check_id, "status": status, "detail": detail})

    manifest = read_platform_manifest(platform_package)
    version = str(manifest.get("version") or "")
    record("package_manifest", "PASS", f"平台包版本 {version}；package_type={manifest.get('package_type')}")

    # ① schema_version 与已发布线一致
    released_schema = read_released_schema_version(released_platform_package)
    candidate_schema = str(manifest.get("schema_version") or "")
    if candidate_schema != released_schema:
        record(
            "manifest_schema_version",
            "FAIL",
            f"manifest.schema_version={candidate_schema!r} 与已发布线 {released_schema!r} 不一致："
            "老编译器可能读不懂该包（跨版本契约变更不能由单个平台包推进）",
        )
    else:
        record("manifest_schema_version", "PASS", f"manifest.schema_version = {candidate_schema}（与已发布线一致）")

    # ② 动作词汇：候选包编译器 × 每个源版本 ⊆ 已发布 runner 动作集
    released_actions = runner_package_actions(runner_package)
    compile_result = compile_plans_from_package(platform_package, manifest)
    if compile_result.get("import_error"):
        record("plan_actions_subset", "FAIL", f"候选包内编译器不可导入：{compile_result['import_error']}")
    elif compile_result.get("errors"):
        detail = "; ".join(f"{item['source_version']}: {item['error']}" for item in compile_result["errors"])
        record("plan_actions_subset", "FAIL", f"候选包编译器对某些源版本编译失败：{detail}")
    else:
        by_source: dict[str, Any] = compile_result.get("by_source") or {}
        if not by_source:
            record(
                "plan_actions_subset",
                "FAIL",
                "manifest.source_compatibility.supported_versions 为空：无法确定偏斜矩阵的源版本格",
            )
        else:
            offenders: list[str] = []
            union: set[str] = set()
            for source in sorted(by_source):
                actions = {str(item["type"]) for item in by_source[source]}
                union |= actions
                missing = sorted(actions - released_actions)
                if missing:
                    offenders.append(f"{source} → {', '.join(missing)}")
            if offenders:
                record(
                    "plan_actions_subset",
                    "FAIL",
                    "计划用了已发布 runner 不支持的动作：" + "；".join(offenders)
                    + f"（已发布 runner 支持 {len(released_actions)} 个动作）",
                )
            else:
                record(
                    "plan_actions_subset",
                    "PASS",
                    f"{len(by_source)} 个源版本的计划动作集（并集 {len(union)} 个）全部落在已发布 runner "
                    f"动作集（{len(released_actions)} 个）内：{'、'.join(sorted(union))}",
                )
            record(
                "plan_actions_matrix",
                "PASS",
                "偏斜矩阵：" + "；".join(f"{source}={len(by_source[source])} 动作" for source in sorted(by_source)),
            )
            legacy_sources = sorted(source for source in by_source if source < _NOTE_SOURCE_COMPILED_BELOW)
            if legacy_sources:
                record(
                    "plan_source_compiled_downstream",
                    "WARN",
                    f"源版本 {', '.join(legacy_sources)} 低于 {_NOTE_SOURCE_COMPILED_BELOW}："
                    "这些格的实际计划由**源端已发布 web-api 的老编译器**生成，本门禁只证明了"
                    "「候选包编译器对同一 manifest 编译出的动作集合规」，不能替代老编译器在该格的行为验证"
                    "（后者由兼容矩阵 M1/M4 与 .12 老链路回归覆盖）",
                )

    # ③ 编译器变更提示（不 fail）
    diff = compiler_diff(published_tag)
    if not diff.get("available"):
        record("compiler_changed", "WARN", f"无法比较编译器与 {published_tag} 的差异：{diff.get('detail')}")
    elif diff.get("changed"):
        record(
            "compiler_changed",
            "WARN",
            f"编译器相对 {published_tag} 有变更（{diff.get('lines')} 行 diff）："
            "需人工核对偏斜矩阵，确认各源版本的计划形状；本次结果见上方 plan_actions_matrix",
        )
    else:
        record("compiler_changed", "PASS", f"编译器相对 {published_tag} 无变更")

    failures = [item["id"] for item in checks if item["status"] == "FAIL"]
    warnings = [item["id"] for item in checks if item["status"] == "WARN"]
    return {
        "ok": not failures,
        "platform_package": str(platform_package),
        "runner_package": str(runner_package),
        "version": version,
        "released_runner_actions": sorted(released_actions),
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
    }


def _format(result: dict[str, Any]) -> str:
    lines = [
        f"upgrade plan vocabulary: {result['version']} "
        f"({'OK' if result['ok'] else 'FAILED'}; released runner actions={len(result['released_runner_actions'])})",
    ]
    for item in result["checks"]:
        lines.append(f"  [{item['status']:4}] {item['id']}: {item['detail']}")
    if result["failures"]:
        lines.append(f"FAILED checks: {', '.join(result['failures'])}")
    if result["warnings"]:
        lines.append(f"WARN checks（必须出现在发版检查单）: {', '.join(result['warnings'])}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the candidate platform package's upgrade plan vocabulary.")
    parser.add_argument("platform_package", type=Path, help="候选平台包（.tar.gz）")
    parser.add_argument("--runner-package", type=Path, required=True, help="已发布 runner 组件包（Release 资产）")
    parser.add_argument("--released-platform-package", type=Path, help="已发布平台包（用于取 schema_version 基准）")
    parser.add_argument("--published-tag", default=DEFAULT_PUBLISHED_TAG, help="已发布 tag（编译器变更对比基准）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args()

    try:
        result = verify(
            platform_package=args.platform_package,
            runner_package=args.runner_package,
            released_platform_package=args.released_platform_package,
            published_tag=args.published_tag,
        )
    except GateError as exc:
        print(f"upgrade plan vocabulary: GATE ERROR\n  {exc}")
        raise SystemExit(2) from exc

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format(result))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
