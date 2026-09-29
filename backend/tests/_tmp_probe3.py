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
print("mapped =", svc._legacy_residual_host_path("/prometheus-data"))

def hv(t):
    return t.startswith("/data/smartx-storage-forecast/")

with mock.patch.object(Path, "exists", lambda self: hv(str(self))), \
     mock.patch.object(Path, "is_dir", lambda self: hv(str(self))):
    print("residual =", svc._residual_legacy_paths())
