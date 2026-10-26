from __future__ import annotations

import asyncio

from textual.widgets import Footer, Markdown, Static

from core.config import PulseConfig
from core.llm.base import ChatChunk, ToolCallDelta
from core.tools.defaults import build_default_registry
from tests.conftest import FakeChatModel, text_turn
from tui.app import PulseApp
from tui.widgets.chat_view import ChatView
from tui.widgets.confirm_modal import ConfirmScreen
from tui.widgets.info_panel import InfoPanel
from tui.widgets.messages import ErrorMessage, SystemNotice, UserMessage
from tui.widgets.prompt_input import PromptInput
from tui.widgets.sidebar import SessionSidebar
from tui.widgets.status_bar import StatusBar
from tui.widgets.tool_card import ToolCard


def make_app(tmp_path, script) -> tuple[PulseApp, FakeChatModel]:
    config = PulseConfig(
        base_url="https://example.com",
        api_key="test-key",
        model="test-model",
    )
    model = FakeChatModel(script)
    registry = build_default_registry(workspace=tmp_path)
    app = PulseApp(config=config, model=model, registry=registry, workspace=tmp_path)
    return app, model


async def finish_workers(app, timeout: float = 5.0) -> None:
    await asyncio.wait_for(app.workers.wait_for_complete(), timeout=timeout)


async def wait_until(pilot, predicate, timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("等待界面状态超时")
        await pilot.pause(0.02)


async def test_streaming_answer_is_rendered(tmp_path):
    app, _ = make_app(tmp_path, [text_turn("你好，", "我是 Pulse。")])

    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("你好")
        await finish_workers(app)
        await pilot.pause()

        assert len(app.query(UserMessage)) == 1
        markdown = app.query_one(ChatView).query_one(Markdown)
        assert "你好，我是 Pulse。" in markdown.source
        assert app.query_one(PromptInput).read_only is False
        assert [m.role for m in app.engine.messages] == [
            "system",
            "user",
            "assistant",
        ]


async def test_input_enter_submits(tmp_path):
    app, _ = make_app(tmp_path, [text_turn("收到")])

    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.query_one(PromptInput)
        prompt.text = "测试输入"
        await pilot.press("enter")
        await finish_workers(app)
        await pilot.pause()

        assert app.engine.messages[1].content == "测试输入"
        assert prompt.read_only is False


async def test_shift_enter_inserts_newline_instead_of_submitting(tmp_path):
    app, _ = make_app(tmp_path, [])

    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.query_one(PromptInput)
        prompt.text = "第一行"
        await pilot.press("shift+enter")
        await pilot.pause()

        assert "\n" in prompt.text
        assert prompt.text.replace("\n", "") == "第一行"
        # 只保留系统消息，说明没有提交给模型
        assert len(app.engine.messages) == 1


async def test_enter_with_physical_shift_inserts_newline(tmp_path, monkeypatch):
    """模拟终端把 Shift+Enter 上报为普通 Enter，物理 Shift 仍按下。"""
    monkeypatch.setattr(
        PromptInput, "_shift_held", staticmethod(lambda: True)
    )
    app, _ = make_app(tmp_path, [])

    async with app.run_test(size=(100, 30)) as pilot:
        prompt = app.query_one(PromptInput)
        prompt.text = "第一行"
        await pilot.press("enter")
        await pilot.pause()

        assert "\n" in prompt.text
        assert len(app.engine.messages) == 1


async def test_tool_call_renders_card(tmp_path):
    app, _ = make_app(
        tmp_path,
        [
            [ChatChunk(tool_calls=(ToolCallDelta(0, "call_1", "getcwd", "{}"),))],
            text_turn("完成"),
        ],
    )

    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("当前目录")
        await finish_workers(app)
        await pilot.pause()

        cards = app.query(ToolCard)
        assert len(cards) == 1
        assert cards[0].tool_name == "getcwd"
        assert cards[0].title.startswith("✓ getcwd()")
        assert "ms" in cards[0].title
        assert cards[0].collapsed is True
        assert str(tmp_path) in app.engine.messages[-2].content


async def test_delete_confirmation_denied_keeps_file(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_text("x", encoding="utf-8")
    app, _ = make_app(
        tmp_path,
        [
            [
                ChatChunk(
                    tool_calls=(
                        ToolCallDelta(
                            0,
                            "call_1",
                            "deleteFile",
                            '{"path": "keep.txt"}',
                        ),
                    )
                )
            ],
            text_turn("已取消"),
        ],
    )

    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("删除 keep.txt")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))

        await pilot.press("escape")
        await finish_workers(app)
        await pilot.pause()

        assert target.exists()
        tool_messages = [m for m in app.engine.messages if m.role == "tool"]
        assert tool_messages[-1].content == "用户取消了删除操作"


