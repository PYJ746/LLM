import configparser
import json
import mimetypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests


SYSTEM_PROMPT = (
    "你是一个可以调用工具获取真实信息和操作本地文件的助手。"
    "当用户询问当前日期、时间、今天几号、星期几等问题时，"
    "必须调用 getdate 工具获取结果，不要猜测，"
    "也不要在没有调用工具的情况下声称无法获取。"
    "当用户询问某一年是否为闰年时，必须调用 isLeapYear 工具计算，"
    "即使你知道答案也要调用。如果问题是“今年”，先调用 getdate 获取当前年份，"
    "再调用 isLeapYear。"
    "涉及本地文件操作时，必须调用对应工具："
    "查看当前工作目录用 getcwd；列出目录内容用 listDirectory；"
    "查询文件类型用 getFileType；读取文本文件用 readTextFile；"
    "创建目录用 createDirectory；删除目录用 deleteDirectory；删除文件用 deleteFile；"
    "重命名文件或目录用 renamePath。"
    "不要猜测文件内容或目录结构，也不要在未调用工具时声称操作已完成。"
    "删除操作会由程序向用户请求确认。"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getdate",
            "description": (
                "获取当前电脑的本地日期和时间。"
                "当用户询问现在几点、今天几号、当前日期/时间等问题时必须调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": (
                "判断指定年份是否为闰年。"
                "闰年规则：能被 4 整除且不能被 100 整除，或能被 400 整除。"
                "用户询问某一年是否为闰年时必须调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "要判断的年份，例如 2024",
                    }
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getcwd",
            "description": "获取当前工作目录的绝对路径。用户询问当前目录、工作目录时必须调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDirectory",
            "description": (
                "列出指定目录下的所有文件和子目录（不递归）。"
                "用户要求查看某个目录的文件列表时必须调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录路径，可以是绝对路径或相对当前工作目录的路径；不填则使用当前工作目录",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定路径的文件类型（文件/目录、扩展名、MIME 类型）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件或目录路径，可以是绝对路径或相对路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readTextFile",
            "description": (
                "读取指定纯文本文件的内容，例如 .txt、.md、.py、.json、.csv、.ini、.log 等。"
                "不支持图片、压缩包、Office 文档等二进制文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要读取的纯文本文件路径，可以是绝对路径或相对路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDirectory",
            "description": (
                "创建目录；父目录不存在时会一并创建，目录已存在时不会报错。"
                "用户要求新建文件夹/目录时必须调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要创建的目录路径，可以是绝对路径或相对路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteDirectory",
            "description": (
                "删除指定目录及其中的所有内容（支持非空目录）。"
                "该操作不可恢复，程序会在执行前向用户请求确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的目录路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": (
                "删除指定的文件。该操作不可恢复，程序会在执行前向用户请求确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要删除的文件路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "renamePath",
            "description": (
                "重命名文件或目录，也可以把文件/目录移动到另一个目录。"
                "目标路径已存在时不会覆盖，会返回错误。"
            ),
            "parameters": {
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
        },
    },
]


def load_config(path=None):
    if path:
        candidates = [Path(path)]
    else:
        # 从脚本所在目录逐级向上找，这样多个练习可以共用根目录的一份 config.ini
        here = Path(__file__).resolve().parent
        candidates = [d / "config.ini" for d in (here, *here.parents[:2])]

    for candidate in candidates:
        if candidate.is_file():
            conf = configparser.ConfigParser()
            conf.read(candidate, encoding="utf-8")
            llm = conf["llm"]
            return llm["base_url"], llm["api_key"], llm["model"]

    raise FileNotFoundError(f"找不到配置文件，已查找: {[str(c) for c in candidates]}")


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

        roots.extend([Path(r"C:\Program Files\Git"), Path(r"C:\Program Files (x86)\Git")])

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


def getdate():
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
        except FileNotFoundError as e:
            last_error = e
            continue
        except subprocess.TimeoutExpired:
            last_error = RuntimeError("date 命令执行超时")
            continue

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        last_error = RuntimeError(result.stderr.strip() or "date 命令执行失败")

    raise RuntimeError(f"无法获取日期时间: {last_error}")


def is_leap_year(year):
    """用 Python 代码按闰年规则计算：能被 4 整除且不能被 100 整除，或能被 400 整除。"""
    year = int(year)
    leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    if leap:
        return f"{year} 年是闰年"
    return f"{year} 年不是闰年"


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


def _resolve_path(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("路径不能为空")
    return Path(path).expanduser().resolve()


def _required_argument(arguments, key):
    value = arguments.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"缺少参数 {key}")
    return value


def _confirm(action, target):
    answer = input(f"[确认] 即将{action}: {target}\n确认执行? [y/N]: ")
    return answer.strip().lower() in ("y", "yes")


def get_cwd():
    return f"当前工作目录: {Path.cwd()}"


def list_directory(path="."):
    directory = _resolve_path(path)
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


def get_file_type(path):
    target = _resolve_path(path)
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


def read_text_file(path):
    target = _resolve_path(path)
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
        raise ValueError(
            f"仅支持纯文本文件，{target.name} 的类型是 {mime or '未知'}"
        )

    size = target.stat().st_size
    with target.open("rb") as f:
        data = f.read(MAX_TEXT_BYTES + 1)
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


def create_directory(path):
    target = _resolve_path(path)
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"同名文件已存在: {target}")
    existed = target.exists()
    target.mkdir(parents=True, exist_ok=True)
    if existed:
        return f"目录已存在: {target}"
    return f"已创建目录: {target}"


def delete_directory(path):
    target = _resolve_path(path)
    if not target.exists():
        raise FileNotFoundError(f"目录不存在: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是目录，请使用 deleteFile: {target}")
    if target.parent == target:
        raise ValueError(f"拒绝删除磁盘根目录: {target}")

    cwd = Path.cwd().resolve()
    if target == cwd or cwd.is_relative_to(target):
        raise ValueError(f"拒绝删除当前工作目录或其父目录: {target}")

    if not _confirm("删除目录（含所有内容）", target):
        return "用户取消了删除操作"

    shutil.rmtree(target)
    return f"已删除目录: {target}"


def delete_file(path):
    target = _resolve_path(path)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"是目录，请使用 deleteDirectory: {target}")

    if not _confirm("删除文件", target):
        return "用户取消了删除操作"

    target.unlink()
    return f"已删除文件: {target}"


def rename_path(source, destination):
    src = _resolve_path(source)
    dst = _resolve_path(destination)

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


def call_tool(name, arguments):
    if name == "getdate":
        return getdate()
    if name == "isLeapYear":
        return is_leap_year(_required_argument(arguments, "year"))
    if name == "getcwd":
        return get_cwd()
    if name == "listDirectory":
        return list_directory(arguments.get("path") or ".")
    if name == "getFileType":
        return get_file_type(_required_argument(arguments, "path"))
    if name == "readTextFile":
        return read_text_file(_required_argument(arguments, "path"))
    if name == "createDirectory":
        return create_directory(_required_argument(arguments, "path"))
    if name == "deleteDirectory":
        return delete_directory(_required_argument(arguments, "path"))
    if name == "deleteFile":
        return delete_file(_required_argument(arguments, "path"))
    if name == "renamePath":
        return rename_path(
            _required_argument(arguments, "source"),
            _required_argument(arguments, "destination"),
        )
    return f"Error: 未知工具 {name}"


def stream_completion(base_url, api_key, model, messages):
    """发起一次流式请求，返回 (文本内容, tool_calls 列表)。"""
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "tools": TOOLS,
            "stream": True,
        },
        stream=True,
        timeout=60,
    )
    response.raise_for_status()

    reply = []
    tool_calls = {}
    for line in response.iter_lines():
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            break
        delta = json.loads(data)["choices"][0]["delta"]

        content = delta.get("content") or ""
        if content:
            reply.append(content)
            print(content, end="", flush=True)

        # 流式返回的 tool_calls 是分片的，按 index 拼接 arguments
        for piece in delta.get("tool_calls") or []:
            index = piece.get("index", 0)
            slot = tool_calls.setdefault(
                index,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if piece.get("id"):
                slot["id"] = piece["id"]
            function = piece.get("function") or {}
            if function.get("name"):
                slot["function"]["name"] = function["name"]
            if function.get("arguments"):
                slot["function"]["arguments"] += function["arguments"]

    print()
    return "".join(reply), [tool_calls[i] for i in sorted(tool_calls)]


def main():
    try:
        base_url, api_key, model = load_config()
    except Exception as e:
        print(f"Config error: {e}")
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            prompt = input("Please input your prompt:\n")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        print("---")
        messages.append({"role": "user", "content": prompt})

        try:
            while True:
                content, tool_calls = stream_completion(base_url, api_key, model, messages)

                if not tool_calls:
                    messages.append({"role": "assistant", "content": content})
                    break

                # 先记录助手的工具调用请求，再逐个执行并回填结果
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": tool_calls,
                    }
                )

                for tool_call in tool_calls:
                    name = tool_call["function"]["name"]
                    try:
                        arguments = json.loads(tool_call["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        arguments = {}

                    # 在真正执行之前，明确显示模型调用了哪个工具、传入了什么参数
                    arguments_text = json.dumps(arguments, ensure_ascii=False)
                    print(f"[调用工具] {name}  参数: {arguments_text}")

                    try:
                        result = call_tool(name, arguments)
                    except Exception as e:
                        result = f"Error: {e}"

                    print(f"[工具结果] {name} -> {result}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result,
                        }
                    )
        except requests.HTTPError as e:
            print(f"Error: {e}")
            print(f"Server response: {e.response.text}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
