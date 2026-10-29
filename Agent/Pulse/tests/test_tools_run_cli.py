from __future__ import annotations

import subprocess
import sys

import pytest

from core.tools.builtin import run_cli
from core.tools.builtin.run_cli import (
    MAX_STREAM_CHARS,
    _decode_output,
    _parse_arguments,
    _run_command,
    _truncate_output,
)
from core.tools.defaults import build_default_registry


def test_run_cli_is_registered_with_command_and_args_schema():
    registry = build_default_registry()
    spec = registry.get("RunCli")

    assert spec is not None
    assert spec.parameters["required"] == ["command"]
    assert spec.parameters["properties"]["args"]["type"] == "array"
    assert spec.parameters["properties"]["args"]["items"]["type"] == "string"


def test_parse_arguments_defaults_to_empty_args_list():
    assert _parse_arguments({"command": "git"}) == ("git", [])
    assert _parse_arguments({"command": "git", "args": None}) == ("git", [])
    assert _parse_arguments({"command": "git", "args": ["status"]}) == (
        "git",
        ["status"],
    )


def test_parse_arguments_rejects_invalid_input():
    with pytest.raises(ValueError, match="command"):
        _parse_arguments({})
    with pytest.raises(ValueError, match="字符串数组"):
        _parse_arguments({"command": "git", "args": "status"})
    with pytest.raises(ValueError, match="每一项都必须是字符串"):
        _parse_arguments({"command": "git", "args": ["status", 1]})


async def test_returns_stdout_stderr_and_exit_code(tmp_path):
    code = (
        "import sys\n"
        "print('hello out')\n"
        "print('hello err', file=sys.stderr)\n"
        "sys.exit(3)\n"
    )
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute(
        "call_1",
        "RunCli",
        {"command": sys.executable, "args": ["-c", code]},
    )

    # 非零退出码是有效反馈，不是工具异常
    assert result.ok is True
    assert "退出码: 3" in result.content
    assert "hello out" in result.content
    assert "hello err" in result.content
    assert "标准输出:" in result.content
    assert "标准错误:" in result.content


async def test_command_runs_in_workspace(tmp_path):
    code = "import os; print(os.path.basename(os.getcwd()))"
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute(
        "call_1",
        "RunCli",
        {"command": sys.executable, "args": ["-c", code]},
    )

    assert result.ok is True
    assert tmp_path.name in result.content


def test_subprocess_uses_argv_list_and_shell_false(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, b"ok", b"")

    monkeypatch.setattr(run_cli.subprocess, "run", fake_run)

    content = _run_command("git", ["status", "--short"], tmp_path)

    assert captured["argv"] == ["git", "status", "--short"]
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["timeout"] == run_cli.CLI_TIMEOUT
    assert "退出码: 0" in content


async def test_missing_command_is_reported(tmp_path):
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute("call_1", "RunCli", {"command": "  "})

    assert not result.ok
    assert "command" in result.content


async def test_unknown_program_is_reported(tmp_path):
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute(
        "call_1",
        "RunCli",
        {"command": "pulse-no-such-command-12345", "args": []},
    )

    assert not result.ok
    assert "无法执行命令" in result.content
    assert "PATH" in result.content


async def test_timeout_is_reported_with_partial_output(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            args[0], 30, output=b"partial out", stderr=b"partial err"
        )

    monkeypatch.setattr(run_cli.subprocess, "run", fake_run)
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute(
        "call_1", "RunCli", {"command": "slow-command", "args": []}
    )

    assert not result.ok
    assert "超时" in result.content
    assert "partial out" in result.content
    assert "partial err" in result.content


async def test_long_output_is_truncated_and_labelled(tmp_path):
    code = "print('x' * 20000)"
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute(
        "call_1",
        "RunCli",
        {"command": sys.executable, "args": ["-c", code]},
    )

    assert result.ok is True
    assert "已截断" in result.content
    assert "x" * MAX_STREAM_CHARS in result.content
    assert "x" * (MAX_STREAM_CHARS + 1) not in result.content


async def test_empty_output_is_labelled(tmp_path):
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute(
        "call_1",
        "RunCli",
        {"command": sys.executable, "args": ["-c", "pass"]},
    )

    assert result.ok is True
    assert result.content.count("（无）") == 2


def test_decode_output_handles_gbk():
    assert _decode_output("中文输出".encode("gbk")) == "中文输出"
    assert _decode_output(None) == ""
    assert _decode_output("already str") == "already str"


def test_truncate_output_marks_omitted_characters():
    text = "a" * (MAX_STREAM_CHARS + 50)

    truncated = _truncate_output(text)

    assert "已截断" in truncated
    assert "50 字符未显示" in truncated
    assert len(truncated) < len(text)
