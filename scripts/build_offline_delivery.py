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


def render_offline_compose(source: Path, destination: Path, runner_baseline: str) -> None:
    """把源码 offline compose 渲染成交付版：runner tag 落已发布基线。

    只改 upgrade-runner 的 image 一行，**不动其它任何内容**——交付物里的 compose
    必须与源码可对照（AGENTS §8「发布包中的 Compose 应写入明确、可审计的镜像身份」）。
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
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8")


def build_env_template(source: Path, destination: Path) -> None:
    """从 .env.example 生成 .env.template，密钥位留占位符由安装脚本替换。"""
    text = source.read_text(encoding="utf-8")
    text = text.replace("replace-with-a-long-random-secret", "__GENERATE__")
    text = text.replace("replace-with-a-different-long-random-secret", "__GENERATE__")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def copy_project_files(destination: Path) -> list[str]:
    """复制平台部署文件（compose + prometheus 配置 + 文档）到 install/project/。"""
    copied: list[str] = []
    for name in ("docker-compose.offline.yml", "docker-compose.yml"):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, destination / name)
            copied.append(name)
    prometheus_yml = ROOT / "prometheus" / "prometheus.yml"
    if prometheus_yml.is_file():
        target = destination / "prometheus.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prometheus_yml, target)
        copied.append("prometheus.yml")
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
    parser.add_argument("--runner-baseline", required=True, help="交付 compose 里 runner 的已发布基线 tag，如 v0.3.1")
    parser.add_argument("--readme", required=True, help="交付根 README.md 源文件")
    parser.add_argument("--output-dir", required=True, help="交付目录输出位置")
    parser.add_argument("--platform-version", default=None, help="平台版本（默认从包 manifest 读）")
    parser.add_argument("--allow-existing", action="store_true", help="允许覆盖已存在的输出目录")
    args = parser.parse_args()

    platform_package = Path(args.platform_package)
    runner_package = Path(args.runner_package)
    readme = Path(args.readme)
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

    log("从 runner 组件包提取 upgrade-runner.tar")
    extract_member(runner_package, "images/upgrade-runner.tar", images_dir / "upgrade-runner.tar")
    image_names.append("upgrade-runner.tar")

    prometheus_tar = images_dir / "prometheus.tar"
    docker_save(args.prometheus_image, prometheus_tar)
    image_names.append("prometheus.tar")

    install_sums = write_sha256sums(images_dir, image_names)
    log(f"install/images/SHA256SUMS 已生成（{len(image_names)} 个镜像）")

    # ---------- install/project ----------
    copied = copy_project_files(project_dir)
    # offline compose 渲染为交付基线
    offline_src = project_dir / "docker-compose.offline.yml"
    render_offline_compose(offline_src, offline_src, args.runner_baseline)
    log(f"install/project：{', '.join(copied)}（runner tag 落 {args.runner_baseline}）")
    shutil.copy2(ROOT / "pre_install.sh", project_dir / "pre_install.sh")
    (project_dir / "pre_install.sh").chmod(0o755)
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
    compose_text = (project_dir / "docker-compose.offline.yml").read_text(encoding="utf-8")
    expected = f"upgrade-runner:{args.runner_baseline}"
    if expected not in compose_text:
        raise SystemExit(f"[offline-delivery] compose 未落 runner 基线 {expected}")
    log(f"compose runner 基线校验：{expected} 命中")

    # ---------- 交付摘要 ----------
    log("")
    log(f"交付目录已生成：{output}")
    for path in sorted(output.rglob("*")):
        if path.is_file():
            size_mb = path.stat().st_size / 1024 / 1024
            log(f"  {path.relative_to(output)}  ({size_mb:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
