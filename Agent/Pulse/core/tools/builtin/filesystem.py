"""本地文件系统工具。

语义与 Practice02/chat.py 保持一致，包括：
- 相对路径相对 workspace 解析，绝对路径保持原行为；
- 纯文本判定、UTF-8/GBK 解码、200KB 截断；
- 删除前通过 ToolContext.confirm() 请求前端确认；
- 拒绝删除磁盘根目录、workspace 与当前进程工作目录及其父目录。
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from core.models import ToolOutcome
from core.tools.context import ToolContext
from core.tools.spec import ToolSpec

MAX_TEXT_BYTES = 200_000

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".py", ".pyi", ".json", ".jsonl", ".csv", ".tsv",
    ".ini", ".cfg", ".conf", ".log", ".xml", ".html", ".htm", ".css", ".js",
    ".ts", ".jsx", ".tsx", ".yaml", ".yml", ".toml", ".sh", ".bat", ".cmd",
    ".ps1", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb",
    ".php", ".sql", ".properties", ".tex", ".rst", ".env",
}

TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-javascript",
    "application/x-yaml",
    "application/x-sh",
    "application/x-httpd-php",
}


def _required_argument(arguments: Mapping[str, Any], key: str) -> Any:
    value = arguments.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"缺少参数 {key}")
    return value


def list_directory(path: str, context: ToolContext) -> str:
    directory = context.resolve_path(path)
    if not directory.exists():
        raise FileNotFoundError(f"目录不存在: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"不是目录: {directory}")

    entries = sorted(
        os.scandir(directory),
        key=lambda entry: (not entry.is_dir(follow_symlinks=False), entry.name.lower()),
    )
    lines = [f"目录: {directory}", f"共 {len(entries)} 项"]
    if not entries:
        lines.append("(空目录)")
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            lines.append(f"[目录] {entry.name}")
        elif entry.is_symlink():
            lines.append(f"[链接] {entry.name}")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = -1
            lines.append(f"[文件] {entry.name} ({size} 字节)")
    return "\n".join(lines)


def get_file_type(path: str, context: ToolContext) -> str:
    target = context.resolve_path(path)
    if not target.exists():
        raise FileNotFoundError(f"路径不存在: {target}")
    if target.is_dir():
        return f"{target.name} 的类型: 目录；路径: {target}"

    mime, encoding = mimetypes.guess_type(str(target))
    suffix = target.suffix.lower() or "(无扩展名)"
    kind = mime or "未知"
    if encoding:
        kind += f"；编码: {encoding}"
    return f"{target.name} 的类型: {kind}；扩展名: {suffix}；路径: {target}"


def read_text_file(path: str, context: ToolContext) -> str:
    target = context.resolve_path(path)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"是目录而不是文件: {target}")

    mime, _ = mimetypes.guess_type(str(target))
    looks_text = (
        target.suffix.lower() in TEXT_SUFFIXES
        or (mime is not None and (mime.startswith("text/") or mime in TEXT_MIME_TYPES))
        or target.suffix == ""
    )
    if not looks_text:
        raise ValueError(f"仅支持纯文本文件，{target.name} 的类型是 {mime or '未知'}")

    size = target.stat().st_size
    with target.open("rb") as file:
        data = file.read(MAX_TEXT_BYTES + 1)
    if b"\x00" in data:
        raise ValueError(f"仅支持纯文本文件，{target.name} 包含二进制内容")

    truncated = len(data) > MAX_TEXT_BYTES
    if truncated:
        data = data[:MAX_TEXT_BYTES]

    text = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"无法以 UTF-8 或 GBK 解码 {target.name}，可能不是纯文本文件")

    header = f"文件: {target}\n"
    if truncated:
        header += f"(文件共 {size} 字节，仅显示前 {MAX_TEXT_BYTES} 字节)\n"
    return f"{header}---\n{text}"


def create_directory(path: str, context: ToolContext) -> str:
    target = context.resolve_path(path)
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"同名文件已存在: {target}")
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    if existed:
        return f"目录已存在: {target}"
    return f"已创建目录: {target}"


def _guard_delete_target(target: Path, context: ToolContext) -> None:
    if target.parent == target:
        raise ValueError(f"拒绝删除磁盘根目录: {target}")

    for base in (context.workspace.resolve(), Path.cwd().resolve()):
        if target == base or base.is_relative_to(target):
            raise ValueError(f"拒绝删除当前工作目录或其父目录: {target}")


def rename_path(source: str, destination: str, context: ToolContext) -> str:
    src = context.resolve_path(source)
    dst = context.resolve_path(destination)

    if not src.exists():
        raise FileNotFoundError(f"源路径不存在: {src}")
    if src == dst:
        raise ValueError("源路径和目标路径相同，无需重命名")
    if dst.exists():
        raise FileExistsError(f"目标路径已存在，拒绝覆盖: {dst}")
    if not dst.parent.is_dir():
        raise FileNotFoundError(f"目标所在的目录不存在: {dst.parent}")

    is_dir = src.is_dir()
    src.rename(dst)
    kind = "目录" if is_dir else "文件"
    return f"已重命名{kind}: {src} -> {dst}"


# ---------------------------------------------------------------------------
# 异步处理器
# ---------------------------------------------------------------------------


async def get_cwd_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    return ToolOutcome(f"当前工作目录: {context.workspace}")


async def list_directory_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    return ToolOutcome(
        await asyncio.to_thread(
            list_directory, arguments.get("path") or ".", context
        )
    )


async def get_file_type_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    return ToolOutcome(
        get_file_type(_required_argument(arguments, "path"), context)
    )


async def read_text_file_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    return ToolOutcome(
        await asyncio.to_thread(
            read_text_file, _required_argument(arguments, "path"), context
        )
    )


async def create_directory_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    return ToolOutcome(
        await asyncio.to_thread(
            create_directory, _required_argument(arguments, "path"), context
        )
    )


async def delete_directory_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    target = context.resolve_path(_required_argument(arguments, "path"))
    if not target.exists():
        raise FileNotFoundError(f"目录不存在: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是目录，请使用 deleteFile: {target}")
    _guard_delete_target(target, context)

    if not await context.confirm("删除目录（含所有内容）", str(target)):
        return ToolOutcome("用户取消了删除操作", cancelled=True)

    await asyncio.to_thread(shutil.rmtree, target)
    return ToolOutcome(f"已删除目录: {target}")


async def delete_file_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    target = context.resolve_path(_required_argument(arguments, "path"))
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"是目录，请使用 deleteDirectory: {target}")

    if not await context.confirm("删除文件", str(target)):
        return ToolOutcome("用户取消了删除操作", cancelled=True)

    await asyncio.to_thread(target.unlink)
    return ToolOutcome(f"已删除文件: {target}")


async def rename_path_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    return ToolOutcome(
        await asyncio.to_thread(
            rename_path,
            _required_argument(arguments, "source"),
            _required_argument(arguments, "destination"),
            context,
        )
    )


# ---------------------------------------------------------------------------
# 工具声明
# ---------------------------------------------------------------------------

GET_CWD_SPEC = ToolSpec(
    name="getcwd",
    description="获取当前工作目录的绝对路径。用户询问当前目录、工作目录时必须调用。",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    handler=get_cwd_handler,
)

LIST_DIRECTORY_SPEC = ToolSpec(
    name="listDirectory",
    description=(
        "列出指定目录下的所有文件和子目录（不递归）。"
        "用户要求查看某个目录的文件列表时必须调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目录路径，可以是绝对路径或相对当前工作目录的路径；不填则使用当前工作目录",
            }
        },
        "required": [],
    },
    handler=list_directory_handler,
)

GET_FILE_TYPE_SPEC = ToolSpec(
    name="getFileType",
    description="获取指定路径的文件类型（文件/目录、扩展名、MIME 类型）。",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件或目录路径，可以是绝对路径或相对路径",
            }
        },
        "required": ["path"],
    },
    handler=get_file_type_handler,
)

READ_TEXT_FILE_SPEC = ToolSpec(
    name="readTextFile",
    description=(
        "读取指定纯文本文件的内容，例如 .txt、.md、.py、.json、.csv、.ini、.log 等。"
        "不支持图片、压缩包、Office 文档等二进制文件。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要读取的纯文本文件路径，可以是绝对路径或相对路径",
            }
        },
        "required": ["path"],
    },
    handler=read_text_file_handler,
)

CREATE_DIRECTORY_SPEC = ToolSpec(
    name="createDirectory",
    description=(
        "创建目录；父目录不存在时会一并创建，目录已存在时不会报错。"
        "用户要求新建文件夹/目录时必须调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要创建的目录路径，可以是绝对路径或相对路径",
            }
        },
        "required": ["path"],
    },
    handler=create_directory_handler,
)

DELETE_DIRECTORY_SPEC = ToolSpec(
    name="deleteDirectory",
    description=(
        "删除指定目录及其中的所有内容（支持非空目录）。"
        "该操作不可恢复，程序会在执行前向用户请求确认。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要删除的目录路径",
            }
        },
        "required": ["path"],
    },
    handler=delete_directory_handler,
)

DELETE_FILE_SPEC = ToolSpec(
    name="deleteFile",
    description=(
        "删除指定的文件。该操作不可恢复，程序会在执行前向用户请求确认。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要删除的文件路径",
            }
        },
        "required": ["path"],
    },
    handler=delete_file_handler,
)

RENAME_PATH_SPEC = ToolSpec(
    name="renamePath",
    description=(
        "重命名文件或目录，也可以把文件/目录移动到另一个目录。"
        "目标路径已存在时不会覆盖，会返回错误。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "原文件或目录的路径",
            },
            "destination": {
                "type": "string",
                "description": "新的路径，可以是新名称，也可以是包含目录的新路径",
            },
        },
        "required": ["source", "destination"],
    },
    handler=rename_path_handler,
)
