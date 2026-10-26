"""底部消息输入框：Enter 发送，Shift+Enter 换行。"""

from __future__ import annotations

import sys

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


class PromptInput(TextArea):
    """多行输入框。

    部分终端（尤其是 Windows 控制台）不会把 Shift+Enter 作为独立按键上报，
    而是上报为普通 Enter。此时 action_submit 会读取物理 Shift 键状态来决定
    换行还是发送，保证 Shift+Enter 在常见终端里都能工作。
    """

    BINDINGS = [
        Binding("enter", "submit", "发送", priority=True, show=False),
        Binding("shift+enter", "newline", "换行", show=False),
    ]

    class Submitted(Message):
        """用户提交了一条消息。"""

        def __init__(self, value: str):
            super().__init__()
            self.value = value

    def action_submit(self) -> None:
        if self.read_only:
            return
        if self._shift_held():
            self.action_newline()
            return
        text = self.text.strip()
        if not text:
            return
        self.text = ""
        self.post_message(self.Submitted(text))

    def action_newline(self) -> None:
        if not self.read_only:
            self.insert("\n")

    @staticmethod
    def _shift_held() -> bool:
        """检测物理 Shift 键是否按下（仅 Windows 需要此兜底）。"""
        if sys.platform != "win32":
            return False
        try:
            import ctypes

            return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
        except Exception:
            return False
