"""仓库文档范围门禁（`scripts/verify_repo_doc_scope.py`）的回归锁。

背景（用户 2026-10-21）：「用于内部开发的文档都不要提交了吧，仓库本来就是只用来放代码的」。
仓库曾经累积 151 个 Markdown，其中 128 个是设计稿/计划/工作日志/台账/交接文档。

这里锁住的不是「某个具体文件在不在」，而是**门禁本身的灵敏度**——
用临时目录构造伪造仓库，验证六种坏状态各自必须 FAIL：

1. 新增未登记的 .md → FAIL；
2. 内部文档被重新加回版本控制 → FAIL；
3. 门禁夹具被删 → FAIL；
4. .gitignore 漏掉内部模式 → FAIL；
5. 受控文档链接指向未受控文档（死链）→ FAIL；
6. 内部活动文档链接指向不存在的文件 → FAIL（归档目录冻结，不追溯）。

另外锁死两条「不许退回去」的口径：
- `TRACKED_DOCS` / `REQUIRED_DOCS` 的包含关系（必需项必须仍在白名单内）；
- 内部模式清单必须覆盖 `docs/superpowers/`、根目录三件工作文档、各台账。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "scripts" / "verify_repo_doc_scope.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("verify_repo_doc_scope", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RepoDocScopeUnitTest(unittest.TestCase):
    """清单自洽性：不依赖磁盘与 git 的纯逻辑断言。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = _load_gate()

    def test_required_is_subset_of_tracked(self) -> None:
        extra = self.gate.REQUIRED_DOCS - self.gate.TRACKED_DOCS
        self.assertEqual(extra, frozenset(), f"必需要有项不在白名单里：{sorted(extra)}")

    def test_gitignore_required_is_subset_of_internal_or_tracked_related(self) -> None:
        # .gitignore 要覆盖的模式不能在白名单里（否则「忽略又提交」自相矛盾）
        clash = set(self.gate.GITIGNORE_REQUIRED) & self.gate.TRACKED_DOCS
        self.assertEqual(clash, set(), f"同一路径既被忽略又允许提交：{sorted(clash)}")

    def test_internal_patterns_cover_known_internal_dirs(self) -> None:
        patterns = " ".join(p for p, _ in self.gate.INTERNAL_PATTERNS)
        for token in ("docs/superpowers/", "docs/archive/", "progress", "findings", "task_plan", "pending-tasks"):
            self.assertIn(token, patterns, f"内部模式清单缺少 {token}")

    def test_customer_docs_are_tracked(self) -> None:
        """客户会看的文档必须在白名单里，否则会被「清理」掉。"""
        for path in (
            "README.md",
            "README.zh-CN.md",
            "delivery/README.md",
            "docs/deployment.md",
            "docs/deployment.zh-CN.md",
            "docs/usage.md",
            "docs/troubleshooting.md",
            "docs/releases/CHANGELOG.md",
        ):
            self.assertIn(path, self.gate.TRACKED_DOCS, f"{path} 是客户文档，不该被移出")


    def test_allowlist_is_loaded_from_txt(self) -> None:
        """白名单唯一事实源 = 仓库根 PUSH_ALLOWLIST.txt（不再在代码里维护第二份）。"""
        self.assertTrue(
            (ROOT / "PUSH_ALLOWLIST.txt").is_file(),
            "缺少 PUSH_ALLOWLIST.txt（推送清单的唯一事实源）",
        )
        self.assertTrue(self.gate.TRACKED_DOCS, "白名单解析为空——门禁会静默放行")
        self.assertTrue(self.gate.TRACKED_SCRIPTS, "脚本白名单解析为空")

    def test_allowlist_parses_inline_comments(self) -> None:
        """行尾注释不得被当成路径的一部分。"""
        tmp = Path(tempfile.mkdtemp(prefix="allow-"))
        try:
            target = tmp / "PUSH_ALLOWLIST.txt"
            target.write_text(
                "[docs]\nREADME.md    # 根说明\n\n[scripts]\nops/install.sh  # 安装入口\n",
                encoding="utf-8",
            )
            docs, scripts = self.gate.load_allowlist(target)
            self.assertEqual(docs, frozenset({"README.md"}))
            self.assertEqual(scripts, frozenset({"ops/install.sh"}))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_allowlist_missing_returns_empty(self) -> None:
        """清单缺失时返回空集合（而非静默放行全部）。"""
        docs, scripts = self.gate.load_allowlist(Path("/nonexistent/PUSH_ALLOWLIST.txt"))
        self.assertEqual((docs, scripts), (frozenset(), frozenset()))



