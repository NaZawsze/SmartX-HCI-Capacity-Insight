from __future__ import annotations

try:  # upgrade-runner intentionally avoids the web-api dependency stack.
    from fastapi import HTTPException, UploadFile
except ModuleNotFoundError:  # pragma: no cover - covered by runner image import smoke test.
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str) -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    class UploadFile:  # type: ignore[no-redef]
        filename: str | None
