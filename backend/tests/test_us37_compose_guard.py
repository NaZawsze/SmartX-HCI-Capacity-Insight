"""US-37 compose 变体守卫单测（设计 §5 的 T0–T3）。

守卫是纯 shell 脚本，用桩命令（stub）构造环境验证，不用真机。
T4–T6 需要真实 Docker，只能在 .14 上手工执行，不在本文件覆盖。
"""

from __future__ import annotations

import os
import re
import shutil
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
    # 用绝对路径的 bash：调用方可能把 PATH 极简化到连 bash 都找不到
    bash = shutil.which("bash") or "/bin/bash"
    return subprocess.run(
        [bash, "-c", script, "_", *args],
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
        # 必须用 exit 127 的同名桩抢在真实 docker 前面。
        # 只 prepend 一个空目录**挡不住** /usr/bin/docker——在 10.20.11.3 上
        # 实测会命中真实 docker，读到真机在跑的 compose 变体而失败；
        # 本地 macOS 没有 docker 才碰巧通过。
        bindir = self.base / "nodocker-bin"
        bindir.mkdir(exist_ok=True)
        stub = bindir / "docker"
        stub.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
        stub.chmod(0o755)
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

    def test_install_never_gates_guard_on_variable_expansion(self) -> None:
        """守卫函数名当变量展开 = 恒空 = 防护整体失效。

        背景：2026-09-30 .14 实测抓到——install.sh 用
        `[ -n \"\\${compose_guard_check:-}\" ]` 判断守卫是否可用，但守卫加载的是
        **函数**不是变量，参数展开恒为空，守卫判定/标记回填/标记写入三个分支
        **从未执行过**。36 例静态单测全绿、真机全死，与 2026-09-30
        「21 例单测全绿、条件极性写反」是同一类教训。
        """
        import re as _re
        code_lines = [ln for ln in self.install.splitlines() if not ln.strip().startswith("#")]
        offenders = _re.findall(r"\$\{compose_guard_[A-Za-z_]+[:-]", "\n".join(code_lines))
        self.assertEqual(
            offenders, [],
            f"install.sh 不得用变量展开判断守卫函数（函数不是变量，恒为假）：{offenders}",
        )
        for fn in ("compose_guard_resolve", "compose_guard_write", "compose_guard_check"):
            self.assertRegex(
                self.install, rf"declare -F {fn} ",
                f"调用 {fn} 的分支必须用 declare -F 验证函数存在",
            )

    def test_guard_functions_satisfies_declare_f_at_runtime(self) -> None:
        """行为级：真实守卫文件 source 后，declare -F 必须认得出全部入口函数。

        上一个测试锁「写法」，本测试锁「写法在真实守卫上真的为真」——
        防止将来函数改名后 declare -F 静默失配，守卫又整体哑火。
        """
        import subprocess
        guard = ROOT / "delivery" / "compose-guard.sh"
        script = (
            f'. "{guard}"; '
            "for fn in compose_guard_marker compose_guard_detect_running "
            "compose_guard_write compose_guard_resolve compose_guard_check "
            "compose_guard_down_then_switch; do "
            'declare -F "$fn" >/dev/null || echo "MISSING:$fn"; done; echo DONE'
        )
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, f"守卫加载失败：{proc.stderr}")
        self.assertIn("DONE", proc.stdout)
        self.assertNotIn("MISSING:", proc.stdout, proc.stdout)

    def test_install_writes_marker_into_generated_env(self) -> None:
        """T5：全新安装结束后 .env 必须含 SMARTX_COMPOSE_FILE_ACTIVE。

        背景：2026-09-30 验证期发现——compose_guard_resolve 只在「已有 .env」时
        执行，而全新安装的 .env 由模板重新生成、天然不含标记；若生成后不补写，
        装完的 .env 永远没有标记，守卫对全新环境只能走无标记放行分支。
        """
        self.assertIn(
            "${RESOLVED_COMPOSE:-$COMPOSE_FILE}", self.install,
            "标记值必须用 RESOLVED_COMPOSE（重装时的地面真相），全新安装才退到本次待用变体",
        )
        write_at = self.install.find('compose_guard_write "$ENV_FILE"')
        gen_at = self.install.find('printf \'%s\\n\' "$ENV_CONTENT" > "$ENV_FILE"')
        check_at = self.install.find("compose_guard_check")
        self.assertNotEqual(write_at, -1, "install.sh 必须在生成 .env 后写入标记")
        self.assertNotEqual(gen_at, -1)
        self.assertNotEqual(check_at, -1)
        self.assertLess(gen_at, write_at, "标记必须写在 .env 生成之后")
        self.assertLess(write_at, check_at,
                        "标记必须写在守卫判定之前——--force-env 重装路径才受变体不一致判定保护")

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


class GuardInstallationTest(unittest.TestCase):
    """文档写的诊断路径必须真实存在。

    背景：troubleshooting §10 与 delivery/README §9.1 都在指引客户执行
    `/data/smartx-storage-forecast/project/compose-guard.sh`。
    但守卫原本只从**交付目录**被 source，交付目录会被客户挪走或删除——
    文档指向的路径根本不存在，等于给了客户一条跑不通的命令。
    交付目录移走后，project 目录才是长期驻留的那一个。
    """

    def test_install_copies_guard_into_project_dir(self) -> None:
        install = (ROOT / "delivery" / "install" / "install.sh").read_text(encoding="utf-8")
        self.assertRegex(
            install,
            r'install\s+-m\s+0?755\s+"\$COMPOSE_GUARD"\s+"\$PROJECT_DIR/compose-guard\.sh"',
            "install.sh 必须把守卫以 755 装进 PROJECT_DIR",
        )

    def test_documented_paths_are_produced(self) -> None:
        """文档与脚本提到的守卫路径必须一致（都是 project 目录）。"""
        install = (ROOT / "delivery" / "install" / "install.sh").read_text(encoding="utf-8")
        docs = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
        readme = (ROOT / "delivery" / "README.md").read_text(encoding="utf-8")
        expected = "/data/smartx-storage-forecast/project/compose-guard.sh"
        self.assertIn(expected, docs, "troubleshooting 必须给出可执行的守卫路径")
        self.assertIn(expected, readme, "交付包 README 必须给出可执行的守卫路径")
        # 脚本里用 $PROJECT_DIR 拼出来的路径，默认 install-root 下必须等于文档写的那个
        self.assertIn('"$PROJECT_DIR/compose-guard.sh"', install)
