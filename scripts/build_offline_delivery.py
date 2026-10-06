#!/usr/bin/env python3
"""制作离线交付目录（一键安装 + 一键升级，49-56 步骤 1）。

交付目录必须**可复现、可审计**，不能靠手工拼装，因此由本工具从已门禁的产物组装：

    smartx-capacity-insight-v<版本>-offline/
    ├── README.md                       # 由 --readme 指定（步骤 4 产出）
    ├── install/                        # 首次部署物料（运行物料：镜像归档）
    │   ├── install.sh
    │   ├── images/*.tar + SHA256SUMS
    │   ├── project/                    # 平台部署文件（compose 渲染为已发布 runner 基线）
    │   ├── pre_install.sh
    │   └── .env.template
    └── upgrade/                        # 离线升级物料（版本单元：升级包）
        ├── upgrade.sh
        └── packages/*.tar.gz + SHA256SUMS

两条硬约束（设计 §3）：
1. **安装交付镜像、升级交付包**，两者互不依赖——客户可只拿 install/ 或只拿 upgrade/。
2. 交付物内 compose 的 runner tag 必须落**已发布基线**（`--runner-baseline`），
   不是源码 compose 的开发线 tag（AGENTS §8 / docs/version-governance.md）。

用法:
    python3 scripts/build_offline_delivery.py \
        --platform-package <平台升级包.tar.gz> \
        --runner-package <runner组件包.tar.gz> \
        --prometheus-image prom/prometheus:v2.55.1 \
        --runner-baseline v0.3.1 \
        --readme README.md \
        --output-dir /data/offline-delivery
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 交付脚本的仓库内权威位置（builder 复制进交付包，脚本本身是交付物的一部分）
SCRIPT_SOURCES: dict[str, Path] = {
    "install/install.sh": ROOT / "delivery" / "install" / "install.sh",
    "upgrade/upgrade.sh": ROOT / "delivery" / "upgrade" / "upgrade.sh",
    # US-37 compose 变体守卫。交付目录没有 lib/，所以守卫必须自包含，
    # 且 install/ 与 upgrade/ 各放一份（避免两目录间的相对路径耦合）。
    "install/compose-guard.sh": ROOT / "delivery" / "compose-guard.sh",
    "upgrade/compose-guard.sh": ROOT / "delivery" / "compose-guard.sh",
}

# 交付物禁含清单（docs/ova-delivery.md 制品边界）。
# 命中即构建失败——宁可构建不出来，也不能把现场数据带进客户现场。
FORBIDDEN_NAMES: set[str] = {
    ".env",
    "smartx.db",
    "smartx.db-wal",
    "smartx.db-shm",
    "token",
    "credentials.json",
    "tower-credentials.json",
}
FORBIDDEN_SUFFIXES: set[str] = {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm"}
# 目录名包含即命中（备份/导出/运行数据）
FORBIDDEN_DIR_HINTS: tuple[str, ...] = ("backups", "exports", "migrations", "imports", "prometheus-data")

# 安装需要的平台镜像（与 docker-compose.offline.yml 的服务对应）
PLATFORM_SERVICES: tuple[tuple[str, str], ...] = (
    ("web-api", "web-api.tar"),
    ("collector-worker", "collector-worker.tar"),
    ("frontend", "frontend.tar"),
)


def log(message: str) -> None:
    print(f"[offline-delivery] {message}", flush=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sha256sums(directory: Path, names: list[str]) -> Path:
    """为目录内给定文件生成 SHA256SUMS（`sha256sum -c` 可直接校验）。"""
    target = directory / "SHA256SUMS"
    lines = [f"{sha256_of(directory / name)}  {name}" for name in sorted(names)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def scan_forbidden(root: Path) -> list[str]:
    """扫描交付目录是否含禁含文件。返回命中列表（空 = 通过）。"""
    hits: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        parts = {part.lower() for part in relative.parts}
        if parts & FORBIDDEN_NAMES or path.name.lower() in FORBIDDEN_NAMES:
            hits.append(str(relative))
            continue
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            hits.append(str(relative))
            continue
        if any(hint in parts for hint in FORBIDDEN_DIR_HINTS):
            hits.append(str(relative))
    return sorted(set(hits))


def image_tags_in_archive(archive: Path) -> set[str]:
    """读出 `docker save` 归档里镜像的真实 tag 集合（不加载到 Docker）。

    兼容两种格式：
      · OCI：index.json 的 manifests[].annotations["io.containerd.image.name"]
      · 旧版：manifest.json 的 [].RepoTags

    这是 US-33 的核心防线：**交付前**就知道 `images/*.tar` 里装的到底是哪个 tag，
    而不是等客户 `docker load` 之后才发现与 compose 声明对不上。
    """
    tags: set[str] = set()
    with tarfile.open(archive, "r:*") as tar:
        for member_name, key in (("index.json", "io.containerd.image.name"), ("manifest.json", None)):
            try:
                handle = tar.extractfile(member_name)
            except KeyError:
                continue
            if handle is None:
                continue
            try:
                data = json.loads(handle.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if key is not None:
                for manifest in data.get("manifests") or []:
                    annotations = manifest.get("annotations") or {}
                    name = str(annotations.get(key) or "").strip()
                    # 形如 docker.io/nazawsze/xxx:v0.5.3
                    if "/" in name:
                        name = name.split("/", 1)[1]
                    if name:
                        tags.add(name)
            else:
                for entry in data if isinstance(data, list) else []:
                    for tag in entry.get("RepoTags") or []:
                        tags.add(str(tag).strip())
    return tags


def declared_images_from_compose(compose_path: Path) -> set[str]:
    """从 install compose 里读出它声明的镜像引用。"""
    declared: set[str] = set()
    for line in compose_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("image:"):
            value = stripped.split("image:", 1)[1].strip()
            if value:
                declared.add(value)
    return declared


def extract_member(archive: Path, member_suffix: str, destination: Path) -> Path:
    """从 tar/ tar.gz 里按名字后缀取单个文件。"""
    with tarfile.open(archive, "r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if member.name == member_suffix or member.name.endswith("/" + member_suffix):
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as stream:
                    shutil.copyfileobj(extracted, stream)
                return destination
    raise SystemExit(f"[offline-delivery] 在 {archive} 里找不到 {member_suffix}")


_PLATFORM_IMAGE_SERVICES = ("web-api", "collector-worker", "frontend")


def render_offline_compose(
    source: Path, destination: Path, runner_baseline: str, platform_version: str | None = None
) -> None:
    """把源码 compose 渲染成交付版：runner tag 落已发布基线，平台三件套落目标版本。

    只改 upgrade-runner 与三件套的 image 行，**不动其它任何内容**——交付物里的 compose
    必须与源码可对照（AGENTS §8「发布包中的 Compose 应写入明确、可审计的镜像身份」）。

    `platform_version` 用于**构建比仓库当前 VERSION 更旧的交付目录**（例如拿已发布
    v0.5.2 平台包装出 v0.5.2 基线安装物，用来验证 v0.5.2 → v0.5.4 的源端升级格）。
    不传时保持源码 compose 里的 tag 不变（当前版本自洽）。若不改，交付目录会带着
    仓库当前版本 tag，而 `images/` 里是旧版本镜像——US-33 自洽门禁会当场拦下。
    """
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    in_runner = False
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not in_runner:
            if stripped == "upgrade-runner:" or stripped.startswith("upgrade-runner:"):
                in_runner = True
            continue
        if line[:1].strip() == "" and stripped and ":" in stripped and not stripped.startswith("#"):
            if not line.startswith((" ", "\t")):
                break
        if stripped.startswith("image:") and "-upgrade-runner:" in stripped:
            prefix = line[: line.index("image:") + len("image:")]
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{prefix} nazawsze/smartx-hci-capacity-insight-upgrade-runner:{runner_baseline}{newline}"
            replaced = True
            break
    if not replaced:
        raise SystemExit(f"[offline-delivery] 未能在 {source} 里定位 upgrade-runner 的 image 行")
    if platform_version:
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("image:"):
                continue
            for service in _PLATFORM_IMAGE_SERVICES:
                marker = f"smartx-hci-capacity-insight-{service}:"
                if marker in stripped:
                    prefix = line[: line.index("image:") + len("image:")]
                    repository = stripped.split(marker, 1)[0].split()[-1]
                    newline = "\n" if line.endswith("\n") else ""
                    lines[index] = f"{prefix} {repository}{marker}{platform_version}{newline}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8")


def render_all_delivery_composes(
    project_dir: Path, runner_baseline: str, platform_version: str | None = None
) -> list[str]:
    """把交付 project 目录下**所有** compose 的 runner tag 落已发布基线。

    为什么不止 offline 那一份（2026-09-30 `ops/package.sh` T2 实测发现）：
    原实现只渲染 `docker-compose.offline.yml`，而 `copy_project_files` 是整份复制，
    于是 `docker-compose.yml` 原样带着**源码开发线** tag（实测 v0.3.2）进了交付目录。
    而 `delivery/install/install.sh` 启动用 offline 那份（`COMPOSE_FILE`），却把**两个都装进**
    目标目录——现场同时存在一份 tag 正确和一份 tag 错误的 compose。任何人工
    `docker compose up`（默认读 `docker-compose.yml`）都会拉起未经本轮验收的 runner：
    离线机直接失败（`images/` 里只有基线镜像），联网机则静默换人。违反 AGENTS §8。
    """
    rendered: list[str] = []
    for compose in sorted(project_dir.glob("docker-compose*.yml")):
        render_offline_compose(compose, compose, runner_baseline, platform_version)
        rendered.append(compose.name)
    if not rendered:
        raise SystemExit(f"[offline-delivery] {project_dir} 下没有任何 docker-compose*.yml")
    return rendered


def build_env_template(source: Path, destination: Path) -> None:
    """从 .env.example 生成 .env.template，密钥位留占位符由安装脚本替换。"""
    text = source.read_text(encoding="utf-8")
    text = text.replace("replace-with-a-long-random-secret", "__GENERATE__")
    text = text.replace("replace-with-a-different-long-random-secret", "__GENERATE__")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def copy_project_files(destination: Path) -> list[str]:
    """复制平台部署文件到 install/project/。

    prometheus.yml 必须落在 `project/prometheus/prometheus.yml` —— compose 里是按这个
    路径挂载进容器的（`.../project/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro`），
    放错位置会导致 Prometheus 起不来。
    """
    copied: list[str] = []
    for name in ("docker-compose.offline.yml", "docker-compose.yml"):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, destination / name)
            copied.append(name)
    prometheus_yml = ROOT / "prometheus" / "prometheus.yml"
    if prometheus_yml.is_file():
        target = destination / "prometheus" / "prometheus.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prometheus_yml, target)
        copied.append("prometheus/prometheus.yml")
    return copied


def docker_save(image: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"docker save {image} -> {destination.name}")
    result = subprocess.run(
        ["docker", "save", "-o", str(destination), image],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"[offline-delivery] docker save {image} 失败：{result.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="制作离线交付目录（安装 + 升级）")
    parser.add_argument("--platform-package", required=True, help="平台升级包 tar.gz（提供三件套镜像）")
    parser.add_argument("--runner-package", required=True, help="runner 组件包 tar.gz（提供 runner 镜像）")
    parser.add_argument("--prometheus-image", default="prom/prometheus:v2.55.1", help="prometheus 镜像（docker save）")
    parser.add_argument(
        "--prometheus-archive",
        default=None,
        help="已备好的 prometheus 镜像归档（tar）。给了就直接复制、不再 docker save，"
        "用于字节级可复现构建（docker save 每次会写入时间戳）。",
    )
    parser.add_argument("--runner-baseline", required=True, help="交付 compose 里 runner 的已发布基线 tag，如 v0.3.1")
    parser.add_argument("--readme", required=True, help="交付根 README.md 源文件")
    parser.add_argument("--output-dir", required=True, help="交付目录输出位置")
    parser.add_argument("--platform-version", default=None, help="平台版本（默认从包 manifest 读）")
    parser.add_argument("--allow-existing", action="store_true", help="允许覆盖已存在的输出目录")
    args = parser.parse_args()

    platform_package = Path(args.platform_package)
    runner_package = Path(args.runner_package)
    readme = Path(args.readme)
    # 交付 README 是客户唯一的使用说明书：缺关键章节 = 客户拿到与脚本能力脱节的文档。
    # 随脚本能力演进必须同步更新 README（教训：r9 交付目录里的 README 没有守卫章节）。
    readme_text = readme.read_text(encoding="utf-8")
    for required_heading in (
        "前置条件",
        "首次安装",
        "离线升级",
        "恢复密钥",
        "compose 变体守卫",
        "数据迁移与恢复密钥",
        "常见失败",
    ):
        if required_heading not in readme_text:
            raise SystemExit(
                f"交付 README 缺少必需章节「{required_heading}」——请更新 README 后重试。"
                "（README 是客户唯一说明书，必须与交付脚本能力同步）"
            )
    output = Path(args.output_dir)
    for path, label in ((platform_package, "平台升级包"), (runner_package, "runner 组件包"), (readme, "README")):
        if not path.is_file():
            raise SystemExit(f"[offline-delivery] {label} 不存在：{path}")

    if output.exists():
        if not args.allow_existing:
            raise SystemExit(f"[offline-delivery] 输出目录已存在：{output}（加 --allow-existing 覆盖）")
        log(f"清空已存在的输出目录 {output}")
        shutil.rmtree(output)

    # 平台版本：优先显式传入，否则从平台包 manifest 读
    version = args.platform_version
    if not version:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_member = "manifest.json"
            extracted = extract_member(platform_package, manifest_member, Path(tmpdir) / "manifest.json")
            version = str(json.loads(extracted.read_text(encoding="utf-8")).get("version") or "")
        if not version:
            raise SystemExit(f"[offline-delivery] 无法从 {platform_package} 读出版本，请用 --platform-version 指定")
    log(f"平台版本：{version}；runner 交付基线：{args.runner_baseline}")

    install_dir = output / "install"
    images_dir = install_dir / "images"
    project_dir = install_dir / "project"
    upgrade_dir = output / "upgrade"
    packages_dir = upgrade_dir / "packages"
    for path in (images_dir, project_dir, packages_dir):
        path.mkdir(parents=True, exist_ok=True)

    # ---------- install/images ----------
    image_names: list[str] = []
    for service, member in PLATFORM_SERVICES:
        target = images_dir / member
        log(f"从平台包提取 {member}")
        extract_member(platform_package, f"images/{member}", target)
        image_names.append(member)

    prometheus_tar = images_dir / "prometheus.tar"
    if args.prometheus_archive:
        archive = Path(args.prometheus_archive)
        if not archive.is_file():
            raise SystemExit(f"[offline-delivery] --prometheus-archive 不存在：{archive}")
        log(f"复制已备好的 prometheus 归档 {archive.name}（字节级可复现）")
        shutil.copy2(archive, prometheus_tar)
    else:
        docker_save(args.prometheus_image, prometheus_tar)
    image_names.append("prometheus.tar")

    # runner 安装镜像必须与 compose 声明的 baseline **同 tag**（US-33）。
    # 组件包里装的是"当前版本"（如 v0.3.2），而 install compose 按版本治理落"已发布基线"
    # （v0.3.1）——两者天然不同。若直接把组件包的镜像塞进 install/images/，干净 VM 上
    # `install.sh` 会在"镜像 tag 与 compose 声明不匹配"这一步失败（.14 实测）。
    baseline_image = f"nazawsze/smartx-hci-capacity-insight-upgrade-runner:{args.runner_baseline}"
    inspect = subprocess.run(
        ["docker", "image", "inspect", baseline_image],
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        raise SystemExit(
            f"[offline-delivery] 本地没有安装用 runner 镜像：{baseline_image}\n"
            f"  安装 compose 按版本治理落**已发布基线** {args.runner_baseline}，\n"
            f"  因此交付物必须携带该 tag 的镜像（不是组件包的当前版本）。\n"
            f"  请先在构建机上准备好该镜像，或改用 --runner-baseline 指定本地已有的已发布版本。"
        )
    log(f"导出安装用 runner 镜像（baseline {args.runner_baseline}）：{baseline_image}")
    docker_save(baseline_image, images_dir / "upgrade-runner.tar")
    image_names.append("upgrade-runner.tar")



    # ---------- install/project ----------
    copied = copy_project_files(project_dir)
    # 交付目录内**所有** compose 的 runner tag 都落已发布基线（不只是 offline 那份），
    # 平台三件套 tag 落目标版本（构建比仓库当前 VERSION 更旧的交付目录时必需）
    rendered = render_all_delivery_composes(project_dir, args.runner_baseline, version)
    log(
        f"install/project：{', '.join(copied)}"
        f"（runner tag 落 {args.runner_baseline}，平台 tag 落 {version}：{', '.join(rendered)}）"
    )
    shutil.copy2(ROOT / "pre_install.sh", project_dir / "pre_install.sh")
    (project_dir / "pre_install.sh").chmod(0o755)

    # ---------- 门禁：交付物自洽（US-33）----------
    # 逐个解包 images/*.tar 读出**真实 tag**，与交付 compose 声明逐一比对。
    # 这一步不需要干净机器就能抓到 US-33（compose 要 v0.3.1、镜像却是 v0.3.2），
    # 属于交付物内部自洽性，必须在构建期就断言。
    # 断言覆盖**全部** compose（2026-09-30 起）：只查 offline 会漏掉主 compose 带的
    # 源码开发线 tag，而那份就在现场、且是 `docker compose up` 的默认读取对象。
    compose_files = sorted(project_dir.glob("docker-compose*.yml"))
    expected_runner_image = (
        f"nazawsze/smartx-hci-capacity-insight-upgrade-runner:{args.runner_baseline}"
    )
    for compose in compose_files:
        compose_declared = declared_images_from_compose(compose)  # 返回 set[str]
        if expected_runner_image not in compose_declared:
            raise SystemExit(
                f"[offline-delivery] {compose.name} 的 upgrade-runner tag 未落基线 "
                f"{args.runner_baseline}（实际声明：{sorted(compose_declared)}）——"
                f"交付物 compose 必须写已发布基线，不得写源码开发线 tag（AGENTS §8）"
            )
    declared = declared_images_from_compose(project_dir / "docker-compose.offline.yml")
    provided: dict[str, str] = {}
    available_tags: set[str] = set()
    for tar_path in sorted(images_dir.glob("*.tar")):
        archive_tags = image_tags_in_archive(tar_path)
        if not archive_tags:
            raise SystemExit(
                f"[offline-delivery] 无法从 {tar_path.name} 读出镜像 tag（既无 index.json 也无 manifest.json）"
            )
        available_tags |= archive_tags
        provided[tar_path.name] = ", ".join(sorted(archive_tags))
    missing = sorted(declared - available_tags)
    if missing:
        log("交付物不自洽：compose 声明的镜像在 images/ 里没有对应归档或 tag 不符")
        for tag in missing:
            log(f"  compose 需要: {tag}")
        for name, tags in provided.items():
            log(f"  {name} 实际含: {tags}")
        raise SystemExit(
            "[offline-delivery] 交付物内部不自洽——compose 声明的镜像与 images/ 里的真实 tag 不一致。"
            "（US-33：安装用镜像必须与 compose 的已发布 baseline 同 tag）"
        )
    log(f"交付物自洽校验：compose 声明 {len(declared)} 个镜像，全部有匹配归档")
    for name, tags in provided.items():
        log(f"  {name} → {tags}")

    install_sums = write_sha256sums(images_dir, image_names)
    log(f"install/images/SHA256SUMS 已生成（{len(image_names)} 个镜像）")
    build_env_template(ROOT / ".env.example", install_dir / ".env.template")
    log("install/.env.template 已生成（密钥位为 __GENERATE__ 占位符）")

    # ---------- upgrade/packages ----------
    platform_target = packages_dir / platform_package.name
    shutil.copy2(platform_package, platform_target)
    runner_target = packages_dir / runner_package.name
    shutil.copy2(runner_package, runner_target)
    package_names = [platform_package.name, runner_package.name]
    upgrade_sums = write_sha256sums(packages_dir, package_names)
    log(f"upgrade/packages/SHA256SUMS 已生成（{', '.join(package_names)}）")

    # 升级包附 .sha256（与 .3 构建口径一致）
    for name in package_names:
        digest = sha256_of(packages_dir / name)
        (packages_dir / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")

    # ---------- 交付脚本（install.sh / upgrade.sh）----------
    for relative, source in SCRIPT_SOURCES.items():
        if not source.is_file():
            raise SystemExit(f"[offline-delivery] 缺少交付脚本源文件：{source}")
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target.chmod(0o755)
        log(f"已放入交付脚本 {relative}")

    # ---------- README ----------
    shutil.copy2(readme, output / "README.md")
    log("README.md 已放入")

    # ---------- 门禁：禁含文件扫描 ----------
    hits = scan_forbidden(output)
    if hits:
        log("禁含文件扫描未通过：")
        for hit in hits:
            log(f"  - {hit}")
        raise SystemExit("[offline-delivery] 交付目录含禁含文件，构建失败")
    log("禁含文件扫描：0 命中")

    # ---------- 门禁：compose 不得含未发布 runner tag ----------
    # 覆盖交付目录内**全部** compose：只查 offline 会漏掉主 compose 带的源码开发线 tag
    expected = f"upgrade-runner:{args.runner_baseline}"
    for compose in sorted(project_dir.glob("docker-compose*.yml")):
        compose_text = compose.read_text(encoding="utf-8")
        if expected not in compose_text:
            raise SystemExit(
                f"[offline-delivery] {compose.name} 未落 runner 基线 {expected}——"
                f"交付物 compose 必须写已发布基线（AGENTS §8）"
            )
    log(f"compose runner 基线校验：{expected} 命中（{', '.join(c.name for c in sorted(project_dir.glob('docker-compose*.yml')))}）")


    # ---------- 交付摘要 ----------
    log("")
    log(f"交付目录已生成：{output}")
    for path in sorted(output.rglob("*")):
        if path.is_file():
            size_mb = path.stat().st_size / 1024 / 1024
            log(f"  {path.relative_to(output)}  ({size_mb:.1f} MiB)")
    log("")
    log("可复现性口径（.3 实测两次构建）：")
    log("  · 文件清单结构：完全一致")
    log("  · 平台三件套与 runner 镜像：**字节级一致**（从已门禁的包内解包，不经 docker save）")
    log("  · 升级包：**字节级一致**（文件复制）")
    log("  · prometheus.tar：**每次 SHA 不同** —— `docker save` 会写入时间戳，属固有行为；")
    log("    如需字节级可复现，请预先 `docker save` 一次并把该 tar 作为 --prometheus-archive 传入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
