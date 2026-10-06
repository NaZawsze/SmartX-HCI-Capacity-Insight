"""响应模型必须能在运行时解析（v0.5.4 `.14` C1 实测事故的第四道防线）。

## 事故

2026-10-06 `.14` 跑 v0.5.3 → v0.5.4 直升（任务 `upgrade-af65f9088136f8d8`）成功，
但 C3 的两个前置接口每次调用都 500：

```
GET /api/admin/upgrade/rollback-availability       → Internal Server Error
GET /api/admin/upgrade/full-rollback-availability  → Internal Server Error
pydantic.errors.PydanticUserError: TypeAdapter[Annotated[UpgradeRollbackAvailabilityResponse…]]
  is not fully defined … then call `.rebuild()`
```

根因：`app/v2/api/models.py` 漏导入 `List`，而 B8/B9 新增的两个响应模型在
`from __future__ import annotations` 下用了 `List[str]`。注解是惰性求值，
运行时模块命名空间里没有 `List` → pydantic 解析失败 → **场景 B/C 回滚入口完全不可用**，
US-17 无法关闭。

## 为什么前三道防线都没拦住

| 防线 | 为什么漏 |
| --- | --- |
| 服务层单测 | 直接调 service，**不经过 FastAPI 的响应模型序列化**，未解析的注解不会暴露 |
| `scripts/verify_api_docs.py` | 只做 `api.md` ↔ 后端路由的**双向比对**，不校验响应模型能否构造 |
| B7 前后端门禁 | 跑的是构建与前端测试，没有对**这两个端点**发真实请求 |

即"路由存在 ≠ 端点可用"。这类缺陷只能在**模型构造**与**端点响应**两个层面拦，
本文件就是补上的这两道。

## 覆盖面

- 遍历 `app.v2.api.models` 里全部 `BaseModel`，逐个 `model_rebuild()` +
  `model_validate({})`，凡 `PydanticUndefinedAnnotation`（即模块命名空间缺名字）
  立即失败——与字段必填这类**正常**校验错误区分开。
- 再用 `TestClient` 真实打两个 availability 端点，断言不是 5xx。
  端点需要鉴权，这里注入测试用户覆盖。
"""

import unittest

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.v2.api.models import *  # noqa: F401,F403  （被扫描的模型都定义在这里）
import app.v2.api.models as models_module


class ResponseModelsResolveTest(unittest.TestCase):
    """全部响应模型的注解必须能在运行时解析。"""

    def _model_classes(self) -> list[type[BaseModel]]:
        found: list[type[BaseModel]] = []
        for name, obj in vars(models_module).items():
            if not isinstance(obj, type) or not issubclass(obj, BaseModel):
                continue
            if obj.__module__ != models_module.__name__:
                continue  # 跳过从别处导入的模型
            found.append(obj)
        self.assertGreaterEqual(len(found), 10, f"扫描到的模型过少：{len(found)}，扫描口径可能失效")
        return found

    def test_every_response_model_annotation_resolves(self) -> None:
        undefined: list[str] = []
        for model in self._model_classes():
            try:
                model.model_rebuild()
                model.model_validate({})
            except Exception as exc:  # noqa: BLE001
                # 只把"注解未定义"当缺陷；缺必填字段是正常校验错误
                if type(exc).__name__ == "PydanticUndefinedAnnotation":
                    undefined.append(f"{model.__name__}: {exc}")
        self.assertEqual(
            undefined,
            [],
            "以下响应模型的注解在运行时无法解析（模块命名空间缺少被引用的名字，"
            "典型是漏 typing 导入）：\n  " + "\n  ".join(undefined),
        )


class RollbackAvailabilityEndpointsTest(unittest.TestCase):
    """两个 availability 端点必须真的能返回 JSON（US-17 场景 B/C 的入口）。

    这里刻意**不**用真实 service（它要读 runner 状态文件与业务库）：本用例要验的是
    「响应模型能否序列化 service 返回的 dict」，用假 service 正好把这一层单独钉住，
    也不会因为现场有没有锚点而时绿时红。
    """

    class _FakeUpgradeService:
        def rollback_availability(self) -> dict:
            return {
                "available": False,
                "blockers": ["没有平台回滚锚点（测试桩）"],
                "target_version": "v0.5.3",
                "current_version": "v0.5.4",
                "images": ["nazawsze/smartx-hci-capacity-insight-web-api:v0.5.3"],
                "anchor_source": None,
                "anchor_task_id": None,
                "captured_at": None,
                "scope": "application_only",
                "note": None,
            }

        def full_rollback_availability(self) -> dict:
            return {
                "available": False,
                "blockers": ["没有可用的整备备份（测试桩）"],
                "current_version": "v0.5.4",
                "data_loss_window_seconds": 0,
                "requires_confirmation": True,
                "backup_task_id": None,
            }

    def setUp(self) -> None:
        from app.v2.api.deps import get_upgrade_service, require_user
        from app.v2.auth.service import CurrentUser
        from app.v2.main import create_app

        app = create_app()
        app.dependency_overrides[require_user] = lambda: CurrentUser(username="tester", is_admin=True)
        app.dependency_overrides[get_upgrade_service] = lambda: self._FakeUpgradeService()
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_rollback_availability_not_5xx(self) -> None:
        response = self.client.get("/api/admin/upgrade/rollback-availability")
        self.assertLess(
            response.status_code,
            500,
            f"rollback-availability 返回 {response.status_code}：{response.text[:400]}",
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        payload = response.json()
        self.assertIn("available", payload)
        self.assertIsInstance(payload["blockers"], list)

    def test_full_rollback_availability_not_5xx(self) -> None:
        response = self.client.get("/api/admin/upgrade/full-rollback-availability")
        self.assertLess(
            response.status_code,
            500,
            f"full-rollback-availability 返回 {response.status_code}：{response.text[:400]}",
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        payload = response.json()
        self.assertIn("available", payload)
        self.assertIsInstance(payload["blockers"], list)


if __name__ == "__main__":
    unittest.main()
