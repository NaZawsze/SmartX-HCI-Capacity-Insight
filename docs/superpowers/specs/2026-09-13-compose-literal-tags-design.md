# 升级包 compose 字面量 tag——核实结论与收尾设计（Phase 49-3 修正案，任务 49-15）

更新时间：2026-09-13
状态：设计完成，待实施（范围已缩小：以验证与一致性收尾为主，无管线代码改动）
关联：task_plan.md Phase 49 第 15 项；docs/pending-tasks.md P1 #4；p1-infra-batch-design §5（前次回退记录）

## 1. 核实结论（2026-09-13 读码 + 测试证据）

升级包管线**已经**渲染字面量 tag：

- `scripts/build_upgrade_package.py::_render_packaged_compose_tags`（约 853 行）将源码模板的
  `${SMARTX_IMAGE_PREFIX:-nazawsze}/…:${SMARTX_IMAGE_TAG:-v0.5.2}` 渲染为 `nazawsze/…:v0.5.2` 字面量（runner 同理）；
- builder 测试的 `assertNotIn("SMARTX_IMAGE_TAG", compose_text)`（test_v2_package_builders.py:238/372/1047）远端通过即为证据；
- 升级链路另有防护：`upgrade_runner/actions.py` 升级时从目标 .env 剥离 `SMARTX_IMAGE_TAG/RUNNER_IMAGE_TAG/APP_VERSION/RUNNER_VERSION`（IMAGE_TAG_ENV_KEYS）。

**因此"升级包内 compose 被现场 .env 覆盖"的风险不成立**，无需管线代码改动。上一轮"源码写死 tag"失败的原因也已完全解释：占位符是 `_render_packaged_compose_tags` 正则的匹配锚点，写死后 v0.5.1u2 等旧版本包渲染不出 `:v0.5.1u2`，断言失败。

剩余的真实风险面（很小）：

1. **源码直连部署**（git clone + `docker compose up`）时，`.env` 或 shell 的旧 `SMARTX_IMAGE_TAG` 仍会生效——现有缓解：`check_versions` 源码门禁、deployment.md 警告、runner 升级时剥离。可加一道低成本防呆警告。
2. 前次实施遗留的两个真实问题（本设计收尾）：
   - `upgrade_runner/actions.py DEFAULT_ENV_LINES` 仍含 `SMARTX_CORS_ORIGINS=*`，与 P3 CORS 收紧矛盾（runner 给新部署写默认 .env 会把 `*` 带回来）；
   - 需要一次**真机证据**：构建真实包并确认渲染产物零插值（把"已安全"从推断变成记录在案的验证）。

## 2. 实施项

| # | 内容 | 类型 |
| --- | --- | --- |
| 1 | 真机证据：容器内构建 v0.5.2 全量包与 v0.5.1u2 桥包，grep 包内三个 compose——断言零 `${SMARTX_IMAGE_TAG`/`${SMARTX_RUNNER_IMAGE_TAG`，且含 `:v0.5.2`/`:v0.5.1u2`、runner `:v0.3.1`/`:v0.3.0` | 验证 |
| 2 | `upgrade_runner/actions.py DEFAULT_ENV_LINES` 移除 `SMARTX_CORS_ORIGINS=*` 行（与 CORS 收紧对齐）；对应 runner 测试如有断言默认 env 内容需同步 | 代码（小） |
| 3 | `check_versions()` 增加防呆：检测到仓库 `.env` 定义 `SMARTX_IMAGE_TAG/RUNNER_IMAGE_TAG` 时打印警告"源码部署勿在 .env 固定镜像 tag，将被忽略/导致版本漂移"（不阻断） | 代码（小） |
| 4 | `docs/version-governance.md` 补一段：升级包 compose 为字面量 tag（构建时渲染）；源码部署的 tag 由 VERSION/RUNNER_VERSION 经 compose 占位符默认值决定，.env 不应定义 tag 变量 | 文档 |

## 3. 测试

- builder 现有用例回归（26 个，其中 9 个只读挂载错误为已知基线）。
- 新增：runner 默认 env 不含 `SMARTX_CORS_ORIGINS` 的断言（actions 相关测试处）。
- `check_versions` 警告分支单测（临时 .env 注入）。

## 4. 验收

- [ ] .3 真机构建两包，渲染产物 grep 证据入 progress.md。
- [ ] runner 默认 env 与 CORS 收紧一致。
- [ ] version-governance 文档更新。
- [ ] 全量回归零新失败。
- 完成后 P1 #4 关闭（结论：管线已安全，收尾验证与文档化）。

## 5. 回滚

单提交 revert（涉及 actions.py/check_versions/文档）。
