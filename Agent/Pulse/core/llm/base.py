"""模型流式接口的抽象。

引擎只依赖此协议与 ChatChunk，不关心具体厂商的 JSON 结构。
测试可以注入 FakeChatModel，完全不需要网络。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, Sequence

from core.models import Message
from core.tools.spec import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """流式返回的一个 tool_call 分片。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass(frozen=True, slots=True)
class ChatChunk:
    """模型流中的一小段内容。"""

    content: str = ""
    tool_calls: tuple[ToolCallDelta, ...] = ()
    finish_reason: str | None = None


class ChatModel(Protocol):
    """异步流式对话模型。"""

    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AsyncIterator[ChatChunk]:
        ...
