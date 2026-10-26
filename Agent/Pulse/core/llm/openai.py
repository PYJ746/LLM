"""OpenAI 兼容接口的异步流式客户端。

使用 httpx.AsyncClient 解析 SSE，替代原 chat.py 的同步 requests，
避免阻塞 TUI 事件循环。本模块只负责网络与协议解析，不打印、不拼装
工具调用（分片合并由 AgentEngine 完成）。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Sequence

import httpx

from core.config import PulseConfig
from core.errors import LLMError
from core.llm.base import ChatChunk, ToolCallDelta
from core.models import Message
from core.tools.spec import ToolSpec


class OpenAIChatClient:
    """调用 /chat/completions 的流式客户端。"""

    def __init__(
        self,
        config: PulseConfig,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.request_timeout),
            transport=transport,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AsyncIterator[ChatChunk]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [message.to_wire() for message in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = [_to_openai_tool(spec) for spec in tools]

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        async with self._client.stream(
            "POST", url, headers=headers, json=payload
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise LLMError(
                    f"模型服务返回错误: {body[:500] or response.reason_phrase}",
                    status_code=response.status_code,
                    body=body,
                )

            async for line in response.aiter_lines():
                chunk = _parse_sse_line(line)
                if chunk is not None:
                    yield chunk


def _to_openai_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _parse_sse_line(line: str) -> ChatChunk | None:
    """解析一行 SSE；非 data 行、空行和 [DONE] 返回 None。"""
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return None

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None

    choices = payload.get("choices") or []
    if not choices:
        return None
    choice = choices[0]
    delta = choice.get("delta") or {}

    deltas: list[ToolCallDelta] = []
    for piece in delta.get("tool_calls") or []:
        function = piece.get("function") or {}
        deltas.append(
            ToolCallDelta(
                index=piece.get("index", 0),
                id=piece.get("id") or None,
                name=function.get("name") or None,
                arguments_delta=function.get("arguments") or "",
            )
        )

    content = delta.get("content") or ""
    finish_reason = choice.get("finish_reason")
    if not content and not deltas and finish_reason is None:
        return None

    return ChatChunk(
        content=content,
        tool_calls=tuple(deltas),
        finish_reason=finish_reason,
    )
