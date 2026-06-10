from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any


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
    missing = sorted(required - set(runner_capabilities))
    if missing:
        raise ProtocolValidationError(f"Runner 缺少升级能力：{', '.join(missing)}")
