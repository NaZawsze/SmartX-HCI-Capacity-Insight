# findings 历史归档：专项升级链路（归档指针节）

> 归档日期：2026-09-30 ｜ 来源：仓库根 [`findings.md`](../../findings.md) ｜ 切片范围：2 个 `## ` 小节（首「专项升级链路发现归档」→ 末「专项升级链路历史发现归档（已完成）」）
> 内容为逐字搬运（脚本按 `^## ` 标题切片），与原文 byte 级一致，未改写 / 重排 / 合并。
> 本文件只读：历史记录此后不再改写；这 2 节在 [`findings.md`](../../findings.md) 原位置已换成指针行；完整索引见 [`docs/doc-map.md`](../doc-map.md)。

## 专项升级链路发现归档

`v0.5.1 + runner v0.3.0 -> v0.5.1u2 -> runner v0.3.1 -> v0.5.2` 的详细根因、修复计划、失败记录、包记录和验证证据，统一维护在：

```text
docs/v0.5.1-to-v0.5.2-upgrade-chain-worklog.md
```

本文件只保留稳定结论和项目级注意事项。详细过程、失败记录和中间包仍查专项 worklog。

## 专项升级链路历史发现归档（已完成）

`v0.5.1u2 -> v0.5.2` 升级链路的 UPG-038~048 已完成闭环，详细发现归档到 `docs/v0.5.1-to-v0.5.2-upgrade-chain-task-findings.md`。

核心发现摘要：
- UPG-038/039：数据迁移门禁与 cleanup guard 路径归一化
- UPG-040：空业务库 cleanup 兼容
- UPG-041/045：升级后自动采集（worker 兼容已发布 u2 缺失 marker）
- UPG-042：凭据与 .env 成对迁移保护（0600、fail-closed、XOR 同源配对）
- UPG-043：credential helper target_root 路径映射
- UPG-044：verification 历史排序只读化与最近包稳定选择
- UPG-046：任务中心投影幂等化
- UPG-047：runner 发布包 .env 权限兼容（compose 启动 shim）
- UPG-048/fix8：最终 .env 权限修复与链路闭环

