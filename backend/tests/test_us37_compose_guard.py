"""US-37 compose 变体守卫单测（设计 §5 的 T0–T3）。

守卫是纯 shell 脚本，用桩命令（stub）构造环境验证，不用真机。
T4–T6 需要真实 Docker，只能在 .14 上手工执行，不在本文件覆盖。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "delivery" / "compose-guard.sh"
MARKER_KEY = "SMARTX_COMPOSE_FILE_ACTIVE"

OFFLINE = "docker-compose.offline.yml"
MAIN = "docker-compose.yml"
PROJECT = "smartx-hci-capacity-insight"


def run_guard(func: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """source 守卫并调用一个函数，返回退出码与输出。"""
    script = f'source "{GUARD}"\n{func} "$@"\nexit $?\n'
    return subprocess.run(
        ["bash", "-c", script, "_", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def run_standalone(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(GUARD), *args], capture_output=True, text=True, check=False
    )


class GuardPresenceTest(unittest.TestCase):
    def test_guard_exists_and_is_valid(self) -> None:
        self.assertTrue(GUARD.is_file(), "缺少 delivery/compose-guard.sh")
        completed = subprocess.run(
            ["bash", "-n", str(GUARD)], capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, f"语法错误：{completed.stderr}")

    def test_guard_is_self_contained(self) -> None:
        """交付目录没有 lib/，守卫绝不能 source 外部库。"""
        text = GUARD.read_text(encoding="utf-8")
        sources = re.findall(r"^\s*(?:source|\.)\s+(\S+)", text, re.M)
        # 唯一允许的 source 是独立执行模式的自引用检测（BASH_SOURCE）
        self.assertEqual(
            [s for s in sources if "BASH_SOURCE" not in s],
            [],
            f"守卫不得 source 外部文件，实际发现：{sources}",
        )
        self.assertNotIn("lib/common.sh", text, "守卫不得依赖 ops/lib/common.sh")

    def test_guard_never_sources_env_file(self) -> None:
        """.env 是任意内容执行面，只能 sed 读，绝不能 source/eval。"""
        text = GUARD.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotRegex(
                stripped,
                r"^\s*(source|\.)\s+\S*ENV",
                f"不得 source .env：{stripped}",
            )
            self.assertNotIn("eval ", stripped, f"不得 eval .env：{stripped}")


class GuardMarkerTest(unittest.TestCase):
    """标记的读写。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env_file = self.base / ".env"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, content: str) -> None:
        self.env_file.write_text(content, encoding="utf-8")
        os.chmod(self.env_file, 0o600)

    def test_reads_marker(self) -> None:
        self._write(f"A=1\n{MARKER_KEY}={OFFLINE}\nB=2\n")
        result = run_guard("compose_guard_marker", str(self.env_file))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), OFFLINE)

    def test_missing_marker_reads_empty(self) -> None:
        self._write("A=1\nB=2\n")
        result = run_guard("compose_guard_marker", str(self.env_file))
        self.assertEqual(result.stdout.strip(), "")

    def test_quoted_value_is_unwrapped(self) -> None:
        self._write(f'{MARKER_KEY}="{OFFLINE}"\n')
        result = run_guard("compose_guard_marker", str(self.env_file))
        self.assertEqual(result.stdout.strip(), OFFLINE)

    def test_write_appends_when_absent(self) -> None:
        self._write("A=1\nB=2\n")
        result = run_guard("compose_guard_write", str(self.env_file), OFFLINE)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.env_file.read_text(encoding="utf-8")
        self.assertIn(f"{MARKER_KEY}={OFFLINE}", text)
        self.assertIn("A=1", text)
        self.assertIn("B=2", text)

    def test_write_replaces_in_place(self) -> None:
        self._write(f"A=1\n{MARKER_KEY}={MAIN}\nB=2\n")
        run_guard("compose_guard_write", str(self.env_file), OFFLINE)
        lines = self.env_file.read_text(encoding="utf-8").splitlines()
        marker_lines = [ln for ln in lines if ln.startswith(f"{MARKER_KEY}=")]
        self.assertEqual(len(marker_lines), 1, f"标记应只有一行，实际 {marker_lines}")
        self.assertEqual(marker_lines[0], f"{MARKER_KEY}={OFFLINE}")
        # 原有内容不能丢
        self.assertIn("A=1", lines)
        self.assertIn("B=2", lines)

    def test_write_appends_to_file_without_trailing_newline(self) -> None:
        """原文件末尾无换行时，追加不能与最后一行粘连。"""
        self._write("A=1")
        run_guard("compose_guard_write", str(self.env_file), OFFLINE)
        lines = self.env_file.read_text(encoding="utf-8").splitlines()
        self.assertIn("A=1", lines)
        self.assertIn(f"{MARKER_KEY}={OFFLINE}", lines)

    def test_write_preserves_permissions(self) -> None:
        """.env 是 0600，改完不能被放宽。"""
        self._write("A=1\n")
        os.chmod(self.env_file, 0o600)
        run_guard("compose_guard_write", str(self.env_file), OFFLINE)
        mode = self.env_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f".env 权限被改动：{oct(mode)}")

    def test_basename_normalisation(self) -> None:
        """绝对路径与相对文件名要能比较（调用方可能传完整路径）。"""
        result = run_guard("_cg_basename", f"/data/smartx/project/{OFFLINE}")
        self.assertEqual(result.stdout.strip(), OFFLINE)


