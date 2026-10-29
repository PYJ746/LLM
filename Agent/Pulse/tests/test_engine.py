from __future__ import annotations

import asyncio

from core.agent import AgentEngine
from core.events import (
    ErrorOccurred,
    TextDelta,
    ToolCallCompleted,
    ToolCallRequested,
    TurnFinished,
    TurnStarted,
    TurnStatus,
)
from core.llm.base import ChatChunk, ToolCallDelta
from core.models import ToolOutcome
from core.tools.registry import ToolRegistry
from core.tools.spec import ToolSpec
from tests.conftest import FakeChatModel, text_turn

PARAMS = {"type": "object", "properties": {}}


async def echo_handler(arguments, context):
    return ToolOutcome(f"echo:{arguments.get('value')}")


def echo_registry(workspace=None, handler=echo_handler, name="echo") -> ToolRegistry:
    registry = ToolRegistry(workspace=workspace)
    registry.register(ToolSpec(name, "回显", PARAMS, handler))
    return registry


def tool_turn(*deltas: ToolCallDelta) -> list[ChatChunk]:
    return [ChatChunk(tool_calls=deltas)]


async def collect(engine: AgentEngine, text: str):
    return [event async for event in engine.run_turn(text)]


async def test_plain_text_turn():
    model = FakeChatModel([text_turn("你", "好")])
    engine = AgentEngine(model, echo_registry())

    events = await collect(engine, "你好")

    assert [type(event) for event in events] == [
        TurnStarted,
        TextDelta,
        TextDelta,
        TurnFinished,
    ]
    assert events[-1].status is TurnStatus.COMPLETED
    assert events[-1].content == "你好"
    assert [message.role for message in engine.messages] == [
        "system",
        "user",
        "assistant",
    ]
    assert not engine.is_busy


