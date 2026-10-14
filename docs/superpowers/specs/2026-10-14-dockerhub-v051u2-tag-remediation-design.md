# DockerHub `v0.5.1u2` tag 修复设计（pending #88）

- 日期：2026-10-14
- 来源：pending-tasks #88（2026-10-14 用户质询核查后立项）；根因证据见 findings.md 2026-10-14 节
- 状态：已批准实施（用户 2026-10-14「修复 88、89，写设计文档」）

## 1. 背景与根因（已定案，2026-10-14 registry 独立复核）

DockerHub `nazawsze/smartx-hci-capacity-insight-web-api:v0.5.1u2` 当前指向镜像
config `sha256:556f69e4…`：`created 2026-07-09T05:03Z`、`revision=baaffcd`（= git tag
`v0.5.1u2` 的提交）。而 `git show v0.5.1u2:VERSION` = **`v0.5.2`**——该提交的 VERSION
文件已写成 v0.5.2，CI 据此构建的镜像 `/app/VERSION` 自报 v0.5.2（OCI label 仍为
`v0.5.1u2`，系构建参数覆盖）。

**叙事定性**：并非「镜像被后来重推覆盖」。该 DockerHub tag 自 2026-07-09 CI 构建起就
指向这个自报 v0.5.2 的镜像。GitHub Release `v0.5.1u2` 包内嵌镜像（`b5018a3c…`，
`.3` 留样三个月）`/app/VERSION=v0.5.1u2` 才是原始镜像。**同一版本号、两种内容**。

**后果链**（`.12` 2026-10-14 实测复现）：直接拉 DockerHub v0.5.1u2 做基线安装 →
升级中心读 `/app/VERSION` 判为 v0.5.2 → 上传 v0.5.2 官方包被源兼容/同版本检查拦下
（`precheck.py:214` 范围判定 + `settings.app_version` 取自 `/app/VERSION`）→
「v0.5.1u2 现场升不到 v0.5.2」。

## 2. 目标与决策

**目标**：让 `web-api:v0.5.1u2` DockerHub tag 的内容与 GitHub Release v0.5.1u2 包
一致（`/app/VERSION=v0.5.1u2`），并在交付/安装文档中固化基线镜像来源规则，防止再犯。

**决策（用户待最终确认，本设计按「校正重推为首选、文档为必备」双轨实施）**：
- **D1 校正重推（首选修复）**：用 GitHub Release v0.5.1u2 包内嵌的原始镜像
  （`images/*.tar`）重新打 tag 并推送 DockerHub，覆盖 `556f69e4` 这个错误内容。
  需 DockerHub 写入凭据——由用户提供（历史上 v0.3.1 镜像即由用户提供 token 推送）。
- **D2 文档固化（必做，与 D1 独立生效）**：安装/交付文档注明：**v0.5.1u2 及更早
  版本的安装镜像只从 GitHub Release 对应发布包内 `images/*.tar` 获取**，不从
  DockerHub 拉旧版本 tag。
- **不做**：删除 DockerHub tag（Docker Hub 免费层不支持可靠删 tag，且会让「在线
  安装旧版本」直接无镜像可用，比内容漂移更糟）；改 git tag（`baaffcd` 是发布事实，
  不改写历史）。

## 3. 实施范围

| 项 | 内容 | 位置 |
| --- | --- | --- |
| S1 | 重推校正脚本（加载 Release 包内镜像 → 逐镜像校验 `/app/VERSION` → 重打 tag → 推送），默认 dry-run，`--push` 才真推；推送前失败即停 | `scripts/fix_dockerhub_v051u2_tag.sh` |
| S2 | 客户向安装文档补「基线镜像来源规则」小节（v0.5.1u2 及更早只认 Release 包内镜像；DockerHub 旧版本 tag 内容不可信） | `delivery/README.md` |
| S3 | 内部部署文档同步该规则与本次事故事实 | `docs/deployment.md` |
| S4 | 脚本静态锁测试（存在性/必须含校验与 dry-run 默认/推送需显式 `--push`） | `backend/tests/test_dockerhub_tag_remediation.py` |

**S1 脚本流程（在具备 docker + DockerHub 凭据的机器上执行，如 .3）**：
1. 入参：GitHub Release v0.5.1u2 平台包路径（或已解包的 `images/` 目录）；
2. `docker load` 包内 `images/*.tar`，记录各镜像 ID；
3. 逐镜像校验：`docker run --rm --entrypoint cat <image> /app/VERSION`——
   web-api 必须解出 `v0.5.1u2`，否则**拒绝推送**（frontend/collector-worker 无
   `/app/VERSION` 的按 Release 清单豁免并如实打印）；
4. `docker tag <release-image> nazawsze/smartx-hci-capacity-insight-web-api:v0.5.1u2`
   （frontend/collector-worker 同理）；
5. `--push` 时 `docker push` 三个 tag，否则 dry-run 只打印将执行的命令；
6. 推送后校验：`docker manifest inspect` 回读 digest 与本地 tag 一致。

**凭据边界**：脚本只读环境变量 `DOCKERHUB_USER` / `DOCKERHUB_TOKEN`（或本机
`docker login` 会话），不记录、不落盘；仓库任何位置不得出现凭据（AGENTS §5）。

## 4. 边界与不做

- 不动 runner 镜像/tag（v0.3.1 已于 2026-09-27 正确推送，见 pending #46）；
- 不动 git tag / Release 资产（发布事实）；
- 不改任何产品代码（本项是资产与文档修复）；
- 不为跑脚本而在 `.12` 做任何宿主变更（AGENTS §5）；脚本默认在 .3 执行。

## 5. 测试计划

- T1（静态锁）：脚本存在、默认 dry-run、`--push` 才推、推送前有 `/app/VERSION` 校验分支；
- T2（静态锁）：`delivery/README.md` 与 `docs/deployment.md` 含基线镜像来源规则小节；
- T3（真机，条件性）：用户在 .3 提供凭据后执行 `--push`，`docker manifest inspect`
  回读 digest == Release 镜像 digest；再从 DockerHub 重拉并校验 `/app/VERSION=v0.5.1u2`。
  **本轮不执行推送**（无凭据），T3 作为发布前检查项留给用户决策窗口。

## 6. 回滚

- 文档改动：`git revert` 即可；
- 脚本：删除文件即可（未推送前零副作用）；
- 已推送的 tag：如需回退到错误内容，重推 `556f69e4` 即可（该镜像仍在 DockerHub），
  但预期不会发生——校正方向是修复而非破坏。
