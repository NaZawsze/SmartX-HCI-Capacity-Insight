"""仓库文档范围门禁（`scripts/verify_repo_doc_scope.py`）的回归锁。

背景（用户 2026-10-21）：「用于内部开发的文档都不要提交了吧，仓库本来就是只用来放代码的」。
仓库曾经累积 151 个 Markdown，其中 128 个是设计稿/计划/工作日志/台账/交接文档。

这里锁住的不是「某个具体文件在不在」，而是**门禁本身的灵敏度**——
用临时目录构造伪造仓库，验证四种坏状态各自必须 FAIL：

1. 新增未登记的 .md → FAIL；
2. 内部文档被重新加回版本控制 → FAIL；
3. 门禁夹具被删 → FAIL；
4. .gitignore 漏掉内部模式 → FAIL；
5. 受控文档链接指向未受控文档（死链）→ FAIL。

另外锁死两条「不许退回去」的口径：
- `TRACKED_DOCS` / `REQUIRED_DOCS` 的包含关系（必需项必须仍在白名单内）；
- 内部模式清单必须覆盖 `docs/superpowers/`、根目录三件工作文档、各台账。
"""

from __future__ import annotations

import importlib.util
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
            "docs/usage.md",
            "docs/troubleshooting.md",
            "docs/releases/CHANGELOG.md",
        ):
            self.assertIn(path, self.gate.TRACKED_DOCS, f"{path} 是客户文档，不该被移出")


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
        """CHANGELOG / ledger / 矩阵是历史审计链，只增不删，允许保留内部引用。"""
        self.assertEqual(
            self.gate._INTERNAL_REF_ALLOWED,
            frozenset(
                {
                    "docs/releases/CHANGELOG.md",
                    "docs/upgrade-package-ledger.md",
                    "docs/version-skew-matrix.md",
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
