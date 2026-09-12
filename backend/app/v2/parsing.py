from __future__ import annotations


def int_or_none(*values: object) -> int | None:
    """返回第一个可解析为整数的值（跳过 None 与空串）；全部不可解析时返回 None。"""
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None