class RepoDocScopeGateTest(unittest.TestCase):
    """在临时目录构造伪造仓库，验证门禁真的会 FAIL。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="docscope-"))
        self.gate = _load_gate()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _init_repo(self, files: dict[str, str], gitignore: str = "") -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        for rel, text in files.items():
            target = self.tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        (self.tmp / ".gitignore").write_text(gitignore, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.tmp, check=True)

    def _run(self) -> dict:
        # 让门禁在临时仓库里跑：替换 ROOT / GITIGNORE
        original_root = self.gate.ROOT
        original_ignore = self.gate.GITIGNORE
        try:
            self.gate.ROOT = self.tmp
            self.gate.GITIGNORE = self.tmp / ".gitignore"
            checks = self.gate.check()
        finally:
            self.gate.ROOT = original_root
            self.gate.GITIGNORE = original_ignore
        return {c["name"]: c for c in checks}

    def test_clean_state_passes(self) -> None:
        # 只提交白名单里的一个文件，且该文件不需要 REQUIRED_DOCS 全在
        # （required_docs_exist 会报缺失，属预期——所以这里只断言链接检查通过）
        self._init_repo(
            {"README.md": "# t\n", ".gitignore": "docs/superpowers/\n"},
            gitignore="docs/superpowers/\n",
        )
        checks = self._run()
        self.assertTrue(checks["no_unlisted_tracked_docs"]["ok"])
        self.assertTrue(checks["no_internal_docs_tracked"]["ok"])
        self.assertTrue(checks["no_dead_doc_links"]["ok"])

    def test_unlisted_doc_fails(self) -> None:
        self._init_repo({"README.md": "# t\n", "docs/some-internal-note.md": "# x\n"})
        checks = self._run()
        self.assertFalse(checks["no_unlisted_tracked_docs"]["ok"])

    def test_internal_doc_tracked_fails(self) -> None:
        self._init_repo(
            {"README.md": "# t\n", "docs/superpowers/specs/x.md": "# design\n"},
            gitignore="",
        )
        checks = self._run()
        self.assertFalse(checks["no_internal_docs_tracked"]["ok"])

    def test_gitignore_gap_fails(self) -> None:
        self._init_repo({"README.md": "# t\n"}, gitignore="# nothing relevant\n")
        checks = self._run()
        self.assertFalse(checks["gitignore_covers_internal"]["ok"])

    def test_dead_link_fails(self) -> None:
        self._init_repo({"README.md": "# t\n\n[gone](docs/internal-thing.md)\n"})
        checks = self._run()
        self.assertFalse(checks["no_dead_doc_links"]["ok"])

    def test_dead_internal_doc_link_fails(self) -> None:
        self._init_repo(
            {"README.md": "# t\n", "docs/doc-map.md": "[gone](missing-design.md)\n"}
        )
        checks = self._run()
        self.assertFalse(checks["no_dead_internal_doc_links"]["ok"])

    def test_internal_doc_link_to_existing_passes(self) -> None:
        self._init_repo(
            {
                "README.md": "# t\n",
                "docs/doc-map.md": "[usage](usage.md)\n",
                "docs/usage.md": "# usage\n",
            }
        )
        checks = self._run()
        self.assertTrue(
            checks["no_dead_internal_doc_links"]["ok"],
            checks["no_dead_internal_doc_links"]["message"],
        )

    def test_archive_historical_links_are_exempt(self) -> None:
        self._init_repo(
            {"README.md": "# t\n", "docs/archive/old.md": "[gone](missing.md)\n"}
        )
        checks = self._run()
        self.assertTrue(checks["no_dead_internal_doc_links"]["ok"])

    def test_link_to_tracked_doc_passes(self) -> None:
        self._init_repo(
            {
                "README.md": "# t\n\n[guide](docs/usage.md)\n",
                "docs/usage.md": "# usage\n",
            }
        )
        checks = self._run()
        self.assertTrue(checks["no_dead_doc_links"]["ok"], checks["no_dead_doc_links"]["message"])

    def test_plaintext_internal_path_fails(self) -> None:
        """纯文本提到内部文档路径（不是链接）也要抓——客户 clone 后看不到该文件。"""
        self._init_repo(
            {"README.md": "# t\n\n设计见 docs/superpowers/specs/x-design.md 与 progress.md。\n"}
        )
        checks = self._run()
        self.assertFalse(checks["no_internal_paths_in_public_docs"]["ok"])

    def test_plaintext_tracked_path_passes(self) -> None:
        self._init_repo({"README.md": "# t\n\n详见 docs/usage.md。\n", "docs/usage.md": "# u\n"})
        checks = self._run()
        self.assertTrue(
            checks["no_internal_paths_in_public_docs"]["ok"],
            checks["no_internal_paths_in_public_docs"]["message"],
        )

    def test_history_docs_are_exempt(self) -> None:
        """CHANGELOG 是历史审计链（已发布版本的事实记录），只增不删，允许保留内部引用。"""
        self.assertEqual(
            self.gate._INTERNAL_REF_ALLOWED,
            frozenset({"docs/releases/CHANGELOG.md"}),
        )


class RepoDocScopeEnforcementTest(unittest.TestCase):
    """门禁必须**真的拦住**，不能只是「事后能查出来」（用户 2026-10-21 追问）。

    背景：门禁脚本存在 ≠ 门禁生效。实测过 `git add -f` 内部文档 + `git commit`
    全程无阻——只有手动跑门禁才报 FAIL。所以这里锁住三道拦截机制本身：
    ① pre-commit hook 存在且可执行；② staged 模式能识别不该提交的 .md；
    ③ 打包脚本与 CI 都调用了门禁。
    """

    def test_precommit_hook_script_exists_and_executable(self) -> None:
        hook = ROOT / "scripts" / "hooks" / "pre-commit"
        self.assertTrue(hook.is_file(), "缺少 scripts/hooks/pre-commit（内部文档拦不住）")
        self.assertTrue(os.access(hook, os.X_OK), "pre-commit hook 必须可执行")

    def test_hook_calls_staged_mode(self) -> None:
        hook = (ROOT / "scripts" / "hooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("--staged", hook, "hook 必须用 --staged 模式（只查本次提交）")
        self.assertIn("SKIP_DOC_SCOPE", hook, "hook 必须提供显式旁路开关")

    def test_installer_exists(self) -> None:
        installer = ROOT / "scripts" / "install_git_hooks.sh"
        self.assertTrue(installer.is_file(), "缺少安装脚本（clone 后 hook 不会自动生效）")
        self.assertTrue(os.access(installer, os.X_OK))

    def test_package_script_runs_gate(self) -> None:
        text = (ROOT / "ops" / "package.sh").read_text(encoding="utf-8")
        self.assertIn("verify_repo_doc_scope.py", text, "打包脚本必须跑文档范围门禁")

    def test_ci_workflow_runs_gate(self) -> None:
        workflow = ROOT / ".github" / "workflows" / "repo-hygiene.yml"
        self.assertTrue(workflow.is_file(), "缺少 CI 卫生门禁 workflow")
        text = workflow.read_text(encoding="utf-8")
        for gate in ("verify_repo_doc_scope.py", "verify_release_docs_safe.py", "verify_changelog.py"):
            self.assertIn(gate, text, f"CI 必须跑 {gate}")


class StagedModeTest(unittest.TestCase):
    """staged 模式：只拦本次要提交的 .md，不因工作树状态误伤。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="staged-"))
        self.gate = _load_gate()
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        self.env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stage(self, rel: str, text: str = "# x\n") -> None:
        target = self.tmp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", "-f", rel], cwd=self.tmp, check=True)

    def _run_staged(self) -> dict:
        original_root = self.gate.ROOT
        try:
            self.gate.ROOT = self.tmp
            checks = self.gate.check_staged()
        finally:
            self.gate.ROOT = original_root
        return {c["name"]: c for c in checks}

    def test_internal_doc_is_blocked(self) -> None:
        self._stage("docs/superpowers/specs/secret.md")
        checks = self._run_staged()
        self.assertFalse(checks["staged_doc_scope"]["ok"])
        self.assertIn("secret.md", checks["staged_doc_scope"]["message"])

    def test_root_worklog_is_blocked(self) -> None:
        self._stage("progress.md")
        checks = self._run_staged()
        self.assertFalse(checks["staged_doc_scope"]["ok"])

    def test_customer_doc_is_allowed(self) -> None:
        self._stage("docs/usage.md")
        checks = self._run_staged()
        self.assertTrue(checks["staged_doc_scope"]["ok"], checks["staged_doc_scope"]["message"])

    def test_non_markdown_is_ignored(self) -> None:
        self._stage("backend/app/whatever.py")
        checks = self._run_staged()
        self.assertTrue(checks["staged_doc_scope"]["ok"])

    def test_dev_only_script_is_blocked(self) -> None:
        """开发自用脚本（探针/数据集/演练/一次性取证）同样不得入库。"""
        self._stage("scripts/probe_something.py")
        checks = self._run_staged()
        self.assertFalse(checks["staged_script_scope"]["ok"])

    def test_evidence_script_is_blocked(self) -> None:
        self._stage("ops/evidence.sh")
        checks = self._run_staged()
        self.assertFalse(checks["staged_script_scope"]["ok"])

    def test_build_script_is_allowed(self) -> None:
        self._stage("scripts/build_upgrade_package.py")
        checks = self._run_staged()
        self.assertTrue(
            checks["staged_script_scope"]["ok"], checks["staged_script_scope"]["message"]
        )

    def test_delivery_script_is_allowed(self) -> None:
        """交付目录里的脚本是交付物本体，必须允许。"""
        self._stage("delivery/install/install.sh")
        checks = self._run_staged()
        self.assertTrue(
            checks["staged_script_scope"]["ok"], checks["staged_script_scope"]["message"]
        )


if __name__ == "__main__":
    unittest.main()
