# 实施计划：升级架构结构性整改（runner v0.3.2 + v0.5.4）

- 设计：**v2** [2026-10-05-upgrade-architecture-v054-design-v2.md](../specs/2026-10-05-upgrade-architecture-v054-design-v2.md)（业界三层形态重构；v1 的问题清单/状态文件/回滚三场景被继承）
- 状态：待实施（按批次推进，每批完成即勾选并补证据）

## 批次 A：runner v0.3.2（先做，能力领先）

> 进度（2026-10-06）：**批次 A 全部完成**（A1/A2/A3/A4/A4b/A5/A5b/A6/A7，均有 `.3` 真机证据）。
> 批次 B **全部完成**（2026-10-06，B1–B10 + B3/B5b/B7/B8/B9/B10）。下一步：批次 C（C1 `.14` 直升 → C2 组件升级格 → C3 回滚六点演练 → C4 `.12` 老链路 → C5 r19 打包全门禁）。
> 后端全量真实基线是 **1 个失败**（镜像有 docker CLI 无 socket）；此前报「6 个 harness 限制」里有 5 个是我打包时混进的 AppleDouble 旁车文件，已纠正（progress.md 有记录）。
> r19 打包在批次 C 开头打一次（用户定序：现在打的包会立刻过期）。
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

## 批次 C：验收与发版火车（2026-10-06 定稿：`.14`=CLI 路径，`.12`=Web/API 路径）

> 执行者：实施 AI（`.14`/`.12` 均 root 直登；`.14` 地址 10.20.11.14，**勿用 10.20.0.14**）。
> 纪律：每格开始前命令序列贴对话等用户确认；意外先停先报、原样留证；r18/r19/r20 作废包不用于任何真机操作。
> 操作清单与判据：`2026-10-06-upgrade-matrix-runbook.md`；取证：`ops/evidence.sh` before/after。

### .14 线（CLI 路径——安装/升级客户脚本全覆盖；数据少，适合试刀）

- [x] C1'' v0.5.3→v0.5.4 直升（r21 平台包，v0.3.1 runner 执行）——**T3 通过**（prometheus 自安装起一次未重建；三条独立证据：容器 ID / created 时间戳 / 存量 hash 与 by_compose 版本标记）；其余 18 项判据全绿；两个回滚可用性端点 500→200（r20 起）；4 项 ℹ️ = v0.3.2 能力在 C1 结构性缺席（判定口径已修正 `ba40893`）。历史：C1(r19) 17✅/4ℹ️ 作废（回滚端点 500）、C1'(r20) 19/20 作废（T3/prometheus 重建）。证据 `/data/evidence/c1/`
- [ ] C1-a 传输 r21 两包到 `.14`（平台 `074a4937…`、runner `05d8e015…` 继承自 r20）并核对 SHA
- [ ] C1-b CLI 同版本重装 + 组件升级一条命令（`upgrade.sh --package <r21平台包> --allow-same-version --with-runner <r21 runner包> --yes`）→ 平台重装（v0.3.1 执行七步，T3 复测）+ runner v0.3.1→v0.3.2（旧编排最后一跳）；evidence.sh before/after
- [ ] C1-c CLI 同版本重装第二次（不带 --with-runner）→ v0.3.2 runner 执行 → 锚点产生
- [ ] C3-14 场景 B（availability=true → 手动回滚 → 计数守卫 → rolled_back）+ 场景 C（整备回滚，显式确认）
- 判据：每步 CLI 退出码 0 + 8 项验收 + T3（b、c 各测一次）+ 锚点出现 + 场景 B/C 判定表

### .12 线（Web/API 路径——pre-wipe 真实数据全覆盖）

- [ ] C0-恢复 备份当前空库（留证）→ 重装 v0.5.2 基线（delivery-v052 的 install.sh）→ 按 backup-recovery.md 恢复五步恢复 **pre-wipe-20261004 快照**（SQLite + prometheus + tower.env **三件成对**，凭据解密依赖配对）→ 基线核验：543/89547、integrity ok、3 Tower 解密成功
- [ ] C0-直升 v0.5.2 → v0.5.4 直升（API 上传 r21 平台包，v0.3.1 执行七步）→ 逐表计数 + prometheus 历史（34 子目录）+ integrity 比对（⚠️ 格转实测，US-17/数据完整性的核心答案）
- [ ] C2 组件升级 v0.3.1→v0.3.2（API，旧编排最后一跳，在 v0.5.4 平台上）→ 判据：计数逐位不变（543/89547 量级）、presence ≤60s、runner=v0.3.2、状态文件心跳刷新
- [ ] C4-analog 同版本重装 v0.5.4→v0.5.4（API，v0.3.2 runner 执行）→ T3 + W4 diff 收敛真机证据 + 锚点
- [ ] C3-12 场景 B（availability=true → 手动回滚 → 真实数据计数守卫）+ 场景 C（整备回滚，显式确认丢数据窗口）
- 采集打折口径：3 Tower 中 2 个（10.12.10.60、10.20.0.6:5443）可能不可达——自动采集"部分成功"算环境因素通过并如实记录哪个失败；数据完整性判据不依赖 Tower，必须全过

### 收尾（矩阵全绿后）

- CHANGELOG 验证说明回填（**不得预写结论**；.14 无 Tower 凭据 →「升级后真实数据采集」如实记未验证）
- ledger 标注「T3 于 v0.3.1 执行者下通过」+ progress 收尾记录
- **停下等用户发布指令**（r21 不发布、dev2 不 push）

### 已完成

- [x] C5 r19→r21 打包 + 全门禁 + ledger（平台 `074a4937…`、runner `05d8e015…` 继承自 r20；r18/r19/r20 平台包均作废；词汇冻结 2 WARN 已处置）
- [x] C5b 离线交付目录：delivery-v054（v0.5.4 + v0.3.2 基线）与 delivery-v052（v0.5.2 + v0.3.1，C0 基线用），US-33 自洽通过；构建器补「平台 tag 可落任意版本」（`9fd1be2`）
- [x] C2b 自换实测（T11）：v0.3.2→v0.3.3-rc，停机 0.75s、presence 7.4s、web-api 零参与
- [x] C3 沙箱先行：①health 失败→rolled_back（w5sb）②apply 失败→rolled_back（w3c）④image.load 失败→干净失败不回滚（w3c）
