"""`.env` 变更重建影响面守卫（US-42，设计 §3.4）。

起因（2026-10-04 `.14` 实测）：为验证磁盘告警真机触发，改了 `.env` 的告警阈值后
执行 `docker compose up -d collector-worker`（**只指定一个服务**），结果
`prometheus` 容器也被重建（ID `f260269773da7` → `45db5a1273dc`）。

两因叠加：
1. `collector-worker` 用 `env_file: [.env]`，Compose 的 config-hash 计入 `.env` **内容**；
2. `collector-worker` 有 `depends_on: [prometheus]`，`up -d <单个服务>` 会把依赖
   纳入操作范围。

当次无故障（TSDB 存活、`/-/healthy` 200、restart 全 0），但与 2026-09-30 `.3` 事故
（意外 recreate 打死运行中容器）同属一类——**事前无人知晓**才是真正的成本。

本文件覆盖设计 §6 第 12 项的三态：未变放行 / 变更拦截 / 确认后放行，
外加两条防回归：依赖闭包解析正确、守卫自身标记键不触发自激循环。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "delivery" / "compose-guard.sh"
SHA_KEY = "SMARTX_ENV_FILE_SHA256"
PROJECT = "smartx-hci-capacity-insight"

# 真实 offline compose 的 collector-worker / prometheus 片段（依赖关系的最小充分集）
COMPOSE_FIXTURE = """services:
  web-api:
    image: example/web-api:v0.5.3
    env_file:
      - .env
  collector-worker:
    image: example/collector-worker:v0.5.3
    env_file:
      - .env
    depends_on:
      - prometheus
  frontend:
    image: example/frontend:v0.5.3
  prometheus:
    image: prom/prometheus:v2.55.1
"""


def run_env_check(*args: str) -> subprocess.CompletedProcess:
    bash = shutil.which("bash") or "/bin/bash"
    return subprocess.run(
        [bash, str(GUARD), "env-check", *args],
        capture_output=True,
        text=True,
        check=False,
    )


class EnvChangeGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = root / ".env"
        self.compose = root / "docker-compose.offline.yml"
        self.compose.write_text(COMPOSE_FIXTURE, encoding="utf-8")
        self.env.write_text(
            "SMARTX_ADMIN_USER=admin\nSMARTX_COMPOSE_FILE_ACTIVE=docker-compose.offline.yml\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _check(self, *extra: str) -> subprocess.CompletedProcess:
        return run_env_check(
            str(self.env), str(self.compose), "collector-worker", PROJECT, *extra
        )

    def _first_run_records_baseline(self) -> None:
        result = self._check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(SHA_KEY, self.env.read_text(encoding="utf-8"))

    def test_first_run_records_baseline_and_passes(self) -> None:
        """既有安装（无该键）首次运行必须放行并写入基线，不得阻断存量环境。"""
        result = self._check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(SHA_KEY, self.env.read_text(encoding="utf-8"))
        self.assertIn("已记录", result.stderr)

    def test_unchanged_env_passes_silently(self) -> None:
        """未变更时静默放行——告警不能变成日常噪音。"""
        self._first_run_records_baseline()
        result = self._check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip(), "", "未变更时不应有任何输出")

    def test_changed_env_is_rejected_and_lists_impact(self) -> None:
        """变更未确认时拦截，并列出依赖闭包。"""
        self._first_run_records_baseline()
        with self.env.open("a", encoding="utf-8") as fh:
            fh.write("SMARTX_ADMIN_PASSWORD=changed\n")

        result = self._check()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn(".env 已变更", result.stderr)
        self.assertIn("collector-worker", result.stderr)
        self.assertIn("prometheus", result.stderr)
        self.assertIn("连带重建", result.stderr)
        self.assertIn("--env-change-ack", result.stderr)

    def test_ack_refreshes_baseline_and_passes(self) -> None:
        """显式确认后放行并刷新基线。"""
        self._first_run_records_baseline()
        with self.env.open("a", encoding="utf-8") as fh:
            fh.write("SMARTX_ADMIN_PASSWORD=changed\n")

        acked = self._check("--env-change-ack")
        self.assertEqual(acked.returncode, 0, acked.stderr)
        self.assertIn("已确认", acked.stderr)

        again = self._check()
        self.assertEqual(again.returncode, 0, "确认后基线应已刷新")
        self.assertEqual(again.stderr.strip(), "")

    def test_guard_marker_keys_do_not_trigger_false_alarm(self) -> None:
        """只改守卫自身的标记键不得报「.env 已变更」——否则自激循环。"""
        self._first_run_records_baseline()
        subprocess.run(
            [shutil.which("bash") or "/bin/bash", str(GUARD), "write", str(self.env), "docker-compose.offline.yml"],
            capture_output=True,
            text=True,
            check=False,
        )
        result = self._check()
        self.assertEqual(result.returncode, 0, f"守卫自身写标记不应触发告警：{result.stderr}")

    def test_depends_on_parsing_is_per_service(self) -> None:
        """依赖解析必须按服务区分：web-api 无依赖，不应被算进闭包。"""
        self._first_run_records_baseline()
        with self.env.open("a", encoding="utf-8") as fh:
            fh.write("SMARTX_TOWER_URL=https://example\n")

        result = self._check()
        self.assertEqual(result.returncode, 3)
        # web-api 不在 collector-worker 的依赖链里
        self.assertNotIn("web-api", result.stderr)

    def test_env_sha_excludes_guard_keys(self) -> None:
        """env-sha 入口：记录值与当前值在首次写入后应相等。"""
        bash = shutil.which("bash") or "/bin/bash"
        self._first_run_records_baseline()
        out = subprocess.run(
            [bash, str(GUARD), "env-sha", str(self.env)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        recorded = [l for l in out.splitlines() if l.startswith("记录=")][0].split("=", 1)[1]
        current = [l for l in out.splitlines() if l.startswith("当前=")][0].split("=", 1)[1]
        self.assertEqual(recorded, current)
        self.assertEqual(len(recorded), 64, "应为 sha256 十六进制")


if __name__ == "__main__":
    unittest.main()
