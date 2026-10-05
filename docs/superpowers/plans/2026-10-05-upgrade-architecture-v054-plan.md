# 实施计划：升级架构结构性整改（runner v0.3.2 + v0.5.4）

- 设计：**v2** [2026-10-05-upgrade-architecture-v054-design-v2.md](../specs/2026-10-05-upgrade-architecture-v054-design-v2.md)（业界三层形态重构；v1 的问题清单/状态文件/回滚三场景被继承）
- 状态：待实施（按批次推进，每批完成即勾选并补证据）

## 批次 A：runner v0.3.2（先做，能力领先）

- [ ] A1 状态文件 `upgrade-runner-state.json`：原子写/自愈/内容结构（设计 §3.1，T1）
- [ ] A2 lease/heartbeat 迁移到状态文件；DB 心跳降级为 best-effort 兼容镜像（失败不 crash 不阻塞，#82 兜底语义保留）
- [ ] A3 runner 停止写 `tasks` 表（删 `_project_task` 路径）；task.json 执行期单写者
- [ ] A4 `compose.apply` diff 收敛 + 差异清单日志 + upgrade-runner 触碰守卫（v2 §2.1，T3/T4）
- [ ] A4b **runner 自换组件升级**（v2 §2.2）：收包触发 → 自 load 镜像 → 写自身 compose → schedule_handoff → presence 回报；web-api 退出编排（T11）
- [ ] A5 回滚机制固化（设计 §5.0）：回滚锚点记录 + 旧镜像 override + 健康门 + 业务计数守卫
- [ ] A5b 场景 A 自动回滚：healthcheck 失败进入回滚子计划（`rollback_on_failure`，失败证据完整保留）
- [ ] A6 project_files 阶段投递 compose-guard.sh + 回填 `.env` 标记（US-39，runner 侧）
- [ ] A7 runner 单元测试补齐（T1/T2/T4）+ `.3` 全量回基线

## 批次 B：平台 v0.5.4

- [ ] B1 presence 读文件优先、DB 兜底（覆盖 v0.5.4+v0.3.1 组合）
- [ ] B2 web-api 从 task.json 投影 tasks 表（监督/状态轮询路径）
- [ ] B3 预检查 `runner_actions` 失败带 `remediation`；前端升级中心两步引导（T9）
- [ ] B4 迁移 expand-only 门禁（registry 断言，T6）
- [ ] B5 动作词汇冻结门禁（计划动作集 ⊆ 已发布 runner，接入 `ops/package.sh`，T7）
- [ ] B5b **七步常量模板**（v2 §2.1）：manifest 不带迁移/交接声明 → 计划自然缩为 backup/load/sync/apply/health/collection/checkpoint；编译器瘦身退役逐版本逻辑（T12）
- [ ] B6 偏斜矩阵写入 upgrade-chain.md
- [ ] B7 `.3` 全量 + 前端门禁
- [ ] B8 场景 B：升级中心「回滚到上一版本」——可回滚性判定 API + 前端入口 + 任务化执行（单飞守卫）
- [ ] B9 场景 C：整备回滚产品化（备份恢复五步进产品流程，显式数据丢失确认）
- [ ] B10 回滚锚点/备份保留期联动 backup_retention

## 批次 C：验收与发版火车

- [ ] C1 `.14` 全新安装 + v0.5.3→v0.5.4 直升（T3 回归判据：runner/prometheus 容器 ID 不变）
- [ ] C2 组件升级：v0.3.1→v0.3.2（兼容矩阵「v0.5.3+v0.3.2」格，旧编排最后一次）
- [ ] C2b 自换实测：v0.3.2→v0.3.3-rc，停机 ≤30s、presence ≤60s、web-api 零参与（T11）
- [ ] C3 回滚演练：场景 A 三失败点 + 场景 B 手动应用回滚 + 场景 C 整备回滚（T5，US-17 关闭）
- [ ] C4 `.12` 老链路回归（v0.5.2 源 × v0.3.1）
- [ ] C5 r18 打包 + 全门禁（含新门禁脚本）→ ledger 登记 → 发布等用户指令
