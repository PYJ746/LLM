"""Agent 引擎：把用户输入转换为 UI 可消费的事件流。

核心不变量：
- 每一轮恰好产生一个 TurnStarted 和一个 TurnFinished；
- 含 tool_calls 的 assistant 消息之后，每个 call_id 都有对应的 tool 消息；
- 流式失败或取消时，不把半截 assistant 消息写入历史；
- 工具异常只影响该次调用，不终止整轮对话。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

from core.events import (
    AgentEvent,
    ErrorOccurred,
    TextDelta,
    ToolCallCompleted,
    ToolCallRequested,
    TurnFinished,
    TurnStarted,
    TurnStatus,
)
from core.llm.base import ChatModel
from core.models import ToolCall, ToolResult
from core.session import Conversation
from core.tools.registry import ToolRegistry


@dataclass
class _ToolCallSlot:
    id: str = ""
    name: str = ""
    arguments: str = ""


class AgentEngine:
    """一段会话的 Agent 执行器。

    一个引擎实例对应一段会话；前端通过 run_turn() 消费事件。
    """

    def __init__(
        self,
        model: ChatModel,
        registry: ToolRegistry,
        session: Conversation | None = None,
        *,
        max_tool_rounds: int = 20,
    ):
        self.model = model
        self.registry = registry
        self.session = session or Conversation()
        self.max_tool_rounds = max(1, max_tool_rounds)
        self._busy = False
        self._turn_seq = 0

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def messages(self):
        return self.session.messages

    @property
    def tool_specs(self):
        return self.registry.specs

    def clear_history(self) -> None:
        if self._busy:
            raise RuntimeError("对话进行中，无法清空历史")
        self.session.clear()

    async def run_turn(self, user_text: str) -> AsyncIterator[AgentEvent]:
        text = user_text.strip()
        if not text:
            raise ValueError("用户输入不能为空")
        if self._busy:
            raise RuntimeError("当前已有对话轮次在执行")

        self._busy = True
        self._turn_seq += 1
        turn_id = self._turn_seq
        self.session.add_user(text)

        try:
            yield TurnStarted(turn_id=turn_id, user_text=text)

            for _ in range(self.max_tool_rounds):
                content_parts: list[str] = []
                slots: dict[int, _ToolCallSlot] = {}

                try:
                    async for chunk in self.model.stream_chat(
                        self.session.messages, self.registry.specs
                    ):
                        if chunk.content:
                            content_parts.append(chunk.content)
                            yield TextDelta(turn_id=turn_id, text=chunk.content)
                        for delta in chunk.tool_calls:
                            self._merge_tool_delta(slots, delta)
                except asyncio.CancelledError:
                    yield TurnFinished(turn_id=turn_id, status=TurnStatus.CANCELLED)
                    raise
                except Exception as exc:
                    yield ErrorOccurred(
                        turn_id=turn_id,
                        message=f"调用模型失败: {exc}",
                        detail=getattr(exc, "body", "") or "",
                    )
                    yield TurnFinished(turn_id=turn_id, status=TurnStatus.ERROR)
                    return

                content = "".join(content_parts)
                calls = self._finalize_calls(slots)

                if not calls:
                    self.session.add_assistant(content)
                    yield TurnFinished(
                        turn_id=turn_id,
                        status=TurnStatus.COMPLETED,
                        content=content,
                    )
                    return

                # 先把 assistant 的工具调用请求提交到历史，再逐个执行并回填
                self.session.add_assistant(content or None, tuple(calls))
                pending_from = 0

                try:
                    for index, call in enumerate(calls):
                        arguments, parse_error = _parse_arguments(call.arguments_raw)
                        yield ToolCallRequested(
                            turn_id=turn_id,
                            call_id=call.id,
                            name=call.name,
                            arguments=arguments if arguments is not None else {},
                            arguments_raw=call.arguments_raw,
                        )

                        if parse_error is not None:
                            result = ToolResult(
                                call_id=call.id,
                                name=call.name,
                                content=parse_error,
                                ok=False,
                            )
                        else:
                            result = await self.registry.execute(
                                call.id, call.name, arguments or {}
                            )

                        self.session.add_tool(call.id, result.content)
                        yield ToolCallCompleted(
                            turn_id=turn_id,
                            call_id=call.id,
                            name=call.name,
                            result=result,
                        )
                        pending_from = index + 1
                except asyncio.CancelledError:
                    # 历史中已提交 assistant(tool_calls)，必须为剩余调用补 tool 消息
                    for call in calls[pending_from:]:
                        message = "Error: 用户取消了操作"
                        self.session.add_tool(call.id, message)
                        yield ToolCallCompleted(
                            turn_id=turn_id,
                            call_id=call.id,
                            name=call.name,
                            result=ToolResult(
                                call_id=call.id,
                                name=call.name,
                                content=message,
                                ok=False,
                                cancelled=True,
                            ),
                        )
                    yield TurnFinished(
                        turn_id=turn_id, status=TurnStatus.CANCELLED
                    )
                    raise

            yield ErrorOccurred(
                turn_id=turn_id,
                message=f"超过最大工具调用轮数（{self.max_tool_rounds}）",
            )
            yield TurnFinished(turn_id=turn_id, status=TurnStatus.MAX_ROUNDS)
        finally:
            self._busy = False

    @staticmethod
    def _merge_tool_delta(
        slots: dict[int, _ToolCallSlot], delta: Any
    ) -> None:
        slot = slots.setdefault(delta.index, _ToolCallSlot())
        if delta.id:
            slot.id = delta.id
        if delta.name:
            slot.name = delta.name
        if delta.arguments_delta:
            slot.arguments += delta.arguments_delta

    @staticmethod
    def _finalize_calls(
        slots: dict[int, _ToolCallSlot],
    ) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for index in sorted(slots):
            slot = slots[index]
            if not slot.name:
                # 没有工具名的分片无法执行，直接忽略
                continue
            calls.append(
                ToolCall(
                    id=slot.id or f"call_{index}",
                    name=slot.name,
                    arguments_raw=slot.arguments or "{}",
                )
            )
        return calls


def _parse_arguments(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """解析工具参数；失败时返回错误文本，调用方不会执行工具。"""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        return None, f"Error: 工具参数不是合法 JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return None, "Error: 工具参数必须是 JSON 对象"
    return parsed, None
