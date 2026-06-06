from __future__ import annotations

import json
from typing import Any


VOLUME_FIELD_NAMES = [
    "id",
    "name",
    "path",
    "type",
    "size",
    "used_size",
    "unique_size",
    "unique_logical_size",
    "guest_used_size",
    "used_size_usage",
    "guest_size_usage",
    "elf_storage_policy",
    "elf_storage_policy_replica_num",
    "elf_storage_policy_thin_provision",
    "elf_storage_policy_ec_k",
    "elf_storage_policy_ec_m",
]


def normalize_vm_volumes(volumes: Any) -> list[dict[str, Any]]:
    if not isinstance(volumes, list):
        return []
    return [item for index, volume in enumerate(volumes) if (item := normalize_vm_volume(volume, index=index))]


def compact_vm_volumes_json(volumes: Any) -> str:
    return json.dumps(normalize_vm_volumes(volumes), ensure_ascii=False, separators=(",", ":"))


def normalize_vm_volume(volume: Any, index: int = 0) -> dict[str, Any]:
    if not isinstance(volume, dict):
        return {}
    volume_id = _text(volume.get("id"), volume.get("volume_id"), volume.get("local_id"), volume.get("path"), volume.get("name"))
    normalized: dict[str, Any] = {
        "id": volume_id or f"volume-{index}",
        "name": _text(volume.get("name"), volume.get("volume_name"), volume.get("path"), volume_id),
        "path": _text(volume.get("path")),
        "type": _text(volume.get("type"), volume.get("volume_type")),
        "size": _integer(volume.get("size"), volume.get("size_bytes"), volume.get("capacity"), volume.get("capacity_bytes"), volume.get("provisioned_size"), volume.get("provisioned_size_bytes")),
        "used_size": _integer(volume.get("used_size"), volume.get("used_size_bytes")),
        "unique_size": _integer(volume.get("unique_size"), volume.get("unique_size_bytes")),
        "unique_logical_size": _integer(volume.get("unique_logical_size"), volume.get("unique_logical_size_bytes")),
        "guest_used_size": _integer(volume.get("guest_used_size"), volume.get("guest_used_size_bytes")),
        "used_size_usage": _number(volume.get("used_size_usage"), volume.get("used_ratio")),
        "guest_size_usage": _number(volume.get("guest_size_usage"), volume.get("guest_used_ratio")),
        "elf_storage_policy": _text(volume.get("elf_storage_policy"), volume.get("storage_policy"), volume.get("storagePolicy"), volume.get("policy_name"), volume.get("policyName"), volume.get("policy")),
        "elf_storage_policy_replica_num": _integer(volume.get("elf_storage_policy_replica_num"), volume.get("replica_num"), volume.get("replicaNum"), volume.get("replica_count"), volume.get("replicaCount")),
        "elf_storage_policy_thin_provision": _boolean(volume.get("elf_storage_policy_thin_provision"), volume.get("thin_provision"), volume.get("thinProvision")),
        "elf_storage_policy_ec_k": _integer(volume.get("elf_storage_policy_ec_k"), volume.get("ec_data"), volume.get("ecData"), volume.get("ec_k"), volume.get("ecDataUnits")),
        "elf_storage_policy_ec_m": _integer(volume.get("elf_storage_policy_ec_m"), volume.get("ec_parity"), volume.get("ecParity"), volume.get("ec_m"), volume.get("ecParityUnits")),
    }
    return {key: value for key, value in normalized.items() if value is not None and value != ""}


def _text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _integer(*values: Any) -> int | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return int(number)
    return None


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _boolean(*values: Any) -> bool | None:
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return None
