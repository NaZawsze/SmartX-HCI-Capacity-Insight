# 实施计划：升级架构结构性整改（runner v0.3.2 + v0.5.4）

- 设计：**v2** [2026-10-05-upgrade-architecture-v054-design-v2.md](../specs/2026-10-05-upgrade-architecture-v054-design-v2.md)（业界三层形态重构；v1 的问题清单/状态文件/回滚三场景被继承）
- 状态：待实施（按批次推进，每批完成即勾选并补证据）

## 批次 A：runner v0.3.2（先做，能力领先）

> 进度（2026-10-06）：**批次 A 全部完成**（A1/A2/A3/A4/A4b/A5/A5b/A6/A7，均有 `.3` 真机证据）。
> 批次 B **全部完成**（2026-10-06，B1–B10 + B3/B5b/B7/B8/B9/B10）。下一步：批次 C（C1 `.14` 直升 → C2 组件升级格 → C3 回滚六点演练 → C4 `.12` 老链路 → C5 r18 打包全门禁）。
> 后端全量真实基线是 **1 个失败**（镜像有 docker CLI 无 socket）；此前报「6 个 harness 限制」里有 5 个是我打包时混进的 AppleDouble 旁车文件，已纠正（progress.md 有记录）。
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
- [x] B3 预检查失败带 `remediation` + 前端预检查区渲染（T9）——`e6f0407`：文案由包携带（`_source_compatibility().remediation`，逐字=定稿那句），precheck 只在 ok=false 时给结构化字段 + message 文案（老包兜底「请先升级到 X 及以上」），前端只在预检查结果区渲染（不做向导）；`.3` `TSC_EXIT=0` / `VITEST_EXIT=0`（110 tests）/ 后端 9 例单测
- [x] B4 迁移 expand-only 门禁（registry 断言，T6）
- [x] B5 动作词汇冻结门禁（计划动作集 ⊆ 已发布 runner，接入 `ops/package.sh`，T7）
- [x] B5b **常量计划模板**（v2 §2.1，T12）——`f82572d`：用户定案收窄到 v0.5.2+（`_effective_min_version`/`_directory_transition`/`_legacy_cleanup` 置空/`_post_upgrade` 采集与 cleanup 解耦），断言锁**动作集合**（平台包 6 类、bundle +health.prometheus、迁移 +script.run_sandboxed）+ FORBIDDEN 清单不泄漏；`.3` 1030 tests 与基线对齐、三源格 ⊆ 已发布 25 动作、退役登记见 impl-spec §W6.3
- [x] B6 偏斜矩阵写入 upgrade-chain.md——`65e17ad`：§7 为权威（两行源格 × v0.3.1/v0.3.2 + 同版本重装；≤v0.5.1u2 标 ⛔ 不支持 + 引导）；**已用已发布 v0.5.2/v0.5.3 镜像内编译器实测**，两者对 v0.5.4 manifest 的动作集与候选编译器一致（各 8 动作）
- [x] B7 `.3` 全量 + 前端门禁——后端 1040 tests / fail_count=1（docker 无 socket，唯一环境限制）、`TSC_EXIT=0`、`VITEST_EXIT=0` / 110 tests
- [x] B8 场景 B：升级中心「回滚到上一版本」——`f706855`：判定 API（blockers 结构化）+ 前端入口（逐条显示阻塞原因）+ 任务化执行（`compose.override`→`compose.apply`→`health.http`，既有词汇，单飞/审计/投影适用）；锚点读状态文件，**不新建第三份锚点**；`TSC_EXIT=0`/`VITEST_EXIT=0`/114 tests
- [x] B9 场景 C：整备回滚产品化——`dc23171`：复用 `rollback.restore`（已实现恢复五步，不新写第二份）+ 备份 SHA 校验 + `confirm_data_loss` 必须显式为真；丢多少数据写在 400 错误里
- [x] B10 回滚锚点/备份保留期联动——`8593463`：`plan_cleanup/purge_backups(protect=…)` 强制豁免锚点引用的备份；读锚点失败时跳过保护（宁可少删不可误删）

## 批次 C：验收与发版火车

- [ ] C1 `.14` 全新安装 + v0.5.3→v0.5.4 直升——**阻塞：`.14` 网络不可达**（10.20.0.14 100% 丢包；10.20.11.14 凭据被拒）
- [ ] C2 组件升级 v0.3.1→v0.3.2（兼容矩阵格，旧编排最后一次）——**同 C1 阻塞**
- [x] C2b 自换实测：v0.3.2→v0.3.3-rc，停机 ≤30s、presence ≤60s、web-api 零参与（T11）
- [ ] C3 回滚演练（2026-10-06 修订触发面）——**②④ 已在 `.3` 沙箱 `w3c` 实测通过**（② apply 失败→rolled_back；④ image.load 失败→干净失败不回滚），① 早前 w5sb 已验；③ post_upgrade 失败、⑤场景B、⑥场景C 仍需真机：①health.* 失败 → 自动回滚（无条件路径；w5sb 沙箱已先行验证，本项在 .14 全装实例复测）；②compose.apply 失败 → 回滚（opt-in，v0.5.4 包 manifest 已显式 true）；③post_upgrade 失败 → 回滚（opt-in）；④**image.load 失败 → 不回滚**（正向断言：旧容器未动、任务干净失败——防「乱滚」）；⑤场景 B 手动应用回滚；⑥场景 C 整备回滚（T5，US-17 关闭）
- [ ] C4 `.12` 老链路回归（v0.5.2 源 × v0.3.1）——**阻塞：`.12` 凭据被拒**
- [x] C5 r18 打包 + 全门禁 + ledger 登记（平台包 `ff4c0f6f…`、runner `6b0c1700…`；身份/一致性 13 PASS/迁移/词汇冻结/禁令/敏感 全 PASS）——**发布等用户指令，且 C1–C4 完成前不得发布**
