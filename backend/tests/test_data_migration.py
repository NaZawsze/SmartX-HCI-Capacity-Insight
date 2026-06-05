import tarfile
from pathlib import Path
from types import SimpleNamespace

from app.services.data_migration import _create_import_backup


def test_create_import_backup_includes_database_and_prometheus_blocks(tmp_path, monkeypatch) -> None:
    data_path = tmp_path / "app"
    prometheus_path = tmp_path / "prometheus"
    backup_path = tmp_path / "backups"
    data_path.mkdir()
    prometheus_path.mkdir()
    (data_path / "smartx.db").write_text("db", encoding="utf-8")
    (data_path / "upgrades").mkdir()
    (data_path / "upgrades" / "runtime.txt").write_text("skip", encoding="utf-8")
    block = prometheus_path / "01ABC"
    block.mkdir()
    (block / "meta.json").write_text("{}", encoding="utf-8")
    (prometheus_path / "wal").mkdir()
    (prometheus_path / "wal" / "runtime").write_text("skip", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.data_migration.get_settings",
        lambda: SimpleNamespace(data_path=data_path, prometheus_data_path=prometheus_path, backup_path=backup_path),
    )
    task = {"task_id": "abc", "logs": []}

    backup = _create_import_backup(task)

    assert backup.exists()
    assert task["backup_path"] == str(backup)
    with tarfile.open(backup, mode="r:gz") as archive:
        names = set(archive.getnames())
    assert "manifest.json" in names
    assert "smartx-data/smartx.db" in names
    assert "prometheus-data/01ABC/meta.json" in names
    assert "smartx-data/upgrades/runtime.txt" not in names
    assert "prometheus-data/wal/runtime" not in names
