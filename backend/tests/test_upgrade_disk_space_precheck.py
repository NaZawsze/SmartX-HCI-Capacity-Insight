from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.v2.upgrade.service.precheck import (  # noqa: E402
    COMPRESSED_ARCHIVE_EXPANSION,
    _check_disk_space,
    human_bytes,
    package_payload_bytes,
    required_upgrade_bytes,
)
from tests.test_v2_upgrade import build_schema3_package, record_runner_state  # noqa: E402

GIB = 1024 ** 3
# 与本文件其它用例一致：构造的升级包约 1000 字节
PACKAGE_SIZE = 1000


class RequiredBytesTest(unittest.TestCase):
    def test_required_is_payload_plus_headroom(self):
        self.assertEqual(required_upgrade_bytes(1000, 500), 1500)

    def test_negative_headroom_is_clamped(self):
        self.assertEqual(required_upgrade_bytes(1000, -5), 1000)

    def test_human_bytes_uses_binary_units(self):
        self.assertEqual(human_bytes(0), "0.00 B")
        self.assertEqual(human_bytes(1536), "1.50 KiB")
        self.assertEqual(human_bytes(3 * GIB), "3.00 GiB")


class PayloadBytesTest(unittest.TestCase):
    def test_directory_payload_is_sum_of_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "manifest.json").write_bytes(b"m" * 100)
            (root / "images").mkdir()
            (root / "images" / "web-api.tar").write_bytes(b"i" * 900)
            self.assertEqual(package_payload_bytes(root), 1000)

    def test_archive_payload_applies_expansion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "upgrade.tar.gz"
            archive.write_bytes(b"x" * 1000)
            self.assertEqual(package_payload_bytes(archive), 1000 * COMPRESSED_ARCHIVE_EXPANSION)


class DiskSpaceCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.package = Path(self.tmp.name) / "upgrade.tar.gz"
        self.package.write_bytes(b"x" * 1000)
        self.targets = [Path(self.tmp.name)]

    def _usage(self, free):
        return lambda _path: SimpleNamespace(total=free * 4, used=free * 3, free=free)

    def test_passes_when_free_space_is_enough(self):
        result = _check_disk_space(self.package, self.targets, GIB, usage=self._usage(10 * GIB))
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "disk_space")
        self.assertEqual(result["detail"]["package_bytes"], 1000 * COMPRESSED_ARCHIVE_EXPANSION)
        self.assertEqual(result["detail"]["required_bytes"], 1000 * COMPRESSED_ARCHIVE_EXPANSION + GIB)

    def test_directory_package_uses_sum_of_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "package"
            (root / "images").mkdir(parents=True)
            (root / "images" / "web-api.tar").write_bytes(b"i" * 5000)
            (root / "manifest.json").write_bytes(b"m" * 100)
            result = _check_disk_space(root, [Path(tmpdir)], GIB, usage=self._usage(10 * GIB))
        self.assertTrue(result["detail"]["payload_uncompressed"])
        self.assertEqual(result["detail"]["package_bytes"], 5100)
        self.assertEqual(result["detail"]["required_bytes"], 5100 + GIB)

    def test_fails_when_free_space_is_short(self):
        result = _check_disk_space(self.package, self.targets, GIB, usage=self._usage(1))
        self.assertFalse(result["ok"])
        self.assertIn("磁盘空间不足", result["message"])
        self.assertIn(str(self.targets[0]), result["message"])
        self.assertEqual(len(result["detail"]["filesystems"]), 1)

    def test_missing_package_fails(self):
        missing = Path(self.tmp.name) / "nope.tar.gz"
        result = _check_disk_space(missing, self.targets, GIB, usage=self._usage(10 * GIB))
        self.assertFalse(result["ok"])
        self.assertIn("无法读取升级包大小", result["message"])

    def test_filesystems_on_same_device_are_checked_once(self):
        child = Path(self.tmp.name) / "backups"
        child.mkdir()
        result = _check_disk_space(self.package, [Path(self.tmp.name), child], GIB, usage=self._usage(10 * GIB))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["detail"]["filesystems"]), 1)

    def test_unreadable_targets_are_skipped(self):
        result = _check_disk_space(
            self.package, [Path(self.tmp.name), Path(self.tmp.name) / "missing-dir"], GIB, usage=self._usage(10 * GIB)
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["detail"]["filesystems"]), 1)

    def test_all_targets_unreadable_fails(self):
        result = _check_disk_space(self.package, [Path(self.tmp.name) / "missing-dir"], GIB, usage=self._usage(10 * GIB))
        self.assertFalse(result["ok"])
        self.assertIn("无法获取", result["message"])

    def test_no_headroom_still_requires_package_expansion(self):
        result = _check_disk_space(self.package, self.targets, 0, usage=self._usage(1000))
        self.assertFalse(result["ok"])
        self.assertEqual(result["detail"]["required_bytes"], 1000 * COMPRESSED_ARCHIVE_EXPANSION)


