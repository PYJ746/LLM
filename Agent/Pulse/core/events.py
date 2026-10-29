"""引擎 → 前端的事件契约。

前端只消费这些不可变事件，不接触引擎内部状态；事件只包含可序列化数据，
因此未来 Web 前端可以直接转换为 JSON 推送。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeAlias

from core.models import ToolResult


class TurnStatus(str, Enum):
    """一轮对话的终止原因。"""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"
    MAX_ROUNDS = "max_rounds"


@dataclass(frozen=True, slots=True)
class TurnStarted:
    turn_id: int
    user_text: str


@dataclass(frozen=True, slots=True)
class TextDelta:
    turn_id: int
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallRequested:
    turn_id: int
    call_id: str
    name: str
    arguments: dict[str, Any]
    arguments_raw: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallCompleted:
    turn_id: int
    call_id: str
    name: str
    result: ToolResult


@dataclass(frozen=True, slots=True)
class ErrorOccurred:
    turn_id: int
    message: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class TurnFinished:
    turn_id: int
    status: TurnStatus
    content: str = ""


AgentEvent: TypeAlias = (
    TurnStarted
    | TextDelta
    | ToolCallRequested
    | ToolCallCompleted
    | ErrorOccurred
    | TurnFinished
)
