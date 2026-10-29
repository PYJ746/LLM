from __future__ import annotations

import sys

from core.models import ToolOutcome
import core.tools.builtin.datetime_tools as date_tools
from core.tools.defaults import build_default_registry


def test_leap_year_rules():
    assert date_tools.is_leap_year(2024) == "2024 年是闰年"
    assert date_tools.is_leap_year(2023) == "2023 年不是闰年"
    assert date_tools.is_leap_year(1900) == "1900 年不是闰年"
    assert date_tools.is_leap_year(2000) == "2000 年是闰年"
    assert date_tools.is_leap_year("2024") == "2024 年是闰年"


async def test_is_leap_year_tool(workspace):
    registry = build_default_registry(workspace=workspace)
    result = await registry.execute("call_1", "isLeapYear", {"year": 2024})
    assert result.ok
    assert result.content == "2024 年是闰年"


async def test_is_leap_year_requires_argument(workspace):
    registry = build_default_registry(workspace=workspace)
    result = await registry.execute("call_1", "isLeapYear", {})
    assert not result.ok
    assert "缺少参数 year" in result.content


async def test_getdate_uses_date_command(workspace, monkeypatch):
    commands = [[sys.executable, "-c", "print('2026-10-22 10:00:00')"]]
    monkeypatch.setattr(date_tools, "_date_commands", lambda: commands)

    result = await build_default_registry(workspace=workspace).execute(
        "call_1", "getdate", {}
    )

    assert result.ok
    assert result.content == "2026-10-22 10:00:00"


async def test_getdate_without_any_command(workspace, monkeypatch):
    monkeypatch.setattr(date_tools, "_date_commands", lambda: [])
    result = await build_default_registry(workspace=workspace).execute(
        "call_1", "getdate", {}
    )
    assert not result.ok
    assert "没有找到可用的 date 命令" in result.content
