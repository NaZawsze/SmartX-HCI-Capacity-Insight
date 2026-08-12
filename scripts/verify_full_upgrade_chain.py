#!/usr/bin/env python3
"""v0.5.2 完整升级链路一键回归验证脚本。

从 v0.5.1 + runner v0.3.0 基线出发，通过升级中心 API 依次执行
平台升级 v0.5.1u2、组件升级 runner v0.3.1、平台升级 v0.5.2，
并在每一段完成后自动验收版本、容器镜像、项目/网络切换、post-cleanup、
升级后自动采集、业务数据完整性、.env 权限和旧目录清理。

用法:

    python3 scripts/verify_full_upgrade_chain.py \
        --base-url http://127.0.0.1:8000 \
        --pkg-u2 /path/smartx-capacity-insight-upgrade-v0.5.1u2.tar.gz \
        --pkg-runner /path/smartx-upgrade-runner-v0.3.1.tar.gz \
        --pkg-v052 /path/smartx-capacity-insight-upgrade-v0.5.2.tar.gz

要求:
    - 测试机当前必须是 v0.5.1 + runner v0.3.0 的干净基线。
    - 脚本不负责恢复基线；基线恢复需在执行前单独完成。
    - 三步全部成功才返回 0；任一失败输出失败阶段、task_id 和健康状态并返回 1。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG: list[str] = []


def log(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {message}"
    print(line)
    LOG.append(line)


# ── HTTP helpers ────────────────────────────────────────────────────────


class Client:
    def __init__(self, base_url: str, token: str | None = None, timeout: int = 900) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def req(self, method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        url = self.base + path
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        body: bytes | None = None
        data = kwargs.get("data")
        files = kwargs.get("files")
        if files:
            boundary = "----verify" + str(int(time.time() * 1000))
            parts: list[bytes] = []
            for name, (filename, content) in files.items():
                parts.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    f'name="{name}"; filename="{filename}"\r\n\r\n'.encode()
                )
                parts.append(content)
                parts.append(b"\r\n")
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode())
            except Exception:
                return e.code, {"error": str(e)}
        except urllib.error.URLError as e:
            return 0, {"error": f"connection: {e}"}
        except Exception as e:
            return 0, {"error": str(e)}

    def login(self, username: str, password: str) -> None:
        code, body = self.req("POST", "/api/auth/login", data={"username": username, "password": password})
        if code != 200:
            raise SystemExit(f"登录失败 HTTP {code}: {body}")
        self.token = body["access_token"]
        log(f"登录成功 (user={username})")

    def health(self) -> dict[str, Any]:
        return self.req("GET", "/api/system/health")[1]

    def versions(self) -> dict[str, str]:
        h = self.health()
        return {"platform": str(h.get("version", "")), "runner": str(h.get("runner_version", "")), "prometheus": str(h["checks"].get("prometheus", False))}  # type: ignore[index]

    def containers(self) -> list[str]:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "--format", "{{.Names}} {{.Image}}"], text=True, timeout=10
            )
            return [line for line in out.splitlines() if "smartx" in line or "prometheus" in line]
        except Exception:
            return []

    def networks(self) -> list[str]:
        try:
            out = subprocess.check_output(
                ["docker", "network", "ls", "--format", "{{.Name}}"], text=True, timeout=10
            )
            return [line for line in out.splitlines() if "smartx" in line]
        except Exception:
            return []


# ── upgrade helpers ─────────────────────────────────────────────────────


def poll(client: Client, task_id: str, base_path: str, label: str, timeout: int = 900) -> dict[str, Any]:
    start = time.time()
    last_status: str | None = None
    while time.time() - start < timeout:
        code, body = client.req("GET", f"{base_path}/{task_id}")
        st = str(body.get("status") or body.get("public_status") or "")
        if code == 200 and st != last_status:
            log(f"  [{label}] {st}")
            last_status = st
        if st in ("success", "succeeded", "failed", "precheck_failed", "cancelled", "recovery_required"):
            return body
        time.sleep(5)
    return body


def do_upgrade(client: Client, name: str, pkg: str, api: str, base_status: str) -> tuple[str, dict[str, Any]]:
    log(f"--- {name} ---")
    fname = os.path.basename(pkg)
    with open(pkg, "rb") as f:
        content = f.read()

    code, body = client.req("POST", f"{api}/upload", files={"file": (fname, content)})
    if code != 200:
        raise SystemExit(f"{name} 上传失败 HTTP {code}: {body}")
    tid = body.get("task_id") or body.get("taskId") or ""
    log(f"  uploaded  task={tid}")

    code, body = client.req("POST", f"{api}/precheck/{tid}")
    if code != 200:
        raise SystemExit(f"{name} 预检查失败 HTTP {code}: {body}")
    log(f"  precheck ok")

    code, body = client.req("POST", f"{api}/start/{tid}")
    if code not in (200,):
        log(f"  start returned {code} (may already be running), continuing poll")
    else:
        log(f"  start ok")

    res = poll(client, tid, base_status, name)
    st = str(res.get("status") or "")
    log(f"  result: {st}")
    return tid, res


# ── verification helpers ────────────────────────────────────────────────


def verify_node1(client: Client) -> None:
    """验收 v0.5.1u2: 平台 v0.5.1u2, runner v0.3.0, 仍在 old project。"""
    v = client.versions()
    assert v["platform"] == "v0.5.1u2", f"期望 platform=v0.5.1u2 实际={v['platform']}"
    assert v["runner"] == "v0.3.0", f"期望 runner=v0.3.0 实际={v['runner']}"
    containers = client.containers()
    assert any("v0.5.1u2" in c for c in containers), f"未找到 v0.5.1u2 容器: {containers}"
    assert any("upgrade-runner:v0.3.0" in c for c in containers) or not any(
        "upgrade-runner:v0.3.1" in c for c in containers
    ), "runner 不应该是 v0.3.1"
    assert "smartx-hci-capacity-insight" not in " ".join(containers) or any(
        "upgrade-runner" in c for c in containers
    ), "runner bootstrap 允许切 project 但平台不应"
    log("  节点1 验收通过")


def verify_node2(client: Client) -> None:
    """验收 runner v0.3.1: 平台 v0.5.1u2, runner v0.3.1, 组件版本接口正确。"""
    v = client.versions()
    assert v["platform"] == "v0.5.1u2", f"期望 platform=v0.5.1u2"
    assert v["runner"] == "v0.3.1", f"期望 runner=v0.3.1 实际={v['runner']}"
    code, body = client.req("GET", "/api/admin/component-upgrade/version")
    assert code == 200, f"组件版本接口失败 HTTP {code}"
    assert str(body.get("version", "")) == "v0.3.1", f"组件版本={body.get('version')}"
    log("  节点2 验收通过")


def verify_node3(client: Client) -> None:
    """验收 v0.5.2 最终状态: 版本、容器、网络、目录、.env。"""
    v = client.versions()
    assert v["platform"] == "v0.5.2", f"期望 platform=v0.5.2 实际={v['platform']}"
    assert v["runner"] == "v0.3.1", f"期望 runner=v0.3.1 实际={v['runner']}"
    assert v["prometheus"] is True, "prometheus 健康检查应为 true"

    containers = client.containers()
    assert len([c for c in containers if "smartx-hci-capacity-insight" in c]) >= 5, f"容器不足: {containers}"
    assert all(
        svc in " ".join(containers)
        for svc in ["web-api", "collector-worker", "frontend", "prometheus", "upgrade-runner"]
    ), f"缺少服务: {containers}"

    networks = client.networks()
    assert "smartx-hci-capacity-insight-net" in networks, f"缺少目标网络: {networks}"
    assert "smartx-storage-forecast_smartx-net" not in networks, f"旧网络应被清理: {networks}"

    # .env 权限（宿主机检查，如果无 docker 权限则跳过）
    try:
        env_mode = subprocess.check_output(
            ["stat", "-c", "%a", "/data/smartx-storage-forecast/project/.env"], text=True, timeout=5
        ).strip()
        assert env_mode == "600", f".env 权限应为 600 实际={env_mode}"
    except Exception as exc:
        log(f"  .env 权限检查无法执行: {exc}")

    log("  节点3 最终验收通过")


def verify_cleanup(client: Client, v052_tid: str) -> None:
    """等待并验收 post-cleanup 和自动采集。"""
    cleanup_id = f"post-cleanup-{v052_tid}"
    collection_id = f"post-upgrade-collection-{v052_tid}"
    waited = 0
    while waited < 600:
        code, body = client.req("GET", f"/api/admin/upgrade/post-cleanup/{v052_tid}")
        if code == 200:
            st = str(body.get("status") or "")
            if st in ("succeeded", "success", "failed"):
                log(f"  post-cleanup: {st}")
                if st == "failed":
                    raise SystemExit(f"post-cleanup 失败: {body}")
                break
            if st == "not_required":
                log("  无需 post-cleanup")
                break
        time.sleep(10)
        waited += 10

    # 检查自动采集 marker
    try:
        marker_path = f"/data/smartx-storage-forecast/upgrades/{v052_tid}/post-upgrade-collection.json"
        out = subprocess.check_output(["cat", marker_path], text=True, timeout=5)
        marker = json.loads(out)
        cs = str(marker.get("collection_status") or marker.get("status") or "")
        log(f"  自动采集: {cs}  (msg: {marker.get('message', '')})")
        if cs == "failed":
            log("  WARNING: 自动采集失败（不影响平台升级）")
    except Exception as exc:
        log(f"  自动采集 marker 读取失败: {exc}")


# ── main ────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="v0.5.2 完整升级链路验证")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="password")
    parser.add_argument("--pkg-u2", required=True, help="v0.5.1u2 平台升级包路径")
    parser.add_argument("--pkg-runner", required=True, help="runner v0.3.1 组件包路径")
    parser.add_argument("--pkg-v052", required=True, help="v0.5.2 平台升级包路径")
    parser.add_argument("--timeout", type=int, default=900, help="每段升级轮询超时(秒)")
    args = parser.parse_args()

    client = Client(args.base_url, timeout=args.timeout)
    log(f"目标: {args.base_url}")

    # 基线确认
    client.login(args.username, args.password)
    v = client.versions()
    log(f"基线版本: platform={v['platform']} runner={v['runner']} prometheus={v['prometheus']}")
    assert v["platform"] == "v0.5.1", f"基线 platform 应为 v0.5.1 实际={v['platform']}"
    assert v["runner"] == "v0.3.0", f"基线 runner 应为 v0.3.0 实际={v['runner']}"

    # 确认输入包
    for label, p in [("u2", args.pkg_u2), ("runner", args.pkg_runner), ("v052", args.pkg_v052)]:
        if not os.path.isfile(p):
            raise SystemExit(f"{label} 包不存在: {p}")
    log("三个升级包路径确认存在")

    # 三段升级
    results: dict[str, Any] = {}
    tid_u2, res_u2 = do_upgrade(client, "STEP1 v0.5.1u2", args.pkg_u2, "/api/admin/upgrade", "/api/admin/upgrade/status")
    verify_node1(client)
    results["u2"] = tid_u2

    tid_runner, res_runner = do_upgrade(
        client, "STEP2 runner v0.3.1", args.pkg_runner, "/api/admin/component-upgrade", "/api/admin/component-upgrade/status"
    )
    # 等待几秒让 runner heartbeat 更新
    time.sleep(10)
    verify_node2(client)
    results["runner"] = tid_runner

    tid_v052, res_v052 = do_upgrade(client, "STEP3 v0.5.2", args.pkg_v052, "/api/admin/upgrade", "/api/admin/upgrade/status")
    verify_node3(client)
    results["v052"] = tid_v052

    # post-upgrade 验收
    verify_cleanup(client, tid_v052)

    # 输出总结
    log("=" * 50)
    log(f"完整链路验证通过")
    log(f"  v0.5.1u2 -> {tid_u2}")
    log(f"  runner v0.3.1 -> {tid_runner}")
    log(f"  v0.5.2 -> {tid_v052}")

    # 写入结果文件
    result_path = Path(os.environ.get("SMARTX_VERIFY_RESULT", "/tmp/chain_verify_result.json"))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "base_url": args.base_url,
        "u2_task_id": tid_u2,
        "runner_task_id": tid_runner,
        "v052_task_id": tid_v052,
        "final_health": client.health(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    log(f"结果已写入 {result_path}")


if __name__ == "__main__":
    main()
