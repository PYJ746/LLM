"""联网搜索工具：调用百度千帆 AI 搜索（web_search）API。

API 文档：https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5

- 端点：POST https://qianfan.baidubce.com/v2/ai_search/web_search
- 鉴权：Authorization: Bearer <API Key>（来自 config.ini 的 [search] 段）
- 请求：messages + search_source + resource_type_filter
- 响应：references[]，包含标题、URL、站点、日期与内容摘要
- 该接口只返回搜索结果，不生成模型摘要；由 Agent 根据参考来源自行作答

工具只负责把结果整理成纯文本交给模型；任何网络、鉴权或响应格式问题
都以异常抛出，由 ToolRegistry 归一为带 "Error:" 前缀的工具结果。
"""

from __future__ import annotations

from typing import Any, Mapping

import httpx

from core.models import ToolOutcome
from core.tools.context import ToolContext
from core.tools.spec import ToolSpec

SEARCH_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
SEARCH_ENGINE = "baidu_search_v2"
SEARCH_EDITION = "standard"
SEARCH_TIMEOUT = 45.0
MAX_REFERENCES = 10
MAX_SNIPPET_CHARS = 300
MAX_TITLE_CHARS = 200

MISSING_API_KEY_MESSAGE = (
    "未配置百度千帆 API Key，无法联网搜索。"
    "请在 config.ini 的 [search] 段中设置 baidu_qianfan_api_key 后重试。"
)


async def search_web_handler(
    arguments: Mapping[str, Any], context: ToolContext
) -> ToolOutcome:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("缺少参数 query（搜索关键词或问题）")

    api_key = (context.search_api_key or "").strip()
    if not api_key:
        raise RuntimeError(MISSING_API_KEY_MESSAGE)

    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
        content = await request_search(
            client, api_key=api_key, query=query.strip()
        )
    return ToolOutcome(content)


async def request_search(
    client: httpx.AsyncClient, *, api_key: str, query: str
) -> str:
    """执行一次联网搜索并返回整理后的文本。

    client 由调用方提供，便于测试时注入 httpx.MockTransport。
    """
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": query}],
        "search_source": SEARCH_ENGINE,
        "edition": SEARCH_EDITION,
        "resource_type_filter": [
            {"type": "web", "top_k": MAX_REFERENCES}
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = await client.post(
            SEARCH_ENDPOINT, headers=headers, json=payload
        )
    except httpx.TimeoutException as exc:
        raise RuntimeError("联网搜索请求超时，请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"联网搜索请求失败: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        snippet = _clean_text(response.text, 200)
        raise RuntimeError(
            f"联网搜索服务返回了无法解析的响应"
            f"（HTTP {response.status_code}）: {snippet or '空响应'}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError("联网搜索服务返回了非预期的响应格式")

    if response.status_code != 200 or _error_code(data) is not None:
        raise RuntimeError(_api_error_message(response.status_code, data))

    return format_search_result(data)


def format_search_result(data: Mapping[str, Any]) -> str:
    """把 API 响应整理为「参考来源标题 + URL + 摘要」。"""
    references = _extract_references(data)
    if not references:
        raise RuntimeError("联网搜索没有返回参考来源，请更换 query 后重试。")

    lines: list[str] = [f"参考来源（共 {len(references)} 条）："]

    for index, reference in enumerate(references, 1):
        url = str(reference["url"]).strip()
        title = _first_text(reference, "title", "web_anchor") or url
        # references[].id 是搜索结果编号，保留它便于模型对照网页内容。
        ref_id = reference.get("id")
        label = str(ref_id).strip() if ref_id not in (None, "") else str(index)
        lines.append(f"{label}. {title}")
        lines.append(f"   URL: {url}")

        meta: list[str] = []
        website = _first_text(reference, "website")
        date = _first_text(reference, "date")
        if website:
            meta.append(f"站点: {website}")
        if date:
            meta.append(f"时间: {date}")
        if meta:
            lines.append("   " + "；".join(meta))

        snippet = _clean_text(
            reference.get("snippet") or reference.get("content"),
            MAX_SNIPPET_CHARS,
        )
        if snippet:
            lines.append(f"   摘要: {snippet}")

    return "\n".join(lines)


def _extract_references(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("references")
    if not isinstance(raw, list):
        return []

    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        if url in seen:
            continue
        seen.add(url)
        references.append(item)
        if len(references) >= MAX_REFERENCES:
            break
    return references


def _error_code(data: Mapping[str, Any]) -> Any:
    """正常响应没有 code，或 code 为 0/"0"；其余都视为错误。"""
    code = data.get("code")
    return None if code in (None, "", 0, "0") else code


def _api_error_message(status_code: int, data: Mapping[str, Any]) -> str:
    parts = [f"HTTP {status_code}"]
    code = _error_code(data)
    if code is not None:
        parts.append(f"错误码 {code}")
    request_id = data.get("request_id") or data.get("requestId")
    if request_id:
        parts.append(f"request_id {request_id}")
    message = data.get("message") or data.get("error_msg") or "未知错误"
    return f"联网搜索服务返回错误（{', '.join(parts)}）：{message}"


def _first_text(data: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        text = _clean_text(value, MAX_TITLE_CHARS)
        if text:
            return text
    return ""


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


SEARCH_WEB_SPEC = ToolSpec(
    name="searchWeb",
    description=(
        "使用百度千帆 AI 搜索获取互联网上的实时信息，"
        "返回参考来源的标题、URL、站点、日期与内容摘要。"
        "当用户询问新闻、实时数据、最新事件、近期动态、价格行情等需要联网核实的问题时"
        "必须调用，不要凭记忆回答。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "搜索关键词或完整问题，建议 72 个字符以内"
                    "（一个汉字按两个字符计）"
                ),
            }
        },
        "required": ["query"],
    },
    handler=search_web_handler,
)
