from __future__ import annotations

import json

import httpx
import pytest

from core.tools.builtin.web_search import (
    MAX_REFERENCES,
    SEARCH_ENDPOINT,
    format_search_result,
    request_search,
)
from core.tools.defaults import build_default_registry


def make_response(references=None) -> dict:
    return {
        "request_id": "req-1",
        "references": references
        if references is not None
        else [
            {
                "id": 1,
                "title": "标题一",
                "url": "https://example.com/1",
                "web_anchor": "锚文本一",
                "snippet": "第一条参考摘要",
                "content": "第一条参考正文",
                "website": "示例站点",
                "date": "2026-10-01",
                "type": "web",
            },
            {
                "id": 2,
                "title": "标题二",
                "url": "https://example.com/2",
                "web_anchor": "锚文本二",
                "snippet": "第二条参考摘要",
                "type": "web",
            },
        ],
    }


async def run_with_transport(handler, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        return await request_search(client, **kwargs)


async def test_request_uses_expected_endpoint_headers_and_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=make_response())

    text = await run_with_transport(
        handler, api_key="test-key", query="今天有什么新闻"
    )

    assert captured["url"] == SEARCH_ENDPOINT
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert body["messages"] == [
        {"role": "user", "content": "今天有什么新闻"}
    ]
    assert body["search_source"] == "baidu_search_v2"
    assert body["edition"] == "standard"
    assert body["resource_type_filter"] == [
        {"type": "web", "top_k": MAX_REFERENCES}
    ]
    # 新接口不再接收 model，也不再返回模型摘要
    assert "model" not in body
    assert "搜索摘要：" not in text
    assert "参考来源（共 2 条）" in text
    assert "1. 标题一" in text
    assert "https://example.com/1" in text
    assert "站点: 示例站点" in text
    assert "摘要: 第一条参考摘要" in text
    assert "2. 标题二" in text
    assert "https://example.com/2" in text


async def test_api_error_is_reported_with_code_and_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "requestId": "req-err",
                "code": 216003,
                "message": "get authorization error",
            },
        )

    with pytest.raises(RuntimeError) as excinfo:
        await run_with_transport(handler, api_key="bad-key", query="test")

    message = str(excinfo.value)
    assert "HTTP 401" in message
    assert "216003" in message
    assert "get authorization error" in message


async def test_network_error_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(RuntimeError, match="联网搜索请求失败"):
        await run_with_transport(handler, api_key="key", query="test")


async def test_timeout_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(RuntimeError, match="请求超时"):
        await run_with_transport(handler, api_key="key", query="test")


async def test_non_json_response_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(RuntimeError, match="无法解析的响应"):
        await run_with_transport(handler, api_key="key", query="test")


async def test_empty_search_result_is_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"references": []})

    with pytest.raises(RuntimeError, match="没有返回参考来源"):
        await run_with_transport(handler, api_key="key", query="test")


async def test_missing_api_key_returns_clear_tool_error(tmp_path):
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute("call_1", "searchWeb", {"query": "新闻"})

    assert not result.ok
    assert "baidu_qianfan_api_key" in result.content
    assert "[search]" in result.content


async def test_missing_query_returns_clear_tool_error(tmp_path):
    registry = build_default_registry(
        workspace=tmp_path, search_api_key="test-key"
    )

    result = await registry.execute("call_1", "searchWeb", {"query": "  "})

    assert not result.ok
    assert "query" in result.content


def test_references_are_deduplicated_and_limited():
    references = [
        {"title": f"标题{i}", "url": "https://example.com/same"}
        for i in range(12)
    ]
    text = format_search_result(make_response(references=references))

    assert text.count("https://example.com/same") == 1
    assert "共 1 条" in text


def test_title_falls_back_to_web_anchor_then_url():
    text = format_search_result(
        make_response(
            references=[
                {"id": 1, "url": "https://example.com/a", "web_anchor": "锚文本"},
                {"id": 2, "url": "https://example.com/b"},
            ]
        )
    )

    assert "1. 锚文本" in text
    assert "2. https://example.com/b" in text


def test_snippet_falls_back_to_content():
    text = format_search_result(
        make_response(
            references=[
                {
                    "id": 1,
                    "title": "只有正文",
                    "url": "https://example.com/page",
                    "content": "这是网页正文片段",
                }
            ]
        )
    )

    assert "摘要: 这是网页正文片段" in text


def test_reference_number_matches_api_id():
    references = [
        {"id": 5, "title": "被引用的来源", "url": "https://example.com/5"}
    ]
    text = format_search_result(make_response(references=references))

    assert "5. 被引用的来源" in text
