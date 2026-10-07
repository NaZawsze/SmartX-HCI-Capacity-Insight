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
    # `-v` 左半边由宿主 dockerd 解析：脚本挂载与参数挂载一样必须过
    # docker_host_path()——容器内 /data/upgrades/... 在宿主是
    # /data/smartx-storage-forecast/upgrades/...，两者不一致时源路径在宿主
    # 不存在，dockerd 会静默自建**空目录**，Python 挂到目录上只报
    # "can't find '__main__' module"（US-40，.3 2026-10-08 升级 r34 首跑实证）。
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
        f"{context.docker_host_path(script)}:/upgrade/{script.name}:ro",
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
