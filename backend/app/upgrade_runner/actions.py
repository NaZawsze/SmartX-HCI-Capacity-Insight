from __future__ import annotations

import hashlib
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
    backups_path: Path
    compose_runtime_path: Path
    prometheus_path: Path
    compose_file: str
    compose_project: str
    executor: CommandExecutor
    task_id: str = "upgrade-task"
    target_version: str = "unknown"
    host_data_path: Path | None = None
    host_backups_path: Path | None = None
    host_compose_runtime_path: Path | None = None
    host_prometheus_path: Path | None = None
    host_project_path: Path | None = None

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
            backups_path=root / "backups",
            compose_runtime_path=root / "compose-runtime",
            prometheus_path=root / "prometheus",
            compose_file="docker-compose.offline.yml",
            compose_project="smartx-storage-forecast",
            executor=executor or CommandExecutor(),
        )
        for path in (
            context.package_path,
            context.project_path,
            context.data_path,
            context.backups_path,
            context.compose_runtime_path,
            context.prometheus_path,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return context

    def as_dict(self) -> dict[str, Any]:
        return {"action_context": self}

    def docker_host_path(self, source: Path) -> Path:
        resolved = source.resolve()
        mappings = (
            (self.backups_path.resolve(), self.host_backups_path),
            (self.compose_runtime_path.resolve(), self.host_compose_runtime_path),
            (self.prometheus_path.resolve(), self.host_prometheus_path),
            (self.project_path.resolve(), self.host_project_path),
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


def files_sync(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(context_payload)
    params = action.get("params", {})
    source_root = context.package_path / _safe_relative(str(params.get("source") or "project"))
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
        target = context.project_path / relative
        backup = backup_root / relative
        if target.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        journal.append({"path": str(relative), "sha256": _sha256(target), "backup": str(backup) if backup.exists() else None})
        _persist_checkpoint(context_payload, {"files": journal})
    return {"backup_path": str(backup_root), "checkpoint": {"files": journal, "completed": True}}


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
    return {"services": services, "checkpoint": {"submitted": True}}


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
                archive.extractall(extracted, filter="data")
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
    if backup_root.is_dir():
        for source in sorted(backup_root.rglob("*")):
            if source.is_file():
                relative = source.relative_to(backup_root)
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
        "files.sync": files_sync,
        "compose.override": compose_override,
        "script.run_sandboxed": run_sandboxed_script,
        "compose.apply": compose_apply,
        "health.http": health_http,
        "health.prometheus": health_prometheus,
        "checkpoint.write": checkpoint_write,
        "rollback.restore": rollback_restore,
    }
