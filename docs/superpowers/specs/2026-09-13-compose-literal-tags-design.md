# 升级包 compose 字面量 tag 渲染设计（Phase 49-3 修正案，任务 49-15）

更新时间：2026-09-13
状态：设计完成，待实施
关联：task_plan.md Phase 49 第 15 项；docs/pending-tasks.md P1 #4；前次尝试与回退见 p1-infra-batch-design §5

## 1. 机制现状（2026-09-13 读码确认）

升级包构建的版本渲染链路（`scripts/build_upgrade_package.py`）：

1. `temporary_image_version_metadata(version)` 临时改写源文件到目标包版本：VERSION/RUNNER_VERSION、config DEFAULT 常量、README、**四个 compose 的 `SMARTX_IMAGE_TAG:-<默认>` 占位符默认值**（`_replace_compose_version_tags`，保留 `${...}` 插值形态），构建后恢复。
2. `_assert_project_files_match_version(version, project_dir)` 断言包内 project compose 含 `:<version>`（旧版本包还断言 runner `:v0.3.0` 与 legacy project/network 标识）。
3. `check_versions(version)` 发布门禁：断言**源码** compose 占位符默认值与仓库 VERSION/RUNNER_VERSION 一致（"Version metadata OK"）。

风险（Phase 49-3）：包内 project compose 渲染后仍是 `${SMARTX_IMAGE_TAG:-v0.5.1u2}`——现场 `.env` 或 shell 环境携带旧 tag 时，手工 `docker compose up` 会静默跑错版本。升级链路本身已有防护（`upgrade_runner/actions.py:364` `IMAGE_TAG_ENV_KEYS` 会在升级时从目标 .env 剥离这四个变量），剩余风险面即手工操作场景。

前次教训：源码 compose 写死字面量会破坏 1/2 两个环节（占位符是改写与断言的锚点），已回退。

## 2. 方案：包构建时渲染字面量 tag

- **`_replace_compose_version_tags` 末尾追加字面量化两步**（该函数同时服务于临时源文件与包内 project 文件）：

  ```python
  text = re.sub(r"\$\{SMARTX_IMAGE_TAG:-([^}]+)\}", r"\1", text)
  text = re.sub(r"\$\{SMARTX_RUNNER_IMAGE_TAG:-([^}]+)\}", r"\1", text)
  ```

  效果：`${SMARTX_IMAGE_TAG:-v0.5.1u2}` → `v0.5.1u2`。临时源文件与包内文件全部变为字面量，任何 .env/shell 环境都无法再覆盖包内版本。
- **源码模板不动**：保留 `${SMARTX_IMAGE_TAG:-v0.5.2}` 占位符（`check_versions` 源码门禁与开发流程依赖；上一轮回退的原因）。
- **断言加强**：`_assert_project_files_match_version` 追加反向断言——包内三个 compose **不得包含** `${SMARTX_IMAGE_TAG`/`${SMARTX_RUNNER_IMAGE_TAG`（fail closed，防止未来改动悄悄退回插值形态）。
- 升级链路的 `IMAGE_TAG_ENV_KEYS` 剥离逻辑保留（纵深防御，覆盖源码直连部署场景）。

## 3. 测试影响

- 现有 builder 用例中断言包内 compose 含 `SMARTX_IMAGE_TAG:-<版本>` 插值形态的，改为断言字面量 `:<版本>`（`_assert_project_files_match_version` 的既有断言 `:{version}` 天然兼容字面量）。
- 新增用例：渲染后的包 project compose 不含 `${SMARTX_IMAGE_TAG`/`${SMARTX_RUNNER_IMAGE_TAG`。

## 4. 相关一致性修复（同批）

- `upgrade_runner/actions.py` `DEFAULT_ENV_LINES` 仍含 `SMARTX_CORS_ORIGINS=*`，与 P3 CORS 收紧（默认同源、白名单显式配置）矛盾：从默认行中移除；跨域部署按 deployment.md 显式追加。

## 5. 验证

1. 容器内运行 builder 全部用例（含新增断言）。
2. 真实构建两个包并检查渲染产物：
   - v0.5.2 全量包：包内三个 compose 无 `${SMARTX_IMAGE_TAG`/`${SMARTX_RUNNER_IMAGE_TAG`，含 `:v0.5.2` 与 runner `:v0.3.1`；
   - v0.5.1u2 桥包：含 `:v0.5.1u2` 与 runner `:v0.3.0`（legacy 标识断言不变）。
3. `check_versions` 源码门禁通过（Version metadata OK）。
4. 构建出的包走一次升级中心上传 + 预检查（API 层即可），确认包解析不受字面量影响。

## 6. 回滚

单提交 revert。
