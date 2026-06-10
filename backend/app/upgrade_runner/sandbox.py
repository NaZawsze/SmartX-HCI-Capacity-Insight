from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.upgrade_runner.actions import ActionContext, _context, _safe_relative


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_sandboxed_script(action: dict[str, Any], context_payload: dict[str, Any]) -> dict[str, Any]:
    context: ActionContext = _context(context_payload)
    params = action.get("params", {})
    script = context.package_path / _safe_relative(str(params.get("script") or ""))
    if not script.is_file():
        raise FileNotFoundError(f"迁移脚本不存在：{script}")
    expected = str(params.get("sha256") or "")
    actual = _sha256(script)
    if not expected or actual != expected:
        raise ValueError("迁移脚本 SHA256 校验失败。")
    timeout = min(max(int(params.get("timeout_seconds") or 900), 1), 3600)
    image = str(params.get("image") or "")
    if not image:
        raise ValueError("迁移脚本未声明执行镜像。")

    allowed_roots = [
        context.data_path.resolve(),
        context.backups_path.resolve(),
        context.prometheus_path.resolve(),
        context.project_path.resolve(),
        context.compose_runtime_path.resolve(),
    ]
    command = [
        "docker",
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-v",
        f"{script}:/upgrade/{script.name}:ro",
    ]
    for mount in params.get("mounts") or []:
        source = Path(str(mount.get("source") or "")).resolve()
        data_root = context.data_path.resolve()
        if data_root in source.parents:
            relative = source.relative_to(data_root)
            if relative.parts and relative.parts[0] in {"exports", "upgrades"}:
                raise ValueError(f"沙箱禁止挂载运行产物目录：{source}")
        if not any(source == root or root in source.parents for root in allowed_roots):
            raise ValueError(f"沙箱挂载路径不在白名单：{source}")
        target = str(mount.get("target") or "")
        mode = "rw" if mount.get("mode") == "rw" else "ro"
        command.extend(["-v", f"{context.docker_host_path(source)}:{target}:{mode}"])
    interpreter = "python" if script.suffix == ".py" else "sh"
    command.extend([image, interpreter, f"/upgrade/{script.name}"])
    context.executor.run(command, timeout=timeout)

    marker = params.get("completion_marker")
    if marker and not Path(str(marker)).is_file():
        raise RuntimeError("迁移脚本未写入完成标记。")
    return {"checkpoint": {"completed": True, "sha256": actual}, "timeout_seconds": timeout}
