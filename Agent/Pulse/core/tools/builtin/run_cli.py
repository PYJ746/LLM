"""本地命令行工具：以子进程方式执行已安装的 CLI 程序。

教学用途：让 Agent 完整体验「调用本地工具 → 获取反馈 → 决定下一步」的循环。

安全边界（本阶段有意简化）：
- 不做命令白名单、黑名单或审批；
- 命令以运行 Pulse 的当前用户权限执行，仅应在受控教学环境中使用。

执行方式：
- command 与 args 拼装为列表，subprocess.run(shell=False)；
- 不拼接 Shell 字符串，因此管道、重定向等语法需要显式调用 shell 程序；
- stdin 接到 DEVNULL，避免交互式程序卡住；
- 30 秒超时，stdout/stderr 分别截断并标注。
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path
from typing import Any, Mapping

from core.models import ToolOutcome
from core.tools.context import ToolContext
from core.tools.spec import ToolSpec

CLI_TIMEOUT = 30
MAX_STREAM_CHARS = 8000


async def run_cli_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    command, args = _parse_arguments(arguments)
    content = await asyncio.to_thread(
        _run_command, command, args, context.workspace
    )
    return ToolOutcome(content)


def _parse_arguments(
    arguments: Mapping[str, Any],
) -> tuple[str, list[str]]:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("缺少参数 command（要执行的程序名称，例如 git、python）")
    command = command.strip()

    raw_args = arguments.get("args", [])
    if raw_args is None:
        raw_args = []
    if not isinstance(raw_args, (list, tuple)):
        raise ValueError(
            "参数 args 必须是字符串数组，例如 [\"status\", \"--short\"]"
        )

    args: list[str] = []
    for item in raw_args:
        if not isinstance(item, str):
            raise ValueError("参数 args 中的每一项都必须是字符串")
        args.append(item)
    return command, args


def _run_command(command: str, args: list[str], workspace: Path) -> str:
    argv = [command, *args]
    try:
        completed = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=str(workspace),
            timeout=CLI_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(_timeout_message(exc)) from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"无法执行命令 {command!r}: {exc}"
            "（请确认程序已安装并在 PATH 中；command 只放程序名，参数请放入 args）"
        ) from exc

    stdout = _truncate_output(_decode_output(completed.stdout))
    stderr = _truncate_output(_decode_output(completed.stderr))
    return "\n".join(
        [
            f"命令: {shlex.join(argv)}",
            f"退出码: {completed.returncode}",
            "",
            "标准输出:",
            stdout or "（无）",
            "",
            "标准错误:",
            stderr or "（无）",
        ]
    )


def _timeout_message(exc: subprocess.TimeoutExpired) -> str:
    lines = [f"命令执行超时（超过 {CLI_TIMEOUT} 秒），已终止"]
    stdout = _truncate_output(_decode_output(exc.stdout))
    stderr = _truncate_output(_decode_output(exc.stderr))
    if stdout:
        lines.extend(["", "标准输出（超时前的部分输出）:", stdout])
    if stderr:
        lines.extend(["", "标准错误（超时前的部分输出）:", stderr])
    return "\n".join(lines)


def _truncate_output(text: str) -> str:
    if len(text) <= MAX_STREAM_CHARS:
        return text
    omitted = len(text) - MAX_STREAM_CHARS
    return (
        text[:MAX_STREAM_CHARS].rstrip()
        + f"\n…（输出过长，已截断：仅保留前 {MAX_STREAM_CHARS} 字符，"
        f"其余 {omitted} 字符未显示）"
    )


def _decode_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


RUN_CLI_SPEC = ToolSpec(
    name="RunCli",
    description=(
        "在本地执行任意已安装的命令行程序（CLI），返回标准输出、标准错误和退出码。"
        "command 只填程序名称或完整路径（如 \"git\"、\"python\"、\"npm\"），"
        "参数必须逐项放入 args 字符串数组（如 [\"status\", \"--short\"]），"
        "不要拼接 Shell 命令字符串；不支持管道、重定向等 Shell 语法。"
        "命令在 Pulse 的 workspace 目录中执行，超过 30 秒会被终止，"
        "过长的输出会被截断并标注。请根据退出码判断命令是否成功。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的程序名称或完整路径，例如 git、python、npm",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "程序参数列表，每个参数单独一项；"
                    "没有参数时传空数组 []，例如 [\"status\", \"--short\"]"
                ),
            },
        },
        "required": ["command"],
    },
    handler=run_cli_handler,
)
