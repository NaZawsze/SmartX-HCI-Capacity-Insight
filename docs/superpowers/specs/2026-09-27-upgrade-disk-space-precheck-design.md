# 设计：升级预检查补磁盘空间硬校验（US-07 / S1-1）

状态：**已实施并验证**（2026-09-27）。问题台账 [upgrade-strategy-issues.md](../../upgrade-strategy-issues.md) US-07；执行顺序 [../plans/2026-09-27-remaining-work-sequence.md](../plans/2026-09-27-remaining-work-sequence.md) S1-1。

## 1. 背景

`image.load`（解包 + `docker load`）、`backup.create`、文件同步都要占磁盘，但升级预检查的 checks 只有 manifest / paths / source_compatibility / runner_protocol / runner_actions / checksums / images / project_files / prometheus 权限——**没有磁盘空间检查**。空间不足时预检查放行，失败发生在执行中段（镜像加载或备份写满），留下半升级现场：镜像只 load 了一部分、备份不完整、容器可能已切一半，需要人工介入。

## 2. 口径

在 `precheck()` 的 checks 中新增一项 `disk_space`：

- **需求估算**：`需要 = 包内容 + 预留 headroom`。
  - **包内容**：预检查拿到的 `package_path` 是**上传时已解包的目录**（`<task_dir>/package`，见 `intake.py:33`），里面的 `images/*.tar` 是 `docker save` 的**未压缩**归档，`docker load` 会在 docker 存储里再写一份同量级数据 → 所以取目录内文件求和即可（`.3` 实测 v0.5.3 候选包：压缩包 235.6 MiB，解包后 595.8 MiB，其中三个镜像 tar 593.6 MiB）。若传入的是 `.tar.gz` 文件本体，则按压缩膨胀系数 3 估算。
  - headroom 默认 **2 GiB**，覆盖 SQLite 备份（VACUUM INTO）+ 备份轮转 + 校验/解压临时文件 + 余量；可用 `SMARTX_UPGRADE_DISK_HEADROOM_BYTES` 覆盖（0 表示不预留）。
- **检查对象**：按 `st_dev` 去重后逐个检查
  - `settings.upgrades_dir`（升级包与解包落盘）
  - `settings.backups_dir`（备份写入）
  - `/`（docker 镜像存储所在文件系统；容器内 `/` 反映宿主根文件系统）
- **判定**：任一文件系统 `可用空间 < 需要` → 该项 `ok=False` → 任务 `precheck_failed`，message 给出「哪个路径、可用多少、需要多少」与估算构成；`detail` 带 `package_bytes` / `required_bytes` / `headroom_bytes` / `payload_uncompressed` / `filesystems[]` 供任务详情与排障使用。
- **不做**：不改升级引擎运行时行为、不改 runner、不新增界面选项；只加一项预检查。

## 3. 已知限制

- 若 `/var/lib/docker` 位于容器**不可见**的独立挂载（容器里只挂了 docker.sock），本检查无法测量该文件系统，只能覆盖容器可见的 upgrades/backups/根文件系统。真实环境这三者与 docker 存储通常同在单盘/同一挂载，够用；不足时由 `SMARTX_UPGRADE_DISK_HEADROOM_BYTES` 调大预留来覆盖。
- 估算的是"够不够跑完"，不是精确值；系数与预留偏保守，宁可误报失败（可调参），也不要半升级现场。

## 4. 测试计划

1. 单测 `backend/tests/test_upgrade_disk_space_precheck.py`：
   - `required_upgrade_bytes()` 纯函数（系数与预留叠加）；
   - 注入 fake `disk_usage`：空间充足 → `ok=True`；低于需求 → `ok=False` 且 message 含路径与数值；包不存在 → `ok=False`；
   - 去重：同一 `st_dev` 的多路径只检查一次；
   - 预检查集成：patch `shutil.disk_usage` 让空间极小 → 任务状态 `precheck_failed`，checks 含 `disk_space`；空间充足 → `precheck_passed` 不受影响。
2. `.3`：后端全量回归（应 386 + 新增用例全绿）+ 用真实 v0.5.3 候选包跑一次预检查，确认 `disk_space` 项出现在 checks 中且通过。

## 5. 回滚

删除 `precheck()` 中的 `disk_space` 项与 `_check_disk_space`/`package_payload_bytes`/`required_upgrade_bytes`/`human_bytes` 及配置项即可；无数据影响、无 runner 参与。

## 6. 实现修正（`.3` 首跑发现，2026-09-27）

首版把「包体积」取成 `package_path.stat().st_size`：`.3` 用真实 v0.5.3 候选包跑时暴露这是**错的**——`package_path` 是解包后的目录（`intake.py:33`），`st_size` 只有几 KB（目录项大小），于是需求被算成"只有 2 GiB 预留"，等于没检查包内容。修正为 `package_payload_bytes()`：目录取**文件求和**（未压缩镜像 tar，即 `docker load` 要再写一份的量级），传入压缩包文件时才按 ×3 估；并补"目录求和"与"压缩包 ×3"两条单测。

`.3` 实测（root，真实路径，修正后）：`package_bytes = 624777779`（≈595.8 MiB，来自对真实候选包解包目录的求和）、`headroom = 2 GiB`、`required ≈ 2.58 GiB`、`/data/smartx-storage-forecast/upgrades` 可用 **33.34 GiB** → `ok=True`。
