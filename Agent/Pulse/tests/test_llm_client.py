from __future__ import annotations

import json

import httpx
import pytest

from core.config import PulseConfig
from core.errors import LLMError
from core.llm.openai import OpenAIChatClient
from core.models import Message
from core.tools.spec import ToolSpec


def sse(*payloads: str) -> bytes:
    frames = "".join(f"data: {payload}\n\n" for payload in payloads)
    return f"{frames}data: [DONE]\n\n".encode("utf-8")


def make_client(body: bytes, status: int = 200, captured: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content)
        return httpx.Response(status, content=body)

    config = PulseConfig(base_url="https://example.com", api_key="secret", model="m1")
    return OpenAIChatClient(config, transport=httpx.MockTransport(handler))


async def collect(client: OpenAIChatClient):
    return [
        chunk
        async for chunk in client.stream_chat(
            [Message("user", "你好")],
            [
                ToolSpec(
                    "t",
                    "工具",
                    {"type": "object", "properties": {}},
                    None,  # 仅用于导出 schema，不会被调用
                )
            ],
        )
    ]


async def test_stream_text_and_finish_reason():
    body = sse(
        '{"choices":[{"delta":{"content":"你"}}]}',
        '{"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}',
    )
    chunks = await collect(make_client(body))

    assert "".join(chunk.content for chunk in chunks) == "你好"
    assert chunks[-1].finish_reason == "stop"


async def test_stream_fragmented_tool_calls():
    first = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "echo", "arguments": '{"va'},
                            }
                        ]
                    }
                }
            ]
        }
    )
    second = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": 'lue": 1}'}}
                        ]
                    }
                }
            ]
        }
    )
    chunks = await collect(make_client(sse(first, second)))

    assert chunks[0].tool_calls[0].id == "call_1"
    assert chunks[0].tool_calls[0].name == "echo"
    assert chunks[1].tool_calls[0].arguments_delta == 'lue": 1}'


async def test_request_payload_and_headers():
    captured: dict = {}
    body = sse('{"choices":[{"delta":{"content":"ok"}}]}')
    await collect(make_client(body, captured=captured))

    assert captured["url"] == "https://example.com/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer secret"
    assert captured["json"]["model"] == "m1"
    assert captured["json"]["stream"] is True
    assert captured["json"]["messages"][0]["role"] == "user"
    assert captured["json"]["tools"][0]["function"]["name"] == "t"


async def test_http_error_raises_llm_error():
    client = make_client(b"nope", status=500)
    with pytest.raises(LLMError) as exc_info:
        await collect(client)

    assert exc_info.value.status_code == 500
    assert "nope" in str(exc_info.value)


async def test_ignores_malformed_and_non_data_lines():
    body = (
        b": keep-alive\n\n"
        b"event: message\n\n"
        b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
        b"data: not-json\n\n"
        b"data: [DONE]\n\n"
    )
    chunks = await collect(make_client(body))
    assert "".join(chunk.content for chunk in chunks) == "a"
