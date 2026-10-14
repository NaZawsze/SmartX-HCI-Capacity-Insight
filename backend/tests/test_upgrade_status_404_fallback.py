"""#89 CLI 兜底门禁：upgrade.sh 对 status 快照缺失必须降级 health 轮询（2026-10-14）。

场景（`.12`/`.14` 跨机实测）：升级实际成功，但 post-cleanup 回收任务目录后
`GET /api/admin/upgrade/status/<id>` 返回 404「升级任务不存在。」——响应体没有
status 字段，轮询记 unknown 空转到 1800s 误报「超时未收敛」。

本文件两类锁定：
1. **行为**：从 upgrade.sh 抽出 `health_reports_target_version` 函数，用 stub 掉的
   curl 驱动——版本到达目标判收敛、未到达/不可达/目标未知都不判；
2. **静态**：轮询段必须有 unknown 兜底分支、超时后必须有最后一线、成功输出必须
   说明兜底判据、`--with-runner` 的清理等待在快照缺失时必须跳过。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = ROOT / "delivery" / "upgrade" / "upgrade.sh"


class Status404FallbackStaticLockTest(unittest.TestCase):
    """静态锁：兜底的四个接线点必须在位。"""

    @classmethod
    def setUpClass(cls):
        cls.text = UPGRADE_SH.read_text(encoding="utf-8")

    def test_helper_function_defined_before_poll_loop(self):
        self.assertIn("health_reports_target_version() {", self.text)
        self.assertLess(
            self.text.index("health_reports_target_version() {"),
            self.text.index("# ── 轮询 ──"),
            "兜底函数必须定义在轮询段之前",
        )

    def test_poll_loop_has_unknown_fallback(self):
        self.assertIn(
            'if [ "$STATUS" = "unknown" ] && health_reports_target_version; then',
            self.text,
            "轮询段缺少 unknown → health 兜底分支",
        )

    def test_timeout_has_last_chance_health_check(self):
        self.assertIn(
            'if [ -z "$FINAL_STATUS" ] && health_reports_target_version; then',
            self.text,
            "超时宣判前缺少最后一线 health 复核",
        )

    def test_success_output_explains_health_convergence(self):
        self.assertIn("CONVERGED_VIA_HEALTH", self.text)
        self.assertIn("任务终态快照缺失", self.text)

    def test_runner_cleanup_wait_skipped_when_snapshot_missing(self):
        self.assertIn("SKIP_CLEANUP_WAIT", self.text)
        self.assertIn(
            'while [ "$SKIP_CLEANUP_WAIT" -eq 0 ] && [ "$CLEANUP_WAITED" -lt "$POLL_TIMEOUT" ]; do',
            self.text,
            "清理等待循环必须可被 SKIP_CLEANUP_WAIT 跳过",
        )

    def test_poll_timeout_default_unchanged(self):
        self.assertIn("POLL_TIMEOUT=1800", self.text, "既有超时默认值不得被改动")

    def test_no_destructive_ops_introduced(self):
        # 只锁本文件关注的「不引入新危险操作」：脚本头注本身含 docker load 字样
        # （「本脚本不含 docker load…」的说明文字），不断言那一项（既有测试已锁）。
        self.assertNotIn("rm -rf", self.text)
        self.assertNotIn("docker rm", self.text)


class HealthReportsTargetVersionBehaviorTest(unittest.TestCase):
    """行为：抽取函数 + stub curl 驱动四种场景。"""

    def _run(self, *, target: str, body: str, health_url: str | None = None, stub_rc: int = 0):
        """驱动抽取出的函数；stub 把收到的参数写文件（函数内 `2>/dev/null` 会吞掉 stderr）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            func_file = Path(tmpdir) / "func.sh"
            text = UPGRADE_SH.read_text(encoding="utf-8")
            start = text.index("health_reports_target_version() {")
            end = text.index("\n}\n", start) + 3
            func_file.write_text(text[start:end], encoding="utf-8")
            args_file = Path(tmpdir) / "curl-args.txt"
            driver = Path(tmpdir) / "driver.sh"
            driver.write_text(
                "set -u\n"
                'TARGET_VERSION="$TT"\n'
                'HEALTH_URL="${HU:-http://127.0.0.1:8000/api/system/health}"\n'
                "curl() {\n"
                '  [ -n "${STUB_ARGS:+x}" ] && printf "ARGS:%s\\n" "$*" >> "$STUB_ARGS_FILE"\n'
                '  printf "%s" "$STUB_BODY"\n'
                f"  return {stub_rc}\n"
                "}\n"
                f"source {func_file}\n"
                "if health_reports_target_version; then echo CONVERGED; else echo NOT_CONVERGED; fi\n",
                encoding="utf-8",
            )
            env = {
                "PATH": "/usr/bin:/bin",
                "TT": target,
                "HU": health_url or "",
                "STUB_BODY": body,
                "STUB_RC": str(stub_rc),
                "STUB_ARGS": "1",
                "STUB_ARGS_FILE": str(args_file),
            }
            proc = subprocess.run(
                ["bash", str(driver)],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            args_text = args_file.read_text(encoding="utf-8") if args_file.exists() else ""
        return proc, args_text

    def test_version_reached_target_converges(self):
        proc, args_text = self._run(target="v0.5.4", body='{"ok":true,"version":"v0.5.4"}')
        self.assertEqual(proc.stdout.strip(), "CONVERGED", proc.stderr)
        self.assertIn("/api/system/health", args_text, "必须查 /api/system/health")

    def test_version_below_target_does_not_converge(self):
        proc, _ = self._run(target="v0.5.4", body='{"ok":true,"version":"v0.5.3"}')
        self.assertEqual(proc.stdout.strip(), "NOT_CONVERGED")

    def test_unreachable_health_does_not_converge(self):
        proc, _ = self._run(target="v0.5.4", body="", stub_rc=7)
        self.assertEqual(proc.stdout.strip(), "NOT_CONVERGED")

    def test_unknown_target_version_short_circuits(self):
        # 目标未知时不得调用 health（防止拿未知目标和任意版本误判）
        proc, args_text = self._run(target="unknown", body='{"version":"v0.9.9"}')
        self.assertEqual(proc.stdout.strip(), "NOT_CONVERGED")
        self.assertEqual(args_text, "", "目标 unknown 时不应调用 health")

    def test_custom_health_url_is_respected(self):
        proc, args_text = self._run(
            target="v0.5.4",
            body='{"version":"v0.5.4"}',
            health_url="http://127.0.0.1:9000/api/system/health",
        )
        self.assertEqual(proc.stdout.strip(), "CONVERGED")
        self.assertIn("127.0.0.1:9000/api/system/health", args_text)


if __name__ == "__main__":
    unittest.main()
