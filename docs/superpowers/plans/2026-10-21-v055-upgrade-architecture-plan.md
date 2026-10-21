# v0.5.5 集中升级架构实施计划

设计依据：[v0.5.5 集中升级架构收口设计](../specs/2026-10-21-v055-upgrade-architecture-redesign.md)。

## 阶段 0：基线冻结与兼容矩阵

- [ ] 保留 v0.5.4 当前候选验收结论，不改包、不重写其历史。
- [ ] 从最终发布 ledger 固定 0.5.4 平台包、runner 组件包、镜像 digest 和能力指纹。
- [ ] 定义支持源端：至少 v0.5.4 实际配对；评估是否同时支持 v0.5.3 + runner v0.3.1 直达。
- [ ] 记录旧平台的组件升级入口能否启动新 runner project；不满足则补兼容引导或明确 remediation。

## 阶段 1：隔离 runner 生命周期

- [ ] 增加独立 runner Compose 配置和稳定目录；平台 Compose 移除 runner 服务。
- [ ] 分离 `platform_compose_project` 与 `runner_compose_project` 配置，迁移全部双重语义引用。
- [ ] 固定双方共享的 external network 与跨 project 健康探测方式；移除跨 project `depends_on`。
- [ ] 统一交付 Compose、runtime Compose writer、组件升级、自换、回滚和安装脚本中的 runner project 来源。
- [ ] 构造新旧 runner 并行桥接：健康探测 → 唯一租约转移 → 旧实例退役；失败时保持旧实例。
- [ ] 添加平台 project 全量 stop/up/down 的 runner 隔离测试。

## 阶段 2：引导、恢复和身份契约

- [ ] 提供不依赖 web-api 的离线 runner 恢复 CLI；干跑默认、显式 apply 执行。
- [ ] 恢复入口校验 runner 包 SHA、镜像 digest、版本、能力、配置、网络和挂载后才启动。
- [ ] runner 自换支持失败回切，handoff 标记持久且幂等。
- [ ] 预检查和任务状态展示报告实际镜像身份/能力探针，不把版本号当作内容证明。
- [ ] Compose healthcheck、状态文件生成器、runner presence 与恢复 CLI 使用同一判据。
- [ ] 覆盖 runner 缺失、停止、SIGKILL、旧镜像同版本异内容、心跳停滞和错误 project 配置。

## 阶段 3：迁移执行归一

- [ ] 统一 `migrations/registry.json` 与数据库 schema 变更声明，消除重复 `_ensure_column` 定义。
- [ ] 迁移载荷使用稳定通用 runner 协议；迁移逻辑来自平台包，不新增每条迁移专属 runner action。
- [ ] migration 在备份后、目标服务启动前执行；写入唯一 ledger，并对 SQLite 写入方做停写/互斥。
- [ ] web-api 和 collector-worker 启动只校验目标 schema，不并发竞争执行版本迁移。
- [ ] 验证 expand-only 失败恢复、旧代码兼容和 runner 执行迁移时的数据库完整性。

## 阶段 4：本地测试与构建门禁

- [ ] 按 P3 套餐完成 L0、前端门禁、L1 包/镜像/能力/digest/迁移门禁。
- [ ] 对所有迁移、handoff、缺 runner 恢复和平台 project 隔离测试加入可复现的反向用例。
- [ ] 用最终候选平台/runner 资产跑 `verify_data_integrity.py` 的同状态自检，确认测试工具本身 0 FAIL。

## 阶段 5：验证机全链路定稿

- [ ] `.14` 全新安装：两个 Compose project 独立，数据集、8 项健康、长时间 runner health 均通过。
- [ ] `.14` 从锁定的真实 v0.5.4 配对升级到 0.5.5，分别走 Web 与 CLI，逐跳 compare。
- [ ] `.14` 执行 runner 缺失恢复、能力/digest 不符拒绝、迁移重复执行、handoff 重启和网络故障反向用例。
- [ ] `.12` 生产等价升级、业务完整性逐位比较、L5 B/C 回滚与升级后采集全过。
- [ ] L6 站点验收、矩阵回填、原始日志归档和 package ledger SHA 记录完成。

## 完成判据

同一个 v0.5.5 交付批次通过全部 P3 核心验收；平台升级无法重建/停止 runner；runner 缺失可离线恢复；迁移只执行一次且可回滚到旧平台；平台数据完整性 compare 全 PASS。没有完成的关键格不得通过拆成 v0.5.6 来隐藏。

