import tempfile
from pathlib import Path
from unittest import mock
from app.v2.config import V2Settings
from app.v2.database import V2Database
from app.v2.tasks.service import TaskService
from app.v2.upgrade.service import UpgradeService

M = {"/prometheus-data": "/data/smartx-storage-forecast/prometheus"}
d = tempfile.mkdtemp()
pd = Path(d) / "project"; pd.mkdir(parents=True)
s = V2Settings(data_root=Path(d), secret_key="k", app_version="v0.5.3", project_path_override=pd)
db = V2Database(s); db.initialize()
svc = UpgradeService(s, TaskService(db), project_path=pd)
svc._container_mount_source = lambda dest: M.get(dest, "")

# 宿主视角：只有真正的 legacy 路径残留
LEGACY = {"/opt/smartx-storage-forecast", "/data/smartx-capacity-insight-data", "/data/upgrades"}
def hv(self):
    return str(self) in LEGACY

with mock.patch.object(Path, "exists", hv), mock.patch.object(Path, "is_dir", hv):
    print("A 只剩 /opt 残留 ->", svc._residual_legacy_paths())

LEGACY.clear()
LEGACY.add("/prometheus-data")
print("B 挂载点也残留（映射失效时）->", end=" ")
LEGACY.clear()
svc._container_mount_source = lambda dest: None
def hv2(self):
    return str(self) in {"/prometheus-data"}
with mock.patch.object(Path, "exists", hv2), mock.patch.object(Path, "is_dir", hv2):
    print(svc._residual_legacy_paths())
