"""测试替身：无需网络即可驱动完整 Agent 循环。"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import AsyncIterator, Sequence

import pytest

from core.confirmation import ConfirmationRequest
from core.llm.base import ChatChunk
from core.models import Message
from core.tools.spec import ToolSpec


class FakeChatModel:
    """按脚本返回流式片段；可选的 gate 用于确定性取消测试。"""

    def __init__(self, script: Sequence[Sequence[ChatChunk | BaseException]] | None = None):
        self.script = [list(turn) for turn in (script or [])]
        self.calls: list[tuple[tuple[Message, ...], tuple[ToolSpec, ...]]] = []
        self.gate: asyncio.Event | None = None

    async def stream_chat(
        self, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append((tuple(messages), tuple(tools)))
        if self.gate is not None:
            await self.gate.wait()

        turn = self.script.pop(0) if self.script else [ChatChunk(content="好的")]
        for item in turn:
            if isinstance(item, BaseException):
                raise item
            yield item


class ScriptedConfirmation:
    """按顺序返回预设答案，并记录每次确认请求。"""

    def __init__(self, responses: Sequence[bool]):
        self.responses = deque(responses)
        self.requests: list[ConfirmationRequest] = []

    async def confirm(self, request: ConfirmationRequest) -> bool:
        self.requests.append(request)
        if self.responses:
            return self.responses.popleft()
        return False


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


def text_turn(*parts: str) -> list[ChatChunk]:
    """把若干文本片段包装成一轮模型输出。"""
    return [ChatChunk(content=part) for part in parts]
