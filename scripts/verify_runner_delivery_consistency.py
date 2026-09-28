#!/usr/bin/env python3
"""Runner 交付一致性硬门禁（#47② / US-02）。

把「仓库 RUNNER_VERSION + 动作表 ｜ runner 组件包 ｜ DockerHub tag」三处同源核对
做成一条可重复执行的命令：任一不一致即非零退出。设计见
docs/superpowers/specs/2026-09-27-runner-delivery-consistency-gate-design.md。

默认完全离线、零副作用：组件包内的镜像归档按 OCI/docker-save 层直接解析，不 load、
不碰本地 tag。可选 `--image` 用 docker 活体探测一个已存在的镜像（需要 docker）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER_VERSION_FILE = ROOT / "RUNNER_VERSION"
ACTIONS_FILE = ROOT / "backend" / "app" / "upgrade_runner" / "actions.py"
SOURCE_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.offline.yml",
    "docker-compose.release.yml",
)
RUNNER_IMAGE_REPO = "nazawsze/smartx-hci-capacity-insight-upgrade-runner"
DOCKERHUB_TAGS_API = "https://hub.docker.com/v2/repositories/{namespace}/{name}/tags/{tag}"
PROBE_MARKER = "SMARTX_RUNNER_PROBE:"
REQUIRED_ACTION = "post_upgrade.schedule_collection"
IMAGE_RUNNER_VERSION_PATH = "RUNNER_VERSION"
IMAGE_ACTIONS_PATH = "upgrade_runner/actions.py"
# US-28 门禁补洞：原先只校验 actions.py 的 md5，改 lease.py/main.py 等其它 runner 模块
# 不会被发现——那正是「同版本号、不同能力」的核心风险。改为对整个 runner 源码树聚合指纹。
IMAGE_RUNNER_PKG_PREFIX = "app/upgrade_runner"

LIVE_PROBE_SCRIPT = """
import hashlib, json
from pathlib import Path

import app.upgrade_runner.actions as actions_module
from app.upgrade_runner.actions import default_handlers

actions_path = Path(actions_module.__file__)
pkg_root = Path(actions_path).parent
tree = hashlib.md5()
files = []
for py in sorted(pkg_root.rglob("*.py")):
    if "__pycache__" in py.parts:
        continue
    rel = py.relative_to(pkg_root).as_posix()
    digest = hashlib.md5(py.read_bytes()).hexdigest()
    files.append([rel, digest])
    tree.update(rel.encode("utf-8"))
    tree.update(digest.encode("utf-8"))
payload = {
    "runner_version": Path("/app/RUNNER_VERSION").read_text(encoding="utf-8").strip(),
    "actions_path": str(actions_path),
    "actions_md5": hashlib.md5(actions_path.read_bytes()).hexdigest(),
    "tree_md5": tree.hexdigest(),
    "tree_files": files,
    "actions": sorted(default_handlers().keys()),
}
print("__PROBE_MARKER__" + json.dumps(payload))
""".replace("__PROBE_MARKER__", PROBE_MARKER)


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-4000:]}"
        )
    return completed.stdout


def sha256_stream(handle: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def repo_runner_tree_fingerprint() -> tuple[str, list[list[str]]]:
    """US-28 门禁补洞：整个 runner 源码树的聚合指纹（含 lease.py/main.py/engine.py 等）。"""
    pkg_root = ROOT / "backend" / "app" / "upgrade_runner"
    tree = hashlib.md5()
    files: list[list[str]] = []
    for py in sorted(pkg_root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(pkg_root).as_posix()
        digest = hashlib.md5(py.read_bytes()).hexdigest()
        files.append([rel, digest])
        tree.update(rel.encode("utf-8"))
        tree.update(digest.encode("utf-8"))
    return tree.hexdigest(), files


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3]) or (0,)


def summarize(value: Any, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def check(check_id: str, status: str, detail: Any, **extra: Any) -> dict[str, Any]:
    record: dict[str, Any] = {"id": check_id, "status": status, "detail": summarize(detail)}
    record.update(extra)
    return record


def read_repo_runner_version() -> str:
    if not RUNNER_VERSION_FILE.exists():
        raise SystemExit(f"missing {RUNNER_VERSION_FILE}")
    version = RUNNER_VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"v\d+\.\d+\.\d+[A-Za-z0-9._-]*", version):
        raise SystemExit(f"invalid RUNNER_VERSION: {version!r}")
    return version


def parse_actions_source(source: str) -> list[str]:
    """静态提取 default_handlers() 的返回字典键（AST，不 import 业务模块）。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "default_handlers":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                    keys = [key.value for key in child.value.keys if isinstance(key, ast.Constant)]
                    if keys:
                        return sorted(keys)
    raise SystemExit("cannot locate default_handlers() action registry in source")


