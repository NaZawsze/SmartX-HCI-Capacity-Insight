from __future__ import annotations


def in_enabled_scope(key: tuple[int, str], enabled_scope: set[tuple[int, str]]) -> bool:
    # Fail closed: an empty scope means no cluster is enabled, so nothing may pass.
    return key in enabled_scope if enabled_scope else False
