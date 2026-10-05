# 实施计划：升级架构结构性整改（runner v0.3.2 + v0.5.4）

- 设计：**v2** [2026-10-05-upgrade-architecture-v054-design-v2.md](../specs/2026-10-05-upgrade-architecture-v054-design-v2.md)（业界三层形态重构；v1 的问题清单/状态文件/回滚三场景被继承）
- 状态：待实施（按批次推进，每批完成即勾选并补证据）

## 批次 A：runner v0.3.2（先做，能力领先）

> 进度（2026-10-06）：**批次 A 全部完成**（A1/A2/A3/A4/A4b/A5/A5b/A6/A7，均有 `.3` 真机证据）。
> 下一步进批次 B：B3（预检查 remediation + 前端两步引导）、B5b（W6 七步断言与退役清单）、B6（偏斜矩阵入文档）、B7（`.3` 全量 + 前端门禁）。
> r18 打包在批次 C 开头打一次（用户定序：现在打的包会立刻过期）。
> **A4 完成并勾选**（`40f3b0a`/`ac97b06`）：三层防护（剔除 runner / 差异清单 / apply
> 后断言执行者未被换掉）+ W7 第 4 道 `--force-recreate` 禁令门禁；`.3` 全量 975 tests 与基线
> 953 tests 逐条对齐（NO_NEW_FAILURES），门禁端到端 `GATE_EXIT=0`，沙箱 `w4sb` T3 判据成立。
> **发布包形态的 `.14` 直升回归仍归 C1/C5**（须先经 `ops/package.sh` 全门禁出 r18）。
> A4 期望镜像取自计划里的 `compose.override` 动作（编译器只给 `compose.apply` 传 `services`）。
> **W3b（2026-10-05 用户决策，方案 A）已完成**——宿主/容器路径混用的系统性修复，
> 含双视图回归测试与静态纪律断言。**M1/M2 归入批次 C 回归格**（执行者是现场 v0.3.1 runner，
> 不验证本轮修复；路径修复的验证是 T11）。

- [x] A1 状态文件 `upgrade-runner-state.json`：原子写/自愈/内容结构（设计 §3.1，T1）
- [x] A2 lease/heartbeat 迁移到状态文件；DB 心跳降级为 best-effort 兼容镜像（失败不 crash 不阻塞，#82 兜底语义保留）
- [x] A3 runner 停止写 `tasks` 表（删 `_project_task` 路径）；task.json 执行期单写者
- [x] A4 `compose.apply` diff 收敛 + 差异清单日志 + upgrade-runner 触碰守卫（v2 §2.1）——`40f3b0a`/`ac97b06`；`.3` 全量 975 tests 与基线逐条对齐、W7 第 4 道 `--force-recreate` 禁令门禁 `GATE_EXIT=0`、沙箱 `w4sb` T3 收敛判据实测（runner/prometheus 容器 ID 不变）
- [x] A4b **runner 自换组件升级**（v2 §2.2）：收包触发 → 自 load 镜像 → 写自身 compose → schedule_handoff → presence 回报；web-api 退出编排（T11）
- [x] A5 回滚机制固化（设计 §5.0）——`c8c3bf3`/`e594432`：apply 前捕获锚点四要素 + 落 task.json 与状态文件持久段、锚点驱动应用回滚（override 旧 tag → apply → health）、业务计数守卫「不得减少」；`.3` 沙箱 `w5sb` 实测 healthcheck 失败 → `rolled_back`（27s、老版本恢复 200、计数逐表一致、runner/prometheus 容器 ID 未变）
- [x] A5b 场景 A 自动回滚：触发面 `compose.apply`/`health.*`/`post_upgrade.*`，新增面需 manifest `rollback_on_failure: true`（health 保持无条件，老 manifest 行为不回退）；失败证据完整保留、回滚失败进 recovery ——「up 后不健康」失败点已实测，另两个失败点归批次 C3
- [x] A6 project_files 阶段投递 compose-guard.sh + 回填 `.env` 标记（US-39）——`87c6858`：守卫进 `project_file_list` 逐字节取自 `delivery/compose-guard.sh`；`files.sync` 末尾按运行中容器的 `config_files` 标签回填标记（幂等、判不出不写、保留 .env 权限、自包含不 source）；`.3` 打包侧+runner 侧 166 tests OK、全量 1015 与基线对齐。**真包落到客户现场待 C1/C5 实证**
- [x] A7 runner 单元测试补齐（T1/T2/T4）+ `.3` 全量回基线

## 批次 B：平台 v0.5.4

- [x] B1 presence 读文件优先、DB 兜底（覆盖 v0.5.4+v0.3.1 组合）
- [x] B2 web-api 从 task.json 投影 tasks 表（监督/状态轮询路径）
- [ ] B3 预检查 `runner_actions` 失败带 `remediation`；前端升级中心两步引导（T9）
- [x] B4 迁移 expand-only 门禁（registry 断言，T6）
- [x] B5 动作词汇冻结门禁（计划动作集 ⊆ 已发布 runner，接入 `ops/package.sh`，T7）
- [ ] B5b **七步常量模板**（v2 §2.1）：manifest 不带迁移/交接声明 → 计划自然缩为 backup/load/sync/apply/health/collection/checkpoint；编译器瘦身退役逐版本逻辑（T12）
- [ ] B6 偏斜矩阵写入 upgrade-chain.md
- [ ] B7 `.3` 全量 + 前端门禁
- [ ] B8 场景 B：升级中心「回滚到上一版本」——可回滚性判定 API + 前端入口 + 任务化执行（单飞守卫）
- [ ] B9 场景 C：整备回滚产品化（备份恢复五步进产品流程，显式数据丢失确认）
- [ ] B10 回滚锚点/备份保留期联动 backup_retention

## 批次 C：验收与发版火车

- [ ] C1 `.14` 全新安装 + v0.5.3→v0.5.4 直升（T3 回归判据：runner/prometheus 容器 ID 不变）
- [ ] C2 组件升级：v0.3.1→v0.3.2（兼容矩阵「v0.5.3+v0.3.2」格，旧编排最后一次）
- [x] C2b 自换实测：v0.3.2→v0.3.3-rc，停机 ≤30s、presence ≤60s、web-api 零参与（T11）
- [ ] C3 回滚演练：场景 A 三失败点 + 场景 B 手动应用回滚 + 场景 C 整备回滚（T5，US-17 关闭）
- [ ] C4 `.12` 老链路回归（v0.5.2 源 × v0.3.1）
- [ ] C5 r18 打包 + 全门禁（含新门禁脚本）→ ledger 登记 → 发布等用户指令