async def test_delete_confirmation_approved_removes_file(tmp_path):
    target = tmp_path / "gone.txt"
    target.write_text("x", encoding="utf-8")
    app, _ = make_app(
        tmp_path,
        [
            [
                ChatChunk(
                    tool_calls=(
                        ToolCallDelta(
                            0,
                            "call_1",
                            "deleteFile",
                            '{"path": "gone.txt"}',
                        ),
                    )
                )
            ],
            text_turn("已删除"),
        ],
    )

    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("删除 gone.txt")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.pause(0.1)

        await pilot.click("#confirm")
        await finish_workers(app)
        await pilot.pause()

        assert not target.exists()


async def test_escape_cancels_running_turn(tmp_path):
    app, model = make_app(tmp_path, [text_turn("不会到达")])
    model.gate = asyncio.Event()

    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("取消我")
        await wait_until(pilot, lambda: app.engine.is_busy)

        await pilot.press("escape")
        await finish_workers(app)
        await pilot.pause()

        assert app.query_one(PromptInput).read_only is False
        assert [m.role for m in app.engine.messages] == ["system", "user"]
        notices = [str(item.content) for item in app.query(SystemNotice)]
        assert any("已取消" in text for text in notices)


async def test_error_is_rendered(tmp_path):
    app, _ = make_app(tmp_path, [[RuntimeError("网络断了")]])

    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("你好")
        await finish_workers(app)
        await pilot.pause()

        errors = app.query(ErrorMessage)
        assert len(errors) == 1
        assert "网络断了" in str(errors[0].content)
        assert app.query_one(PromptInput).read_only is False


async def test_slash_commands(tmp_path):
    app, _ = make_app(tmp_path, [])

    async with app.run_test(size=(100, 40)) as pilot:
        await app.submit("/tools")
        await pilot.pause()
        notices = "\n".join(str(item.content) for item in app.query(SystemNotice))
        assert "getdate" in notices
        assert "renamePath" in notices

        await app.submit("/help")
        await pilot.pause()
        notices = "\n".join(str(item.content) for item in app.query(SystemNotice))
        assert "/clear" in notices

        await app.submit("/unknown")
        await pilot.pause()
        notices = "\n".join(str(item.content) for item in app.query(SystemNotice))
        assert "未知命令" in notices
        # 命令不会被发送给模型
        assert len(app.engine.messages) == 1


async def test_clear_resets_history_and_view(tmp_path):
    app, _ = make_app(tmp_path, [text_turn("回答")])

    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("你好")
        await finish_workers(app)
        await pilot.pause()
        assert len(app.engine.messages) == 3

        await app.submit("/clear")
        await pilot.pause()

        assert len(app.engine.messages) == 1
        assert len(app.query(UserMessage)) == 0


async def test_layout_has_info_panel_and_sidebar(tmp_path):
    app, _ = make_app(tmp_path, [])

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        info = app.query_one(InfoPanel)
        chat = app.query_one(ChatView)
        sidebar = app.query_one(SessionSidebar)
        status = app.query_one(StatusBar)
        footer = app.query_one(Footer)

        assert info.region.y < chat.region.y
        assert chat.region.x < sidebar.region.x
        assert sidebar.region.width >= 30
        assert status.region.y > chat.region.y
        assert footer.region.y >= status.region.y

        assert str(app.query_one("#kv-model", Static).content) == "test-model"
        sidebar_text = " ".join(str(widget.content) for widget in sidebar.query(Static))
        assert "getdate" in sidebar_text
        assert "deleteFile" in sidebar_text


async def test_sidebar_toggle_clear_and_new_session(tmp_path):
    app, _ = make_app(tmp_path, [text_turn("回答")])

    async with app.run_test(size=(120, 40)) as pilot:
        sidebar = app.query_one(SessionSidebar)
        assert sidebar.display is True

        await pilot.press("ctrl+b")
        await pilot.pause()
        assert sidebar.display is False

        await pilot.press("ctrl+b")
        await pilot.pause()
        assert sidebar.display is True

        await app.submit("你好")
        await finish_workers(app)
        await pilot.pause()
        assert len(app.engine.messages) == 3

        # 清屏只清视觉，不丢历史
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert len(app.engine.messages) == 3
        assert len(app.query(UserMessage)) == 0

        first_session = str(app.query_one("#kv-session", Static).content)
        await pilot.press("ctrl+n")
        await pilot.pause()

        assert len(app.engine.messages) == 1
        assert str(app.query_one("#kv-turns", Static).content) == "0"
        assert str(app.query_one("#kv-session", Static).content) != first_session
