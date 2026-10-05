from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: project 目录下主 compose 文件名（US-32 对账与 W3 自换 writeback 共用同一份）。
COMPOSE_FILENAME = "docker-compose.yml"


class CommandExecutor:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
    ) -> None:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return
        subprocess.run(command, cwd=str(cwd) if cwd else None, timeout=timeout, check=True)

    def output(self, command: list[str], *, cwd: Path | None = None) -> str:
        if os.environ.get("SMARTX_UPGRADE_DRY_RUN") == "1":
            return ""
        result = subprocess.run(command, cwd=str(cwd) if cwd else None, check=True, text=True, capture_output=True)
        return result.stdout


@dataclass
class ActionContext:
    package_path: Path
    project_path: Path
    data_path: Path
    upgrades_path: Path
    backups_path: Path
    exports_path: Path
    compose_runtime_path: Path
    prometheus_path: Path
    compose_file: str
    compose_project: str
    executor: CommandExecutor
    task_id: str = "upgrade-task"
    target_version: str = "unknown"
    host_data_path: Path | None = None
    host_upgrades_path: Path | None = None
    host_backups_path: Path | None = None
    host_exports_path: Path | None = None
    host_compose_runtime_path: Path | None = None
    host_prometheus_path: Path | None = None
    host_project_path: Path | None = None
    current_container_id: str = ""

    @classmethod
    def minimal(
        cls,
        root: Path,
        *,
        executor: CommandExecutor | None = None,
        package_path: Path | None = None,
        project_path: Path | None = None,
    ) -> "ActionContext":
        root = Path(root)
        context = cls(
            package_path=package_path or root / "package",
            project_path=project_path or root / "project",
            data_path=root / "data",
            upgrades_path=root / "upgrades",
            backups_path=root / "backups",
            exports_path=root / "exports",
            compose_runtime_path=root / "compose-runtime",
            prometheus_path=root / "prometheus",
            compose_file="docker-compose.offline.yml",
            compose_project="smartx-hci-capacity-insight",
            executor=executor or CommandExecutor(),
        )
        for path in (
            context.package_path,
            context.project_path,
            context.data_path,
            context.upgrades_path,
            context.backups_path,
            context.exports_path,
            context.compose_runtime_path,
            context.prometheus_path,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return context

    def as_dict(self) -> dict[str, Any]:
        return {"action_context": self}

    def docker_host_path(self, source: Path) -> Path:
        resolved = source.resolve()
        host_roots = tuple(
            root.resolve()
            for root in (
                self.host_backups_path,
                self.host_compose_runtime_path,
                self.host_prometheus_path,
                self.host_project_path,
                self.host_upgrades_path,
                self.host_exports_path,
                self.host_data_path,
            )
            if root is not None
        )
        for host_root in host_roots:
            if resolved == host_root or host_root in resolved.parents:
                return source
        mappings = (
            (self.backups_path.resolve(), self.host_backups_path),
            (self.compose_runtime_path.resolve(), self.host_compose_runtime_path),
            (self.prometheus_path.resolve(), self.host_prometheus_path),
            (self.project_path.resolve(), self.host_project_path),
            (self.upgrades_path.resolve(), self.host_upgrades_path),
            (self.exports_path.resolve(), self.host_exports_path),
            (self.data_path.resolve(), self.host_data_path),
        )
        for container_root, host_root in mappings:
            if host_root is not None and (resolved == container_root or container_root in resolved.parents):
                return Path(host_root) / resolved.relative_to(container_root)
        return source


def _context(payload: dict[str, Any]) -> ActionContext:
    context = payload.get("action_context")
    if not isinstance(context, ActionContext):
        raise TypeError("ActionContext 缺失。")
    return context


def _persist_checkpoint(payload: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    writer = payload.get("checkpoint_writer")
    if callable(writer):
        writer(checkpoint)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"路径不在允许白名单内：{value}")
    return path


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    try:
        archive.extractall(destination, filter="data")
    except TypeError:  # Python < 3.12 has no extraction filter argument.
        archive.extractall(destination)


def _runner_image_from_task(task: Any) -> str:
    """取"该写进 compose 的 runner 镜像"。

    **以执行计划为准，不以 manifest 为准**：平台升级时 web-api 只在内存里把现场镜像注入
    编译用的计划（`_inject_field_runner_image`），落盘的 `task.json` 里 manifest 仍是包内
    基线（实测 v0.3.1）。现场镜像出现在两个计划动作里：
      - `schedule-runner-target-runtime-handoff` 的 `params.image`（权威，handoff 实际用的）
      - `write-compose-override` 的 `params.images[]` 中 service=upgrade-runner 条目
    两者都取不到时才退回 manifest（组件升级的计划未必带 handoff）。
    """
    if not isinstance(task, dict):
        return ""
    plan = task.get("execution_plan")
    actions = plan.get("actions") if isinstance(plan, dict) else None
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        params = action.get("params") or {}
        if str(action.get("type") or "").startswith("runner.handoff"):
            image = str(params.get("image") or "").strip()
            if image:
                return image
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        for image in (action.get("params") or {}).get("images") or []:
            if isinstance(image, dict) and str(image.get("service") or "") == "upgrade-runner":
                declared = str(image.get("image") or "").strip()
                if declared:
                    return declared
    manifest = task.get("manifest")
    if isinstance(manifest, dict):
        for component in manifest.get("components") or []:
            if not isinstance(component, dict):
                continue
            for image in component.get("images") or []:
                if isinstance(image, dict) and str(image.get("service") or "") == "upgrade-runner":
                    return str(image.get("image") or "").strip()
    return ""


def reconcile_project_runner_tag(context: ActionContext, task: dict[str, Any]) -> str:
    """US-32：把 project compose 里的 runner tag 对齐到本次计划声明的镜像。

    为什么必须在 runner 侧做：web-api 的 project 目录是**只读挂载**
    （`docker-compose.yml` 里 `:ro`），它调用的同名回写函数写入必然抛 OSError 并被
    `except OSError: continue` 吞掉 —— US-26 的 compose 回写因此自实现起从未生效，
    compose 长期停留在包内基线（如 v0.3.1）而现场实际跑 v0.3.2。
    任何一次宿主侧 `docker compose up -d` 都会据此把 runner 静默降级。

    放在任务收尾（所有动作完成、project 文件同步之后）执行，用计划里已注入的现场镜像，
    不需要 `docker inspect`，也不新增动作/能力集 —— 旧 runner 缺这段逻辑只是维持现状，
    不会让升级失败，平台包的 minimum_runner_version 无需变更。
    """
    runner_image = _runner_image_from_task(task)
    if not runner_image:
        return ""
    compose_path = context.project_path / "docker-compose.yml"
    try:
        if not compose_path.is_file():
            return ""
        lines = compose_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        # 绝不静默：写不进去必须留痕，否则又是一次长期潜伏的多事实源
        logging.getLogger(__name__).warning(
            "US-32 runner tag 对账跳过（compose 不可读 %s）：%s", compose_path, exc
        )
        return ""
    in_runner = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not in_runner:
            if stripped == "upgrade-runner:" or stripped.startswith("upgrade-runner:"):
                in_runner = True
            continue
        if line[:1].strip() == "" and stripped and ":" in stripped and not stripped.startswith("#"):
            if not line.startswith((" ", "\t")):
                break
        if stripped.startswith("image:"):
            current = stripped.split("image:", 1)[1].strip()
            if current == runner_image:
                return ""
            prefix = line[: line.index("image:") + len("image:")]
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{prefix} {runner_image}{newline}"
            try:
                compose_path.write_text("".join(lines), encoding="utf-8")
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "US-32 runner tag 对账失败（compose 不可写 %s）：%s", compose_path, exc
                )
                return ""
            logging.getLogger(__name__).warning(
                "US-32 compose runner tag 已对齐：%s -> %s（此前不一致会让 compose 重建降级 runner）",
                current, runner_image,
            )
            return current
    return ""


