# 交付物 project compose 的 runner tag 必须全部落已发布基线

- 日期：2026-09-30
- 关联：task_plan 第 58 项（CLI 工具链）实施过程中发现；违反 AGENTS §8
- 状态：设计定稿，待实施

## 1. 问题

`cli/package.sh` 端到端实测（T2）时发现：交付目录里两个 compose 的 runner tag 不一致。

| 文件 | runner tag | 是否正确 |
| --- | --- | --- |
| `install/project/docker-compose.offline.yml` | `v0.3.1` | ✅ 已发布基线 |
| `install/project/docker-compose.yml` | `v0.3.2` | ❌ 源码开发线版本 |

实测输出：
```
offline-delivery/install/project/docker-compose.offline.yml -> v0.3.1
offline-delivery/install/project/docker-compose.yml         -> v0.3.2
```

## 2. 根因

`scripts/build_offline_delivery.py` 只对 offline 那一份做了基线渲染：

```python
offline_src = project_dir / "docker-compose.offline.yml"
render_offline_compose(offline_src, offline_src, args.runner_baseline)   # 只改了这一个
```

而 `copy_project_files(project_dir)` 是**从平台包/源码整份复制**所有 compose，`docker-compose.yml`
原样带着源码的 `v0.3.2`（源码三个 compose 都写 v0.3.2，属开发线）。

现有自洽门禁也只查 offline 那一份：
```python
declared = declared_images_from_compose(project_dir / "docker-compose.offline.yml")
```

## 3. 为什么这是必须修的（不是洁癖）

1. **违反 AGENTS §8 硬性规则**：「发布包中的 Compose 应写入明确、可审计的镜像身份」+
   「交付物 compose 必须落**已发布** runner 基线」。
2. **主 compose 就在现场**：`delivery/install/install.sh:41` 用
   `COMPOSE_FILE="docker-compose.offline.yml"` 启动，但 322–333 行会把
   **两个 compose 都装进** `$PROJECT_DIR`。于是现场同时存在一份 tag 正确的（offline）
   和一份 tag 错误的（主 compose）。任何人手工 `docker compose up`（默认读 `docker-compose.yml`）
   就会拉起 v0.3.2 —— **而交付目录里只有 v0.3.1 的镜像**（`images/` 按基线准备），
   离线机器上直接失败；联网机器上则会静默拉一个**未经本轮验收**的 runner 上来。
3. **与 US-26 同类**：多事实源。已修过一次（compose tag 回写），这里是**构建期就没对齐**。

## 4. 方案

### 4.1 渲染范围：交付目录内**所有** compose 一律落基线

在 `build_offline_delivery.py` 里把 `render_offline_compose` 的调用从「只改 offline」
改为「改交付 `project/` 目录下所有 compose 文件的 upgrade-runner image 行」。

**为什么不是"删掉主 compose"**：主 compose 是现场默认读取的文件，删掉会让
`docker compose up`（不带 `-f`）直接报"找不到文件"，把一个静默错误换成一个显式故障——
但它同时也是 `install.sh` 322 行要安装的文件之一。保留并对齐是改动最小的正解。

**为什么不是"只在自检里报错"**：构建期能改对的事，不该留给现场。

### 4.2 自洽门禁同步扩到全部 compose

把 `declared_images_from_compose` 的调用从「offline 一份」改为「遍历交付 project 下所有
`docker-compose*.yml`」，任一文件的 upgrade-runner tag 与 `--runner-baseline` 不一致即
`SystemExit`。**先渲染、再断言**，保证门禁检查的是最终产物。

### 4.3 与既有门禁的关系

- `verify_runner_delivery_consistency.py` 的 C3 查的是**源码** compose 字面量（应为 `RUNNER_VERSION`
  即 v0.3.2）——**不冲突**：源码是开发线 v0.3.2 是对的，交付物是已发布 v0.3.1 也是对的，
  两者本就该不同。这正是「源码口径 vs 交付口径」的区分。
- 新增的交付物侧门禁保证「交付物内部一致且落已发布基线」。

## 5. 边界

- **只改 `scripts/build_offline_delivery.py`**，不改 `delivery/install/install.sh`、
  不改 `delivery/upgrade/upgrade.sh`、不改任何 compose 源文件。
- 不新增参数（`--runner-baseline` 已是权威输入）。
- 对 `docker-compose.release.yml`：它不在 `project_file_list` 里（交付物只带 offline + 主 compose），
  遍历时若存在也一并对齐——**宁多不少**。

## 6. 验收

1. 新增单测：构造一个源码 compose tag 为 v0.3.2 的临时目录，跑
   `build_offline_delivery.py`，断言交付目录内**所有** compose 的 upgrade-runner tag
   都等于 `--runner-baseline`。
2. **负向实证**：把 `render_*` 的调用去掉（旧行为），断言该单测 FAIL —— 证明它真的能抓到。
3. `.3` 重跑 `cli/package.sh`（T2），实测交付目录两个 compose 均为 v0.3.1。
4. `.3` 后端全量无回归。

## 7. 风险与回滚

- 风险：若某 compose 的 upgrade-runner image 行格式特殊，渲染可能失败 → `render_offline_compose`
  已在找不到时抛错（"未能在 … 里定位 upgrade-runner 的 image 行"），是**快速失败**而非静默。
- 回滚：`git revert` 即可，改动集中在单个脚本的一个函数调用与一处断言。
