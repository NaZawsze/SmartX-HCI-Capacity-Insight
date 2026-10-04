"""损坏文件的读取必须给可读错误，而非 500（pending #80，2026-10-04）。

`intake.py::_read_manifest` 原先只捕 `json.JSONDecodeError`。而
`path.read_text(encoding="utf-8")` 对非 UTF-8 字节抛的是 `UnicodeDecodeError`
（`JSONDecodeError` 的父类是 `ValueError`，两者都继承自 `ValueError`，
但 `UnicodeDecodeError` **不是** `JSONDecodeError` 的子类），于是直接穿透成
500 Internal Server Error。

后果是两类坏包表现不一致：
- 合法 UTF-8 但非法 JSON → 干净的 400「manifest.json 格式不正确」
- 根本不是合法 UTF-8（截断/二进制损坏）→ **500**，客户看到底层报错

本文件的用例钉住两者都返回 400。另覆盖 `_read_task_file` 的同类问题
（损坏的 task.json 不得让 `history()`/`status()` 整页 500）。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path


class CorruptManifestReadTest(unittest.TestCase):
    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeService

        settings = V2Settings(data_root=Path(tmpdir), secret_key="s", app_version="v0.5.3")
        database = V2Database(settings)
        database.initialize()
        return settings, UpgradeService(settings, TaskService(database))

    def _upload(self, service, payload: bytes) -> None:
        from app.v2.upgrade.service._compat import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            service.upload_package_bytes(payload, filename="upgrade.tar.gz")
        self.assertEqual(ctx.exception.status_code, 400, f"实际 {ctx.exception.status_code}")
        return ctx.exception.detail

    def _tar_with_manifest_bytes(self, manifest_bytes: bytes) -> bytes:
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            ti = tarfile.TarInfo("manifest.json")
            ti.size = len(manifest_bytes)
            tf.addfile(ti, io.BytesIO(manifest_bytes))
        return buf.getvalue()

    def test_binary_manifest_returns_400_not_500(self) -> None:
        """非 UTF-8 的 manifest → 400（回归守卫：原为 500）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, service = self._service(tmpdir)
            detail = self._upload(service, self._tar_with_manifest_bytes(os.urandom(2048)))
            self.assertIn("损坏", str(detail))
            self.assertIn("UTF-8", str(detail))

    def test_valid_utf8_invalid_json_returns_400(self) -> None:
        """合法 UTF-8 但非法 JSON → 仍是 400（既有行为不得回退）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, service = self._service(tmpdir)
            detail = self._upload(service, self._tar_with_manifest_bytes(b"{not json"))
            self.assertIn("格式不正确", str(detail))

    def test_truncated_utf8_manifest_returns_400(self) -> None:
        """多字节 UTF-8 字符被截断（典型的传输中断）→ 400 而非 500。

        切在**字符中间**才是非法 UTF-8。这里在测试内自验证构造出的字节确实解码失败，
        不靠手算字节偏移——首次写这个用例时我把 `[:-2]` 当成"切在字符中间"，
        实际它只砍掉了结尾的 `"}`，UTF-8 依然合法，于是走的是「非法 JSON」分支，
        用例以「断言 损坏 失败」暴露。
        """
        full = json.dumps({"v": "中文"}, ensure_ascii=False).encode("utf-8")
        truncated = full[:-3]
        with self.assertRaises(UnicodeDecodeError):
            truncated.decode("utf-8")  # 自验证：确实是坏 UTF-8

        with tempfile.TemporaryDirectory() as tmpdir:
            _, service = self._service(tmpdir)
            detail = self._upload(service, self._tar_with_manifest_bytes(truncated))
            self.assertIn("损坏", str(detail))

    def test_corrupt_task_json_does_not_break_history(self) -> None:
        """损坏的 task.json 不得让 history() 整页 500。"""
        from app.v2.upgrade.service._compat import HTTPException

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            bad = settings.upgrades_dir / "upgrade-bad01"
            bad.mkdir(parents=True)
            (bad / "task.json").write_bytes(os.urandom(512))

            with self.assertRaises(HTTPException) as ctx:
                service.history()
            self.assertNotEqual(
                ctx.exception.status_code,
                500,
                "损坏记录不应产生 500",
            )
            self.assertIn(ctx.exception.status_code, (400, 404))

    def test_corrupt_task_json_status_is_clean_error(self) -> None:
        """按 ID 查一个记录损坏的任务 → 干净 404，而非 500。"""
        from app.v2.upgrade.service._compat import HTTPException

        with tempfile.TemporaryDirectory() as tmpdir:
            settings, service = self._service(tmpdir)
            bad = settings.upgrades_dir / "upgrade-bad02"
            bad.mkdir(parents=True)
            (bad / "task.json").write_bytes(os.urandom(512))

            with self.assertRaises(HTTPException) as ctx:
                service.status("upgrade-bad02")
            self.assertEqual(ctx.exception.status_code, 404)
            self.assertIn("损坏", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
