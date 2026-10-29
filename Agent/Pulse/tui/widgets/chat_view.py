"""聊天流容器。"""

from __future__ import annotations

from textual.containers import VerticalScroll

from tui.widgets.messages import (
    AssistantMessage,
    ErrorMessage,
    SystemNotice,
    UserMessage,
)
from tui.widgets.tool_card import ToolCard


class ChatView(VerticalScroll):
    """单栏聊天视图，工具调用以内联卡片显示。"""

    def __init__(self):
        super().__init__(id="chat")

    async def add_user(self, text: str) -> UserMessage:
        widget = UserMessage(text)
        await self.mount(widget)
        self.scroll_if_at_end()
        return widget

    async def add_assistant(self) -> AssistantMessage:
        widget = AssistantMessage()
        await self.mount(widget)
        self.scroll_if_at_end()
        return widget

    async def add_tool_card(self, call_id: str, name: str, arguments: dict) -> ToolCard:
        widget = ToolCard(call_id, name, arguments)
        await self.mount(widget)
        self.scroll_if_at_end()
        return widget

    async def add_error(self, message: str) -> None:
        await self.mount(ErrorMessage(message))
        self.scroll_if_at_end()

    async def add_notice(self, message: str) -> None:
        await self.mount(SystemNotice(message))
        self.scroll_if_at_end()

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()

    def scroll_if_at_end(self) -> None:
        """用户正在向上翻阅时不强行拉回底部。"""
        try:
            at_end = self.is_vertical_scroll_end
        except Exception:
            at_end = True
        if at_end:
            self.scroll_end(animate=False)