def parse_repo_actions(path: Path = ACTIONS_FILE) -> list[str]:
    return parse_actions_source(path.read_text(encoding="utf-8"))


def image_prefix_for(name: str) -> str:
    return "docker.io/nazawsze" if name == "docker-compose.release.yml" else "nazawsze"


def check_source_compose(version: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in SOURCE_COMPOSE_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        expected = f"{image_prefix_for(name)}/smartx-hci-capacity-insight-upgrade-runner:{version}"
        if expected not in text:
            results.append(check("source_compose_literal", "FAIL", f"{name} missing literal runner tag: {expected}"))
            continue
        templates = [
            key
            for key in (
                "SMARTX_IMAGE_TAG",
                "SMARTX_RUNNER_IMAGE_TAG",
                "SMARTX_IMAGE_PREFIX",
                "SMARTX_RUNNER_IMAGE_PREFIX",
            )
            if key in text
        ]
        if templates:
            results.append(check("source_compose_literal", "FAIL", f"{name} must use literal tags; found {templates}"))
            continue
        if ":latest" in text:
            results.append(check("source_compose_literal", "FAIL", f"{name} must not reference the latest tag"))
            continue
        results.append(check("source_compose_literal", "PASS", f"{name} runner tag = {version}", file=name))
    return results


def read_package_manifest(package: Path) -> dict[str, Any]:
    with tarfile.open(package, "r:gz") as archive:
        handle = archive.extractfile("manifest.json")
        if handle is None:
            raise SystemExit(f"{package} has no readable manifest.json")
        return json.loads(handle.read().decode("utf-8"))


def package_image_entry(manifest: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    for component in manifest.get("components") or []:
        for image in component.get("images") or []:
            if image.get("service") == "upgrade-runner":
                return image.get("archive"), image.get("sha256"), image.get("image")
    return None, None, None


def check_package_manifest(package: Path, version: str) -> tuple[list[dict[str, Any]], str | None]:
    results: list[dict[str, Any]] = []
    manifest = read_package_manifest(package)
    manifest_version = str(manifest.get("version") or "")
    if manifest_version == version:
        results.append(check("package_manifest", "PASS", f"manifest.version = {version}"))
    else:
        results.append(
            check("package_manifest", "FAIL", f"manifest.version={manifest_version!r} != RUNNER_VERSION {version!r}")
        )

    # min_version / min_runner_version 是「可从此版本及以上升级」的下界（组件包默认 v0.1.0），
    # 不是「本包内容版本」；只有大于自身版本才是无意义配置。
    min_runner = str(
        (manifest.get("compatibility") or {}).get("min_runner_version") or manifest.get("min_version") or ""
    )
    if min_runner and version_tuple(min_runner) > version_tuple(version):
        results.append(check("package_manifest", "FAIL", f"min_runner_version={min_runner!r} > {version!r} 无意义"))
    else:
        results.append(check("package_manifest", "PASS", f"min_runner_version={min_runner or '(absent)'} (<= {version})"))

    archive_rel, expected_sha, manifest_image = package_image_entry(manifest)
    if not archive_rel:
        results.append(check("package_manifest", "FAIL", "manifest has no upgrade-runner image archive entry"))
        return results, None

    with tarfile.open(package, "r:gz") as archive:
        handle = archive.extractfile(archive_rel)
        if handle is None:
            results.append(check("package_manifest", "FAIL", f"cannot read {archive_rel} from package"))
            return results, archive_rel
        actual_sha = sha256_stream(handle)
    if expected_sha and actual_sha != expected_sha:
        results.append(
            check("package_manifest", "FAIL", f"{archive_rel} sha256 {actual_sha} != manifest {expected_sha}")
        )
    else:
        results.append(
            check("package_manifest", "PASS", f"{archive_rel} sha256 matches manifest", image=manifest_image)
        )
    return results, archive_rel


def read_image_archive_member(package: Path, archive_rel: str) -> bytes:
    with tarfile.open(package, "r:gz") as archive:
        handle = archive.extractfile(archive_rel)
        if handle is None:
            raise SystemExit(f"{package} has no readable {archive_rel}")
        return handle.read()


def pick_member(layer: tarfile.TarFile, suffix: str) -> tarfile.TarInfo | None:
    candidates = []
    for member in layer.getmembers():
        name = member.name[2:] if member.name.startswith("./") else member.name
        if not member.isfile():
            continue
        if name == suffix or name.endswith("/" + suffix):
            candidates.append((name.count("/"), name, member))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def inspect_image_archive(archive_bytes: bytes) -> dict[str, Any]:
    """按 docker-save/OCI 层解析镜像归档，取 /app 下版本文件与动作表内容；不需要 docker。

    US-28 门禁补洞：除版本文件与动作表外，还收集**整个 runner 源码树**的 md5，
    用于发现「改了 lease.py/main.py 等模块但版本号不变」的能力漂移。
    """
    payload: dict[str, Any] = {}
    tree_files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        handle = archive.extractfile("manifest.json")
        if handle is None:
            raise SystemExit("image archive has no docker manifest.json")
        entries = json.loads(handle.read().decode("utf-8"))
        if not entries:
            raise SystemExit("image archive manifest.json is empty")
        entry = entries[0]
        payload["repo_tags"] = entry.get("RepoTags") or []
        layers = entry.get("Layers") or []
        payload["layer_count"] = len(layers)
        for layer_path in layers:
            try:
                layer_handle = archive.extractfile(layer_path)
            except KeyError:
                continue
            if layer_handle is None:
                continue
            with tarfile.open(fileobj=layer_handle, mode="r:*") as layer:
                # 后出现的层覆盖先出现的（同一文件被多层修改时以最终内容为准）
                for member in layer.getmembers():
                    if not member.name.endswith(".py") or "__pycache__" in member.name:
                        continue
                    index = member.name.find(IMAGE_RUNNER_PKG_PREFIX + "/")
                    if index < 0:
                        continue
                    rel = member.name[index + len(IMAGE_RUNNER_PKG_PREFIX) + 1:]
                    member_data = layer.extractfile(member)
                    if member_data is not None:
                        tree_files[rel] = hashlib.md5(member_data.read()).hexdigest()
                version_member = pick_member(layer, IMAGE_RUNNER_VERSION_PATH)
                if version_member is not None:
                    data = layer.extractfile(version_member)
                    if data is not None:
                        payload["runner_version"] = data.read().decode("utf-8").strip()
                        payload["runner_version_path"] = version_member.name
                actions_member = pick_member(layer, IMAGE_ACTIONS_PATH)
                if actions_member is not None:
                    data = layer.extractfile(actions_member)
                    if data is not None:
                        source = data.read()
                        payload["actions_path"] = actions_member.name
                        payload["actions_md5"] = hashlib.md5(source).hexdigest()
                        payload["actions"] = parse_actions_source(source.decode("utf-8"))
    ordered = sorted(tree_files.items())
    if ordered:
        tree = hashlib.md5()
        for rel, digest in ordered:
            tree.update(rel.encode("utf-8"))
            tree.update(digest.encode("utf-8"))
        payload["tree_md5"] = tree.hexdigest()
        payload["tree_files"] = [[rel, digest] for rel, digest in ordered]
    return payload


def docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def probe_live_image(image: str) -> dict[str, Any]:
    output = run(["docker", "run", "--rm", "--entrypoint", "python", image, "-c", LIVE_PROBE_SCRIPT])
    for line in output.splitlines():
        if line.startswith(PROBE_MARKER):
            return json.loads(line[len(PROBE_MARKER):])
    raise SystemExit(f"image probe produced no {PROBE_MARKER} line for {image}:\n{output[-2000:]}")


def compare_probe(payload: dict[str, Any], version: str, repo_actions: list[str], source: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    probed_version = str(payload.get("runner_version") or "")
    where = payload.get("runner_version_path") or "/app/RUNNER_VERSION"
    if probed_version == version:
        results.append(check("package_image", "PASS", f"{source}: {where} = {version}"))
    else:
        results.append(check("package_image", "FAIL", f"{source}: {where}={probed_version!r} != {version!r}"))

    # US-28 门禁补洞：整个 runner 源码树的聚合指纹（actions.py 之外的 lease.py/main.py 等
    # 同样必须同源——只比 actions.py 会漏掉「改 lease.py 但版本号不变」这类能力漂移）。
    repo_tree, repo_files = repo_runner_tree_fingerprint()
    probed_tree = str(payload.get("tree_md5") or "")
    probed_files = {str(item[0]): str(item[1]) for item in (payload.get("tree_files") or []) if len(item) == 2}
    repo_map = {str(rel): str(digest) for rel, digest in repo_files}
    if probed_tree and probed_tree == repo_tree:
        results.append(
            check("package_image", "PASS", f"{source}: runner 源码树指纹 matches repo ({repo_tree}, {len(repo_files)} 个模块)")
        )
    elif not probed_tree:
        results.append(
            check(
                "package_image",
                "FAIL",
                f"{source}: 探针未提供 runner 源码树指纹，无法确认 lease.py/main.py 等模块与仓库同源",
            )
        )
    else:
        drift = sorted(
            name for name in set(repo_map) | set(probed_files) if repo_map.get(name) != probed_files.get(name)
        )
        results.append(
            check(
                "package_image",
                "FAIL",
                f"{source}: runner 源码树指纹 {probed_tree} != repo {repo_tree}；不一致模块：{', '.join(drift) or '(未知)'}",
            )
        )

    repo_md5 = md5_file(ACTIONS_FILE)
    probed_md5 = str(payload.get("actions_md5") or "")
    if probed_md5 == repo_md5:
        results.append(check("package_image", "PASS", f"{source}: actions.py md5 matches repo ({repo_md5})"))
    else:
        results.append(
            check(
                "package_image",
                "FAIL",
                f"{source}: actions.py md5 {probed_md5} != repo {repo_md5}（镜像非出自本仓库源码）",
            )
        )

    probed_actions = set(payload.get("actions") or [])
    missing = sorted(set(repo_actions) - probed_actions)
    extra = sorted(probed_actions - set(repo_actions))
    if missing or extra:
        results.append(check("package_image", "FAIL", f"{source}: action mismatch missing={missing} extra={extra}"))
    else:
        results.append(check("package_image", "PASS", f"{source}: action set matches repo ({len(repo_actions)} actions)"))
    return results


def check_dockerhub(version: str) -> dict[str, Any]:
    namespace, name = RUNNER_IMAGE_REPO.split("/", 1)
    url = DOCKERHUB_TAGS_API.format(namespace=namespace, name=name, tag=version)
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return check("dockerhub_tag", "FAIL", f"DockerHub tag {version} HTTP {error.code}（未推送）", url=url)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return check("dockerhub_tag", "FAIL", f"cannot query DockerHub: {error}", url=url)
    return check("dockerhub_tag", "PASS", f"DockerHub tag {version} exists (digest={payload.get('digest')})", url=url)


def verify(
    package: Path | None = None,
    image: str | None = None,
    check_hub: bool = False,
    live_probe: bool = False,
) -> dict[str, Any]:
    version = read_repo_runner_version()
    results: list[dict[str, Any]] = [check("repo_version", "PASS", f"RUNNER_VERSION = {version}")]

    repo_actions = parse_repo_actions()
    results.append(check("repo_actions", "PASS", f"{len(repo_actions)} actions from default_handlers()"))
    if REQUIRED_ACTION not in repo_actions:
        results.append(check("repo_actions", "FAIL", f"repo action table missing {REQUIRED_ACTION}（仓库动作表异常）"))
    results.extend(check_source_compose(version))

    if package is not None:
        manifest_results, archive_rel = check_package_manifest(package, version)
        results.extend(manifest_results)
        if archive_rel:
            payload = inspect_image_archive(read_image_archive_member(package, archive_rel))
            if payload.get("runner_version") is None or payload.get("actions_md5") is None:
                results.append(
                    check(
                        "package_image",
                        "FAIL",
                        "image archive does not expose /app RUNNER_VERSION or upgrade_runner/actions.py",
                    )
                )
            else:
                results.extend(compare_probe(payload, version, repo_actions, "package image"))
    elif image:
        results.append(check("package_image", "SKIP", f"live probe not requested for {image}"))
    else:
        results.append(check("package_image", "SKIP", "no --package/--image given"))

    if image:
        if not live_probe:
            results.append(check("live_image", "SKIP", "--live-probe not given"))
        elif not docker_available():
            results.append(check("live_image", "SKIP", "docker not available"))
        else:
            results.extend(compare_probe(probe_live_image(image), version, repo_actions, f"live image {image}"))

    if check_hub:
        results.append(check_dockerhub(version))
    else:
        results.append(check("dockerhub_tag", "SKIP", "pass --check-dockerhub to query DockerHub"))

    failures = [item for item in results if item["status"] == "FAIL"]
    skipped = [item for item in results if item["status"] == "SKIP"]
    return {
        "ok": not failures,
        "runner_version": version,
        "repo_action_count": len(repo_actions),
        "checks": results,
        "failures": [item["id"] for item in failures],
        "skipped": [item["id"] for item in skipped],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify runner delivery consistency across repo, component package and DockerHub."
    )
    parser.add_argument("--package", type=Path, help="runner component package (.tar.gz) to verify")
    parser.add_argument("--image", help="optionally live-probe an already-present image via docker")
    parser.add_argument("--live-probe", action="store_true", help="run the docker probe for --image")
    parser.add_argument("--check-dockerhub", action="store_true", help="query DockerHub tags API (needs network)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    result = verify(package=args.package, image=args.image, check_hub=args.check_dockerhub, live_probe=args.live_probe)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"runner delivery consistency: {result['runner_version']} ({'OK' if result['ok'] else 'FAILED'})")
        for item in result["checks"]:
            print(f"  [{item['status']:4}] {item['id']}: {item['detail']}")
        if result["failures"]:
            print(f"FAILED checks: {', '.join(sorted(set(result['failures'])))}")
        if result["skipped"]:
            print(f"skipped checks: {', '.join(sorted(set(result['skipped'])))}")
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
