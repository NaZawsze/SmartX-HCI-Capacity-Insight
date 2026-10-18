"""L3-c 门禁：平台包必须声明**执行**所需的最低 runner 版本。

背景：v0.5.1u2 → v0.5.2 → 直连 v0.5.4 时，runner v0.3.1 的能力集与 v0.3.2 同名同数，
能力级预检查放行；但其沙箱把容器内包路径原样挂给 docker（旧布局下两者一致所以能跑），
v0.5.2 布局迁移后挂载源不存在 → 迁移脚本失败在 image.load 之后、compose.apply 之前，
环境半迁移。因此平台包要显式声明执行门槛，预检查按**版本号**拒绝。

「安装基线」（`_expected_web_api_runner_baseline`，按发布事实钉已发布版）与
「执行门槛」（本模块测的字段）是两件事，不能混用。
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_builder():
    path = ROOT / "scripts" / "build_upgrade_package.py"
    spec = importlib.util.spec_from_file_location("build_upgrade_package", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlatformExecutionRunnerMinimumTest(unittest.TestCase):
    def test_v054_requires_v032_execution_runner(self) -> None:
        module = _load_builder()
        self.assertEqual(module._platform_execution_minimum_runner("v0.5.4"), "v0.3.2")

    def test_other_versions_declare_nothing(self) -> None:
        module = _load_builder()
        for version in ("v0.5.2", "v0.5.3", "v0.5.1u2", ""):
            self.assertEqual(module._platform_execution_minimum_runner(version), "", version)

    def test_manifest_wiring_overrides_baseline(self) -> None:
        """安装基线不得泄漏成执行门槛：manifest 的 minimum_runner_version 必须被执行门槛覆盖。"""
        source = (ROOT / "scripts" / "build_upgrade_package.py").read_text(encoding="utf-8")
        self.assertIn('manifest["minimum_runner_version"] = execution_runner', source)
        self.assertIn("PLATFORM_EXECUTION_RUNNER_MINIMUM", source)

    def test_precheck_compares_runner_version(self) -> None:
        """预检查必须真的比版本号（只在报错文案里用等于没拦）。"""
        source = (ROOT / "backend" / "app" / "v2" / "upgrade" / "service" / "execution.py").read_text(encoding="utf-8")
        self.assertIn("_version_tuple(runner_version) < _version_tuple(minimum_runner_version)", source)


if __name__ == "__main__":
    unittest.main()
