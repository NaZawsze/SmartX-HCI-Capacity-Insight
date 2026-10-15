"""`collection/service.py` 的依赖兼容层（**worker 镜像不带 fastapi**）。

`collector-worker` 与 `web-api` 用**不同的依赖集**构建（`requirements-worker.txt` 不含 fastapi），
但两者都会 import `app.v2.collection.service`（worker 经 `app.v2.worker`）。因此本模块**不得**硬依赖
fastapi —— 与 `app/v2/upgrade/service/_compat.py`（runner 侧）同一模式。

2026-10-15 事故：`submit_manual_collection` 直接 `from fastapi import HTTPException` ⇒ 全新安装后
`collector-worker` 立即 `ModuleNotFoundError` 崩溃重启（`.14` 链 A 真机发现）。
"""

from __future__ import annotations

try:  # pragma: no cover - 有依赖时走真实实现（web-api 路径）
    from fastapi import HTTPException
except ModuleNotFoundError:  # pragma: no cover - worker 镜像路径

    class HTTPException(Exception):  # type: ignore[no-redef]
        def __init__(self, status_code: int, detail: str) -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)


__all__ = ["HTTPException"]