async def test_tool_call_round_trip():
    model = FakeChatModel(
        [
            tool_turn(ToolCallDelta(0, "call_1", "echo", '{"value": "x"}')),
            text_turn("完成"),
        ]
    )
    engine = AgentEngine(model, echo_registry())

    events = await collect(engine, "调用工具")

    assert [type(event) for event in events] == [
        TurnStarted,
        ToolCallRequested,
        ToolCallCompleted,
        TextDelta,
        TurnFinished,
    ]
    requested = events[1]
    assert requested.name == "echo"
    assert requested.arguments == {"value": "x"}
    completed = events[2]
    assert completed.result.ok
    assert completed.result.content == "echo:x"

    assert [message.role for message in engine.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert engine.messages[2].tool_calls[0].id == "call_1"
    assert engine.messages[3].tool_call_id == "call_1"


async def test_fragmented_and_multiple_tool_calls():
    first_turn = [
        ChatChunk(
            tool_calls=(
                ToolCallDelta(0, "call_1", "echo", '{"val'),
                ToolCallDelta(1, "call_2", "echo", '{"value": "b"}'),
            )
        ),
        ChatChunk(tool_calls=(ToolCallDelta(0, arguments_delta='ue": "a"}'),)),
    ]
    model = FakeChatModel([first_turn, text_turn("好")])
    engine = AgentEngine(model, echo_registry())

    events = await collect(engine, "两个工具")

    requested = [e for e in events if isinstance(e, ToolCallRequested)]
    completed = [e for e in events if isinstance(e, ToolCallCompleted)]
    assert [item.arguments for item in requested] == [
        {"value": "a"},
        {"value": "b"},
    ]
    assert [item.result.content for item in completed] == ["echo:a", "echo:b"]
    assert len([m for m in engine.messages if m.role == "tool"]) == 2


async def test_tool_exception_does_not_abort_turn():
    async def boom(arguments, context):
        raise RuntimeError("坏了")

    model = FakeChatModel(
        [tool_turn(ToolCallDelta(0, "call_1", "boom", "{}")), text_turn("已处理")]
    )
    engine = AgentEngine(model, echo_registry(handler=boom, name="boom"))

    events = await collect(engine, "执行")

    completed = next(e for e in events if isinstance(e, ToolCallCompleted))
    assert not completed.result.ok
    assert completed.result.content == "Error: 坏了"
    assert isinstance(events[-1], TurnFinished)
    assert events[-1].status is TurnStatus.COMPLETED
    assert engine.messages[-2].content == "Error: 坏了"


async def test_malformed_arguments_are_not_executed():
    executed = False

    async def handler(arguments, context):
        nonlocal executed
        executed = True
        return ToolOutcome("ran")

    model = FakeChatModel(
        [tool_turn(ToolCallDelta(0, "call_1", "echo", "{oops")), text_turn("好")]
    )
    engine = AgentEngine(model, echo_registry(handler=handler))

    events = await collect(engine, "执行")

    completed = next(e for e in events if isinstance(e, ToolCallCompleted))
    assert not completed.result.ok
    assert "不是合法 JSON" in completed.result.content
    assert executed is False
    assert engine.messages[3].content.startswith("Error: 工具参数不是合法 JSON")


async def test_stream_error_keeps_history_consistent():
    model = FakeChatModel(
        [[ChatChunk(content="半截"), RuntimeError("连接中断")]]
    )
    engine = AgentEngine(model, echo_registry())

    events = await collect(engine, "你好")

    assert isinstance(events[1], TextDelta)
    assert isinstance(events[2], ErrorOccurred)
    assert events[-1].status is TurnStatus.ERROR
    assert [message.role for message in engine.messages] == ["system", "user"]


async def test_max_tool_rounds():
    model = FakeChatModel(
        [
            tool_turn(ToolCallDelta(0, "call_1", "echo", "{}")),
            tool_turn(ToolCallDelta(0, "call_2", "echo", "{}")),
        ]
    )
    engine = AgentEngine(model, echo_registry(), max_tool_rounds=1)

    events = await collect(engine, "循环")

    assert isinstance(events[-2], ErrorOccurred)
    assert events[-1].status is TurnStatus.MAX_ROUNDS
    assert [message.role for message in engine.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


async def test_busy_guard():
    model = FakeChatModel([text_turn("x")])
    model.gate = asyncio.Event()
    engine = AgentEngine(model, echo_registry())

    task = asyncio.create_task(collect(engine, "第一次"))
    await asyncio.sleep(0.05)

    try:
        with_error = None
        try:
            await collect(engine, "第二次")
        except RuntimeError as exc:
            with_error = exc
        assert with_error is not None
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def test_cancel_while_waiting_for_model():
    model = FakeChatModel([text_turn("不会到达")])
    model.gate = asyncio.Event()
    engine = AgentEngine(model, echo_registry())
    events = []

    async def drive():
        try:
            async for event in engine.run_turn("取消我"):
                events.append(event)
        except asyncio.CancelledError:
            return

    task = asyncio.create_task(drive())
    await asyncio.sleep(0.05)
    task.cancel()
    await task

    assert events[-1].status is TurnStatus.CANCELLED
    assert [message.role for message in engine.messages] == ["system", "user"]
    assert not engine.is_busy


async def test_cancel_during_tool_batch_keeps_tool_messages():
    started = asyncio.Event()
    never = asyncio.Event()

    async def slow(arguments, context):
        started.set()
        await never.wait()
        return ToolOutcome("done")

    model = FakeChatModel(
        [
            tool_turn(
                ToolCallDelta(0, "call_1", "slow", "{}"),
                ToolCallDelta(1, "call_2", "echo", '{"value": "b"}'),
            )
        ]
    )
    engine = AgentEngine(model, echo_registry(handler=slow, name="slow"))
    events = []

    async def drive():
        try:
            async for event in engine.run_turn("取消工具"):
                events.append(event)
        except asyncio.CancelledError:
            return

    task = asyncio.create_task(drive())
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    await task

    assert events[-1].status is TurnStatus.CANCELLED
    roles = [message.role for message in engine.messages]
    assert roles == ["system", "user", "assistant", "tool", "tool"]
    tool_messages = [m for m in engine.messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["call_1", "call_2"]
    assert all(m.content == "Error: 用户取消了操作" for m in tool_messages)
    assert not engine.is_busy
