# CloudTower API 版本对接矩阵（4.4.0+）

> **这份文档是长期维护件**：每出一个新的 CloudTower 版本（或文档站新增版本），按
> §5「更新流程」重跑探针、更新本表、同步版本画像与测试。**矩阵与画像表必须一致**——
> `backend/tests/test_cloudtower_api_version_matrix.py` 会解析本文件并比对
> `backend/app/v2/cloudtower/profiles.py`，不一致即测试失败（防止文档漂移）。

- 覆盖范围：**CloudTower 4.4.0 及以上**（2026-10-07 用户口径；低于 4.4.0 不在支持面内）
- 证据来源：官方文档站按版本发布的 OpenAPI 规范
  `https://code-site.smartx.com/specs/<version>-swagger.json`
- 生成方式：按版本抓取上述规范并做结构比对（只读、带缓存；开发期用一次性探针完成，
  该探针不随仓库分发）
- 首次实测日期：**2026-10-07**；覆盖版本 4.9.0 / 4.8.1 / 4.8.0 / 4.7.2 / 4.7.0 /
  4.6.0 / 4.5.0 / 4.4.1 / 4.4.0（`4.7.1 / 4.6.2 / 4.6.1 / 4.4.2` 在文档站 `specs/`
  目录下没有规范文件——站点返回 HTML——由相邻版本覆盖断点两侧）

## 1. 平台对接的 API 清单（调用点）

| # | 端点 | 用途 | 调用位置 |
| --- | --- | --- | --- |
| 1 | `POST /v2/api/login` | 取 token（用户名密码或 API Token） | `cloudtower/client.py::login` |
| 2 | `GET /v2/api/get-version` | **Tower 平台版本**（纯文本，必须 GET；POST 同路径 405） | `client.py::get_version` |
| 3 | `POST /v2/api/get-clusters` | 集群列表：集群元数据（节点版本 + 容量兜底） | `client.py::cluster_metadata` |
| 4 | `POST /v2/api/get-vms` | 虚拟机列表（含 owner 标签、folder 虚拟机组、回收站标记） | `client.py::get_vms` |
| 5 | `POST /v2/api/get-vm-volumes` | 卷列表（容量、策略、副本、精简） | `client.py::get_vm_volumes` |
| 6 | `POST /v2/api/get-cluster-storage-info` | **集群容量（已用/总量）** | `client.py::get_cluster_storage_info` |

## 2. 版本差异矩阵（哪些版本需要换 API / 换字段）

**需要换路径的断点（端点级）**：

| 断点 | 差异 | 我们的做法 |
| --- | --- | --- |
| **4.5.0** | `get-cluster-storage-info` **4.4.x 不存在**（4.5.0 起才有） | 4.4.x 改从 `get-clusters` 的 `Cluster.used_data_space/total_data_capacity` 取容量（该字段 4.4.0+ 全有）；≥4.5.0 走端点 |

**需要换字段的断点（字段级，读取侧容错）**：

| 断点 | 差异 | 我们的做法 |
| --- | --- | --- |
| **4.7.0** | 卷扁平字段 `elf_storage_policy_replica_num` / `_thin_provision` / `_ec_k` / `_ec_m` **4.6.0 及以下没有** | 没有则按策略串推导（`REPLICA_2_THIN_PROVISION` → 2 副本 / 精简；枚举见 §4） |
| **4.6.0** | `Vm.used_size` / `VmVolume.used_size` **4.5.0 及以下没有** | 缺失按「未上报」处理（卷页面显示 `-`，不参与增长计算） |

**始终可用的**：`login`、`get-version`、`get-clusters`、`get-vms`、`get-vm-volumes`
在 4.4.0+ 全部存在；`GET /v2/api/get-version` 在支持面内始终可读到版本号。

### 每版一行（✅=有 / —=无）

<!-- API-MATRIX-TABLE-START（本表由探针矩阵生成；测试会解析本块并比对画像表） -->

