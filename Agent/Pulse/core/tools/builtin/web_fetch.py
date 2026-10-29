"""网页正文抓取工具：本地 curl 下载 HTML，trafilatura 提取 Markdown。

流程：
1. 用 subprocess 以参数列表调用本地 curl（不使用 shell=True）获取 HTML；
2. 用 trafilatura 只保留正文，输出 Markdown（标题、段落、列表、表格、链接）；
3. 去除导航栏、广告、页脚等样板内容，并限制返回长度以节省上下文 Token。

所有失败（缺少 curl、网络错误、超时、HTTP 错误、解析失败、正文为空）
都抛出 RuntimeError，由 ToolRegistry 归一为 "Error: ..." 的工具结果。
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from typing import Any, Mapping
from urllib.parse import urlparse

from core.models import ToolOutcome
from core.tools.context import ToolContext
from core.tools.spec import ToolSpec

CURL_CONNECT_TIMEOUT = 10
CURL_TIMEOUT = 30
MAX_HTML_BYTES = 5_000_000
MAX_MARKDOWN_CHARS = 20_000
STATUS_MARKER = "__PULSE_HTTP_STATUS__"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 Pulse/0.1"
)

CURL_ERROR_HINTS = {
    6: "无法解析域名",
    7: "无法连接到服务器",
    28: "请求超时",
    35: "TLS/SSL 握手失败",
    47: "重定向次数过多",
    52: "服务器未返回内容",
    56: "接收数据失败",
    60: "证书验证失败",
    63: "网页内容过大",
}


async def fetch_web_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    url = _validate_url(arguments.get("url"))
    content = await asyncio.to_thread(fetch_page_markdown, url)
    return ToolOutcome(content)


def fetch_page_markdown(url: str) -> str:
    """同步完成下载与正文提取；由 handler 放入线程池执行。"""
    html, _ = fetch_html(url)
    title, markdown = extract_markdown(html, url)

    lines = [f"原始 URL: {url}"]
    if title:
        lines.append(f"网页标题: {title}")
    lines.append("")
    lines.append("正文（Markdown）：")
    lines.append(markdown)
    return "\n".join(lines)


def build_curl_command(curl_path: str, url: str) -> list[str]:
    """构造参数列表；调用方必须用 subprocess 的列表形式且不启用 shell。"""
    return [
        curl_path,
        "--location",
        "--silent",
        "--show-error",
        "--compressed",
        "--proto",
        "=http,https",
        "--proto-redir",
        "=http,https",
        "--connect-timeout",
        str(CURL_CONNECT_TIMEOUT),
        "--max-time",
        str(CURL_TIMEOUT),
        "--max-redirs",
        "5",
        "--max-filesize",
        str(MAX_HTML_BYTES),
        "--user-agent",
        USER_AGENT,
        "--header",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "--header",
        "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "--write-out",
        f"\n{STATUS_MARKER}%{{http_code}}",
        url,
    ]


def fetch_html(url: str) -> tuple[str, int]:
    """调用 curl 获取 HTML，返回 (解码后的 HTML, HTTP 状态码)。"""
    curl_path = shutil.which("curl")
    if not curl_path:
        raise RuntimeError(
            "未找到 curl 程序，无法访问网页；请先安装 curl 并确保它在 PATH 中"
        )

    try:
        completed = subprocess.run(
            build_curl_command(curl_path, url),
            capture_output=True,
            timeout=CURL_TIMEOUT + 15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"网页访问超时（超过 {CURL_TIMEOUT} 秒）") from exc
    except OSError as exc:
        raise RuntimeError(f"无法启动 curl: {exc}") from exc

    if completed.returncode != 0:
        raise RuntimeError(_curl_error_message(completed))

    body, status = split_curl_output(completed.stdout)
    if not 200 <= status < 400:
        raise RuntimeError(f"网页访问失败（HTTP {status}）")
    if len(body) > MAX_HTML_BYTES:
        raise RuntimeError(
            f"网页内容过大（超过 {MAX_HTML_BYTES // 1_000_000} MB），已放弃解析"
        )

    return decode_html(body), status


def split_curl_output(stdout: bytes) -> tuple[bytes, int]:
    """拆分 curl 的页面正文与 --write-out 附加的状态码。"""
    body, found, tail = stdout.rpartition(
        f"\n{STATUS_MARKER}".encode("ascii")
    )
    if not found:
        raise RuntimeError("无法解析 curl 的输出（缺少 HTTP 状态码）")
    try:
        status = int(tail.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"无法解析 curl 返回的 HTTP 状态码: {tail[:20]!r}"
        ) from exc
    return body, status


def extract_markdown(html: str, url: str) -> tuple[str, str]:
    """用 trafilatura 提取正文，返回 (标题, Markdown)。"""
    try:
        import trafilatura
    except ImportError as exc:
        raise RuntimeError(
            "缺少 trafilatura 依赖，无法解析网页；请运行 pip install trafilatura"
        ) from exc

    title = ""
    try:
        metadata = trafilatura.extract_metadata(html, default_url=url)
        if metadata is not None:
            title = (getattr(metadata, "title", "") or "").strip()
    except Exception:
        # 标题只是锦上添花，元数据解析失败不影响正文提取
        title = ""

    try:
        markdown = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_images=False,
            include_formatting=True,
            include_links=True,
            deduplicate=True,
        )
    except Exception as exc:
        raise RuntimeError(f"网页 HTML 解析失败: {exc}") from exc

    if not isinstance(markdown, str) or not markdown.strip():
        raise RuntimeError(
            "无法从该网页提取正文（页面可能由 JavaScript 动态渲染，或内容为空）"
        )

    text = markdown.strip()
    if len(text) > MAX_MARKDOWN_CHARS:
        text = (
            text[:MAX_MARKDOWN_CHARS].rstrip()
            + "\n\n…（正文过长，已截断）"
        )
    return title, text


def decode_html(raw: bytes) -> str:
    """按 meta charset、UTF-8、GB18030 的顺序解码网页。"""
    candidates: list[str] = []
    match = re.search(
        rb"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", raw[:4096], re.IGNORECASE
    )
    if match:
        candidates.append(match.group(1).decode("ascii", "ignore"))
    candidates.extend(["utf-8-sig", "gb18030"])

    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _curl_error_message(completed: subprocess.CompletedProcess) -> str:
    code = completed.returncode
    hint = CURL_ERROR_HINTS.get(code)
    label = f"网页访问失败（curl 退出码 {code}"
    if hint:
        label += f"，{hint}"
    label += "）"
    stderr = _decode_stderr(completed.stderr).strip()
    if stderr:
        return f"{label}: {stderr}"
    return label


def _decode_stderr(raw: bytes | None) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _validate_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("缺少参数 url（要抓取的网页地址）")
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url 必须是完整的 http:// 或 https:// 地址")
    return url


FETCH_WEB_SPEC = ToolSpec(
    name="fetchWeb",
    description=(
        "获取指定网页的正文内容并转换为 Markdown（保留标题、段落、列表、表格和链接），"
        "自动去除导航栏、广告、页脚等无关内容，同时返回原始 URL。"
        "当需要阅读 searchWeb 返回的参考来源全文，或用户直接给出网页 URL 时调用；"
        "不要猜测网页内容。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要抓取的完整网页地址，必须以 http:// 或 https:// 开头",
            }
        },
        "required": ["url"],
    },
    handler=fetch_web_handler,
)
