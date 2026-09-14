"""可选的 AI 措辞增强层。

基础报告使用离线规则模板生成建议措辞；本模块提供可选的 AI 改写接口。
未配置 AI 服务时（默认），``enhance_wording`` 直接返回规则文案，行为与现状一致。

接入点：未来配置 ``SMARTX_AI_WORDING_ENDPOINT`` 后，在此调用 AI 服务改写措辞，
失败时回退原文本（基础报告必须保持离线规则可用）。
"""

from __future__ import annotations

import os
from typing import Any


def ai_wording_enabled() -> bool:
    """AI 措辞增强是否启用（由 SMARTX_AI_WORDING_ENDPOINT 控制，默认关闭）。"""
    return bool(os.environ.get("SMARTX_AI_WORDING_ENDPOINT"))


def enhance_wording(text: str, *, context: dict[str, Any] | None = None) -> str:
    """改写建议措辞；未配置 AI 服务时返回原文本（离线规则回退）。"""
    if not ai_wording_enabled():
        return text
    # TODO: 接入 AI 服务（内网离线产品暂不实际调用）。
    # 未来在此调用外部/本地模型改写 text，失败时回退原文本。
    return text
