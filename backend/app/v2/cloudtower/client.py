from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.v2.cloudtower.profiles import NEWEST_PROFILE, ApiProfile
from app.v2.inventory.models import ClusterInput

# 回收站 VM 的命名前缀（Tower 侧约定）：`in-recycle-bin-<uuid>`。
# 采集侧记录（49-47），展示侧（新建/增长列表）按此前缀或 in_recycle_bin 标记排除（49-40/49-47）。
RECYCLE_BIN_VM_PREFIX = "in-recycle-bin-"


class CloudTowerError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudTowerCredentials:
    base_url: str
    username: str | None = None
    password: str | None = None
    api_token: str | None = None
    verify_tls: bool = True


class CloudTowerClient:
    def __init__(self, credentials: CloudTowerCredentials, http_client: Any | None = None, timeout: float = 30.0) -> None:
        self.credentials = credentials
        self.base_url = credentials.base_url.rstrip("/")
        self._token = credentials.api_token
        self._owns_client = http_client is None
        if http_client is None:
            import httpx

            http_client = httpx.Client(base_url=self.base_url, timeout=timeout, verify=credentials.verify_tls)
        self._client = http_client
        #: 集群元数据（版本/容量）按需缓存：4.4.x 容量兜底与版本刷新共用同一次 get-clusters
        self._cluster_metadata_cache: dict[str, dict[str, Any]] | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def login(self) -> None:
        if self._token:
            return
        if not self.credentials.username or not self.credentials.password:
            raise CloudTowerError("Tower requires either an API token or username/password.")
        response = self._client.post(
            "/v2/api/login",
            json={"username": self.credentials.username, "source": "LOCAL", "password": self.credentials.password},
            headers={"accept": "application/json", "content-language": "en-US"},
        )
        if response.status_code >= 400:
            detail = response.text.replace("\n", " ")[:300]
            raise CloudTowerError(f"Login failed with HTTP {response.status_code}: {detail}")
        token = _extract_token(response.json())
        if not token:
            raise CloudTowerError("Login response did not include a token.")
        self._token = token

    def post(self, path: str, payload: dict[str, Any] | None = None, retry: bool = True) -> Any:
        self.login()
        response = self._client.post(
            path,
            json=payload or {},
            headers={
                "Authorization": str(self._token),
                "accept": "application/json",
                "content-language": "en-US",
            },
        )
        if response.status_code in {401, 403} and retry and not self.credentials.api_token:
            self._token = None
            self.login()
            return self.post(path, payload, retry=False)
        if response.status_code >= 400:
            raise CloudTowerError(f"{path} failed with HTTP {response.status_code}: {response.text[:240]}")
        data = response.json()
        if isinstance(data, dict):
            return data.get("data", data)
        return data

    def paged_post(self, path: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        limit = 100
        offset = 0
        while True:
            payload = dict(query or {})
            payload.setdefault("first", limit)
            payload.setdefault("skip", offset)
            page = _extract_items(self.post(path, payload))
            items.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return items

    def get_clusters(self) -> list[ClusterInput]:
        return [cluster for cluster in (_normalize_cluster(item) for item in self.paged_post("/v2/api/get-clusters")) if cluster is not None]

    def get_version(self) -> str | None:
        """CloudTower（Tower）平台自身版本：`GET /v2/api/get-version`，返回**纯文本**（实测 `v4.5.0`）。

        注意必须用 GET——同一路径 POST 会返回 405 Method Not Allowed（2026-10-07 `.3` 实测）。
        与 `get-clusters[].version`（SMTX OS 集群/节点版本）是两个层级，勿混用。
        """
        self.login()
        response = self._client.get(
            "/v2/api/get-version",
            headers={"Authorization": str(self._token), "accept": "application/json"},
        )
        if response.status_code >= 400:
            raise CloudTowerError(f"/v2/api/get-version failed with HTTP {response.status_code}: {response.text[:240]}")
        version = str(response.text or "").strip()
        return version or None

    def cluster_versions(self) -> dict[str, str]:
        """各集群的 SMTX OS（节点）版本：`get-clusters[].version`，如 `6.1.1`。"""
        versions: dict[str, str] = {}
        for item in self.paged_post("/v2/api/get-clusters"):
            cluster_id = str(item.get("id") or "")
            version = str(item.get("version") or "").strip()
            if cluster_id and version:
                versions[cluster_id] = version
        return versions

    def version_info(self) -> dict[str, Any]:
        """一次取全：平台版本 + 各集群节点版本（供采集顺带刷新与测试连接复用）。"""
        return {"platform": self.get_version(), "clusters": self.cluster_versions()}

    def cluster_metadata(self) -> dict[str, dict[str, Any]]:
        """`get-clusters` 里我们关心的元数据：节点版本 + 集群记录自带的容量。

        - `version`：SMTX OS（节点）版本，如 `6.1.1`；
        - `used_data_space` / `total_data_capacity`：容量兜底来源——
          4.4.x 塔没有 `get-cluster-storage-info` 端点，容量只能从这里读（#84，见 profiles.py）。
        """
        metadata: dict[str, dict[str, Any]] = {}
        for item in self.paged_post("/v2/api/get-clusters"):
            cluster_id = str(item.get("id") or "")
            if not cluster_id:
                continue
            metadata[cluster_id] = {
                "version": str(item.get("version") or "").strip() or None,
                "used_data_space": _int_or_none(item.get("used_data_space")),
                "total_data_capacity": _int_or_none(item.get("total_data_capacity")),
            }
        return metadata

    def cluster_versions(self) -> dict[str, str]:
        """各集群的 SMTX OS（节点）版本：`get-clusters[].version`，如 `6.1.1`。"""
        return {
            cluster_id: info["version"]
            for cluster_id, info in self.cluster_metadata().items()
            if info.get("version")
        }

    def version_info(self) -> dict[str, Any]:
        """一次取全：平台版本 + 各集群节点版本（供采集顺带刷新与测试连接复用）。"""
        return {"platform": self.get_version(), "clusters": self.cluster_versions()}

    def get_cluster_storage_info(self, cluster_id: str) -> dict[str, Any]:
        data = self.post("/v2/api/get-cluster-storage-info", {"where": {"id": cluster_id}, "effect": {}})
        if isinstance(data, list):
            return data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def _cluster_capacity(self, cluster_id: str, profile: ApiProfile | None) -> tuple[dict[str, Any], str]:
        """按版本画像取集群容量，返回 (容量字典, 来源)。

        - 画像说端点可用（4.5.0+）：走 `get-cluster-storage-info`；
        - 画像说端点不可用（4.4.x）：读 `get-clusters` 的集群记录；
        - 版本未知（画像为 None → 最新画像）：先试端点，**端点失败自动回退**到集群记录
          （能力探测兜底，保证读不到版本时不会整体采集失败）。
        """
        authoritative = profile if profile is not None else NEWEST_PROFILE
        if authoritative.cluster_storage_info_endpoint:
            try:
                return self.get_cluster_storage_info(cluster_id), "cluster-storage-info"
            except CloudTowerError:
                if profile is not None:
                    raise
        metadata = (self._cluster_metadata_cache or {}).get(cluster_id)
        if metadata is None:
            self._cluster_metadata_cache = self.cluster_metadata()
            metadata = (self._cluster_metadata_cache or {}).get(cluster_id) or {}
        capacity = {
            "used_data_space": metadata.get("used_data_space"),
            "total_data_capacity": metadata.get("total_data_capacity"),
        }
        return capacity, "cluster-record"

    def get_vms(self, cluster_id: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if cluster_id:
            where["cluster"] = {"id": cluster_id}
        return self.paged_post("/v2/api/get-vms", {"where": where})

    def get_vm_volumes(self, vm_id: str) -> list[dict[str, Any]]:
        return self.paged_post("/v2/api/get-vm-volumes", {"where": {"vm_disks_some": {"vm": {"id": vm_id}}}})

    def collect_cluster(self, cluster_id: str, profile: ApiProfile | None = None) -> dict[str, Any]:
        storage, capacity_source = self._cluster_capacity(cluster_id, profile)
        vms = self._collect_vms_with_volumes(cluster_id)
        # #75 终版：已分配 = Σ(每卷供给容量 × 副本数)，EC 卷按 (k+m)/k 折算——
        # 在采集时就地计算（卷数据此时都在手上），随集群样本落库，
        # dashboard 直接读存好的值（页面零计算，且与已使用同时点）。
        #
        # 口径变更（2026-10-03 用户决策，覆盖 #75 初版「回收站不计入」）：
        # **回收站 VM 的卷同样计入已分配**。
        # 理由：回收站卷的物理块仍被占用，「已使用」（Tower 的 used_data_space）
        # 本来就含它。若已分配排除，会出现「已分配 < 已使用」的反常关系，
        # 且与基于「已使用」的容量预测口径不一致。两者必须同口径。
        # 回收站数据的处置见 #77：入库保留、purge 按 VM 维度、页面展示另议。
        allocated = 0
        for vm in vms:
            for volume in vm.get("volumes", []):
                size = _number(volume.get("size_bytes")) or 0
                if size <= 0:
                    continue
                ec_k = _number(volume.get("ec_k")) or 0
                ec_m = _number(volume.get("ec_m")) or 0
                if ec_k > 0:
                    allocated += size * (ec_k + ec_m) / ec_k
                else:
                    allocated += size * (_number(volume.get("replica_num")) or 0)
        return {
            "cluster": {
                "used_bytes": int(
                    _number(storage.get("used_data_space"), storage.get("used_capacity"), storage.get("used_size"), storage.get("capacity_used")) or 0
                ),
                "total_bytes": int(
                    _number(storage.get("total_data_capacity"), storage.get("total_capacity"), storage.get("total_size"), storage.get("capacity_total")) or 0
                ),
                "allocated_bytes": int(allocated),
                # #84：容量来自哪个来源（cluster-storage-info / cluster-record），便于运维判读与取证
                "capacity_source": capacity_source,
            },
            "vms": vms,
        }

    def _collect_vms_with_volumes(self, cluster_id: str) -> list[dict[str, Any]]:
        vms: list[dict[str, Any]] = []
        for raw_vm in self.get_vms(cluster_id):
            normalized_vm = _normalize_vm(raw_vm)
            if normalized_vm is None:
                continue
            normalized_vm["volumes"] = [_normalize_volume(volume) for volume in self.get_vm_volumes(normalized_vm["vm_id"])]
            vms.append(normalized_vm)
        return vms


def _normalize_cluster(raw: dict[str, Any]) -> ClusterInput | None:
    cluster_id = str(raw.get("id") or raw.get("cluster_id") or "")
    if not cluster_id:
        return None
    return ClusterInput(cluster_id=cluster_id, name=str(raw.get("name") or raw.get("cluster_name") or cluster_id), enabled=True)


#: CloudTower 约定：VM 的"所有者"以系统标签承载（2026-10-07 `.3` 只读账号实测——
#: `labels: [{"key": "system.cloudtower/owner", "value": "root"}]`，值已是用户名）。
#: 只读账号可见；`get-users` 无权限也不需要（不需要 ID→名字解析）。
OWNER_LABEL_KEY = "system.cloudtower/owner"


def _owner_from_labels(labels: Any) -> str | None:
    """从 VM 的 `labels` 提取所有者：第一条 `system.cloudtower/owner` 的 value。

    口径（设计 §3）：无 labels / 无该 key / 值为空 → None（不猜不填充）；
    值非字符串时 str() 化；多条同 key 取第一条。
    """
    if not isinstance(labels, list):
        return None
    for label in labels:
        if isinstance(label, dict) and str(label.get("key") or "") == OWNER_LABEL_KEY:
            value = label.get("value")
            if value is None or str(value).strip() == "":
                return None
            return str(value)
    return None


def _folder_name(folder: Any) -> str | None:
    """从 VM 的 `folder` 提取「虚拟机组」名（CloudTower folder；用户口径见设计 §1）。

    folder 缺失 / 非对象 / name 为空 → None。只存名字，不存 folder id。
    """
    if not isinstance(folder, dict):
        return None
    name = str(folder.get("name") or "").strip()
    return name or None


def _normalize_vm(raw: dict[str, Any]) -> dict[str, Any] | None:
    """回收站 VM 也记录（49-47）：带 in_recycle_bin/original_name/deleted_at 落库，
    供"后台记录哪台被删、叫什么"以及后续核对彻底删除。展示侧仍按名称/标记排除。

    Phase 69（2026-10-07）：增加 `owner`（labels 系统标签）与 `folder_name`（虚拟机组）。
    """
    vm_id = str(raw.get("id") or raw.get("vm_id") or "")
    if not vm_id:
        return None
    name = str(raw.get("name") or raw.get("vm_name") or vm_id)
    in_recycle_bin = bool(raw.get("in_recycle_bin", False))
    return {
        "vm_id": vm_id,
        "name": name,
        "used_bytes": int(_number(raw.get("used_size"), raw.get("used_size_bytes"), raw.get("capacity_used")) or 0),
        "in_recycle_bin": in_recycle_bin,
        # 仅回收站状态下保留删除前名称与删除时间；恢复后清空标记
        "original_name": (str(raw.get("original_name") or "") or None) if in_recycle_bin else None,
        "deleted_at": (str(raw.get("deleted_at") or "") or None) if in_recycle_bin else None,
        # Phase 69：所有者与虚拟机组（与 VM 列表同一次 get-vms 返回，零新增 API 依赖）
        "owner": _owner_from_labels(raw.get("labels")),
        "folder_name": _folder_name(raw.get("folder")),
    }


def _non_negative(value: int | None) -> int | None:
    """负值一律视为"未上报"（CloudTower 对无用量数据的卷返回 `used_size: -1` 哨兵，
    2026-10-07 `.3` 实测：原样落库会在页面显示「实际使用空间 -1 B / 实际占用 -2 B」）。"""
    if value is None:
        return None
    return value if value >= 0 else None


def _policy_tokens(policy: Any) -> str:
    return str(policy or "").upper().replace("-", "_")


def _policy_replica_num(policy: Any) -> int | None:
    """新版卷响应只给策略串（`REPLICA_2_THIN_PROVISION`），没有 `elf_storage_policy_replica_num`
    等扁平字段（2026-10-07 `.3` 只读账号实测）——缺失时按串推导副本数，
    否则采集侧「已分配 = Σ size × replica_num」恒乘 0，Test 集群已分配永远是 0。

    只认 `REPLICA_<n>`（与扁平字段同语义）；EC 策略串的 k/m 从未见过实际样本，
    不猜（ec_k/ec_m 缺失时该卷按 0 计，与修前一致）。
    """
    match = re.search(r"REPLICA_(\d+)", _policy_tokens(policy))
    return int(match.group(1)) if match else None


def _policy_thin_provision(policy: Any) -> bool | None:
    tokens = _policy_tokens(policy)
    if "THIN_PROVISION" in tokens:
        return True
    if "THICK" in tokens:
        return False
    return None


def _normalize_volume(raw: dict[str, Any]) -> dict[str, Any]:
    storage_policy = raw.get("storage_policy") or raw.get("elf_storage_policy")
    replica_num = _int_or_none(raw.get("replica_num"), raw.get("elf_storage_policy_replica_num"))
    if replica_num is None:
        replica_num = _policy_replica_num(storage_policy)
    thin_provision = _bool_or_none(raw.get("thin_provision", raw.get("elf_storage_policy_thin_provision")))
    if thin_provision is None:
        thin_provision = _policy_thin_provision(storage_policy)
    return {
        "volume_id": str(raw.get("volume_id") or raw.get("id") or raw.get("name") or ""),
        "name": raw.get("name"),
        "path": raw.get("path"),
        "size_bytes": _non_negative(_int_or_none(raw.get("size_bytes"), raw.get("size"))),
        "used_bytes": _non_negative(_int_or_none(raw.get("used_bytes"), raw.get("used_size"))),
        "storage_policy": storage_policy,
        "replica_num": replica_num,
        "thin_provision": thin_provision,
        "ec_k": _int_or_none(raw.get("ec_k"), raw.get("elf_storage_policy_ec_k")),
        "ec_m": _int_or_none(raw.get("ec_m"), raw.get("elf_storage_policy_ec_m")),
    }


def _extract_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "data", "nodes", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _extract_token(payload: Any) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            token = _extract_token(item)
            if token:
                return token
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return _extract_token(payload.get("data"))


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


# 语义与 parsing.int_or_none 不同：经 _number 取首个可解析值，保持独立实现。
def _int_or_none(*values: Any) -> int | None:
    number = _number(*values)
    return int(number) if number is not None else None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)
