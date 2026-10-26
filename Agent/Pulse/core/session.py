"""会话历史。

保证发给模型的消息序列合法：system 始终位于首位；含 tool_calls 的
assistant 消息之后由引擎补齐对应的 tool 消息。
"""

from __future__ import annotations

from typing import Any, Sequence

from core.models import Message, ToolCall
from core.prompts import SYSTEM_PROMPT


class Conversation:
    """一段独立的对话。"""

    def __init__(self, system_prompt: str = SYSTEM_PROMPT):
        self._system_prompt = system_prompt
        self._messages: list[Message] = [Message("system", system_prompt)]

    def __len__(self) -> int:
        return len(self._messages)

    @property
    def messages(self) -> tuple[Message, ...]:
        """返回只读快照，防止前端直接改写历史。"""
        return tuple(self._messages)

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def turn_count(self) -> int:
        """用户消息数量（system 不计）。"""
        return sum(1 for message in self._messages if message.role == "user")

    def add_user(self, content: str) -> Message:
        message = Message("user", content)
        self._messages.append(message)
        return message

    def add_assistant(
        self, content: str | None, tool_calls: Sequence[ToolCall] = ()
    ) -> Message:
        message = Message("assistant", content, tuple(tool_calls))
        self._messages.append(message)
        return message

    def add_tool(self, tool_call_id: str, content: str) -> Message:
        message = Message("tool", content, tool_call_id=tool_call_id)
        self._messages.append(message)
        return message

    def clear(self) -> None:
        """清空历史，但保留 system 提示词。"""
        self._messages = [Message("system", self._system_prompt)]

    def to_wire(self) -> list[dict[str, Any]]:
        """转换为请求体中的 messages 数组。"""
        return [message.to_wire() for message in self._messages]
