#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = Path("/data/upgrade-packages")


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载构建脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_platform_builder() -> ModuleType:
    return _load_script("build_upgrade_package.py")


def load_prometheus_builder() -> ModuleType:
    return _load_script("build_prometheus_component_package.py")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract(package: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(package, mode="r:gz") as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"升级包包含不安全路径：{member.name}")
        try:
            archive.extractall(destination, filter="data")
        except TypeError:  # Python < 3.12 has no extraction filter argument.
            archive.extractall(destination)


def _copy_tree(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _prefixed_components(components: list[dict], prefix: str) -> list[dict]:
    result: list[dict] = []
    for component in components:
        copied = {**component}
        images = []
        for image in component.get("images") or []:
            copied_image = {**image}
            if copied_image.get("archive"):
                copied_image["archive"] = f"{prefix}/{copied_image['archive']}"
            images.append(copied_image)
        copied["images"] = images
        result.append(copied)
    return result


def build_package(
    *,
    platform_version: str,
    prometheus_version: str,
    min_platform_version: str,
    min_prometheus_version: str,
    output_dir: Path,
    build_platform_images: bool,
    include_frontend_build: bool,
    pull_prometheus: bool,
    offline_prometheus_image: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    platform_builder = load_platform_builder()
    prometheus_builder = load_prometheus_builder()

    with tempfile.TemporaryDirectory(dir=output_dir) as tmpdir:
        temporary = Path(tmpdir)
        platform_package = platform_builder.build_package(
            platform_version,
            min_version=min_platform_version,
            output_dir=temporary,
            build_images=build_platform_images,
            include_frontend_build=include_frontend_build,
        )
        prometheus_package = prometheus_builder.build_package(
            prometheus_version,
            min_prometheus_version,
            temporary,
            pull_image=pull_prometheus,
            offline_image=offline_prometheus_image,
        )
        platform_source = temporary / "platform-source"
        prometheus_source = temporary / "prometheus-source"
        _extract(platform_package, platform_source)
        _extract(prometheus_package, prometheus_source)

        platform_manifest = json.loads((platform_source / "manifest.json").read_text(encoding="utf-8"))
        prometheus_manifest = json.loads((prometheus_source / "manifest.json").read_text(encoding="utf-8"))

        work = temporary / f"smartx-capacity-insight-bundle-{platform_version}"
        _copy_tree(platform_source / "images", work / "platform" / "images")
        _copy_tree(platform_source / "project", work / "platform" / "project")
        (work / "platform" / "migrations").mkdir(parents=True, exist_ok=True)
        platform_migration = dict(platform_manifest.get("migration") or {})
        migration_script = Path(str(platform_migration.get("script") or "scripts/migrate.sh"))
        if migration_script.is_absolute() or ".." in migration_script.parts:
            raise RuntimeError(f"平台迁移脚本路径不安全：{migration_script}")
        migration_source = platform_source / migration_script
        if not migration_source.is_file():
            raise RuntimeError(f"平台包缺少迁移脚本：{migration_script}")
        shutil.copy2(migration_source, work / "platform" / "migrations" / "migrate.sh")
        _copy_tree(prometheus_source / "images", work / "observability" / "images")
        _copy_tree(prometheus_source / "config", work / "observability" / "config")
        _copy_tree(prometheus_source / "health", work / "observability" / "health")

        components = [
            *_prefixed_components(platform_manifest.get("components") or [], "platform"),
            *_prefixed_components(prometheus_manifest.get("components") or [], "observability"),
        ]
        migration = {
            **(platform_manifest.get("migration") or {}),
            "script": "platform/migrations/migrate.sh",
            "sha256": sha256_file(work / "platform" / "migrations" / "migrate.sh"),
        }
        required_capabilities = sorted(
            {
                *platform_manifest.get("required_capabilities", []),
                *prometheus_manifest.get("required_capabilities", []),
            }
        )
        manifest = {
            "schema_version": "3",
            "minimum_runner_protocol": max(
                int(platform_manifest.get("minimum_runner_protocol") or 1),
                int(prometheus_manifest.get("minimum_runner_protocol") or 1),
            ),
            "required_capabilities": required_capabilities,
            "product": "smartx-storage-forecast",
            "package_id": f"smartx-capacity-insight-bundle-{platform_version}",
            "package_type": "bundle",
            "version": platform_version,
            "components": components,
            "project_files": True,
            "project_source": "platform/project",
            "project_file_list": list(platform_manifest.get("project_file_list") or []),
            "file_sets": [
                {
                    **file_set,
                    "source": f"observability/{file_set.get('source')}",
                }
                for file_set in prometheus_manifest.get("file_sets") or []
            ],
            "migration": migration,
            "restart_services": list(platform_manifest.get("restart_services") or [])
            + list(prometheus_manifest.get("restart_services") or []),
            "compatibility": {
                "min_platform_version": min_platform_version,
                "min_prometheus_version": min_prometheus_version,
            },
            "notes": "release-notes.md",
        }
        work.mkdir(parents=True, exist_ok=True)
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (work / "release-notes.md").write_text(
            f"# {platform_version} 平台与观测组合升级包\n\n"
            f"- 平台版本：{platform_version}\n"
            f"- Prometheus 版本：{prometheus_version}\n"
            "- 不包含 upgrade-runner；Runner 协议能力不足时应先单独升级 Runner。\n"
            "- 不包含 SQLite、Prometheus 历史数据、.env 或任何凭据。\n",
            encoding="utf-8",
        )

        members = sorted(
            path.relative_to(work).as_posix()
            for path in work.rglob("*")
            if path.is_file()
        )
        (work / "checksums.sha256").write_text(
            "\n".join(f"{sha256_file(work / member)}  {member}" for member in members) + "\n",
            encoding="utf-8",
        )
        members.append("checksums.sha256")
        package = output_dir / f"smartx-capacity-insight-bundle-{platform_version}.tar.gz"
        if package.exists():
            package.unlink()
        with tarfile.open(package, mode="w:gz", compresslevel=1) as archive:
            for member in members:
                archive.add(work / member, arcname=member)
        (output_dir / f"{package.name}.sha256").write_text(
            f"{sha256_file(package)}  {package.name}\n",
            encoding="utf-8",
        )
        return package


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a platform and Prometheus bundle upgrade package.")
    parser.add_argument("--platform-version", required=True)
    parser.add_argument("--prometheus-version", default="v2.55.1")
    parser.add_argument("--min-platform-version", default="v0.5.0")
    parser.add_argument("--min-prometheus-version", default="v2.55.1")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--skip-frontend-build", action="store_true")
    parser.add_argument("--no-pull-prometheus", action="store_true")
    parser.add_argument("--offline-prometheus-image", action="store_true", help="Include observability/images/prometheus.tar in the bundle.")
    args = parser.parse_args()
    package = build_package(
        platform_version=args.platform_version,
        prometheus_version=args.prometheus_version,
        min_platform_version=args.min_platform_version,
        min_prometheus_version=args.min_prometheus_version,
        output_dir=args.output_dir,
        build_platform_images=not args.no_build,
        include_frontend_build=not args.skip_frontend_build,
        pull_prometheus=not args.no_pull_prometheus,
        offline_prometheus_image=args.offline_prometheus_image,
    )
    print(package)
    print(sha256_file(package))


if __name__ == "__main__":
    main()