def component_verify(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    """组件包校验（自换第 1 步）：复核镜像 tar 的 SHA256 与 manifest 声明一致。

    为什么 load 之前要单独一步：web-api 收包时验过一次，但那是在**上传路径**上验的，
    中间隔着落盘、任务目录搬运与 runner 拾取。自换会把 runner 自己换掉，
    带着一个坏镜像完成自换 = 新 runner 起不来且旧 runner 已经退出，
    现场只剩一个没有执行器的平台——必须执行前再核一次。
    """
    context = _context(context_payload)
    params = action.get("params", {})
    archive = context.package_path / _safe_relative(str(params.get("archive") or ""))
    if not archive.is_file():
        raise FileNotFoundError(f"组件镜像归档不存在：{archive}")
    actual = _sha256(archive)
    expected = str(params.get("sha256") or "")
    if not expected:
        raise ValueError("组件包未声明镜像归档 SHA256，拒绝执行自换。")
    if actual != expected:
        raise ValueError(f"组件镜像归档校验失败：{archive.name}")
    return {
        "archive": str(archive),
        "sha256": actual,
        "size_bytes": archive.stat().st_size,
        "checkpoint": {"verified": True, "sha256": actual},
    }


def component_image_load(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    """加载组件新镜像（自换第 2 步）——`image.load` 的同义动作。

    与 `image.load` 逻辑一致，单独命名是为了让**任务步骤**读起来是"加载组件新镜像"
    而不是"加载升级镜像"（组件升级任务里没有"升级"这回事）。
    新动作类型只出现在由 v0.3.2+ runner 执行的任务中，符合动作词汇冻结纪律
    （impl-spec §0.3：平台升级计划仍只用 v0.3.1 的 26 个动作）。
    """
    return image_load(action, context_payload)


def component_compose_writeback(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    """写入组件自身部署配置（自换第 3 步）：把 compose 里的 runner tag 对齐到新镜像。

    **回滚锚点必须在调用本动作之前捕获**（`selfhandoff.capture_component_rollback_anchor`）。
    writeback 会覆盖 `docker-compose.yml` 里的 image 行，anchor 的
    `previous_image_tag` / `previous_image_id` 只在被覆盖之前读得到——顺序反了，
    锚点里记到的就是新版本，组件回滚会退化成"把新版本换回新版本"。

    幂等：tag 已经等于目标值时直接返回，不重复写。
    """
    context = _context(context_payload)
    target_image = str(action.get("params", {}).get("image") or "").strip()
    if not target_image:
        raise ValueError("自换 writeback 缺少目标镜像。")
    compose_path = context.project_path / COMPOSE_FILENAME
    if not compose_path.is_file():
        raise FileNotFoundError(f"project compose 不存在：{compose_path}")
    lines = compose_path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_runner = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not in_runner:
            if stripped.startswith("upgrade-runner:"):
                in_runner = True
            continue
        if line[:1].strip() == "" and stripped.endswith(":") and not stripped.startswith("#"):
            break
        if stripped.startswith("image:"):
            current = stripped.split("image:", 1)[1].strip()
            if current == target_image:
                return {
                    "image": target_image,
                    "changed": False,
                    "previous_image_tag": current,
                    "checkpoint": {"aligned": True, "changed": False},
                }
            prefix = line[: line.index("image:") + len("image:")]
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{prefix} {target_image}{newline}"
            temporary = compose_path.with_suffix(".tmp")
            try:
                temporary.write_text("".join(lines), encoding="utf-8")
                os.replace(temporary, compose_path)
            except OSError as exc:
                raise OSError(f"写入 runner compose tag 失败：{compose_path}：{exc}") from exc
            logging.getLogger(__name__).warning(
                "runner 自换 compose tag 已对齐：%s -> %s", current, target_image
            )
            return {
                "image": target_image,
                "changed": True,
                "previous_image_tag": current,
                "compose_file": str(compose_path),
                "checkpoint": {"aligned": True, "changed": True, "previous_image_tag": current},
            }
    raise ValueError(f"compose 中未找到 upgrade-runner 的 image 声明：{compose_path}")


def component_schedule_self_handoff(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    """调度执行器自换（自换第 4 步，也是本任务的最后一步）。

    委托给 v0.3.1 已有的 `runner.schedule_target_runtime_handoff`——动作词汇冻结：
    不新造 handoff 机制，只在它前面加一道「锚点已就绪」的断言。
    委托后原样透传 `handoff_final` 哨兵，`UpgradeEngine` 见哨兵即停。
    """
    params = action.get("params", {})
    anchor = params.get("rollback_anchor") or {}
    if not anchor:
        # 锚点缺失不该静默通过：组件回滚能力会在自换成功后静默消失，
        # 而现场已经没有任何进程能重新读出旧 tag。
        raise ValueError("自换缺少回滚锚点，拒绝调度 handoff（writeback 之后旧 tag 已不可读）。")
    delegated = dict(action)
    delegated["type"] = "runner.schedule_target_runtime_handoff"
    delegated["params"] = {**params, "rollback_anchor": anchor}
    result = runner_schedule_target_runtime_handoff(delegated, context_payload)
    return {**result, "rollback_anchor": anchor}


def backup_create(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    scope = str(action.get("params", {}).get("scope") or "platform")
    context.backups_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    final_path = context.backups_path / f"upgrade-{context.target_version}-before-{timestamp}.tar.gz"
    temporary_path = final_path.with_suffix(final_path.suffix + ".tmp")
    with tempfile.TemporaryDirectory(dir=context.backups_path) as tmpdir:
        snapshot = Path(tmpdir) / "smartx.db"
        database = context.data_path / "smartx.db"
        if database.is_file():
            with sqlite3.connect(database) as source, sqlite3.connect(snapshot) as destination:
                source.backup(destination)
        with tarfile.open(temporary_path, mode="w:gz") as archive:
            if snapshot.is_file():
                archive.add(snapshot, arcname="app/smartx.db", recursive=False)
            if scope in {"observability", "bundle"} and context.prometheus_path.exists():
                for path in sorted(context.prometheus_path.rglob("*")):
                    relative = path.relative_to(context.prometheus_path)
                    if any(part in {"wal", "chunks_head", "lock", "queries.active"} for part in relative.parts):
                        continue
                    archive.add(path, arcname=str(Path("prometheus") / relative), recursive=False)
    os.replace(temporary_path, final_path)
    return {
        "path": str(final_path),
        "scope": scope,
        "sha256": _sha256(final_path),
        "checkpoint": {"completed": True, "path": str(final_path)},
    }


def image_load(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    archive = context.package_path / _safe_relative(str(params.get("archive") or ""))
    if not archive.is_file():
        raise FileNotFoundError(f"镜像归档不存在：{archive}")
    actual = _sha256(archive)
    expected = str(params.get("sha256") or "")
    if expected and actual != expected:
        raise ValueError(f"镜像归档校验失败：{archive.name}")
    context.executor.run(["docker", "load", "-i", str(archive)])
    return {"image": params.get("image"), "checkpoint": {"sha256": actual, "loaded": True}}


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


HOST_CLEANUP_HELPER_SCRIPT = r"""
import json
import os
import pathlib
import shutil
import sys

paths = json.loads(os.environ.get("SMARTX_CLEANUP_PATHS", "[]"))
protected = {str(pathlib.PurePosixPath(str(item))) for item in json.loads(os.environ.get("SMARTX_PROTECTED_PATHS", "[]"))}
host_root = pathlib.Path("/host")
results = []

def unsafe(raw):
    value = str(raw or "").strip()
    if not value:
        return "empty path"
    logical = pathlib.PurePosixPath(value)
    if not logical.is_absolute():
        return "not absolute"
    if ".." in logical.parts:
        return "contains .."
    if str(logical) in {"/", "/data", "/opt"}:
        return "critical system path"
    if str(logical) in protected:
        return "protected target path"
    return ""

for raw in paths:
    reason = unsafe(raw)
    if reason:
        raise SystemExit(f"refusing cleanup path {raw}: {reason}")
    logical = pathlib.PurePosixPath(str(raw))
    target = host_root.joinpath(*logical.parts[1:])
    try:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
            results.append({"path": str(raw), "status": "deleted"})
        elif target.exists() or target.is_symlink():
            target.unlink()
            results.append({"path": str(raw), "status": "deleted"})
        else:
            results.append({"path": str(raw), "status": "missing"})
    except Exception as exc:
        print(json.dumps({"path": str(raw), "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise

print(json.dumps(results, ensure_ascii=False))
"""


def _cleanup_paths_with_host_helper(
    paths: list[str],
    protected_paths: set[str],
    *,
    helper_image: str,
    context: ActionContext,
) -> list[dict[str, str]]:
    command = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "-v",
        "/:/host",
        "-e",
        f"SMARTX_CLEANUP_PATHS={json.dumps(paths, ensure_ascii=False)}",
        "-e",
        f"SMARTX_PROTECTED_PATHS={json.dumps(sorted(protected_paths), ensure_ascii=False)}",
        "--entrypoint",
        "python",
        helper_image,
        "-c",
        HOST_CLEANUP_HELPER_SCRIPT,
    ]
    output = context.executor.output(command)
    if not output.strip():
        return [{"path": path, "status": "deleted"} for path in paths]
    try:
        parsed = json.loads(output.strip().splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("无法解析宿主机清理 helper 输出。") from exc
    if not isinstance(parsed, list):
        raise RuntimeError("宿主机清理 helper 输出格式错误。")
    return [{"path": str(item.get("path") or ""), "status": str(item.get("status") or "")} for item in parsed if isinstance(item, dict)]


def _backup_existing_path(source: Path, backup: Path) -> str | None:
    if not source.exists() and not source.is_symlink():
        return None
    backup.parent.mkdir(parents=True, exist_ok=True)
    _remove_path(backup)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, backup)
        shutil.rmtree(source)
        return "directory"
    shutil.copy2(source, backup)
    source.unlink()
    return "file"


def files_sync(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    source_root = context.package_path / _safe_relative(str(params.get("source") or "project"))
    target_root_value = str(params.get("target") or "")
    target_root = _safe_relative(target_root_value) if target_root_value else Path("")
    checksums = {str(key): str(value) for key, value in (params.get("checksums") or {}).items()}
    declared = [str(item) for item in params.get("files") or []]
    if not declared:
        declared = [str(path.relative_to(source_root)) for path in sorted(source_root.rglob("*")) if path.is_file()]
    completed = {str(item.get("path")) for item in action.get("checkpoint", {}).get("files") or []}
    journal = list(action.get("checkpoint", {}).get("files") or [])
    backup_root = context.backups_path / f"project-files-{context.task_id}"
    for value in declared:
        relative = _safe_relative(value)
        if str(relative) in completed:
            continue
        source = source_root / relative
        if not source.is_file():
            raise FileNotFoundError(f"项目文件不存在：{relative}")
        expected = checksums.get(str(relative))
        if expected and _sha256(source) != expected:
            raise ValueError(f"项目文件校验失败：{relative}")
        target_relative = target_root / relative
        target = context.project_path / target_relative
        backup = backup_root / target_relative
        backup_type = _backup_existing_path(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        journal.append(
            {
                "path": str(target_relative),
                "sha256": _sha256(target),
                "backup": str(backup) if backup.exists() else None,
                "backup_type": backup_type,
            }
        )
        _persist_checkpoint(context_payload, {"files": journal})
    return {"backup_path": str(backup_root), "checkpoint": {"files": journal, "completed": True}}


APP_RUNTIME_ENTRIES = {"backups", "exports", "upgrades", "compose-runtime", "prometheus", "lost+found"}
PROMETHEUS_RUNTIME_ENTRIES = {"wal", "chunks_head", "lock", "queries.active"}
IMAGE_TAG_ENV_KEYS = {"SMARTX_IMAGE_TAG", "SMARTX_RUNNER_IMAGE_TAG", "SMARTX_APP_VERSION", "SMARTX_RUNNER_VERSION"}
DB_COUNT_TABLES = ("users", "towers", "clusters", "vm_latest", "vm_volumes", "collection_runs")
DB_BUSINESS_TABLES = ("towers", "clusters", "vm_latest", "vm_volumes")
DEFAULT_ENV_LINES = [
    "SMARTX_SECRET_KEY=replace-with-a-long-random-secret",
    "SMARTX_CREDENTIAL_KEY=replace-with-a-different-long-random-secret",
    "SMARTX_ADMIN_USER=admin",
    "SMARTX_ADMIN_PASSWORD=password",
    "SMARTX_DB_PATH=/data/smartx.db",
    "SMARTX_PROMETHEUS_URL=http://prometheus:9090",
    "SMARTX_COLLECTION_TIMEZONE=Asia/Shanghai",
    "SMARTX_COLLECTION_HOUR=2",
    "SMARTX_COLLECTION_MINUTE=10",
]

CREDENTIAL_ENV_CHECK_SCRIPT = r"""
import json

from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.inventory.service import InventoryService

settings = V2Settings()
database = V2Database(settings)
service = InventoryService(database, settings)
encrypted_credentials = 0
authenticated_credentials = 0
unauthenticated_credentials = 0
compatible = True
with database.connection() as connection:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(towers)").fetchall()
    }
    if {"password_encrypted", "api_token_encrypted"}.issubset(columns):
        rows = connection.execute(
            "SELECT password_encrypted, api_token_encrypted FROM towers"
        ).fetchall()
        for row in rows:
            for value in (row["password_encrypted"], row["api_token_encrypted"]):
                if not value:
                    continue
                encrypted_credentials += 1
                if str(value).startswith("gAAAA"):
                    authenticated_credentials += 1
                else:
                    unauthenticated_credentials += 1
                if not service._decrypt_tower_secret(value):
                    compatible = False

print(json.dumps({
    "encrypted_credentials": encrypted_credentials,
    "authenticated_credentials": authenticated_credentials,
    "unauthenticated_credentials": unauthenticated_credentials,
    "compatible": compatible,
}))
"""


def _sanitize_env_text(text: str, *, sanitize_image_tags: bool) -> str:
    if not sanitize_image_tags:
        return text if text.endswith("\n") else f"{text}\n"
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in IMAGE_TAG_ENV_KEYS:
                continue
        lines.append(line)
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_env_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    try:
        os.chown(path, 0, 0)
    except (PermissionError, AttributeError):
        pass


def _encrypted_tower_credential_count(database_path: Path) -> int:
    if not database_path.is_file():
        return 0
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(towers)").fetchall()
        }
        credential_columns = {"password_encrypted", "api_token_encrypted"}
        present_credential_columns = credential_columns & columns
        if not columns:
            return 0
        if present_credential_columns and present_credential_columns != credential_columns:
            missing = ", ".join(sorted(credential_columns - present_credential_columns))
            raise RuntimeError(f"Tower 凭据字段不完整，缺少：{missing}")
        if not present_credential_columns:
            return 0
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM towers
            WHERE COALESCE(password_encrypted, '') <> ''
               OR COALESCE(api_token_encrypted, '') <> ''
            """
        ).fetchone()
    except RuntimeError:
        raise
    except sqlite3.Error as exc:
        raise RuntimeError(f"无法读取 Tower 凭据数据库：{database_path}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
    return int(row[0] if row else 0)


def _check_env_credential_compatibility(
    *,
    database_path: Path,
    env_path: Path,
    helper_image: str,
    context: ActionContext,
    target_root: Path | None = None,
) -> dict[str, Any]:
    if not helper_image:
        raise RuntimeError("Tower 凭据迁移需要 web-api helper 镜像验证密钥兼容性。")

    def helper_host_path(path: Path) -> Path:
        resolved = path.resolve()
        if target_root is not None and target_root.is_absolute():
            resolved_target_root = target_root.resolve()
            if resolved == resolved_target_root or resolved_target_root in resolved.parents:
                return path
        return context.docker_host_path(path)

    host_database_path = helper_host_path(database_path)
    host_env_path = helper_host_path(env_path)
    output = context.executor.output(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "-v",
            f"{host_database_path}:/check/smartx.db:ro",
            "-v",
            f"{host_env_path}:/check/runtime.env:ro",
            "--env-file",
            str(host_env_path),
            "-e",
            "SMARTX_DB_PATH=/check/smartx.db",
            "--entrypoint",
            "python",
            helper_image,
            "-c",
            CREDENTIAL_ENV_CHECK_SCRIPT,
        ]
    )
    try:
        result = json.loads(output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("无法解析 Tower 凭据密钥兼容性检查结果。") from exc
    return {
        "encrypted_credentials": int(result.get("encrypted_credentials") or 0),
        "authenticated_credentials": int(result.get("authenticated_credentials") or 0),
        "unauthenticated_credentials": int(result.get("unauthenticated_credentials") or 0),
        "compatible": bool(result.get("compatible")),
    }


def _migrate_env_file(
    params: dict[str, Any],
    project_path: Path,
    *,
    database_path: Path,
    database_migrated_from_legacy: bool,
    helper_image: str,
    context: ActionContext,
    target_root: Path | None = None,
) -> dict[str, Any]:
    config = params.get("env_file_migration")
    if not isinstance(config, dict) or not config:
        return {"status": "not_configured"}
    target = Path(str(config.get("target") or project_path / ".env"))
    sanitize_image_tags = bool(config.get("sanitize_image_tags", True))
    legacy_candidates = [Path(str(value)) for value in config.get("legacy_candidates") or [] if str(value)]
    candidates = legacy_candidates + [target] if database_migrated_from_legacy else [target] + legacy_candidates
    existing_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen or not candidate.is_file():
            continue
        seen.add(key)
        existing_candidates.append(candidate)

    encrypted_credentials = _encrypted_tower_credential_count(database_path)
    require_decryption = bool(config.get("require_credential_decryption", False)) and encrypted_credentials > 0
    selected: Path | None = None
    validation_mode = "not_required"
    validation_results: list[dict[str, Any]] = []
    if require_decryption:
        legacy_candidate_paths = {str(path) for path in legacy_candidates}
        for candidate in existing_candidates:
            validation = _check_env_credential_compatibility(
                database_path=database_path,
                env_path=candidate,
                helper_image=helper_image,
                context=context,
                target_root=target_root,
            )
            validation_results.append(
                {
                    "source": str(candidate),
                    "encrypted_credentials": validation["encrypted_credentials"],
                    "authenticated_credentials": validation["authenticated_credentials"],
                    "unauthenticated_credentials": validation["unauthenticated_credentials"],
                    "compatible": validation["compatible"],
                }
            )
            has_unauthenticated = validation["unauthenticated_credentials"] > 0
            if has_unauthenticated and database_migrated_from_legacy:
                if str(candidate) not in legacy_candidate_paths:
                    continue
                if validation["compatible"]:
                    selected = candidate
                    validation_mode = "source_pair_preserved"
                    break
                continue
            if has_unauthenticated and candidate == target and not database_migrated_from_legacy:
                if validation["compatible"]:
                    selected = candidate
                    validation_mode = "existing_pair_preserved"
                    break
                continue
            if not has_unauthenticated and validation["compatible"]:
                selected = candidate
                validation_mode = "authenticated_decryption"
                break
        if selected is None:
            has_unauthenticated = any(
                int(item.get("unauthenticated_credentials") or 0) > 0
                for item in validation_results
            )
            if database_migrated_from_legacy and has_unauthenticated:
                raise RuntimeError(
                    "Tower XOR 凭据无法认证密钥，且未找到可保留来源配对关系的旧环境 `.env`；"
                    "已停止升级，拒绝使用目标目录中的不确定密钥。"
                )
            raise RuntimeError(
                "Tower 账号包含加密凭据，但目标和旧环境 `.env` 均没有可用的配套密钥；"
                "已停止升级，未使用默认密钥覆盖旧凭据。"
            )
    elif existing_candidates:
        selected = existing_candidates[0]

    if selected is not None:
        text = _sanitize_env_text(selected.read_text(encoding="utf-8"), sanitize_image_tags=sanitize_image_tags)
        _write_env_file(target, text)
        status = "sanitized_existing" if selected == target else "copied"
        result: dict[str, Any] = {
            "status": status,
            "target": str(target),
            "credential_guard": {
                "required": require_decryption,
                "encrypted_credentials": encrypted_credentials,
                "compatible": True,
                "validation_mode": validation_mode,
                "validated_candidates": validation_results,
            },
        }
        if selected != target:
            result["source"] = str(selected)
        return result
    if config.get("fallback_defaults", True):
        _write_env_file(target, "\n".join(DEFAULT_ENV_LINES) + "\n")
        return {
            "status": "created",
            "target": str(target),
            "credential_guard": {
                "required": False,
                "encrypted_credentials": encrypted_credentials,
                "compatible": True,
                "validated_candidates": validation_results,
            },
        }
    return {
        "status": "missing",
        "target": str(target),
        "credential_guard": {
            "required": False,
            "encrypted_credentials": encrypted_credentials,
            "compatible": encrypted_credentials == 0,
            "validated_candidates": validation_results,
        },
    }


def _copy_tree_missing(source: Path, target: Path, *, skip_names: set[str] | None = None) -> bool:
    if not source.exists() or not source.is_dir():
        return False
    copied = False
    skip = skip_names or set()
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if any(part in skip for part in relative.parts):
            continue
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if not item.is_file() or destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
        copied = True
    return copied


def _copy_known_app_files(source: Path, target: Path) -> bool:
    copied = False
    for name in ("smartx.db", "upgrade-runner.version"):
        candidate = source / name
        destination = target / name
        if candidate.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, destination)
            copied = True
    return copied


def _sqlite_count_table(connection: sqlite3.Connection, table: str) -> int:
    exists = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _db_counts(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "valid": False,
        "counts": {table: 0 for table in DB_COUNT_TABLES},
        "business_data": False,
        "error": "",
    }
    if not path.is_file():
        return result
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            counts = {table: _sqlite_count_table(connection, table) for table in DB_COUNT_TABLES}
    except Exception as exc:
        result["error"] = str(exc)
        return result
    result["valid"] = True
    result["counts"] = counts
    result["business_data"] = any(int(counts.get(table) or 0) > 0 for table in DB_BUSINESS_TABLES)
    return result


def _business_counts_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_counts = dict(left.get("counts") or {})
    right_counts = dict(right.get("counts") or {})
    return all(int(left_counts.get(table) or 0) == int(right_counts.get(table) or 0) for table in DB_BUSINESS_TABLES)


def _business_counts_at_least(target: dict[str, Any], source: dict[str, Any]) -> bool:
    target_counts = dict(target.get("counts") or {})
    source_counts = dict(source.get("counts") or {})
    return all(int(target_counts.get(table) or 0) >= int(source_counts.get(table) or 0) for table in DB_BUSINESS_TABLES)


def _counts_have_business_data(counts: dict[str, Any]) -> bool:
    return any(int(counts.get(table) or 0) > 0 for table in DB_BUSINESS_TABLES)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def _resolve_data_guard_db_path(path: Path, context: ActionContext | None) -> tuple[Path, str]:
    if context is None or context.host_data_path is None:
        return path, ""
    host_data_path = Path(context.host_data_path)
    if path == host_data_path or _path_is_relative_to(path, host_data_path):
        relative = path.relative_to(host_data_path)
        return Path(context.data_path) / relative, "host_data_path"
    return path, ""


def _parent_migration_checkpoint(params: dict[str, Any], context: ActionContext | None) -> dict[str, Any]:
    parent_task_id = str(params.get("parent_task_id") or "")
    if not parent_task_id or context is None:
        return {}
    task_file = context.upgrades_path / parent_task_id / "task.json"
    if not task_file.is_file():
        return {}
    try:
        task = json.loads(task_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    actions = (task.get("execution_plan") or {}).get("actions") or []
    for action in actions:
        if action.get("type") == "filesystem.prepare":
            checkpoint = action.get("checkpoint")
            return dict(checkpoint) if isinstance(checkpoint, dict) else {}
    return {}


def _backup_empty_target_db(target_db: Path) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = target_db.with_name(f"smartx.db.pre-upg038-empty-target.{timestamp}.bak")
    counter = 1
    while backup.exists():
        backup = target_db.with_name(f"smartx.db.pre-upg038-empty-target.{timestamp}.{counter}.bak")
        counter += 1
    shutil.move(str(target_db), str(backup))
    return str(backup)


def _migrate_app_data_source(source: Path, target: Path) -> dict[str, Any] | None:
    if not source.exists() or not source.is_dir():
        return None
    source_db = source / "smartx.db"
    target_db = target / "smartx.db"
    source_counts = _db_counts(source_db)
    target_counts_before = _db_counts(target_db)
    copied = False
    replaced = False
    backup_path = ""

    if bool(source_counts["business_data"]):
        if bool(target_counts_before["business_data"]):
            if not _business_counts_equal(source_counts, target_counts_before):
                raise RuntimeError(
                    "业务数据库冲突："
                    f"source={source_db} counts={source_counts['counts']} "
                    f"target={target_db} counts={target_counts_before['counts']}"
                )
        else:
            target.mkdir(parents=True, exist_ok=True)
            if target_db.exists():
                backup_path = _backup_empty_target_db(target_db)
                replaced = True
            shutil.copy2(source_db, target_db)
            copied = True
    elif source_db.is_file() and not target_db.exists():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_db, target_db)
        copied = True

    runner_version = source / "upgrade-runner.version"
    target_runner_version = target / "upgrade-runner.version"
    if runner_version.is_file() and not target_runner_version.exists():
        target_runner_version.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runner_version, target_runner_version)
        copied = True

    target_counts_after = _db_counts(target_db)
    if not (copied or source_db.is_file() or runner_version.is_file()):
        return None
    return {
        "source": str(source),
        "source_db_path": str(source_db),
        "source_db_counts": source_counts,
        "target_db_counts_before": target_counts_before,
        "target_db_counts_after": target_counts_after,
        "copied": copied,
        "replaced_empty_target_db": replaced,
        "target_db_backup": backup_path,
    }


def _docker_copy_missing(
    context: ActionContext,
    *,
    image: str,
    source: str,
    target: str,
    mode: str,
    skip_names: set[str] | None = None,
) -> bool:
    if not image:
        return False
    script = r"""
from pathlib import Path
import os
import shutil

source = Path("/from")
target = Path("/to")
mode = os.environ.get("SMARTX_COPY_MODE", "tree")
skip = {item for item in os.environ.get("SMARTX_SKIP_NAMES", "").split(",") if item}
copied = False
if mode == "project":
    for item in sorted(source.rglob("*")):
        rel = item.relative_to(source)
        if any(part in skip for part in rel.parts):
            continue
        dst = target / rel
        if item.is_dir():
            if dst.is_file() or dst.is_symlink():
                dst.unlink()
            dst.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)
            copied = True
elif mode == "app":
    for name in ("smartx.db", "upgrade-runner.version"):
        src = source / name
        dst = target / name
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied = True
else:
    has_blocks = any(item.is_dir() and (item / "meta.json").is_file() for item in target.iterdir()) if target.exists() else False
    if not has_blocks:
        for item in sorted(source.rglob("*")):
            rel = item.relative_to(source)
            if any(part in skip for part in rel.parts):
                continue
            dst = target / rel
            if item.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            elif item.is_file() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)
                copied = True
if not copied:
    raise SystemExit(3)
print("copied=1")
"""
    command = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--entrypoint",
        "python",
        "-v",
        f"{source}:/from:ro",
        "-v",
        f"{target}:/to",
        "-e",
        f"SMARTX_COPY_MODE={mode}",
        "-e",
        f"SMARTX_SKIP_NAMES={','.join(sorted(skip_names or set()))}",
        image,
        "-c",
        script,
    ]
    try:
        context.executor.run(command, timeout=900)
    except Exception:
        return False
    return True


def _docker_chown_path(context: ActionContext, *, image: str, target: str, uid: int, gid: int) -> bool:
    if not image or not target:
        return False
    script = """
from pathlib import Path
import os

target = Path("/target")
target.mkdir(parents=True, exist_ok=True)
for path in [target, *target.rglob("*")]:
    try:
        os.chown(path, int(os.environ["SMARTX_CHOWN_UID"]), int(os.environ["SMARTX_CHOWN_GID"]))
    except PermissionError:
        raise
target.chmod(0o755)
print("chowned=1")
"""
    try:
        context.executor.run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--entrypoint",
                "python",
                "-v",
                f"{target}:/target",
                "-e",
                f"SMARTX_CHOWN_UID={uid}",
                "-e",
                f"SMARTX_CHOWN_GID={gid}",
                image,
                "-c",
                script,
            ],
            timeout=900,
        )
    except Exception as exc:
        raise RuntimeError(f"Prometheus 数据目录权限修复失败：{target} uid={uid} gid={gid}: {exc}") from exc
    return True


def filesystem_prepare(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    target_root_value = str(params.get("target_root") or "").strip()
    target_root = Path(target_root_value) if target_root_value else None
    project_path = Path(str(params.get("project_path") or context.project_path))
    data_path = Path(str(params.get("app_data_path") or context.data_path))
    prometheus_path = Path(str(params.get("prometheus_data_path") or context.prometheus_path))
    upgrades_path = Path(str(params.get("upgrades_path") or context.upgrades_path))
    backups_path = Path(str(params.get("backups_path") or context.backups_path))
    exports_path = Path(str(params.get("exports_path") or context.exports_path))
    compose_runtime_path = Path(str(params.get("compose_runtime_path") or context.compose_runtime_path))
    directories = [
        project_path,
        data_path,
        prometheus_path,
        upgrades_path,
        backups_path,
        exports_path,
        compose_runtime_path,
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    app_target = data_path
    prometheus_target = prometheus_path
    project_target = Path(str(params.get("project_path") or ""))
    copied_app_sources: list[str] = []
    copied_prometheus_sources: list[str] = []
    copied_project_sources: list[str] = []
    prepared_permissions: list[str] = []
    initial_target_counts = _db_counts(app_target / "smartx.db")
    app_migration: dict[str, Any] = {
        "source_db_path": "",
        "source_db_counts": {},
        "target_db_counts_before": dict(initial_target_counts.get("counts") or {}),
        "target_db_counts_after": dict(initial_target_counts.get("counts") or {}),
        "replaced_empty_target_db": False,
        "target_db_backup": "",
    }
    helper_image = str(params.get("helper_image") or params.get("image") or "")

    if project_target and project_target.is_absolute():
        package_project = context.package_path / "project"
        project_source = package_project if package_project.is_dir() else context.docker_host_path(context.project_path)
        if str(project_source) != str(project_target):
            project_skip_names = {".env"} if package_project.is_dir() else APP_RUNTIME_ENTRIES | {".env"}
            copied = _docker_copy_missing(
                context,
                image=helper_image,
                source=str(project_source),
                target=str(project_target),
                mode="project",
                skip_names=project_skip_names,
            )
            if copied:
                copied_project_sources.append(str(project_source))

    for value in params.get("legacy_app_data_paths") or []:
        source = Path(str(value))
        try:
            if source.resolve() == app_target.resolve():
                continue
        except OSError:
            pass
        try:
            # runner 把宿主机 app 目录挂载在 /data；此时 legacy 候选 "/data" 的
            # smartx.db 就是目标在线库自己，绝不能当作 legacy 源迁移（UPG-049）
            live_db = Path(os.environ.get("SMARTX_DB_PATH") or "/data/smartx.db")
            candidate_db = source / "smartx.db"
            if candidate_db.is_file() and candidate_db.resolve() == live_db.resolve():
                continue
        except OSError:
            pass
        migration = _migrate_app_data_source(source, app_target)
        if not migration:
            continue
        app_migration.update(
            {
                "source_db_path": migration["source_db_path"],
                "source_db_counts": dict((migration["source_db_counts"] or {}).get("counts") or {}),
                "target_db_counts_before": dict((migration["target_db_counts_before"] or {}).get("counts") or {}),
                "target_db_counts_after": dict((migration["target_db_counts_after"] or {}).get("counts") or {}),
                "replaced_empty_target_db": migration["replaced_empty_target_db"],
                "target_db_backup": migration["target_db_backup"],
            }
        )
        if migration["copied"]:
            copied_app_sources.append(str(source))
        break
    if not copied_app_sources and not app_migration.get("source_db_path") and not (app_target / "smartx.db").exists() and helper_image:
        target_app_path = str(params.get("app_data_path") or "")
        if target_app_path:
            for value in params.get("legacy_app_data_paths") or []:
                copied = _docker_copy_missing(
                    context,
                    image=helper_image,
                    source=str(value),
                    target=target_app_path,
                    mode="app",
                )
                if copied:
                    copied_app_sources.append(str(value))
                    app_migration["target_db_counts_after"] = dict(_db_counts(app_target / "smartx.db").get("counts") or {})
                    break

    env_file = _migrate_env_file(
        params,
        project_path,
        database_path=app_target / "smartx.db",
        database_migrated_from_legacy=bool(app_migration.get("source_db_path") or copied_app_sources),
        helper_image=helper_image,
        context=context,
        target_root=target_root,
    )

    target_prometheus_path = str(params.get("prometheus_data_path") or "")
    if target_prometheus_path and helper_image:
        for value in params.get("legacy_prometheus_data_paths") or []:
            copied = _docker_copy_missing(
                context,
                image=helper_image,
                source=str(value),
                target=target_prometheus_path,
                mode="prometheus",
                skip_names=PROMETHEUS_RUNTIME_ENTRIES,
            )
            if copied:
                copied_prometheus_sources.append(str(value))
                break
    if not copied_prometheus_sources:
        has_prometheus_blocks = any(item.is_dir() and (item / "meta.json").is_file() for item in prometheus_target.iterdir())
        if not has_prometheus_blocks:
            # runner 把宿主机 prometheus 目录挂在 SMARTX_PROMETHEUS_DATA_PATH（默认
            # /prometheus-data）；legacy 候选解析到该路径时就是在线数据自己，
            # 绝不能当作 legacy 源复制，否则会在目标里嵌套出畸变副本（UPG-049）
            live_prometheus = Path(os.environ.get("SMARTX_PROMETHEUS_DATA_PATH") or "/prometheus-data")
            for value in params.get("legacy_prometheus_data_paths") or []:
                source = Path(str(value))
                try:
                    is_live_self = source.resolve() in (prometheus_target.resolve(), live_prometheus.resolve())
                except OSError:
                    is_live_self = False
                if not source.exists() or is_live_self:
                    copied = False
                else:
                    copied = _copy_tree_missing(source, prometheus_target, skip_names=PROMETHEUS_RUNTIME_ENTRIES)
                if copied:
                    copied_prometheus_sources.append(str(source))
                    break
    if target_prometheus_path and helper_image:
        uid = int(params.get("prometheus_uid") or 65534)
        gid = int(params.get("prometheus_gid") or 65534)
        if _docker_chown_path(context, image=helper_image, target=target_prometheus_path, uid=uid, gid=gid):
            prepared_permissions.append(f"{target_prometheus_path}:{uid}:{gid}")

    return {
        "created_directories": [str(path) for path in directories],
        "copied_project_sources": copied_project_sources,
        "copied_app_sources": copied_app_sources,
        **app_migration,
        "copied_prometheus_sources": copied_prometheus_sources,
        "prepared_permissions": prepared_permissions,
        "env_file": env_file,
        "checkpoint": {
            "completed": True,
            "created_directories": [str(path) for path in directories],
            "copied_project_sources": copied_project_sources,
            "copied_app_sources": copied_app_sources,
            **app_migration,
            "copied_prometheus_sources": copied_prometheus_sources,
            "prepared_permissions": prepared_permissions,
            "env_file": env_file,
        },
    }


def compose_override(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    context.compose_runtime_path.mkdir(parents=True, exist_ok=True)
    target = context.compose_runtime_path / f"docker-compose.{context.task_id}.yml"
    lines = ["services:"]
    for image in action.get("params", {}).get("images") or []:
        lines.extend([f"  {image['service']}:", f"    image: {image['image']}"])
    content = "\n".join(lines) + "\n"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target)
    return {"path": str(target), "sha256": _sha256(target), "checkpoint": {"path": str(target), "sha256": _sha256(target)}}


def compose_apply(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    override = context.compose_runtime_path / f"docker-compose.{context.task_id}.yml"
    services = [str(item) for item in action.get("params", {}).get("services") or []]
    command = [
        "docker",
        "compose",
        "-f",
        context.compose_file,
        "-f",
        str(override),
        "--project-name",
        context.compose_project,
        "up",
        "-d",
        "--no-deps",
        *services,
    ]
    context.executor.run(command, cwd=context.project_path)
    connected_networks = _connect_current_runner_to_project_networks(context, services)
    return {"services": services, "connected_networks": connected_networks, "checkpoint": {"submitted": True, "connected_networks": connected_networks}}


def _current_runner_mounts(context: ActionContext) -> list[dict[str, Any]]:
    if not context.current_container_id:
        return []
    try:
        inspected = context.executor.output(["docker", "inspect", context.current_container_id])
        containers = json.loads(inspected or "[]")
    except Exception:
        return []
    if not containers:
        return []
    return list(containers[0].get("Mounts") or [])


def _runner_uses_target_runtime(context: ActionContext) -> bool:
    required = {
        "/data": context.host_data_path,
        "/data/upgrades": context.host_upgrades_path,
        "/data/backups": context.host_backups_path,
        "/data/exports": context.host_exports_path,
        "/data/compose-runtime": context.host_compose_runtime_path,
        "/prometheus-data": context.host_prometheus_path,
    }
    if not context.current_container_id:
        return False
    mounts = _current_runner_mounts(context)
    if not mounts:
        return False
    by_destination = {str(item.get("Destination") or ""): Path(str(item.get("Source") or "")) for item in mounts}
    for destination, host_path in required.items():
        if host_path is None:
            continue
        if by_destination.get(destination) != Path(host_path):
            return False
    return True


def _runner_network_block(network_name: str, subnet: str) -> str:
    if subnet:
        return f"""  smartx-net:
    name: {network_name}
    ipam:
      config:
        - subnet: {subnet}
"""
    return f"""  smartx-net:
    external: true
    name: {network_name}
"""


def _safe_absolute_path(value: Any, *, label: str) -> Path:
    path = Path(str(value or "").strip())
    if not str(path):
        raise ValueError(f"{label} 不能为空。")
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} 必须是安全的绝对路径：{value}")
    if str(path) in {"/", "/data", "/opt"}:
        raise ValueError(f"{label} 指向关键系统路径：{value}")
    return path


def _runner_runtime_paths(context: ActionContext, params: dict[str, Any]) -> dict[str, Path]:
    project_path = _safe_absolute_path(
        params.get("project_path") or context.host_project_path or context.project_path,
        label="runner project_path",
    )
    data_path = _safe_absolute_path(params.get("app_data_path") or context.host_data_path or context.data_path, label="runner app_data_path")
    upgrades_path = _safe_absolute_path(
        params.get("upgrades_path") or context.host_upgrades_path or context.upgrades_path,
        label="runner upgrades_path",
    )
    backups_path = _safe_absolute_path(
        params.get("backups_path") or context.host_backups_path or context.backups_path,
        label="runner backups_path",
    )
    exports_path = _safe_absolute_path(
        params.get("exports_path") or context.host_exports_path or context.exports_path,
        label="runner exports_path",
    )
    compose_runtime_path = _safe_absolute_path(
        params.get("compose_runtime_path") or context.host_compose_runtime_path or context.compose_runtime_path,
        label="runner compose_runtime_path",
    )
    prometheus_path = _safe_absolute_path(
        params.get("prometheus_data_path") or context.host_prometheus_path or context.prometheus_path,
        label="runner prometheus_data_path",
    )
    return {
        "project_path": project_path,
        "data_path": data_path,
        "upgrades_path": upgrades_path,
        "backups_path": backups_path,
        "exports_path": exports_path,
        "compose_runtime_path": compose_runtime_path,
        "prometheus_path": prometheus_path,
    }


def _write_runner_runtime_compose(context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
    image = str(params.get("image") or "").strip()
    if not image:
        raise ValueError("runner handoff 缺少 upgrade-runner 镜像。")
    project_name = _safe_docker_name(params.get("compose_project") or context.compose_project)
    network_name = _safe_docker_name(params.get("network_name") or f"{project_name}_smartx-net")
    subnet = str(params.get("subnet") or "").strip()
    paths = _runner_runtime_paths(context, params)
    compose_path = paths["compose_runtime_path"] / "docker-compose.runner-upgrade.yml"
    compose_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""services:
  upgrade-runner:
    image: {image}
    command: ["python", "-m", "app.upgrade_runner.main"]
    environment:
      TZ: Asia/Shanghai
      SMARTX_PROJECT_PATH: {paths["project_path"]}
      SMARTX_COMPOSE_FILE: {context.compose_file}
      SMARTX_COMPOSE_PROJECT_NAME: {project_name}
      SMARTX_DB_PATH: /data/smartx.db
      SMARTX_UPGRADES_PATH: /data/upgrades
      SMARTX_BACKUPS_PATH: /data/backups
      SMARTX_EXPORTS_PATH: /data/exports
      SMARTX_COMPOSE_RUNTIME_PATH: /data/compose-runtime
      SMARTX_PROMETHEUS_DATA_PATH: /prometheus-data
      SMARTX_HOST_DATA_PATH: {paths["data_path"]}
      SMARTX_HOST_UPGRADES_PATH: {paths["upgrades_path"]}
      SMARTX_HOST_BACKUPS_PATH: {paths["backups_path"]}
      SMARTX_HOST_EXPORTS_PATH: {paths["exports_path"]}
      SMARTX_HOST_COMPOSE_RUNTIME_PATH: {paths["compose_runtime_path"]}
      SMARTX_HOST_PROMETHEUS_DATA_PATH: {paths["prometheus_path"]}
      SMARTX_HOST_PROJECT_PATH: {paths["project_path"]}
    volumes:
      - {paths["project_path"]}:{paths["project_path"]}
      - {paths["data_path"]}:/data
      - {paths["upgrades_path"]}:/data/upgrades
      - {paths["backups_path"]}:/data/backups
      - {paths["exports_path"]}:/data/exports
      - {paths["compose_runtime_path"]}:/data/compose-runtime
      - {paths["prometheus_path"]}:/prometheus-data
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - smartx-net
    restart: unless-stopped

networks:
{_runner_network_block(network_name, subnet).rstrip()}
"""
    temporary = compose_path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, compose_path)
    return {
        "image": image,
        "compose_file": compose_path,
        "compose_project": project_name,
        "network": network_name,
        "paths": paths,
    }


def runner_handoff_target_runtime(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    if _runner_uses_target_runtime(context):
        return {"message": "upgrade-runner 已在目标运行目录", "checkpoint": {"completed": True, "resumed": True}}

    params = action.get("params", {})
    runtime = _write_runner_runtime_compose(context, params)
    compose_path = Path(runtime["compose_file"])
    project_name = str(runtime["compose_project"])
    context.executor.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_path),
            "--project-name",
            project_name,
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "upgrade-runner",
        ],
        cwd=compose_path.parent,
    )
    return {
        "compose_file": str(compose_path),
        "compose_project": project_name,
        "network": str(runtime["network"]),
        "checkpoint": {"completed": True, "compose_file": str(compose_path), "compose_project": project_name},
    }


RUNNER_CUTOVER_HELPER_SCRIPT = r"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

task_file = Path(os.environ["SMARTX_PARENT_TASK_FILE"])
compose_file = os.environ["SMARTX_RUNNER_COMPOSE_FILE"]
compose_project = os.environ["SMARTX_TARGET_COMPOSE_PROJECT"]
timeout = int(os.environ.get("SMARTX_CUTOVER_TIMEOUT_SECONDS", "120"))
deadline = time.time() + timeout
terminal_without_cutover = {"failed", "rollback_failed", "rolled_back", "recovery_required", "cancelled"}

while time.time() < deadline:
    try:
        task = json.loads(task_file.read_text(encoding="utf-8"))
    except Exception:
        time.sleep(1)
        continue
    status = str(task.get("status") or "")
    if status == "success":
        break
    if status in terminal_without_cutover:
        print(f"parent task ended with {status}; skip runner cutover")
        sys.exit(0)
    time.sleep(1)
else:
    print("timed out waiting for parent task success", file=sys.stderr)
    sys.exit(1)

subprocess.run(
    [
        "docker",
        "compose",
        "-f",
        compose_file,
        "--project-name",
        compose_project,
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "upgrade-runner",
    ],
    check=True,
)
"""


def resolve_runner_stop_decision(
    *,
    runner_project: str,
    target_project: str,
    purpose: str,
) -> dict[str, Any]:
    """US-03 收敛点：**"能不能停这个 runner"只有一个决策处**。

    此前三个入口各自隐含判断，任何一处漏判就会误停刚启动的 runner——
    US-04 正是这么产生的（v0.5.2 源端 web-api 无条件 stop，10s SIGKILL / exit=137）。
    本函数把规则写成数据（可断言、可记录），三个入口都必须经它。

    规则（唯一）：
        **目标 project 与 runner 所在 project 不同才允许停。**
        相同 = 原地组件升级，停掉的是刚 up 起来的新 runner。

    返回 {"stop": bool, "reason": str, "runner_project": ..., "target_project": ...}。
    `purpose` 用于决策留痕（handoff / legacy-cleanup），便于事后取证。
    """
    runner_project = str(runner_project or "").strip()
    target_project = str(target_project or "").strip()
    if not target_project:
        # 未声明目标 project：保守停止（旧行为），避免旧 runner 心跳覆盖新环境
        return {
            "stop": True,
            "reason": f"未声明目标 project（purpose={purpose}），保守停止以免旧 runner 心跳覆盖",
            "runner_project": runner_project,
            "target_project": target_project,
        }
    if runner_project and runner_project == target_project:
        return {
            "stop": False,
            "reason": (
                f"runner 与目标同属 project '{target_project}'，停掉的就是刚启动的新 runner"
                f"（purpose={purpose}）——跳过"
            ),
            "runner_project": runner_project,
            "target_project": target_project,
        }
    return {
        "stop": True,
        "reason": (
            f"runner 属于旧 project '{runner_project or '未知'}'，目标为 '{target_project}'"
            f"，停止以免旧 runner 心跳覆盖（purpose={purpose}）"
        ),
        "runner_project": runner_project,
        "target_project": target_project,
    }


def _helper_container_name(task_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in task_id)[:48]
    return f"smartx-runner-cutover-{safe or 'task'}"


def runner_schedule_target_runtime_handoff(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    """调度 runner 自换：写目标运行目录的 compose → 起辅助容器 → **本进程到此为止**。

    W3（Phase 68）：自换时代，这个动作之后旧 runner 的代码**不会执行**
    （docker 随即替换容器）。因此返回带 `handoff_final` 哨兵的结果，
    `UpgradeEngine` 在该返回点立刻停止，不再写任何状态——收尾全部由新 runner
    启动路径的 `_finish_runner_component_steps` 完成（机制 v0.3.1 已具备）。

    为什么必须用哨兵而不是"约定它是最后一个动作"：engine 在动作返回后必然会
    把动作标记 succeeded、跑 compose tag 对账、把任务置 success。这三步在自换
    窗口内随时会被 SIGKILL 打断，留下 revision 与实际状态不一致的 task.json
    ——US-24 的崩溃循环正是这么来的。
    """
    from app.upgrade_runner.selfhandoff import handoff_final_result

    context = _context(context_payload)
    params = action.get("params", {})
    runtime = _write_runner_runtime_compose(context, params)
    compose_path = Path(runtime["compose_file"])
    paths = runtime["paths"]
    target_task_dir_value = str(context_payload.get("task_mirror_dir") or params.get("task_mirror_dir") or "")
    target_task_dir = Path(target_task_dir_value) if target_task_dir_value else paths["upgrades_path"] / context.task_id
    target_task_dir = _target_upgrade_state_path(context, target_task_dir)
    task_file = target_task_dir / "task.json"
    if not task_file.is_file():
        raise FileNotFoundError(f"目标任务状态不存在，无法调度 runner cutover：{task_file}")

    helper_name = _helper_container_name(context.task_id)
    try:
        context.executor.run(["docker", "rm", "-f", helper_name])
    except Exception:
        pass
    helper_compose_file = Path("/runner-cutover/runtime") / compose_path.name
    helper_task_file = Path("/runner-cutover/task") / "task.json"
    context.executor.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            helper_name,
            "--network=none",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{target_task_dir}:/runner-cutover/task:ro",
            "-v",
            f"{paths['compose_runtime_path']}:/runner-cutover/runtime:ro",
            "-e",
            f"SMARTX_PARENT_TASK_FILE={helper_task_file}",
            "-e",
            f"SMARTX_RUNNER_COMPOSE_FILE={helper_compose_file}",
            "-e",
            f"SMARTX_TARGET_COMPOSE_PROJECT={runtime['compose_project']}",
            "-e",
            f"SMARTX_CUTOVER_TIMEOUT_SECONDS={int(params.get('timeout_seconds') or 120)}",
            "--entrypoint",
            "python",
            str(runtime["image"]),
            "-c",
            RUNNER_CUTOVER_HELPER_SCRIPT,
        ]
    )
    # 注意：这个 return 就是本函数的**最后一句可执行代码**。
    # 它的后续（返回给 engine → engine 标记动作 succeeded → compose tag 对账 →
    # 任务置 success）在自换窗口内都可能被 SIGKILL 打断。
    # engine 见到 handoff_final 哨兵会原地停止，收尾交给新 runner。
    return handoff_final_result(
        helper_container=helper_name,
        compose_file=str(compose_path),
        parent_task_file=str(task_file),
        anchor=params.get("rollback_anchor") or {},
        checkpoint={
            "completed": True,
            "helper_container": helper_name,
            "compose_file": str(compose_path),
            "parent_task_file": str(task_file),
            "rollback_anchor": params.get("rollback_anchor") or {},
        },
    )


def _same_container(left: str, right: str) -> bool:
    left = left.strip().lstrip("/")
    right = right.strip().lstrip("/")
    return bool(left and right and (left == right or left.startswith(right) or right.startswith(left)))


def _path_is_same_or_child(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    resolved_root = root.resolve()
    return resolved == resolved_root or resolved_root in resolved.parents


def _target_upgrade_state_path(context: ActionContext, target: Path) -> Path:
    if context.host_upgrades_path is not None and _path_is_same_or_child(target, context.host_upgrades_path):
        return target
    if context.host_upgrades_path is not None and _path_is_same_or_child(target, context.upgrades_path):
        return Path(context.host_upgrades_path) / target.resolve().relative_to(context.upgrades_path.resolve())
    return target


def _container_labels(container: dict[str, Any]) -> dict[str, str]:
    labels = container.get("Labels")
    if not isinstance(labels, dict):
        config = container.get("Config") or {}
        labels = config.get("Labels") if isinstance(config, dict) else {}
    return {str(key): str(value) for key, value in (labels or {}).items()}


def _is_legacy_runner_container(container: dict[str, Any], *, expected_name: str, legacy_project: str) -> bool:
    name = str(container.get("Name") or "").lstrip("/")
    labels = _container_labels(container)
    project = labels.get("com.docker.compose.project", "")
    service = labels.get("com.docker.compose.service", "")
    return name == expected_name or (project == legacy_project and service == "upgrade-runner")


def runner_stop_legacy_runtime(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    legacy_project = _safe_docker_name(params.get("legacy_project"))
    legacy_runner_container = _safe_docker_name(params.get("legacy_runner_container") or f"{legacy_project}-upgrade-runner-1")
    target_project = str(params.get("target_project") or context.compose_project or "").strip()
    # US-03：经唯一决策处判断能否停（不再由各入口各自隐含判断）
    decision = resolve_runner_stop_decision(
        runner_project=legacy_project, target_project=target_project, purpose="legacy-cleanup"
    )
    try:
        inspected = context.executor.output(["docker", "inspect", legacy_runner_container])
    except Exception:
        return {
            "container": legacy_runner_container,
            "container_id": "",
            "status": "missing",
            "stopped": False,
            "removed": False,
            "checkpoint": {"completed": True, "status": "missing"},
        }
    try:
        containers = json.loads(inspected or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"无法解析旧 runner 容器信息：{legacy_runner_container}") from exc
    if not containers:
        return {
            "container": legacy_runner_container,
            "container_id": "",
            "status": "missing",
            "stopped": False,
            "removed": False,
            "checkpoint": {"completed": True, "status": "missing"},
        }
    container = containers[0]
    container_id = str(container.get("Id") or container.get("ID") or "")
    container_name = str(container.get("Name") or legacy_runner_container).lstrip("/")
    labels = _container_labels(container)
    project_label = labels.get("com.docker.compose.project", "")
    service_label = labels.get("com.docker.compose.service", "")
    if _same_container(container_id, context.current_container_id) or _same_container(container_name, context.current_container_id):
        raise RuntimeError(f"不允许停止当前 runner：{container_name or container_id}")
    if target_project and (project_label == target_project or container_name == f"{target_project}-upgrade-runner-1"):
        raise RuntimeError(f"不允许停止目标 project runner：{container_name}")
    # US-03：容器实际所属 project 与目标一致 → 停它就是停新 runner，必须拒绝。
    # 这与 web-api 侧 `_should_stop_previous_runner` 是**同一条规则**（经
    # `resolve_runner_stop_decision` 统一），三处入口不再各自隐含判断。
    if not decision["stop"]:
        return {
            "container": container_name,
            "container_id": container_id,
            "status": "skipped",
            "stopped": False,
            "removed": False,
            "skip_reason": decision["reason"],
            "checkpoint": {
                "completed": True,
                "container": container_name,
                "container_id": container_id,
                "status": "skipped",
                "stopped": False,
                "removed": False,
                "reason": decision["reason"],
            },
        }
    if not _is_legacy_runner_container(container, expected_name=legacy_runner_container, legacy_project=legacy_project):
        raise RuntimeError(
            f"拒绝停止非旧 runner 容器：name={container_name}, project={project_label}, service={service_label}"
        )
    state = container.get("State") or {}
    running = bool(state.get("Running")) or str(state.get("Status") or "").lower() == "running"
    if running:
        context.executor.run(["docker", "stop", container_id or container_name])
    context.executor.run(["docker", "rm", container_id or container_name])
    return {
        "container": container_name,
        "container_id": container_id,
        "status": "removed",
        "stopped": running,
        "removed": True,
        "checkpoint": {
            "completed": True,
            "container": container_name,
            "container_id": container_id,
            "status": "removed",
            "stopped": running,
            "removed": True,
        },
    }


def _connect_current_runner_to_project_networks(context: ActionContext, services: list[str]) -> list[str]:
    current = context.current_container_id
    if not current or "web-api" not in services:
        return []
    web_api_containers = _docker_lines(
        context.executor.output(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={context.compose_project}",
                "--filter",
                "label=com.docker.compose.service=web-api",
                "--format",
                "{{.ID}}",
            ]
        )
    )
    if not web_api_containers:
        return []
    inspected = context.executor.output(["docker", "inspect", web_api_containers[0]])
    containers = json.loads(inspected or "[]")
    networks = sorted((containers[0].get("NetworkSettings", {}).get("Networks") or {}).keys()) if containers else []
    connected: list[str] = []
    for network in networks:
        try:
            context.executor.run(["docker", "network", "connect", network, current])
            connected.append(network)
        except Exception:
            inspected_runner = context.executor.output(["docker", "inspect", current])
            runner = json.loads(inspected_runner or "[]")
            runner_networks = (runner[0].get("NetworkSettings", {}).get("Networks") or {}) if runner else {}
            if network in runner_networks:
                connected.append(network)
            else:
                raise
    return connected


def _docker_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _safe_docker_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("Docker 名称不能为空。")
    if any(part in name for part in ("/", "\\", "..")):
        raise ValueError(f"Docker 名称不安全：{name}")
    return name


def compose_project_migrate(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    migrated_projects: list[str] = []
    removed_networks: list[str] = []
    prepared_layouts: list[dict[str, Any]] = []
    skipped: list[str] = []
    for transition in action.get("params", {}).get("transitions") or []:
        directory_transition = transition.get("directory_transition") if isinstance(transition, dict) else None
        if isinstance(directory_transition, dict) and directory_transition:
            prepared_layouts.append(filesystem_prepare({"params": directory_transition}, context_payload))
        from_project = _safe_docker_name(transition.get("from_project"))
        to_project = _safe_docker_name(transition.get("to_project") or context.compose_project)
        context.compose_project = to_project
        if from_project == to_project:
            skipped.append(from_project)
            continue
        containers = _docker_lines(
            context.executor.output(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"label=com.docker.compose.project={from_project}",
                    "--format",
                    "{{.ID}}",
                ]
            )
        )
        removable_containers = [container for container in containers if not _same_container(container, context.current_container_id)]
        if removable_containers:
            context.executor.run(["docker", "stop", *removable_containers])
            context.executor.run(["docker", "rm", *removable_containers])
            migrated_projects.append(from_project)
        from_network = str(transition.get("from_network") or "").strip()
        if not from_network:
            continue
        from_network = _safe_docker_name(from_network)
        try:
            inspected = context.executor.output(["docker", "network", "inspect", from_network])
        except Exception:
            skipped.append(from_network)
            continue
        try:
            networks = json.loads(inspected or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"无法解析 Docker 网络信息：{from_network}") from exc
        network = networks[0] if networks else {}
        attached = dict(network.get("Containers") or {})
        legacy_network_containers: list[str] = []
        external_names: list[str] = []
        current_runner_attached = False
        for container_id, item in attached.items():
            name = str(item.get("Name") or container_id)
            if _same_container(container_id, context.current_container_id) or _same_container(name, context.current_container_id):
                current_runner_attached = True
                continue
            if _is_legacy_project_container(name, from_project):
                legacy_network_containers.append(str(container_id))
            else:
                external_names.append(name)
        if external_names:
            names = sorted(external_names)
            raise RuntimeError(f"旧网络 {from_network} 仍有外部容器连接：{', '.join(names)}")
        if legacy_network_containers:
            context.executor.run(["docker", "stop", *legacy_network_containers])
            context.executor.run(["docker", "rm", *legacy_network_containers])
            if from_project not in migrated_projects:
                migrated_projects.append(from_project)
        if current_runner_attached:
            skipped.append(from_network)
            continue
        context.executor.run(["docker", "network", "rm", from_network])
        removed_networks.append(from_network)
    return {
        "migrated_projects": migrated_projects,
        "removed_networks": removed_networks,
        "prepared_layouts": prepared_layouts,
        "skipped": skipped,
        "checkpoint": {
            "completed": True,
            "migrated_projects": migrated_projects,
            "removed_networks": removed_networks,
            "prepared_layouts": prepared_layouts,
        },
    }


def _same_directory(left: Path, right: Path) -> bool:
    """按 inode 判定两个路径是否同一目录（含 bind mount 双视图别名）。

    49-50 修复（2026-09-27 在 10.20.11.12 实测）：runner 容器里 source(`/data/upgrades/…`) 与
    target(`/data/smartx-storage-forecast/upgrades/…`) 是**同一宿主目录的两个 bind mount 视图**，
    `Path.resolve()` 只折叠符号链接、看不出等价 → 旧逻辑走到 `rmtree(target)` 把源目录一起删掉，
    随后 `copytree(source)` 找不到源 → 任务目录被销毁 + `RevisionConflict`，升级卡死在「迁移升级任务状态」。
    """
    try:
        return left.is_dir() and right.is_dir() and os.path.samefile(left, right)
    except OSError:
        return False


def task_migrate_runtime_state(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    source_task_dir = Path(str(params.get("source_task_dir") or context.upgrades_path / context.task_id))
    target_task_dir_value = str(params.get("target_task_dir") or "")
    if target_task_dir_value:
        target_task_dir = Path(target_task_dir_value)
    else:
        target_upgrades = Path(str(params.get("target_upgrades_path") or ""))
        if not str(target_upgrades):
            raise ValueError("任务状态迁移缺少 target_upgrades_path。")
        target_task_dir = target_upgrades / context.task_id
    target_task_dir = _target_upgrade_state_path(context, target_task_dir)
    if _same_directory(source_task_dir, target_task_dir) or source_task_dir.resolve() == target_task_dir.resolve():
        # 同一目录（含 bind mount 双视图）：只确保存在，绝不能 rmtree（会把源一起删掉）
        target_task_dir.mkdir(parents=True, exist_ok=True)
    elif source_task_dir.is_dir():
        target_task_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_task_dir.exists():
            shutil.rmtree(target_task_dir)
        shutil.copytree(source_task_dir, target_task_dir)
    else:
        target_task_dir.mkdir(parents=True, exist_ok=True)
    migrated_history_dirs: list[str] = []
    source_root = source_task_dir.parent
    target_root = target_task_dir.parent
    if (
        not _same_directory(source_root, target_root)
        and source_root.resolve() != target_root.resolve()
        and source_root.is_dir()
    ):
        target_root.mkdir(parents=True, exist_ok=True)
        for child in sorted(source_root.iterdir()):
            if not child.is_dir() or not (child / "task.json").is_file():
                continue
            if child.resolve() == source_task_dir.resolve():
                continue
            destination = target_root / child.name
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(child, destination)
            migrated_history_dirs.append(str(destination))
    return {
        "source_task_dir": str(source_task_dir),
        "mirror_task_dir": str(target_task_dir),
        "migrated_history_dirs": migrated_history_dirs,
        "checkpoint": {
            "completed": True,
            "source_task_dir": str(source_task_dir),
            "mirror_task_dir": str(target_task_dir),
            "migrated_history_dirs": migrated_history_dirs,
        },
    }


def task_sync_runtime_state(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    target_task_dir_value = str(context_payload.get("task_mirror_dir") or params.get("target_task_dir") or "")
    if target_task_dir_value:
        target_task_dir = _target_upgrade_state_path(context, Path(target_task_dir_value))
    else:
        target_upgrades = Path(str(params.get("target_upgrades_path") or ""))
        if not str(target_upgrades):
            raise ValueError("任务状态同步缺少 target_task_dir。")
        target_task_dir = _target_upgrade_state_path(context, target_upgrades / context.task_id)
    if not str(target_task_dir):
        raise ValueError("任务状态同步缺少 target_task_dir。")
    task_file = Path(target_task_dir) / "task.json"
    if not task_file.is_file():
        raise FileNotFoundError(f"新任务状态不存在：{task_file}")
    return {"task_file": str(task_file), "checkpoint": {"completed": True, "task_file": str(task_file)}}


def _is_legacy_project_container(name: str, from_project: str) -> bool:
    normalized = name.lstrip("/")
    return normalized == from_project or normalized.startswith(f"{from_project}-") or normalized.startswith(f"{from_project}_")


def _cleanup_path_is_unsafe(raw: str, protected_paths: set[str]) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return "空路径"
    path = Path(value)
    if ".." in path.parts:
        return "包含 .."
    if value in {"/", "/data", "/opt"}:
        return "关键系统路径"
    normalized = str(path)
    if normalized in protected_paths:
        return "目标正式目录"
    return None


def _health_payload(url: str, timeout: int) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        status = int(response.status)
        body = response.read()
    if status != 200:
        raise RuntimeError(f"清理前健康检查失败：HTTP {status}")
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("清理前健康检查返回非 JSON。") from exc


def _require_cleanup_health(params: dict[str, Any]) -> dict[str, Any] | None:
    required = params.get("required_health")
    if not isinstance(required, dict) or not required:
        return None
    payload = _health_payload(str(params.get("health_url") or "http://web-api:8000/api/system/health"), int(params.get("timeout_seconds") or 15))
    if not payload.get("ok"):
        raise RuntimeError("清理前健康检查未通过。")
    expected_version = str(required.get("version") or "")
    if expected_version and str(payload.get("version") or "") != expected_version:
        raise RuntimeError(f"清理前平台版本不匹配：{payload.get('version')}")
    expected_runner = str(required.get("runner_version") or "")
    if expected_runner and str(payload.get("runner_version") or "") != expected_runner:
        raise RuntimeError(f"清理前 runner 版本不匹配：{payload.get('runner_version')}")
    checks = payload.get("checks") or {}
    missing = [str(name) for name in required.get("checks") or [] if not checks.get(str(name))]
    if missing:
        raise RuntimeError(f"清理前健康检查项未通过：{', '.join(missing)}")
    return payload


def _require_data_migration_guard(params: dict[str, Any], context: ActionContext | None = None) -> dict[str, Any]:
    guard = params.get("data_migration_guard")
    if not isinstance(guard, dict) or not guard:
        return {"configured": False}
    original_target_db = Path(str(guard.get("target_db_path") or ""))
    target_db, target_resolved_from = _resolve_data_guard_db_path(original_target_db, context)
    legacy_db_paths = [Path(str(path)) for path in guard.get("legacy_db_paths") or [] if str(path)]
    legacy_counts: list[dict[str, Any]] = []
    business_sources: list[dict[str, Any]] = []
    ignored_legacy_paths: list[dict[str, str]] = []
    for legacy_db in legacy_db_paths:
        resolved_legacy_db, resolved_from = _resolve_data_guard_db_path(legacy_db, context)
        if _same_path(resolved_legacy_db, target_db):
            ignored_legacy_paths.append(
                {
                    "path": str(legacy_db),
                    "resolved_path": str(resolved_legacy_db),
                    "reason": "same_as_target_after_handoff",
                    **({"resolved_from": resolved_from} if resolved_from else {}),
                }
            )
            continue
        counts = _db_counts(resolved_legacy_db)
        counts["original_path"] = str(legacy_db)
        if resolved_from:
            counts["resolved_from"] = resolved_from
        legacy_counts.append(counts)
        if bool(counts.get("business_data")):
            business_sources.append(counts)
    target_counts = _db_counts(target_db)
    target_counts["original_path"] = str(original_target_db)
    if target_resolved_from:
        target_counts["resolved_from"] = target_resolved_from
    if not business_sources:
        if ignored_legacy_paths and not bool(target_counts.get("business_data")):
            parent_checkpoint = _parent_migration_checkpoint(params, context)
            parent_source_counts = dict(parent_checkpoint.get("source_db_counts") or {})
            if not target_counts.get("valid") or _counts_have_business_data(parent_source_counts):
                raise RuntimeError(
                    "业务数据迁移校验失败：handoff 后旧业务库路径已映射为目标库，但目标库没有业务数据。"
                    f" target={target_db} counts={target_counts.get('counts')} ignored_legacy={ignored_legacy_paths}"
                )
            return {
                "configured": True,
                "required": False,
                "skipped_reason": "parent_source_had_no_business_data",
                "legacy_db_counts": legacy_counts,
                "ignored_legacy_db_paths": ignored_legacy_paths,
                "target_db_counts": target_counts,
                "parent_migration_checkpoint": {
                    "source_db_counts": parent_source_counts,
                    "target_db_counts_after": dict(parent_checkpoint.get("target_db_counts_after") or {}),
                },
            }
        return {
            "configured": True,
            "required": False,
            **(
                {"skipped_reason": "legacy_sources_unavailable_after_handoff"}
                if ignored_legacy_paths and bool(target_counts.get("business_data"))
                else {}
            ),
            "legacy_db_counts": legacy_counts,
            "ignored_legacy_db_paths": ignored_legacy_paths,
            "target_db_counts": target_counts,
        }
    if not bool(target_counts.get("business_data")):
        raise RuntimeError(
            "业务数据迁移校验失败：旧业务库存在数据，但目标库没有业务数据。"
            f" target={target_db} counts={target_counts.get('counts')} legacy={legacy_counts}"
        )
    missing = [source for source in business_sources if not _business_counts_at_least(target_counts, source)]
    if missing:
        raise RuntimeError(
            "业务数据迁移校验失败：目标库业务计数小于旧业务库。"
            f" target={target_db} counts={target_counts.get('counts')} legacy={missing}"
        )
    return {
        "configured": True,
        "required": True,
        "legacy_db_counts": legacy_counts,
        "ignored_legacy_db_paths": ignored_legacy_paths,
        "target_db_counts": target_counts,
    }


LEGACY_RUNNER_MOUNT_SOURCES = {
    "/opt/smartx-storage-forecast",
    "/data/upgrades",
    "/data/backups",
    "/data/exports",
    "/data/compose-runtime",
    "/data/smartx-capacity-insight-data",
    "/prometheus-data",
}


def _require_runner_handoff_before_cleanup(context: ActionContext) -> None:
    for mount in _current_runner_mounts(context):
        source = str(mount.get("Source") or "")
        destination = str(mount.get("Destination") or "")
        if source in LEGACY_RUNNER_MOUNT_SOURCES:
            raise RuntimeError(f"当前 runner 仍挂载待清理旧路径，必须先完成 runner handoff：{source}")
        if destination in {"/opt/smartx-storage-forecast", "/data/smartx-capacity-insight-data"}:
            raise RuntimeError(f"当前 runner 仍挂载待清理旧路径，必须先完成 runner handoff：{destination}")


def legacy_cleanup(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    protected_paths = {str(Path(str(path))) for path in params.get("protected_paths") or []}
    all_paths = [str(path) for path in params.get("legacy_paths") or []] + [
        str(path) for path in params.get("target_app_residual_paths") or []
    ]
    for raw in all_paths:
        reason = _cleanup_path_is_unsafe(raw, protected_paths)
        if reason:
            raise ValueError(f"不允许清理路径 {raw}：{reason}")

    _require_runner_handoff_before_cleanup(context)
    health = _require_cleanup_health(params)
    data_migration_guard = _require_data_migration_guard(params, context)
    removed_projects: list[str] = []
    removed_networks: list[str] = []
    skipped: list[dict[str, str]] = []
    for project in params.get("legacy_projects") or []:
        project_name = _safe_docker_name(project)
        if project_name == context.compose_project:
            skipped.append({"type": "project", "name": project_name, "reason": "current project"})
            continue
        containers = _docker_lines(
            context.executor.output(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"label=com.docker.compose.project={project_name}",
                    "--format",
                    "{{.ID}}",
                ]
            )
        )
        named_containers = _docker_lines(
            context.executor.output(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"name={project_name}-",
                    "--format",
                    "{{.ID}}",
                ]
            )
        )
        containers = sorted(set(containers) | set(named_containers))
        removable = [container for container in containers if not _same_container(container, context.current_container_id)]
        if removable:
            context.executor.run(["docker", "stop", *removable])
            context.executor.run(["docker", "rm", *removable])
            removed_projects.append(project_name)

    for network in params.get("legacy_networks") or []:
        network_name = _safe_docker_name(network)
        try:
            inspected = context.executor.output(["docker", "network", "inspect", network_name])
        except Exception:
            skipped.append({"type": "network", "name": network_name, "reason": "missing"})
            continue
        try:
            networks = json.loads(inspected or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"无法解析 Docker 网络信息：{network_name}") from exc
        attached = dict((networks[0] if networks else {}).get("Containers") or {})
        legacy_attached: list[str] = []
        external: list[str] = []
        for container_id, item in attached.items():
            name = str(item.get("Name") or container_id)
            if _same_container(container_id, context.current_container_id) or _same_container(name, context.current_container_id):
                external.append(name)
            elif any(_is_legacy_project_container(name, str(project)) for project in params.get("legacy_projects") or []):
                legacy_attached.append(str(container_id))
            else:
                external.append(name)
        if external:
            skipped.append({"type": "network", "name": network_name, "reason": f"external containers: {', '.join(sorted(external))}"})
            continue
        if legacy_attached:
            context.executor.run(["docker", "stop", *legacy_attached])
            context.executor.run(["docker", "rm", *legacy_attached])
        context.executor.run(["docker", "network", "rm", network_name])
        removed_networks.append(network_name)

    path_results = _cleanup_allowlisted_paths(
        all_paths,
        protected_paths,
        context,
        helper_image=str(params.get("helper_image") or ""),
    )
    return {
        "health": health,
        "data_migration_guard": data_migration_guard,
        "removed_projects": removed_projects,
        "removed_networks": removed_networks,
        "paths": path_results,
        "skipped": skipped,
        "checkpoint": {
            "completed": True,
            "data_migration_guard": data_migration_guard,
            "removed_projects": removed_projects,
            "removed_networks": removed_networks,
            "paths": path_results,
            "skipped": skipped,
        },
    }


def post_upgrade_schedule_cleanup(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    marker = {
        "parent_task_id": context.task_id,
        "cleanup_task_type": str(params.get("cleanup_task_type") or "post_upgrade_cleanup"),
        "failure_severity": str(params.get("failure_severity") or "warning"),
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }
    marker_path = context.upgrades_path / context.task_id / "post-upgrade-cleanup.json"
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        marker_path = Path("")
    return {
        "marker": marker,
        "marker_path": str(marker_path) if str(marker_path) else "",
        "checkpoint": {"completed": True, **marker, "marker_path": str(marker_path) if str(marker_path) else ""},
    }


def post_upgrade_schedule_collection(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    target_upgrades_path = Path(str(params.get("target_upgrades_path") or context.upgrades_path))
    if not target_upgrades_path.is_absolute():
        raise ValueError("升级后采集目标目录必须是绝对路径。")
    marker_path = target_upgrades_path / context.task_id / "post-upgrade-collection.json"
    task_id = f"post-upgrade-collection-{context.task_id}"
    if marker_path.is_file():
        existing = json.loads(marker_path.read_text(encoding="utf-8"))
        return {
            "task_id": str(existing.get("task_id") or task_id),
            "status": str(existing.get("status") or "pending"),
            "marker_path": str(marker_path),
            "checkpoint": {"completed": True, "marker_path": str(marker_path), **existing},
        }
    marker = {
        "schema_version": 1,
        "parent_upgrade_task_id": context.task_id,
        "task_id": task_id,
        "target_version": str(params.get("target_version") or context.target_version),
        "status": "pending",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker_path.with_suffix(marker_path.suffix + ".tmp")
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, marker_path)
    return {
        "task_id": task_id,
        "status": "pending",
        "marker_path": str(marker_path),
        "checkpoint": {"completed": True, "marker_path": str(marker_path), **marker},
    }


def post_cleanup_precheck_target_health(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    health = _require_cleanup_health(params)
    data_migration_guard = _require_data_migration_guard(params, context)
    return {
        "health": health,
        "data_migration_guard": data_migration_guard,
        "checkpoint": {"completed": True, "health": health, "data_migration_guard": data_migration_guard},
    }


def compose_stop_legacy_project(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    removed_projects: list[str] = []
    skipped: list[dict[str, str]] = []
    for project in params.get("legacy_projects") or []:
        project_name = _safe_docker_name(project)
        if project_name == context.compose_project or project_name == str(params.get("target_project") or ""):
            skipped.append({"type": "project", "name": project_name, "reason": "current project"})
            continue
        containers = _docker_lines(
            context.executor.output(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"label=com.docker.compose.project={project_name}",
                    "--format",
                    "{{.ID}}",
                ]
            )
        )
        named_containers = _docker_lines(
            context.executor.output(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"name={project_name}-",
                    "--format",
                    "{{.ID}}",
                ]
            )
        )
        containers = sorted(set(containers) | set(named_containers))
        removable = [container for container in containers if not _same_container(container, context.current_container_id)]
        if removable:
            context.executor.run(["docker", "stop", *removable])
            context.executor.run(["docker", "rm", *removable])
            removed_projects.append(project_name)
        else:
            skipped.append({"type": "project", "name": project_name, "reason": "missing"})
    return {
        "removed_projects": removed_projects,
        "skipped": skipped,
        "checkpoint": {"completed": True, "removed_projects": removed_projects, "skipped": skipped},
    }


def network_remove_legacy(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    removed_networks: list[str] = []
    skipped: list[dict[str, str]] = []
    legacy_projects = [str(project) for project in params.get("legacy_projects") or []]
    for network in params.get("legacy_networks") or []:
        network_name = _safe_docker_name(network)
        try:
            inspected = context.executor.output(["docker", "network", "inspect", network_name])
        except Exception:
            skipped.append({"type": "network", "name": network_name, "reason": "missing"})
            continue
        try:
            networks = json.loads(inspected or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"无法解析 Docker 网络信息：{network_name}") from exc
        attached = dict((networks[0] if networks else {}).get("Containers") or {})
        legacy_attached: list[str] = []
        external: list[str] = []
        for container_id, item in attached.items():
            name = str(item.get("Name") or container_id)
            if _same_container(container_id, context.current_container_id) or _same_container(name, context.current_container_id):
                external.append(name)
            elif any(_is_legacy_project_container(name, project) for project in legacy_projects):
                legacy_attached.append(str(container_id))
            else:
                external.append(name)
        if external:
            skipped.append({"type": "network", "name": network_name, "reason": f"external containers: {', '.join(sorted(external))}"})
            continue
        if legacy_attached:
            context.executor.run(["docker", "stop", *legacy_attached])
            context.executor.run(["docker", "rm", *legacy_attached])
        context.executor.run(["docker", "network", "rm", network_name])
        removed_networks.append(network_name)
    return {
        "removed_networks": removed_networks,
        "skipped": skipped,
        "checkpoint": {"completed": True, "removed_networks": removed_networks, "skipped": skipped},
    }


def _cleanup_path_hits_current_mount(path: str, context: ActionContext) -> bool:
    try:
        candidate = Path(path).resolve()
    except OSError:
        candidate = Path(path)
    current_mounts = {
        str(context.data_path),
        str(context.upgrades_path),
        str(context.backups_path),
        str(context.exports_path),
        str(context.compose_runtime_path),
        str(context.prometheus_path),
    }
    return str(candidate) in {str(Path(item).resolve()) for item in current_mounts}


def _cleanup_path_is_active_target_mountpoint(path: str, context: ActionContext) -> bool:
    if context.host_data_path is None:
        return False
    try:
        candidate = Path(path).resolve()
    except OSError:
        candidate = Path(path)
    host_data = Path(context.host_data_path)
    mountpoints = [
        (host_data / "upgrades", context.host_upgrades_path),
        (host_data / "backups", context.host_backups_path),
        (host_data / "exports", context.host_exports_path),
        (host_data / "compose-runtime", context.host_compose_runtime_path),
    ]
    for mountpoint, mounted_source in mountpoints:
        if mounted_source is None:
            continue
        if candidate == mountpoint.resolve() and Path(mounted_source).resolve() != mountpoint.resolve():
            return True
    return False


def _cleanup_allowlisted_paths(
    paths: list[str],
    protected_paths: set[str],
    context: ActionContext,
    *,
    helper_image: str = "",
) -> list[dict[str, str]]:
    _require_runner_handoff_before_cleanup(context)
    results: list[dict[str, str]] = []
    for raw in paths:
        reason = _cleanup_path_is_unsafe(raw, protected_paths)
        if reason:
            raise ValueError(f"不允许清理路径 {raw}：{reason}")
    skipped = [
        {"path": raw, "status": "skipped", "reason": "active target mountpoint"}
        for raw in paths
        if _cleanup_path_is_active_target_mountpoint(raw, context)
    ]
    cleanup_paths = [raw for raw in paths if not _cleanup_path_is_active_target_mountpoint(raw, context)]
    if not cleanup_paths:
        return skipped
    if helper_image:
        return [*skipped, *_cleanup_paths_with_host_helper(cleanup_paths, protected_paths, helper_image=helper_image, context=context)]
    mounted_paths = [raw for raw in cleanup_paths if _cleanup_path_hits_current_mount(raw, context)]
    if mounted_paths:
        raise RuntimeError(f"清理宿主机路径需要 helper_image，拒绝在 runner 容器内直接删除活动挂载点：{', '.join(mounted_paths)}")
    for raw in cleanup_paths:
        path = Path(raw)
        if path.exists() or path.is_symlink():
            _remove_path(path)
            results.append({"path": raw, "status": "deleted"})
        else:
            results.append({"path": raw, "status": "missing"})
    return [*skipped, *results]


def filesystem_cleanup_legacy_paths(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    data_migration_guard = _require_data_migration_guard(params, context)
    protected_paths = {str(Path(str(path))) for path in params.get("protected_paths") or []}
    paths = [str(path) for path in params.get("paths") or []]
    results = _cleanup_allowlisted_paths(paths, protected_paths, context, helper_image=str(params.get("helper_image") or ""))
    return {
        "paths": results,
        "data_migration_guard": data_migration_guard,
        "checkpoint": {"completed": True, "paths": results, "data_migration_guard": data_migration_guard},
    }


def filesystem_cleanup_target_app_residuals(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    protected_paths = {str(Path(str(path))) for path in params.get("protected_paths") or []}
    paths = [str(path) for path in params.get("paths") or []]
    results = _cleanup_allowlisted_paths(paths, protected_paths, context, helper_image=str(params.get("helper_image") or ""))
    return {"paths": results, "checkpoint": {"completed": True, "paths": results}}


def post_cleanup_verify(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    health = _require_cleanup_health(params)
    data_migration_guard = _require_data_migration_guard(params, context)
    path_results = []
    for raw in params.get("paths") or []:
        path = Path(str(raw))
        path_results.append({"path": str(raw), "exists": path.exists() or path.is_symlink()})
    return {
        "health": health,
        "data_migration_guard": data_migration_guard,
        "paths": path_results,
        "checkpoint": {"completed": True, "health": health, "data_migration_guard": data_migration_guard, "paths": path_results},
    }


def health_http(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    params = action.get("params", {})
    expected = int(params.get("expected_status") or 200)
    attempts = min(max(int(params.get("attempts") or 30), 1), 120)
    delay = min(max(float(params.get("delay_seconds") or 2), 0), 30)
    timeout = min(max(int(params.get("timeout_seconds") or 15), 1), 60)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(str(params.get("url")), timeout=timeout) as response:
                status = int(response.status)
            if status != expected:
                raise RuntimeError(f"HTTP 健康检查失败：{status}")
            return {"status": status, "attempt": attempt, "checkpoint": {"healthy": True}}
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(delay)
    raise RuntimeError(f"HTTP 健康检查失败，已尝试 {attempts} 次：{last_error}")


def health_prometheus(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    return health_http({"params": {**action.get("params", {}), "expected_status": 200}}, context_payload)


def checkpoint_write(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    return {"checkpoint": {"completed": True, **action.get("params", {})}}


def rollback_restore(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    services = [str(item) for item in params.get("services") or [] if item]
    if services:
        context.executor.run(
            [
                "docker",
                "compose",
                "-f",
                context.compose_file,
                "--project-name",
                context.compose_project,
                "stop",
                *services,
            ],
            cwd=context.project_path,
        )
    backup_path = Path(str(params.get("backup_path") or ""))
    backup_scope = str(params.get("backup_scope") or "platform")
    if backup_path.is_file():
        with tempfile.TemporaryDirectory(dir=context.backups_path) as tmpdir:
            extracted = Path(tmpdir)
            with tarfile.open(backup_path, mode="r:gz") as archive:
                for member in archive.getmembers():
                    relative = Path(member.name)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError(f"回滚备份包含不安全路径：{member.name}")
                _safe_extract(archive, extracted)
            database = extracted / "app" / "smartx.db"
            if backup_scope in {"platform", "bundle"} and database.is_file():
                context.data_path.mkdir(parents=True, exist_ok=True)
                shutil.copy2(database, context.data_path / "smartx.db")
            prometheus = extracted / "prometheus"
            if backup_scope in {"observability", "bundle"} and prometheus.is_dir():
                for source in sorted(prometheus.rglob("*")):
                    relative = source.relative_to(prometheus)
                    target = context.prometheus_path / relative
                    if source.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif source.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
    backup_root = Path(str(params.get("project_backup_path") or ""))
    directory_backup_prefixes = [
        _safe_relative(str(item.get("path") or ""))
        for item in params.get("project_files") or []
        if item.get("backup_type") == "directory" and item.get("path")
    ]
    for item in params.get("project_files") or []:
        if item.get("backup_type") != "directory" or not item.get("backup"):
            continue
        relative = _safe_relative(str(item.get("path") or ""))
        backup = Path(str(item.get("backup")))
        target = context.project_path / relative
        if backup.is_dir():
            _remove_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(backup, target)
    if backup_root.is_dir():
        for source in sorted(backup_root.rglob("*")):
            if source.is_file():
                relative = source.relative_to(backup_root)
                if any(relative == prefix or prefix in relative.parents for prefix in directory_backup_prefixes):
                    continue
                target = context.project_path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for item in params.get("project_files") or []:
        relative = _safe_relative(str(item.get("path") or ""))
        if item.get("backup") is None:
            target = context.project_path / relative
            if target.is_file() or target.is_symlink():
                target.unlink()
    override = Path(str(params.get("override_path") or ""))
    if override.is_file():
        override.unlink()
    if services:
        context.executor.run(
            [
                "docker",
                "compose",
                "-f",
                context.compose_file,
                "--project-name",
                context.compose_project,
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                *services,
            ],
            cwd=context.project_path,
        )
    return {"checkpoint": {"restored": True}}


def default_handlers() -> dict[str, Any]:
    from app.upgrade_runner.sandbox import run_sandboxed_script

    return {
        "backup.create": backup_create,
        "image.load": image_load,
        "filesystem.prepare": filesystem_prepare,
        "files.sync": files_sync,
        "compose.override": compose_override,
        "compose.project_migrate": compose_project_migrate,
        "script.run_sandboxed": run_sandboxed_script,
        "compose.apply": compose_apply,
        "runner.handoff_target_runtime": runner_handoff_target_runtime,
        "runner.schedule_target_runtime_handoff": runner_schedule_target_runtime_handoff,
        "runner.stop_legacy_runtime": runner_stop_legacy_runtime,
        "post_upgrade.schedule_cleanup": post_upgrade_schedule_cleanup,
        "post_upgrade.schedule_collection": post_upgrade_schedule_collection,
        "post_cleanup.precheck_target_health": post_cleanup_precheck_target_health,
        "compose.stop_legacy_project": compose_stop_legacy_project,
        "network.remove_legacy": network_remove_legacy,
        "filesystem.cleanup_legacy_paths": filesystem_cleanup_legacy_paths,
        "filesystem.cleanup_target_app_residuals": filesystem_cleanup_target_app_residuals,
        "post_cleanup.verify": post_cleanup_verify,
        "health.http": health_http,
        "health.prometheus": health_prometheus,
        "task.migrate_runtime_state": task_migrate_runtime_state,
        "task.sync_runtime_state": task_sync_runtime_state,
        "legacy.cleanup": legacy_cleanup,
        "checkpoint.write": checkpoint_write,
        "rollback.restore": rollback_restore,
        # ── W3 自换时代的新动作（只允许出现在由 v0.3.2+ runner 执行的任务中） ──
        # 平台升级计划仍只用上面 26 个 v0.3.1 动作（动作词汇冻结，impl-spec §0.3）。
        "component.verify": component_verify,
        "component.image_load": component_image_load,
        "component.compose_writeback": component_compose_writeback,
        "component.schedule_self_handoff": component_schedule_self_handoff,
    }