| 版本 | 容量端点 | 卷扁平策略字段 | 卷 used_size | VM used_size |
| --- | --- | --- | --- | --- |
| 4.9.0 | ✅ | ✅ | ✅ | ✅ |
| 4.8.1 | ✅ | ✅ | ✅ | ✅ |
| 4.8.0 | ✅ | ✅ | ✅ | ✅ |
| 4.7.2 | ✅ | ✅ | ✅ | ✅ |
| 4.7.0 | ✅ | ✅ | ✅ | ✅ |
| 4.6.0 | ✅ | — | ✅ | ✅ |
| 4.5.0 | ✅ | — | — | — |
| 4.4.1 | — | — | — | — |
| 4.4.0 | — | — | — | — |

<!-- API-MATRIX-TABLE-END -->

## 3. 版本画像表（代码侧的唯一映射，与上表一致）

`backend/app/v2/cloudtower/profiles.py`（`profile_for_version` 按 floor 向下取第一个
`version >= floor` 的画像）：

| 画像 floor | 容量端点 | 卷扁平策略字段 | 卷 used_size | VM used_size |
| --- | --- | --- | --- | --- |
| 4.7.0 | ✅ | ✅ | ✅ | ✅ |
| 4.6.0 | ✅ | — | ✅ | ✅ |
| 4.5.0 | ✅ | — | — | — |
| 4.4.0（支持下限） | — | — | — | — |

**运行时规则**（实现见 `backend/app/v2/cloudtower/profiles.py`；各版本端点差异曾用一次性探针核对官方 OpenAPI 规范）：

1. 版本可解析 → 用对应画像；
2. **版本未知**（塔不可达 / 尚未采集 / 字符串不可解析）→ 最新画像 + **能力探测兜底**
   （先试容量端点，失败自动回退集群记录）——读不到版本也必须可用；
3. 低于 4.4.0 → 不阻断，按最旧画像处理（运维排查线索）。

## 4. 附：存储策略枚举（4.9.0 规范原文，用于策略串推导）

`VmVolumeElfStoragePolicyType`：

```text
EC
REPLICA_1_THIN_PROVISION / REPLICA_1_THICK_PROVISION
REPLICA_2_THIN_PROVISION / REPLICA_2_THICK_PROVISION
REPLICA_3_THIN_PROVISION / REPLICA_3_THICK_PROVISION
ELF_CP_REPLICA_2_THIN_PROVISION / ELF_CP_REPLICA_2_THICK_PROVISION
ELF_CP_REPLICA_3_THIN_PROVISION / ELF_CP_REPLICA_3_THICK_PROVISION
```

- 副本数：从串中取 `REPLICA_<n>`（兼容 `ELF_CP_` 前缀与 `-`/大小写混排）；
- 精简：串含 `THIN_PROVISION` → 精简，含 `THICK` → 厚置备；
- 纯 `EC` 串不含 k/m → **不猜**（该卷按 0 计，与修前一致）。

## 5. 更新流程（新版本发布时）

1. 抓取新版本规范：按 `https://code-site.smartx.com/specs/<version>-swagger.json` 逐版本取回，
   与现有 `profiles.py` 的字段假设做结构比对（开发期一次性动作，无需入库脚本）；
2. 对照矩阵看 §2 的三类断点是否有新变化（新端点/新字段/字段消失）；
3. 有变化 → 更新 §3 画像表与 `profiles.py`（**同时**更新 §2 表格）；无变化 → 只把新版本
   加入 §2 每版一行；
4. 跑 `python3 -m unittest tests.test_cloudtower_api_version_matrix`（矩阵 ↔ 画像一致性）
   与后端全量；
5. 在 §6 变更记录追加一行（日期 / 新增版本 / 结论）。

## 6. 变更记录

| 日期 | 变更 | 结论 |
| --- | --- | --- |
| 2026-10-07 | 首次建立（覆盖 4.4.0–4.9.0） | 三个断点：4.5.0 容量端点、4.7.0 卷扁平字段、4.6.0 used_size；画像表落地（#84） |
