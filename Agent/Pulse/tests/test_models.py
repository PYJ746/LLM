from __future__ import annotations

from core.models import Message, ToolCall


def test_plain_message_wire_format():
    assert Message("user", "你好").to_wire() == {"role": "user", "content": "你好"}


def test_assistant_tool_call_wire_format_keeps_none_content():
    call = ToolCall("call_1", "getdate", "{}")
    wire = Message("assistant", None, (call,)).to_wire()

    assert wire["role"] == "assistant"
    assert wire["content"] is None
    assert wire["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "getdate", "arguments": "{}"},
        }
    ]


def test_tool_message_wire_format():
    wire = Message("tool", "结果", tool_call_id="call_1").to_wire()
    assert wire == {"role": "tool", "content": "结果", "tool_call_id": "call_1"}
