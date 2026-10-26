from __future__ import annotations

import pytest

from core.models import ToolOutcome
from core.tools.defaults import build_default_registry
from core.tools.registry import ToolRegistry
from core.tools.spec import ToolSpec


async def echo(arguments, context):
    return ToolOutcome(f"echo: {arguments.get('value')}")


def make_echo_spec(name="echo") -> ToolSpec:
    return ToolSpec(
        name=name,
        description="回显",
        parameters={"type": "object", "properties": {}},
        handler=echo,
    )


def test_default_tool_order_matches_practice02():
    registry = build_default_registry()
    assert registry.names == (
        "getdate",
        "isLeapYear",
        "getcwd",
        "listDirectory",
        "getFileType",
        "readTextFile",
        "createDirectory",
        "deleteDirectory",
        "deleteFile",
        "renamePath",
        "searchWeb",
        "fetchWeb",
        "RunCli",
    )


def test_openai_envelope():
    registry = build_default_registry()
    tools = registry.to_openai_tools()
    assert len(tools) == 13
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "getdate"
    assert "parameters" in tools[0]["function"]


def test_duplicate_registration_rejected():
    registry = ToolRegistry()
    registry.register(make_echo_spec())
    with pytest.raises(ValueError, match="重复注册"):
        registry.register(make_echo_spec())


async def test_unknown_tool_returns_error():
    registry = ToolRegistry()
    result = await registry.execute("call_1", "missing", {})
    assert not result.ok
    assert result.content == "Error: 未知工具 missing"


async def test_handler_exception_is_normalized():
    async def boom(arguments, context):
        raise ValueError("炸了")

    registry = ToolRegistry()
    registry.register(
        ToolSpec("boom", "错误", {"type": "object", "properties": {}}, boom)
    )
    result = await registry.execute("call_1", "boom", {})
    assert not result.ok
    assert result.content == "Error: 炸了"
    assert result.duration_ms >= 0
