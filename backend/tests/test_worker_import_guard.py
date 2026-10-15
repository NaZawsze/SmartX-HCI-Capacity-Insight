"""worker 镜像导入守卫：`app.v2.worker` 的模块链**不得硬依赖 fastapi**。

背景（2026-10-15 `.14` 链 A 真机事故）：`collector-worker` 与 `web-api` 用**不同依赖集**构建
（`requirements-worker.txt` 不含 fastapi），但两者都会 import `app.v2.collection.service`。
`submit_manual_collection` 直接 `from fastapi import HTTPException` ⇒ 全新安装后
`collector-worker` 立即 `ModuleNotFoundError` 崩溃重启。

本测试在「屏蔽 fastapi」的环境下 import worker，锁死这条约束（与 runner 侧
`upgrade/service/_compat.py` 的镜像导入冒烟同思路）。
"""

import importlib
import importlib.abc
import sys
import unittest


class _BlockFastapi(importlib.abc.MetaPathFinder):
    """让 `import fastapi[...]` 抛 ModuleNotFoundError（模拟 worker 镜像）。"""

    def find_spec(self, fullname, path=None, target=None):  # noqa: D102 - 见类说明
        if fullname == "fastapi" or fullname.startswith("fastapi."):
            raise ModuleNotFoundError(f"No module named '{fullname}'")
        return None


class WorkerImportGuardTest(unittest.TestCase):
    def test_worker_chain_imports_without_fastapi(self):
        saved = {name: module for name, module in list(sys.modules.items()) if name.startswith("app.v2")}
        for name in saved:
            del sys.modules[name]
        finder = _BlockFastapi()
        sys.meta_path.insert(0, finder)
        try:
            importlib.import_module("app.v2.worker")
        except ModuleNotFoundError as exc:
            self.assertNotIn(
                "fastapi", str(exc),
                "worker 模块链硬依赖了 fastapi —— worker 镜像不带 fastapi，会导致 collector-worker "
                "启动即崩溃（应改用 app.v2.*._compat 兼容导入）",
            )
            self.skipTest(f"本地缺 worker 侧依赖，跳过：{exc}")
        finally:
            sys.meta_path.remove(finder)
            for name in [n for n in list(sys.modules) if n.startswith("app.v2")]:
                del sys.modules[name]
            sys.modules.update(saved)

    def test_collection_service_imports_without_fastapi(self):
        """直接锁住本次事故的模块（collection.service 被 worker 经 worker.py 导入）。"""
        saved = {name: module for name, module in list(sys.modules.items()) if name.startswith("app.v2")}
        for name in saved:
            del sys.modules[name]
        finder = _BlockFastapi()
        sys.meta_path.insert(0, finder)
        try:
            importlib.import_module("app.v2.collection.service")
        except ModuleNotFoundError as exc:
            self.assertNotIn("fastapi", str(exc), f"collection.service 硬依赖 fastapi：{exc}")
            self.skipTest(f"本地缺依赖，跳过：{exc}")
        finally:
            sys.meta_path.remove(finder)
            for name in [n for n in list(sys.modules) if n.startswith("app.v2")]:
                del sys.modules[name]
            sys.modules.update(saved)


if __name__ == "__main__":
    unittest.main()
