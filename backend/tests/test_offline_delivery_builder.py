"""49-56 步骤 1：`build_offline_delivery.py` 的单元测试。

用**小的假包**构造，不依赖真实的几百 MB 交付物，因此本地/`.3` 都能秒级跑完。
真包路径由 `.3`/`.12` 上的实测覆盖（见 progress.md）。
"""

from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.build_offline_delivery import (
    FORBIDDEN_DIR_HINTS,
    extract_member,
    render_offline_compose,
    scan_forbidden,
    write_sha256sums,
)


def _make_tar_gz(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class ExtractMemberTest(unittest.TestCase):
    def test_extracts_by_exact_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "pkg.tar.gz"
            _make_tar_gz(archive, {"images/web-api.tar": b"web-api-bytes", "manifest.json": b"{}"})
            out = extract_member(archive, "images/web-api.tar", Path(tmpdir) / "out" / "web-api.tar")
            self.assertEqual(out.read_bytes(), b"web-api-bytes")

    def test_extracts_by_suffix_for_nested_layout(self) -> None:
        """OCI/多层布局下成员名可能带前缀，按后缀也要能取到。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "pkg.tar.gz"
            _make_tar_gz(archive, {"top/dir/images/frontend.tar": b"frontend-bytes"})
            out = extract_member(archive, "images/frontend.tar", Path(tmpdir) / "frontend.tar")
            self.assertEqual(out.read_bytes(), b"frontend-bytes")

    def test_missing_member_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "pkg.tar.gz"
            _make_tar_gz(archive, {"manifest.json": b"{}"})
            with self.assertRaises(SystemExit):
                extract_member(archive, "images/web-api.tar", Path(tmpdir) / "x.tar")


class RenderOfflineComposeTest(unittest.TestCase):
    def _compose(self, tmpdir: str) -> Path:
        path = Path(tmpdir) / "docker-compose.offline.yml"
        path.write_text(
            "services:\n"
            "  web-api:\n"
            "    image: repo/web-api:v0.5.3\n"
            "    pull_policy: never\n"
            "  upgrade-runner:\n"
            "    build:\n"
            "      context: .\n"
            "    image: nazawsze/smartx-hci-capacity-insight-upgrade-runner:v0.3.2\n"
            "    env_file:\n"
            "      - .env\n"
            "  prometheus:\n"
            "    image: prom/prometheus:v2.55.1\n",
            encoding="utf-8",
        )
        return path

    def test_renders_published_baseline(self) -> None:
        """交付 compose 必须落已发布基线，而不是源码 compose 的开发线 tag。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = self._compose(tmpdir)
            target = Path(tmpdir) / "out.yml"
            render_offline_compose(source, target, "v0.3.1")
            text = target.read_text(encoding="utf-8")
            self.assertIn("upgrade-runner:v0.3.1", text)
            self.assertNotIn("upgrade-runner:v0.3.2", text)
            # 其它服务与键不得被改动
            self.assertIn("image: repo/web-api:v0.5.3", text)
            self.assertIn("image: prom/prometheus:v2.55.1", text)
            self.assertIn("    build:\n", text)
            self.assertIn("      - .env\n", text)

    def test_raises_when_runner_image_line_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "compose.yml"
            source.write_text("services:\n  web-api:\n    image: repo/web-api:v0.5.3\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                render_offline_compose(source, Path(tmpdir) / "out.yml", "v0.3.1")


class Sha256SumsTest(unittest.TestCase):
    def test_writes_verifiable_sums(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "a.tar").write_bytes(b"aaa")
            (directory / "b.tar").write_bytes(b"bb")
            target = write_sha256sums(directory, ["a.tar", "b.tar"])
            lines = target.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            # 格式必须是 `sha256sum -c` 能直接吃的两空格分隔
            for line in lines:
                self.assertRegex(line, r"^[0-9a-f]{64}  \S+$")

    def test_sorted_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            for name in ("z.tar", "a.tar"):
                (directory / name).write_bytes(b"x")
            target = write_sha256sums(directory, ["z.tar", "a.tar"])
            names = [line.split("  ", 1)[1] for line in target.read_text(encoding="utf-8").strip().splitlines()]
            self.assertEqual(names, ["a.tar", "z.tar"], "输出必须排序，保证两次构建结果一致")


class ScanForbiddenTest(unittest.TestCase):
    def test_clean_delivery_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "install" / "images").mkdir(parents=True)
            (root / "install" / "images" / "web-api.tar").write_bytes(b"x")
            (root / "install" / ".env.template").write_text("SMARTX_SECRET_KEY=__GENERATE__", encoding="utf-8")
            (root / "upgrade" / "packages").mkdir(parents=True)
            (root / "upgrade" / "packages" / "pkg.tar.gz").write_bytes(b"x")
            self.assertEqual(scan_forbidden(root), [])

    def test_detects_real_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "install").mkdir(parents=True)
            (root / "install" / ".env").write_text("SMARTX_SECRET_KEY=real", encoding="utf-8")
            self.assertIn("install/.env", scan_forbidden(root))

    def test_detects_database_and_backup_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app").mkdir(parents=True)
            (root / "app" / "smartx.db").write_bytes(b"x")
            hint = FORBIDDEN_DIR_HINTS[0]
            (root / hint).mkdir(parents=True)
            (root / hint / "upgrade-x.tar.gz").write_bytes(b"x")
            hits = scan_forbidden(root)
            self.assertIn("app/smartx.db", hits)
            self.assertTrue(any(h.startswith(hint) for h in hits))

    def test_env_template_is_allowed(self) -> None:
        """.env.template 是交付物必需的（脚本据此生成），不能被禁含规则误伤。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env.template").write_text("SMARTX_SECRET_KEY=__GENERATE__", encoding="utf-8")
            self.assertEqual(scan_forbidden(root), [])


class ScriptContractTest(unittest.TestCase):
    def test_script_requires_mandatory_args(self) -> None:
        """缺必填参数必须退出（而不是带着 None 往下跑）。"""
        from scripts.build_offline_delivery import main

        with mock.patch("sys.argv", ["build_offline_delivery.py"]), self.assertRaises(SystemExit):
            main()

    def test_platform_services_cover_offline_compose(self) -> None:
        """平台三件套必须与 offline compose 的服务一致，漏一个安装就起不来。"""
        from scripts.build_offline_delivery import PLATFORM_SERVICES

        compose = (Path(__file__).resolve().parent.parent.parent / "docker-compose.offline.yml").read_text(
            encoding="utf-8"
        )
        for service, _member in PLATFORM_SERVICES:
            self.assertIn(f"  {service}:", compose, f"offline compose 缺服务 {service}")
        self.assertIn("  upgrade-runner:", compose)
        self.assertIn("  prometheus:", compose)


if __name__ == "__main__":
    unittest.main()
