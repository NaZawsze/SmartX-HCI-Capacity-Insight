from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from app.upgrade_protocol.constants import LEGACY_CAPABILITY_ALIASES


class ProtocolValidationError(ValueError):
    pass


def validate_manifest_compatibility(
    manifest: Mapping[str, Any],
    runner_protocol_version: int,
    runner_capabilities: Collection[str],
) -> None:
    minimum_protocol = int(manifest.get("minimum_runner_protocol") or 1)
    if minimum_protocol > runner_protocol_version:
        raise ProtocolValidationError(
            f"升级包要求 Runner 协议版本 {minimum_protocol}，当前为 {runner_protocol_version}。"
        )
    required = {str(item) for item in manifest.get("required_capabilities") or []}
    runner_capability_set = set(runner_capabilities)
    missing = sorted(
        capability
        for capability in required
        if capability not in runner_capability_set
        and LEGACY_CAPABILITY_ALIASES.get(capability) not in runner_capability_set
    )
    if missing:
        raise ProtocolValidationError(f"Runner 缺少升级能力：{', '.join(missing)}")
