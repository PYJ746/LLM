"""时间与闰年工具。

getdate 保留原实现的多级回退：PATH 中的 date → Git for Windows 自带
date.exe / bash.exe → PATH 中的 bash。同步子进程通过 asyncio.to_thread
执行，避免阻塞前端事件循环。
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from core.models import ToolOutcome
from core.tools.context import ToolContext
from core.tools.spec import ToolSpec

GIT_DATE_FORMAT = "+%Y-%m-%d %H:%M:%S"


def _git_install_roots():
    """找出可能的 Git 安装目录，用于定位 Git 自带的 date.exe。"""
    roots = []

    git_exe = shutil.which("git")
    if git_exe:
        # <git>\cmd\git.exe -> <git>
        roots.append(Path(git_exe).resolve().parent.parent)

    if sys.platform == "win32":
        try:
            import winreg

            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\GitForWindows") as key:
                        install_path = winreg.QueryValueEx(key, "InstallPath")[0]
                        roots.append(Path(install_path))
                except OSError:
                    continue
        except ImportError:
            pass

        roots.extend(
            [
                Path(r"C:\Program Files\Git"),
                Path(r"C:\Program Files (x86)\Git"),
            ]
        )

    return roots


def _date_commands():
    """按优先级列出可用的 date 命令；Git for Windows 的 usr\\bin 通常不在 PATH 中。"""
    commands = []

    # 1. PATH 中直接有 date（Linux / macOS / Git Bash 环境）
    if shutil.which("date"):
        commands.append(["date", GIT_DATE_FORMAT])

    # 2. Git for Windows 自带的 date.exe / bash.exe
    for root in _git_install_roots():
        for exe in (root / "usr" / "bin" / "date.exe", root / "bin" / "date.exe"):
            if exe.is_file():
                commands.append([str(exe), GIT_DATE_FORMAT])
        for exe in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if exe.is_file():
                commands.append([str(exe), "-c", f"date '{GIT_DATE_FORMAT}'"])

    # 3. PATH 中有 bash 但没有 date
    if shutil.which("bash"):
        commands.append(["bash", "-c", f"date '{GIT_DATE_FORMAT}'"])

    # 去重并保持顺序
    unique = []
    for command in commands:
        if command not in unique:
            unique.append(command)
    return unique


def getdate() -> str:
    """调用本地 date 命令获取当前日期和时间，而不是用 Python 自己拼接。"""
    commands = _date_commands()
    if not commands:
        raise RuntimeError("没有找到可用的 date 命令（未检测到 Git Bash 或 date.exe）")

    last_error = None
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
        except FileNotFoundError as exc:
            last_error = exc
            continue
        except subprocess.TimeoutExpired:
            last_error = RuntimeError("date 命令执行超时")
            continue

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        last_error = RuntimeError(result.stderr.strip() or "date 命令执行失败")

    raise RuntimeError(f"无法获取日期时间: {last_error}")


def is_leap_year(year: int | str) -> str:
    """按闰年规则计算：能被 4 整除且不能被 100 整除，或能被 400 整除。"""
    year = int(year)
    leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    if leap:
        return f"{year} 年是闰年"
    return f"{year} 年不是闰年"


async def getdate_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    return ToolOutcome(await asyncio.to_thread(getdate))


async def is_leap_year_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    year = arguments.get("year")
    if year is None or (isinstance(year, str) and not year.strip()):
        raise ValueError("缺少参数 year")
    return ToolOutcome(is_leap_year(year))


GETDATE_SPEC = ToolSpec(
    name="getdate",
    description=(
        "获取当前电脑的本地日期和时间。"
        "当用户询问现在几点、今天几号、当前日期/时间等问题时必须调用。"
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    handler=getdate_handler,
)

IS_LEAP_YEAR_SPEC = ToolSpec(
    name="isLeapYear",
    description=(
        "判断指定年份是否为闰年。"
        "闰年规则：能被 4 整除且不能被 100 整除，或能被 400 整除。"
        "用户询问某一年是否为闰年时必须调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "year": {
                "type": "integer",
                "description": "要判断的年份，例如 2024",
            }
        },
        "required": ["year"],
    },
    handler=is_leap_year_handler,
)