class PrecheckIntegrationTest(unittest.TestCase):
    """预检查集成：真实包走一遍 checks，确认 disk_space 项存在且低空间时拦下升级。"""

    def _service(self, tmpdir: str):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def run(self, command, *, cwd=None):  # pragma: no cover - 不实际执行
                return None

        settings = V2Settings(data_root=Path(tmpdir), secret_key="upgrade-secret", app_version="v0.5.2")
        database = V2Database(settings)
        database.initialize()
        record_runner_state(database)
        return UpgradeService(
            settings, TaskService(database), executor=FakeExecutor(), project_path=Path(tmpdir) / "project"
        )

    def _manifest(self) -> dict:
        image = b"web-api-image"
        return {
            "schema_version": "3",
            "minimum_runner_protocol": 1,
            "required_capabilities": ["backup.create", "image.load", "files.sync", "compose.apply", "rollback.restore"],
            "version": "v0.5.2",
            "min_version": "v0.5.0",
            "source_compatibility": {
                "min_version": "v0.5.0",
                "max_version_inclusive": "v0.5.2",
                "target_version": "v0.5.2",
                "allow_same_version": True,
                "supported_versions": ["v0.5.0", "v0.5.1", "v0.5.1u2", "v0.5.2"],
                "message": "ok",
            },
            "components": [
                {
                    "type": "platform",
                    "services": ["web-api"],
                    "images": [
                        {
                            "service": "web-api",
                            "image": "repo/web-api:v0.5.2",
                            "archive": "images/web-api.tar",
                            "sha256": hashlib.sha256(image).hexdigest(),
                        }
                    ],
                }
            ],
        }


    def _precheck(self, service, manifest: dict):
        task = service.upload_package_bytes(
            build_schema3_package(manifest, {"images/web-api.tar": b"web-api-image"}), filename="upgrade.tar.gz"
        )
        return service.precheck(task["task_id"])

    def test_disk_space_check_present_and_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            precheck = self._precheck(self._service(tmpdir), self._manifest())
        disk = next(item for item in precheck["checks"] if item["name"] == "disk_space")
        self.assertTrue(disk["ok"], disk)
        self.assertGreater(disk["detail"]["required_bytes"], 0)
        self.assertIn("filesystems", disk["detail"])

    def test_precheck_fails_when_free_space_is_short(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            # 语义更新（2026-10-04）：上传前置检查只拦「物理上装不下」
            # （阈值 = 包本体 × 膨胀系数，不含 headroom）。所以这里必须给一个
            # **装得下包、但不够 headroom** 的空间，才能走到 precheck 触发
            # disk_space 判定——原先 mock free=1 字节会被前置检查截胡，
            # 本用例的意图（验证 precheck 的 9 项检查结构）就丢了。
            free = PACKAGE_SIZE * COMPRESSED_ARCHIVE_EXPANSION + GIB // 2
            with mock.patch(
                "shutil.disk_usage",
                lambda _path: SimpleNamespace(total=free * 10, used=free * 9, free=free),
            ):
                precheck = self._precheck(service, self._manifest())
        self.assertFalse(precheck["ok"])
        disk = next(item for item in precheck["checks"] if item["name"] == "disk_space")
        self.assertFalse(disk["ok"])
        self.assertIn("磁盘空间不足", disk["message"])

    def test_headroom_configuration_blocks_precheck(self):
        from app.v2.config import V2Settings
        from app.v2.database import V2Database
        from app.v2.tasks.service import TaskService
        from app.v2.upgrade.service import UpgradeCommandExecutor, UpgradeService

        class FakeExecutor(UpgradeCommandExecutor):
            def run(self, command, *, cwd=None):  # pragma: no cover
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = V2Settings(
                data_root=Path(tmpdir),
                secret_key="upgrade-secret",
                app_version="v0.5.2",
                upgrade_disk_headroom_bytes=10 ** 15,
            )
            database = V2Database(settings)
            database.initialize()
            record_runner_state(database)
            service = UpgradeService(
                settings, TaskService(database), executor=FakeExecutor(), project_path=Path(tmpdir) / "project"
            )
            # 语义更新（2026-10-04）：headroom 是**业务配置**，只影响 precheck 判定，
            # 不该在上传阶段拦（上传前置检查只用「包 × 膨胀系数」这个物理口径）。
            # 因此这里不 mock 磁盘——真实临时目录空间充足，上传必然通过，
            # 由 precheck 因 headroom=1PB 而判FAIL，用例意图完整保留。
            precheck = self._precheck(service, self._manifest())
        disk = next(item for item in precheck["checks"] if item["name"] == "disk_space")
        self.assertFalse(disk["ok"])
        self.assertEqual(disk["detail"]["headroom_bytes"], 10 ** 15)


if __name__ == "__main__":
    unittest.main()