class GuardCheckTest(unittest.TestCase):
    """T1–T3：放行 / 拒绝。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env_file = self.base / ".env"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, content: str) -> None:
        self.env_file.write_text(content, encoding="utf-8")

    def test_t2_matching_marker_passes(self) -> None:
        self._write(f"{MARKER_KEY}={OFFLINE}\n")
        result = run_guard(
            "compose_guard_check", str(self.env_file), OFFLINE, PROJECT
        )
        self.assertEqual(result.returncode, 0, f"一致时应放行：{result.stderr}")

    def test_t2_absolute_path_also_passes(self) -> None:
        self._write(f"{MARKER_KEY}={OFFLINE}\n")
        result = run_guard(
            "compose_guard_check", str(self.env_file), f"/data/x/{OFFLINE}", PROJECT
        )
        self.assertEqual(result.returncode, 0, "取 basename 后应视为一致")

    def test_t3_mismatch_is_rejected(self) -> None:
        self._write(f"{MARKER_KEY}={OFFLINE}\n")
        result = run_guard(
            "compose_guard_check", str(self.env_file), MAIN, PROJECT
        )
        self.assertEqual(result.returncode, 2, f"不一致必须拒绝：{result.stdout}")
        output = result.stdout + result.stderr
        self.assertIn(OFFLINE, output, "提示必须包含当前实际使用的 compose")
        self.assertIn(MAIN, output, "提示必须包含你要用的 compose")

    def test_t3_explains_consequence(self) -> None:
        """拒绝时必须说清后果，否则用户会以为只是形式检查。"""
        self._write(f"{MARKER_KEY}={OFFLINE}\n")
        result = run_guard("compose_guard_check", str(self.env_file), MAIN, PROJECT)
        output = result.stdout + result.stderr
        self.assertIn("recreate", output)
        self.assertIn("137", output)

    def test_t3_offers_three_paths(self) -> None:
        self._write(f"{MARKER_KEY}={OFFLINE}\n")
        result = run_guard("compose_guard_check", str(self.env_file), MAIN, PROJECT)
        output = result.stdout + result.stderr
        self.assertIn("--force-compose-switch", output, "必须给出显式切换的选项")
        self.assertIn("down", output, "必须给出先停机的选项")

    def test_t1_absent_marker_passes_with_warning(self) -> None:
        """向后兼容：旧环境没标记不能被拦死，但要提醒。"""
        self._write("A=1\n")
        result = run_guard("compose_guard_check", str(self.env_file), OFFLINE, PROJECT)
        self.assertEqual(result.returncode, 0, f"无标记应放行：{result.stderr}")
        output = result.stdout + result.stderr
        self.assertIn(MARKER_KEY, output, "必须提示无法判定")
        self.assertIn("install.sh", output, "必须告诉用户怎么补标记")

    def test_t1_missing_env_file_passes(self) -> None:
        result = run_guard(
            "compose_guard_check", str(self.base / "nope.env"), OFFLINE, PROJECT
        )
        self.assertEqual(result.returncode, 0, "文件不存在按无法判定处理，放行")


class GuardResolveTest(unittest.TestCase):
    """T0：标记回填取自地面真相（容器标签），不是脚本的猜测。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env_file = self.base / ".env"
        self.env_file.write_text("A=1\n", encoding="utf-8")
        os.chmod(self.env_file, 0o600)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _docker_stub(self, cid: str, config_files: str, running: bool = True) -> dict[str, str]:
        """造一个 docker 桩，模拟运行中容器的 compose 标签。"""
        bindir = self.base / "bin"
        bindir.mkdir(exist_ok=True)
        path = bindir / "docker"
        path.write_text(
            "#!/bin/sh\n"
            'case "$1 $2" in\n'
            f'  "ps --quiet") {"echo %s; exit 0" % cid if running else "exit 0"} ;;\n'
            "esac\n"
            'if [ "$1" = "inspect" ]; then\n'
            f"  printf '%s\\n' '{config_files}'\n"
            "  exit 0\n"
            "fi\n"
            "exit 1\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
        return env

    def test_t0_existing_marker_is_kept(self) -> None:
        self.env_file.write_text(f"{MARKER_KEY}={OFFLINE}\n", encoding="utf-8")
        env = self._docker_stub("cid123", f"/data/p/{MAIN}")
        result = run_guard(
            "compose_guard_resolve", str(self.env_file), PROJECT, OFFLINE, env=env
        )
        self.assertEqual(result.stdout.strip(), OFFLINE, "已有标记不得被覆盖")
        self.assertIn(f"{MARKER_KEY}={OFFLINE}", self.env_file.read_text(encoding="utf-8"))

    def test_t0_backfills_from_container_label(self) -> None:
        """无标记但服务在跑 → 取容器标签，**不是**脚本要用的那份。"""
        env = self._docker_stub("cid123", f"/data/smartx/project/{MAIN}")
        result = run_guard(
            "compose_guard_resolve", str(self.env_file), PROJECT, OFFLINE, env=env
        )
        self.assertEqual(
            result.stdout.strip(),
            MAIN,
            f"必须取地面真相 {MAIN}，实际得到 {result.stdout.strip()!r}",
        )
        self.assertIn(f"{MARKER_KEY}={MAIN}", self.env_file.read_text(encoding="utf-8"))

    def test_t0_falls_back_to_requested_when_no_container(self) -> None:
        """无标记且无容器 → 没有 recreate 风险，用本次要启动的那份。"""
        env = self._docker_stub("cid123", "", running=False)
        result = run_guard(
            "compose_guard_resolve", str(self.env_file), PROJECT, OFFLINE, env=env
        )
        self.assertEqual(result.stdout.strip(), OFFLINE)
        self.assertIn(f"{MARKER_KEY}={OFFLINE}", self.env_file.read_text(encoding="utf-8"))

    def test_t0_backfill_works_without_docker(self) -> None:
        """没有 docker 命令时不能崩，退回本次要用的 compose。"""
        # 只屏蔽 docker（保留 bash 与 coreutils，否则 shell 自身都起不来）
        bindir = self.base / "nodocker-bin"
        bindir.mkdir(exist_ok=True)
        env = dict(os.environ)
        env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
        result = run_guard(
            "compose_guard_resolve", str(self.env_file), PROJECT, OFFLINE, env=env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), OFFLINE)


