"""工具声明（叶子模块）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping

from core.models import ToolOutcome

if TYPE_CHECKING:  # 仅用于类型标注，避免 spec <-> context 循环导入
    from core.tools.context import ToolContext

ToolHandler = Callable[[Mapping[str, Any], "ToolContext"], Awaitable[ToolOutcome]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """一个可供模型调用的工具。

    parameters 直接使用 OpenAI Function Calling 的 JSON Schema 格式，
    保证发给模型的内容与原 chat.py 完全一致。
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
