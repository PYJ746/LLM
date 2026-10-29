from __future__ import annotations

import subprocess

import pytest

from core.tools.builtin import web_fetch
from core.tools.builtin.web_fetch import (
    MAX_MARKDOWN_CHARS,
    STATUS_MARKER,
    build_curl_command,
    decode_html,
    extract_markdown,
    fetch_html,
    fetch_page_markdown,
)
from core.tools.defaults import build_default_registry

ARTICLE_PARAGRAPH = "这里是正文段落，包含足够的信息用于测试正文提取。" * 20

ARTICLE_HTML = f"""<!DOCTYPE html>
<html><head><title>测试文章标题</title></head>
<body>
<nav>首页 | 新闻 | 关于我们</nav>
<article>
  <h1>测试文章标题</h1>
  <p>{ARTICLE_PARAGRAPH}包含一个<a href="https://example.com/link">示例链接</a>。</p>
  <h2>小节标题</h2>
  <ul><li>列表项一</li><li>列表项二</li></ul>
  <table>
    <tr><th>名称</th><th>数量</th></tr>
    <tr><td>苹果</td><td>3</td></tr>
  </table>
  <p>{ARTICLE_PARAGRAPH}</p>
</article>
<footer>版权所有 广告 联系方式</footer>
</body></html>"""


def completed(stdout: bytes, returncode: int = 0, stderr: bytes = b""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_default_registry_exposes_fetch_web():
    registry = build_default_registry()
    assert "fetchWeb" in registry.names
    spec = registry.get("fetchWeb")
    assert spec is not None
    assert spec.parameters["required"] == ["url"]


async def test_invalid_url_returns_clear_tool_error(tmp_path):
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute(
        "call_1", "fetchWeb", {"url": "file:///etc/passwd"}
    )

    assert not result.ok
    assert "http://" in result.content
    assert "https://" in result.content


async def test_missing_url_returns_clear_tool_error(tmp_path):
    registry = build_default_registry(workspace=tmp_path)

    result = await registry.execute("call_1", "fetchWeb", {"url": "  "})

    assert not result.ok
    assert "url" in result.content


def test_curl_command_is_argument_list_without_shell():
    command = build_curl_command("curl", "https://example.com/a?x=1&y=2")

    assert isinstance(command, list)
    assert command[0] == "curl"
    assert command[-1] == "https://example.com/a?x=1&y=2"
    assert "--write-out" in command
    assert not any(token in {"shell", "cmd", "/c"} for token in command)


def test_fetch_html_runs_curl_without_shell(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return completed(
            ARTICLE_HTML.encode("utf-8")
            + f"\n{STATUS_MARKER}200".encode("ascii")
        )

    monkeypatch.setattr(web_fetch.shutil, "which", lambda _: "C:/curl.exe")
    monkeypatch.setattr(web_fetch.subprocess, "run", fake_run)

    html, status = fetch_html("https://example.com/article")

    assert status == 200
    assert "测试文章标题" in html
    assert captured["command"][0] == "C:/curl.exe"
    assert "shell" not in captured["kwargs"]
    assert captured["kwargs"]["capture_output"] is True


def test_fetch_html_reports_http_error(monkeypatch):
    monkeypatch.setattr(web_fetch.shutil, "which", lambda _: "curl")
    monkeypatch.setattr(
        web_fetch.subprocess,
        "run",
        lambda *args, **kwargs: completed(
            f"not found\n{STATUS_MARKER}404".encode("ascii")
        ),
    )

    with pytest.raises(RuntimeError, match="HTTP 404"):
        fetch_html("https://example.com/missing")


def test_fetch_html_reports_missing_curl(monkeypatch):
    monkeypatch.setattr(web_fetch.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError, match="未找到 curl"):
        fetch_html("https://example.com")


def test_fetch_html_reports_curl_failure(monkeypatch):
    monkeypatch.setattr(web_fetch.shutil, "which", lambda _: "curl")
    monkeypatch.setattr(
        web_fetch.subprocess,
        "run",
        lambda *args, **kwargs: completed(
            b"", returncode=7, stderr=b"Could not connect to server"
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        fetch_html("https://example.com")

    message = str(excinfo.value)
    assert "退出码 7" in message
    assert "无法连接到服务器" in message
    assert "Could not connect" in message


def test_fetch_html_reports_timeout(monkeypatch):
    monkeypatch.setattr(web_fetch.shutil, "which", lambda _: "curl")

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("curl", 45)

    monkeypatch.setattr(web_fetch.subprocess, "run", raise_timeout)

    with pytest.raises(RuntimeError, match="网页访问超时"):
        fetch_html("https://example.com")


def test_extract_markdown_keeps_structure_and_drops_boilerplate():
    title, markdown = extract_markdown(ARTICLE_HTML, "https://example.com/a")

    assert title == "测试文章标题"
    assert "# 测试文章标题" in markdown
    assert "## 小节标题" in markdown
    assert "- 列表项一" in markdown
    assert "[示例链接](https://example.com/link)" in markdown
    assert "| 名称 | 数量 |" in markdown
    assert "首页 | 新闻" not in markdown
    assert "版权所有" not in markdown


def test_extract_markdown_rejects_page_without_content():
    with pytest.raises(RuntimeError, match="无法从该网页提取正文"):
        extract_markdown("<html><body></body></html>", "https://example.com")


def test_extract_markdown_truncates_long_content(monkeypatch):
    import trafilatura

    monkeypatch.setattr(trafilatura, "extract_metadata", lambda *a, **k: None)
    monkeypatch.setattr(
        trafilatura,
        "extract",
        lambda *a, **k: "x" * (MAX_MARKDOWN_CHARS + 500),
    )

    _, markdown = extract_markdown("<html></html>", "https://example.com")

    assert len(markdown) <= MAX_MARKDOWN_CHARS + 30
    assert "已截断" in markdown


def test_fetch_page_markdown_returns_url_title_and_body(monkeypatch):
    monkeypatch.setattr(
        web_fetch, "fetch_html", lambda url: (ARTICLE_HTML, 200)
    )

    result = fetch_page_markdown("https://example.com/a")

    assert "原始 URL: https://example.com/a" in result
    assert "网页标题: 测试文章标题" in result
    assert "正文（Markdown）：" in result
    assert "# 测试文章标题" in result


def test_decode_html_honours_meta_charset():
    raw = (
        '<html><head><meta charset="gbk"></head>'
        "<body>中文内容</body></html>"
    ).encode("gbk")

    assert "中文内容" in decode_html(raw)
