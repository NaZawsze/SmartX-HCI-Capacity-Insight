"""W7 两道构建门禁：动作词汇冻结 + expand-only 迁移。

- `scripts/verify_upgrade_plan_vocabulary.py`（W7.1）：候选平台包用**包内编译器**对每个
  源版本生成计划，断言动作集 ⊆ 已发布 runner 组件包镜像内的动作集。
- `scripts/verify_migrations_expand_only.py`（W7.2）：迁移 registry 新增条目不得含破坏性模式。

判据要点（与 impl-spec §W7 / §14.1.5 对齐）：
1. 缺动作即 FAIL；注释里的 DROP 不算命中（剥离注释）；放行必须显式 `--allow` 或 contract 通道。
2. 门禁被绕等于没有门禁——因此**必须**同时存在"放行路径"和"放行会留下 WARN 痕迹"。
3. 动作集来源是**已发布 runner 包内镜像归档的 actions.py**，不是仓库工作区。
"""
from __future__ import annotations

import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vocabulary = _load_script("verify_upgrade_plan_vocabulary.py")
expand_only = _load_script("verify_migrations_expand_only.py")


def _docker_save_archive(image: str, app_files: dict[str, str]) -> bytes:
    """造一个最小 docker-save 归档：单层，内含给定 /app 文件。"""
    layer_buf = io.BytesIO()
    with tarfile.open(fileobj=layer_buf, mode="w") as layer:
        for rel, content in app_files.items():
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"app/{rel}")
            info.size = len(payload)
            layer.addfile(info, io.BytesIO(payload))
    layer_bytes = layer_buf.getvalue()

    manifest_bytes = json.dumps(
        [{"Config": "config.json", "RepoTags": [image], "Layers": ["layer.tar"]}]
    ).encode("utf-8")

    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        for name, blob in (("manifest.json", manifest_bytes), ("layer.tar", layer_bytes)):
            info = tarfile.TarInfo(name=name)
            info.size = len(blob)
            archive.addfile(info, io.BytesIO(blob))
    return out.getvalue()


ACTIONS_SOURCE_TEMPLATE = '''\
def default_handlers():
    return {{
        "backup.create": backup_create,
        "compose.apply": compose_apply,
{extra}    }}
'''