class GuardStandaloneTest(unittest.TestCase):
    """独立执行模式（客户诊断用）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env_file = self.base / ".env"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_show_prints_marker(self) -> None:
        self.env_file.write_text(f"{MARKER_KEY}={OFFLINE}\n", encoding="utf-8")
        result = run_standalone("show", str(self.env_file))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), OFFLINE)

    def test_show_absent_marker_exits_nonzero(self) -> None:
        self.env_file.write_text("A=1\n", encoding="utf-8")
        result = run_standalone("show", str(self.env_file))
        self.assertNotEqual(result.returncode, 0)

    def test_check_exit_codes(self) -> None:
        self.env_file.write_text(f"{MARKER_KEY}={OFFLINE}\n", encoding="utf-8")
        self.assertEqual(
            run_standalone("check", str(self.env_file), OFFLINE, PROJECT).returncode, 0
        )
        self.assertEqual(
            run_standalone("check", str(self.env_file), MAIN, PROJECT).returncode, 2
        )

    def test_unknown_action_fails(self) -> None:
        self.assertEqual(run_standalone("bogus").returncode, 1)


if __name__ == "__main__":
    unittest.main()


class GuardWiringTest(unittest.TestCase):
    """交付态接线：守卫必须真的被 install.sh / upgrade.sh 用上。

    背景：2026-09-30 有过「21 例单测全绿、真机因条件极性写反完全不生效」。
    守卫如果只是躺在交付目录里而没接进脚本，等于没有防护——
    所以这里静态锁定接线本身。
    """

    def setUp(self) -> None:
        self.install = (ROOT / "delivery" / "install" / "install.sh").read_text(encoding="utf-8")
        self.upgrade = (ROOT / "delivery" / "upgrade" / "upgrade.sh").read_text(encoding="utf-8")

    def test_install_loads_guard(self) -> None:
        self.assertIn("compose-guard.sh", self.install, "install.sh 必须加载守卫")

    def test_install_resolves_marker_before_idempotency_exit(self) -> None:
        """标记回填必须在幂等 exit 之前，否则旧环境永远补不上（.3 事故现场）。"""
        resolve_at = self.install.find("compose_guard_resolve")
        exit_at = self.install.find('info "本次不做任何修改')
        self.assertNotEqual(resolve_at, -1, "install.sh 必须回填标记")
        self.assertNotEqual(exit_at, -1, "未找到幂等检查的 exit 分支")
        self.assertLess(
            resolve_at, exit_at,
            "标记回填必须早于幂等 exit——已有 .env 的实例会在那里直接退出，"
            "放到之后就对最需要保护的现场失效",
        )

    def test_install_checks_guard_before_compose_up(self) -> None:
        check_at = self.install.find("compose_guard_check")
        up_at = self.install.find("compose_cmd up -d")
        self.assertNotEqual(check_at, -1, "install.sh 必须在 compose up 前调守卫")
        self.assertNotEqual(up_at, -1, "未找到 compose up 调用")
        self.assertLess(check_at, up_at, "守卫必须在 compose up 之前")

    def test_install_supports_force_switch(self) -> None:
        self.assertIn("--force-compose-switch", self.install, "缺少 --force-compose-switch 选项")
        self.assertIn("compose_guard_down_then_switch", self.install, "必须实现先 down 再换")

    def test_upgrade_uses_guard_readonly(self) -> None:
        self.assertIn("compose-guard.sh", self.upgrade, "upgrade.sh 必须带守卫诊断")
        self.assertIn("compose_guard_marker", self.upgrade, "upgrade.sh 应只读标记")
        self.assertNotIn("compose_guard_check", self.upgrade,
                         "upgrade.sh 不得做守卫判定——那会阻断旧环境升级")

    def test_upgrade_gains_no_compose_operations(self) -> None:
        """upgrade.sh 原有单测静态锁定「不含 compose 操作」，守卫不得破坏它。"""
        import re as _re
        offenders = [
            ln for ln in self.upgrade.splitlines()
            if _re.search(r"docker\s+compose|compose\s+(up|down)\b", ln)
            and not ln.strip().startswith("#")
        ]
        self.assertEqual(offenders, [], f"upgrade.sh 不得含 compose 操作：{offenders}")

    def test_delivery_builder_ships_guard_twice(self) -> None:
        """交付目录无 lib/，守卫必须自包含地进 install/ 与 upgrade/。"""
        builder = (ROOT / "scripts" / "build_offline_delivery.py").read_text(encoding="utf-8")
        self.assertIn('"install/compose-guard.sh"', builder)
        self.assertIn('"upgrade/compose-guard.sh"', builder)
