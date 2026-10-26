"""领域数据模型：消息、工具调用与工具执行结果。

本模块是叶子模块，不得导入 core 中的其他业务模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型请求的一次工具调用。"""

    id: str
    name: str
    arguments_raw: str = ""


@dataclass(frozen=True, slots=True)
class Message:
    """与 OpenAI 兼容接口对齐的一条对话消息。"""

    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        """转换为请求体中的消息字典，省略未使用的字段。"""
        if self.role == "tool":
            return {
                "role": "tool",
                "content": self.content or "",
                "tool_call_id": self.tool_call_id or "",
            }

        if self.role == "assistant" and self.tool_calls:
            # 只调用工具、没有文本时，content 必须显式传 None
            return {
                "role": "assistant",
                "content": self.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments_raw or "{}",
                        },
                    }
                    for call in self.tool_calls
                ],
            }

        return {"role": self.role, "content": self.content or ""}


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """工具处理函数的返回值。"""

    content: str
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具经注册表执行后的归一化结果。"""

    call_id: str
    name: str
    content: str
    ok: bool = True
    cancelled: bool = False
    duration_ms: int = 0