def _runner_package(directory: Path, *, version: str, actions: list[str]) -> Path:
    actions_source = ACTIONS_SOURCE_TEMPLATE.format(
        extra="".join(f'        "{action}": placeholder,\n' for action in sorted(actions) if action not in {"backup.create", "compose.apply"})
    )
    archive_bytes = _docker_save_archive(
        f"nazawsze/smartx-hci-capacity-insight-upgrade-runner:{version}",
        {
            "RUNNER_VERSION": f"{version}\n",
            "app/upgrade_runner/actions.py": actions_source,
        },
    )
    work = directory / f"smartx-upgrade-runner-{version}"
    (work / "images").mkdir(parents=True)
    manifest = {
        "schema_version": "3",
        "version": version,
        "package_type": "component",
        "components": [
            {
                "type": "runner",
                "services": ["upgrade-runner"],
                "images": [
                    {
                        "service": "upgrade-runner",
                        "image": f"nazawsze/smartx-hci-capacity-insight-upgrade-runner:{version}",
                        "archive": "images/upgrade-runner.tar",
                    }
                ],
            }
        ],
    }
    (work / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (work / "images" / "upgrade-runner.tar").write_bytes(archive_bytes)
    package = directory / f"smartx-upgrade-runner-{version}.tar.gz"
    with tarfile.open(package, mode="w:gz") as archive:
        for rel in ("manifest.json", "images/upgrade-runner.tar"):
            archive.add(work / rel, arcname=rel)
    return package


def _platform_manifest(
    version: str = "v0.5.4",
    *,
    supported_versions: list[str] | None = None,
    schema_version: str = "3",
    image_archive: str = "images/web-api.tar",
) -> dict:
    return {
        "schema_version": schema_version,
        "version": version,
        "min_version": "v0.5.0",
        "package_type": "platform",
        "minimum_runner_protocol": 1,
        "minimum_runner_version": "v0.3.1",
        "required_capabilities": ["backup.v1", "image.v1", "files.v1", "compose.v1", "health.v1"],
        "source_compatibility": {
            "min_version": "v0.5.0",
            "max_version_inclusive": version,
            "target_version": version,
            "supported_versions": supported_versions if supported_versions is not None else ["v0.5.2", "v0.5.3"],
        },
        "components": [
            {
                "type": "platform",
                "services": ["web-api", "collector-worker", "frontend"],
                "images": [
                    {"service": "web-api", "image": "repo/web-api:" + version, "archive": image_archive},
                ],
            }
        ],
    }


def _platform_package(directory: Path, manifest: dict, *, with_image: bool = True) -> Path:
    work = directory / f"platform-{manifest['version']}-{manifest.get('schema_version')}"
    (work / "images").mkdir(parents=True)
    (work / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    members = ["manifest.json"]
    if with_image:
        (work / "images" / "web-api.tar").write_bytes(_docker_save_archive("repo/web-api", {"VERSION": "v0.5.4\n"}))
        members.append("images/web-api.tar")
    package = directory / f"platform-{manifest['version']}-{manifest.get('schema_version')}.tar.gz"
    with tarfile.open(package, mode="w:gz") as archive:
        for rel in members:
            archive.add(work / rel, arcname=rel)
    return package


class RunnerPackageActionExtractionTests(unittest.TestCase):
    """W7.1 的动作集来源：已发布 runner 包**镜像内**的 actions.py。"""

    def test_actions_parsed_from_package_image_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = _runner_package(
                Path(tmp),
                version="v0.3.1",
                actions=["backup.create", "compose.apply", "image.load", "health.http", "rollback.restore"],
            )
            actions = vocabulary.runner_package_actions(package)
        self.assertEqual(
            actions,
            {"backup.create", "compose.apply", "health.http", "image.load", "rollback.restore"},
        )

    def test_missing_action_table_in_package_is_gate_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "pkg"
            (work / "images").mkdir(parents=True)
            (work / "manifest.json").write_text(
                json.dumps(
                    {
                        "version": "v0.3.1",
                        "components": [
                            {
                                "type": "runner",
                                "images": [{"service": "upgrade-runner", "archive": "images/upgrade-runner.tar"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (work / "images" / "upgrade-runner.tar").write_bytes(
                _docker_save_archive("runner:x", {"VERSION": "1"})
            )
            package = Path(tmp) / "smartx-upgrade-runner-v0.3.1.tar.gz"
            with tarfile.open(package, mode="w:gz") as archive:
                for rel in ("manifest.json", "images/upgrade-runner.tar"):
                    archive.add(work / rel, arcname=rel)
            with self.assertRaises(vocabulary.GateError):
                vocabulary.runner_package_actions(package)


class VocabularySchemaTests(unittest.TestCase):
    """① manifest schema_version 与已发布线一致。"""

    def test_matching_schema_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            released = _platform_package(Path(tmp), _platform_manifest("v0.5.3"))
            self.assertEqual(vocabulary.read_released_schema_version(released), "3")

    def test_missing_baseline_falls_back_to_constant(self) -> None:
        self.assertEqual(vocabulary.read_released_schema_version(None), vocabulary.RELEASED_SCHEMA_VERSION)


class VocabularyPlanCompilationTests(unittest.TestCase):
    """② 候选包内编译器 × 每个源版本 → 动作集 ⊆ 已发布 runner 动作集。"""

    def _install_fake_compiler(self, monkey_actions: list[str]) -> None:
        """替换 compile_plans_from_package：直接返回给定动作集（不依赖 docker）。"""

    def test_verify_fails_when_plan_uses_unsupported_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runner_package = _runner_package(
                directory, version="v0.3.1", actions=["backup.create", "compose.apply", "image.load"]
            )
            platform_package = _platform_package(directory, _platform_manifest())
            original = vocabulary.compile_plans_from_package
            vocabulary.compile_plans_from_package = lambda package, manifest: {
                "by_source": {
                    "v0.5.2": [{"id": "backup", "type": "backup.create"}],
                    "v0.5.3": [
                        {"id": "backup", "type": "backup.create"},
                        {"id": "compose", "type": "compose.apply"},
                        {"id": "handoff", "type": "runner.handoff_target_runtime"},
                    ],
                },
                "errors": [],
            }
            try:
                result = vocabulary.verify(platform_package=platform_package, runner_package=runner_package)
            finally:
                vocabulary.compile_plans_from_package = original
        self.assertFalse(result["ok"])
        subset = next(item for item in result["checks"] if item["id"] == "plan_actions_subset")
        self.assertEqual(subset["status"], "FAIL")
        self.assertIn("runner.handoff_target_runtime", subset["detail"])
        self.assertIn("v0.5.3", subset["detail"])

    def test_verify_passes_when_all_actions_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runner_package = _runner_package(
                directory,
                version="v0.3.1",
                actions=["backup.create", "compose.apply", "image.load", "health.http"],
            )
            platform_package = _platform_package(directory, _platform_manifest())
            original = vocabulary.compile_plans_from_package
            vocabulary.compile_plans_from_package = lambda package, manifest: {
                "by_source": {
                    "v0.5.2": [{"id": "backup", "type": "backup.create"}],
                    "v0.5.3": [{"id": "health", "type": "health.http"}],
                },
                "errors": [],
            }
            try:
                result = vocabulary.verify(platform_package=platform_package, runner_package=runner_package)
            finally:
                vocabulary.compile_plans_from_package = original
        self.assertTrue(result["ok"], result)
        subset = next(item for item in result["checks"] if item["id"] == "plan_actions_subset")
        self.assertEqual(subset["status"], "PASS")

    def test_schema_mismatch_fails_even_when_actions_fine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runner_package = _runner_package(directory, version="v0.3.1", actions=["backup.create"])
            platform_package = _platform_package(directory, _platform_manifest(schema_version="4"))
            original = vocabulary.compile_plans_from_package
            vocabulary.compile_plans_from_package = lambda package, manifest: {
                "by_source": {"v0.5.3": [{"id": "backup", "type": "backup.create"}]},
                "errors": [],
            }
            try:
                result = vocabulary.verify(platform_package=platform_package, runner_package=runner_package)
            finally:
                vocabulary.compile_plans_from_package = original
        self.assertFalse(result["ok"])
        schema_check = next(item for item in result["checks"] if item["id"] == "manifest_schema_version")
        self.assertEqual(schema_check["status"], "FAIL")

    def test_empty_supported_versions_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runner_package = _runner_package(directory, version="v0.3.1", actions=["backup.create"])
            platform_package = _platform_package(directory, _platform_manifest(supported_versions=[]))
            original = vocabulary.compile_plans_from_package
            vocabulary.compile_plans_from_package = lambda package, manifest: {"by_source": {}, "errors": []}
            try:
                result = vocabulary.verify(platform_package=platform_package, runner_package=runner_package)
            finally:
                vocabulary.compile_plans_from_package = original
        self.assertFalse(result["ok"])
        subset = next(item for item in result["checks"] if item["id"] == "plan_actions_subset")
        self.assertEqual(subset["status"], "FAIL")
        self.assertIn("supported_versions", subset["detail"])

    def test_compile_errors_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runner_package = _runner_package(directory, version="v0.3.1", actions=["backup.create"])
            platform_package = _platform_package(directory, _platform_manifest())
            original = vocabulary.compile_plans_from_package
            vocabulary.compile_plans_from_package = lambda package, manifest: {
                "by_source": {},
                "errors": [{"source_version": "v0.5.1", "error": "UpgradeCompilationError: 源版本不支持"}],
            }
            try:
                result = vocabulary.verify(platform_package=platform_package, runner_package=runner_package)
            finally:
                vocabulary.compile_plans_from_package = original
        self.assertFalse(result["ok"])
        subset = next(item for item in result["checks"] if item["id"] == "plan_actions_subset")
        self.assertIn("v0.5.1", subset["detail"])

    def test_low_source_version_emits_warning_about_old_compiler(self) -> None:
        """源版本低于 v0.5.3 时必须提示：那一格的计划由源端老编译器生成，本门禁不覆盖。"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            runner_package = _runner_package(directory, version="v0.3.1", actions=["backup.create"])
            platform_package = _platform_package(directory, _platform_manifest())
            original = vocabulary.compile_plans_from_package
            vocabulary.compile_plans_from_package = lambda package, manifest: {
                "by_source": {
                    "v0.5.1u2": [{"id": "backup", "type": "backup.create"}],
                    "v0.5.3": [{"id": "backup", "type": "backup.create"}],
                },
                "errors": [],
            }
            try:
                result = vocabulary.verify(platform_package=platform_package, runner_package=runner_package)
            finally:
                vocabulary.compile_plans_from_package = original
        note = next(item for item in result["checks"] if item["id"] == "plan_source_compiled_downstream")
        self.assertEqual(note["status"], "WARN")
        self.assertIn("v0.5.1u2", note["detail"])


class ExpandOnlyGateTests(unittest.TestCase):
    """W7.2：迁移 expand-only。"""

    def _registry(self, tmp: str, entries: list[dict]) -> Path:
        path = Path(tmp) / "registry.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def test_add_column_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [
                    {
                        "id": "add-note",
                        "version": "v0.5.4",
                        "description": "加列",
                        "sql": ["ALTER TABLE tasks ADD COLUMN note TEXT"],
                        "operations": [{"action": "add_column_if_missing", "table": "tasks", "column": "note", "definition": "TEXT"}],
                    }
                ],
            )
            result = expand_only.verify(registry_path=registry, baseline_tag=None)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["new_steps"], ["add-note"])

    def test_drop_column_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [{"id": "drop-legacy", "version": "v0.5.4", "description": "删列", "sql": ["ALTER TABLE tasks DROP COLUMN note"]}],
            )
            result = expand_only.verify(registry_path=registry, baseline_tag=None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["kind"], "DROP_COLUMN")
        self.assertEqual(result["failures"][0]["step_id"], "drop-legacy")

    def test_drop_table_and_delete_and_update_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [
                    {"id": "s1", "version": "v0.5.4", "description": "d", "sql": ["DROP TABLE old_stuff"]},
                    {"id": "s2", "version": "v0.5.4", "description": "d", "sql": ["DELETE FROM tasks WHERE id = 1"]},
                    {"id": "s3", "version": "v0.5.4", "description": "d", "sql": ["UPDATE tasks SET status = 'x'"]},
                    {"id": "s4", "version": "v0.5.4", "description": "d", "sql": ["ALTER TABLE tasks RENAME TO tasks_old"]},
                ],
            )
            result = expand_only.verify(registry_path=registry, baseline_tag=None)
        self.assertFalse(result["ok"])
        kinds = {item["kind"] for item in result["failures"]}
        self.assertEqual(kinds, {"DROP_TABLE", "DELETE_FROM", "UPDATE_SET", "ALTER_RENAME"})

    def test_comment_mentioning_drop_is_not_a_hit(self) -> None:
        """假阳性必须被消掉：注释里的 DROP 不是破坏性操作。"""
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [
                    {
                        "id": "s1",
                        "version": "v0.5.4",
                        "description": "d",
                        "sql": [
                            "-- 历史遗留表将来在 contract 阶段 DROP TABLE legacy_stuff\n"
                            "ALTER TABLE tasks ADD COLUMN note TEXT"
                        ],
                    },
                    {
                        "id": "s2",
                        "version": "v0.5.4",
                        "description": "d",
                        "sql": ["/* 计划 DROP COLUMN x */ CREATE TABLE IF NOT EXISTS t2 (id INTEGER)"],
                    },
                ],
            )
            result = expand_only.verify(registry_path=registry, baseline_tag=None)
        self.assertTrue(result["ok"], result)

    def test_unknown_operation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [{"id": "s1", "version": "v0.5.4", "description": "d", "operations": [{"action": "rebuild_table"}]}],
            )
            result = expand_only.verify(registry_path=registry, baseline_tag=None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["kind"], "operation:rebuild_table")

    def test_allowlist_turns_hit_into_warning(self) -> None:
        """必须有放行出口，但放行必须留 WARN 痕迹（§14.1.5）。"""
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [{"id": "drop-legacy", "version": "v0.5.4", "description": "d", "sql": ["DROP TABLE legacy_stuff"]}],
            )
            result = expand_only.verify(
                registry_path=registry, baseline_tag=None, allow=["drop-legacy:DROP_TABLE"]
            )
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("人工放行规则", result["warnings"][0]["reason"])

    def test_wildcard_allowlist_applies_to_any_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [{"id": "any-step", "version": "v0.5.4", "description": "d", "sql": ["DELETE FROM tasks"]}],
            )
            result = expand_only.verify(registry_path=registry, baseline_tag=None, allow=["*:DELETE_FROM"])
        self.assertTrue(result["ok"], result)

    def test_contract_entry_blocked_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [
                    {
                        "id": "contract-drop",
                        "version": "v0.5.4",
                        "description": "d",
                        "sql": ["DROP TABLE legacy_stuff"],
                        "contract": True,
                        "contract_plan": "docs/contract-plan-v0.6.md",
                    }
                ],
            )
            blocked = expand_only.verify(registry_path=registry, baseline_tag=None)
            allowed = expand_only.verify(registry_path=registry, baseline_tag=None, allow_new_contract=True)
        self.assertFalse(blocked["ok"])
        self.assertIn("默认禁止新增 contract", blocked["failures"][0]["reason"])
        self.assertTrue(allowed["ok"])
        self.assertEqual(allowed["warnings"][0]["step_id"], "contract-drop")

    def test_contract_flag_without_plan_is_treated_as_normal_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [{"id": "half", "version": "v0.5.4", "description": "d", "sql": ["DROP TABLE t"], "contract": True}],
            )
            result = expand_only.verify(registry_path=registry, baseline_tag=None, allow_new_contract=True)
        self.assertFalse(result["ok"])
        self.assertNotIn("contract", [item.get("reason", "") for item in result["warnings"]])

    def test_baseline_excludes_existing_steps_from_failure(self) -> None:
        """历史条目不追溯，但要在输出里列出（知情，不是静默）。"""
        with tempfile.TemporaryDirectory() as tmp:
            registry = self._registry(
                tmp,
                [{"id": "ancient", "version": "v0.5.0", "description": "d", "sql": ["DROP TABLE t"]}],
            )
            baseline = Path(tmp) / "baseline.json"
            baseline.write_text(json.dumps([{"id": "ancient", "version": "v0.5.0", "description": "d"}]), encoding="utf-8")
            result = expand_only.verify(registry_path=registry, baseline_path=baseline)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["legacy_destructive_steps"], ["ancient"])
        self.assertEqual(result["new_steps"], [])

    def test_current_repository_registry_is_expand_only(self) -> None:
        """本仓库当前 registry（空）必须通过门禁——门禁自身可用。"""
        result = expand_only.verify(registry_path=expand_only.DEFAULT_REGISTRY, baseline_tag=None)
        self.assertTrue(result["ok"], result)


class CurrentRepositoryRunnerActionSetTests(unittest.TestCase):
    """仓库 runner 动作集必须仍 ⊆ 已发布 v0.3.1 动作集之外的新增需人工决策：这里只固化事实。"""

    def test_repo_actions_include_platform_upgrade_vocabulary(self) -> None:
        import sys

        backend = str(ROOT / "backend")
        if backend not in sys.path:
            sys.path.insert(0, backend)
        from app.upgrade_runner.actions import default_handlers

        actions = set(default_handlers())
        for required in (
            "backup.create",
            "image.load",
            "files.sync",
            "compose.override",
            "compose.apply",
            "health.http",
            "health.prometheus",
            "runner.schedule_target_runtime_handoff",
            "rollback.restore",
        ):
            self.assertIn(required, actions)
        # 平台升级七步常量流程不得下发迁移/交接/legacy 动作（impl-spec §W6）
        for forbidden in ("compose.project_migrate", "runner.handoff_target_runtime", "runner.stop_legacy_runtime"):
            self.assertIn(forbidden, actions, "动作词汇表保留供旧源兼容，只是新计划不用")


if __name__ == "__main__":
    unittest.main()
