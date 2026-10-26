"""聊天消息组件。

模型与工具输出一律使用 markup=False，避免 Rich markup 被当作样式解析。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static


class UserMessage(Vertical):
    """用户消息。"""

    def __init__(self, text: str):
        super().__init__(classes="message user-message")
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static("你", classes="role-label role-user")
        yield Static(self._text, classes="bubble user-bubble", markup=False)


class AssistantMessage(Vertical):
    """助手消息：支持流式追加的 Markdown。"""

    def __init__(self):
        super().__init__(classes="message assistant-message")

    def compose(self) -> ComposeResult:
        yield Static("Pulse", classes="role-label role-assistant")
        yield Markdown("", classes="bubble assistant-bubble")
        yield Static("", classes="message-status")

    @property
    def markdown(self) -> Markdown:
        return self.query_one(Markdown)

    def set_status(self, text: str) -> None:
        self.query_one(".message-status", Static).update(text)


class ErrorMessage(Static):
    """一条错误提示。"""

    def __init__(self, message: str):
        super().__init__(f"错误：{message}", classes="error-message", markup=False)


class SystemNotice(Static):
    """本地系统提示（命令结果、状态说明等）。"""

    def __init__(self, message: str):
        super().__init__(message, classes="system-notice", markup=False)
