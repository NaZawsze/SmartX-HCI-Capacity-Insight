import importlib
from pathlib import Path
import unittest


class V2SkeletonTest(unittest.TestCase):
    def test_backend_v2_modules_are_declared_and_importable(self) -> None:
        registry = importlib.import_module("app.v2.registry")

        expected = {
            "auth",
            "inventory",
            "collection",
            "metrics",
            "forecast",
            "reports",
            "migration",
            "upgrade",
            "tasks",
            "system",
        }

        self.assertEqual(set(registry.V2_BACKEND_MODULES), expected)
        for module_name in expected:
            importlib.import_module(f"app.v2.{module_name}")

    def test_frontend_v2_skeleton_directories_exist(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        expected_dirs = [
            repo_root / "frontend/src/v2/components",
            repo_root / "frontend/src/v2/pages",
            repo_root / "frontend/src/v2/services",
            repo_root / "frontend/src/v2/types",
        ]

        missing = [str(path.relative_to(repo_root)) for path in expected_dirs if not path.is_dir()]

        self.assertEqual(missing, [])

    def test_v2_runtime_entrypoints_are_selected(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        web_dockerfile = (repo_root / "backend/Dockerfile").read_text(encoding="utf-8")
        worker_dockerfile = (repo_root / "backend/Dockerfile.worker").read_text(encoding="utf-8")
        self.assertIn("app.v2.main:app", web_dockerfile)
        self.assertIn("app.v2.worker", worker_dockerfile)
        self.assertNotIn("app.main:app", web_dockerfile)
        self.assertNotIn("app.collector.worker", worker_dockerfile)
        for name in ("docker-compose.yml", "docker-compose.offline.yml", "docker-compose.release.yml"):
            text = (repo_root / name).read_text(encoding="utf-8")
            self.assertIn('command: ["python", "-m", "app.v2.worker"]', text)
            self.assertNotIn('command: ["python", "-m", "app.collector.worker"]', text)


if __name__ == "__main__":
    unittest.main()
