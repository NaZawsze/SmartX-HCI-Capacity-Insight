"""`upgrade/upgrade.sh` 的**源版本支持范围**硬拦截（跨版本兼容）。

背景（2026-10-19 `.14` 实测）：v0.5.1u2 源端跑本脚本时，早先只有 runner 执行门槛
（v0.3.1 < v0.3.2 → 「先组件、后平台」）。但 v0.5.4 的 `source_compatibility` 是
v0.5.2~v0.5.4——照那条提示操作会把客户带进**不受支持**的直升路径。正确出路是
先升 v0.5.3。因此脚本必须先按 manifest 的 source_compatibility 判源版本，
并把包自带的 `remediation` 原样透传（拒绝必须带出路）。

这里用桩命令跑真实脚本，不需要 Docker/真机。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPGRADE = ROOT / "delivery" / "upgrade" / "upgrade.sh"


def _write_package(directory: Path, *, min_version: str = "v0.5.2", max_version: str = "v0.5.4") -> Path:
    """造一个只含 manifest.json 的平台包（SHA256SUMS 缺失时脚本会跳过本地校验）。"""
    manifest = {
        "schema_version": "3",
        "version": "v0.5.4",
        "minimum_runner_version": "v0.3.2",
        "minimum_runner_protocol": 1,
        "source_compatibility": {
            "min_version": min_version,
            "max_version_inclusive": max_version,
            "target_version": "v0.5.4",
            "supported_versions": ["v0.5.2", "v0.5.3", "v0.5.4"],
            "remediation": "v0.5.4 不支持 ≤v0.5.1u2 源；请先升级 v0.5.3（链路已验证）再升 v0.5.4",
        },
        "components": [],
    }
    stage = directory / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    package = directory / "smartx-capacity-insight-upgrade-v0.5.4.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        archive.add(stage / "manifest.json", arcname="manifest.json")
    return package


def _run_upgrade(tmp: Path, package: Path, *, health: dict) -> subprocess.CompletedProcess:
    """用桩 curl 跑脚本：health 返回给定 JSON，其它 API 调用返回空（让脚本停在下一次 die）。"""
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    health_json = json.dumps(health, ensure_ascii=False)
    curl_stub = bin_dir / "curl"
    curl_stub.write_text(
        "#!/usr/bin/env bash\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        f"    *api/system/health*) printf '%s' '{health_json}'; exit 0 ;;\n"
        "  esac\n"
        "done\n"
        "printf '%s' ''\n"
        "exit 0\n",
        encoding="utf-8",
    )
    curl_stub.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(UPGRADE), "--yes", "--package", str(package), "--admin-user", "admin", "--admin-password", "x"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


class UpgradeScriptSourceCompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.assertTrue(UPGRADE.is_file(), "缺少 delivery/upgrade/upgrade.sh")

    def test_unsupported_source_is_blocked_with_package_remediation(self) -> None:
        """v0.5.1u2 源：必须拒绝，并把包的 remediation（先升 v0.5.3）原样给出。"""
        package = _write_package(self.tmp)
        result = _run_upgrade(self.tmp, package, health={"ok": True, "version": "v0.5.1u2", "runner_version": "v0.3.1"})
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("不在升级包支持范围内", output)
        self.assertIn("v0.5.1u2", output)
        self.assertIn("v0.5.2 ~ v0.5.4", output)
        self.assertIn("请先升级 v0.5.3", output, "必须透传包里的 remediation，而不是只报一句不支持")
        self.assertIn("尚未发起任何升级", output)
        # 不得把「先组件后平台」当出路——那是受支持源版本的顺序，不是 ≤v0.5.1u2 的
        self.assertNotIn("先把 upgrade-runner 组件升到", output)

    def test_supported_source_passes_source_gate(self) -> None:
        """v0.5.3 源：源版本门禁放行（后续会在登录环节失败，与本门禁无关）。"""
        package = _write_package(self.tmp)
        result = _run_upgrade(self.tmp, package, health={"ok": True, "version": "v0.5.3", "runner_version": "v0.3.2"})
        output = result.stdout + result.stderr
        self.assertIn("源版本支持范围：v0.5.2 ~ v0.5.4（当前 v0.5.3）", output)
        self.assertNotIn("不在升级包支持范围内", output)
        self.assertNotIn("低于升级包执行门槛", output, "runner v0.3.2 已满足门槛，不应触发拦截")

    def test_v052_source_without_runner_gets_v053_path(self) -> None:
        """v0.5.2 源 + runner 不满足门槛：不得给「先组件后平台」这个死胡同。

        US-04：v0.5.2 的 web-api 会无条件停掉刚启动的新 runner，所以那里升不上去。
        正确指引是先升 v0.5.3（版本偏斜矩阵的 remediation）。
        """
        package = _write_package(self.tmp)
        result = _run_upgrade(self.tmp, package, health={"ok": True, "version": "v0.5.2", "runner_version": "未检测到 runner"})
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("无法先升 runner", output)
        self.assertIn("先把平台升到 v0.5.3", output)
        self.assertIn("尚未发起任何升级", output)
        self.assertNotIn("正确顺序：先把 upgrade-runner 组件升到", output)

    def test_v053_source_with_low_runner_keeps_component_first_hint(self) -> None:
        """v0.5.3 源 + runner v0.3.1：这里「先组件后平台」是正确顺序，必须保留。"""
        package = _write_package(self.tmp)
        result = _run_upgrade(self.tmp, package, health={"ok": True, "version": "v0.5.3", "runner_version": "v0.3.1"})
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("低于升级包执行门槛", output)
        self.assertIn("先把 upgrade-runner 组件升到 v0.3.2", output)
        self.assertNotIn("无法先升 runner", output)


if __name__ == "__main__":
    unittest.main()
