"""破坏性操作的确认弹窗。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from core.confirmation import ConfirmationRequest


class ConfirmScreen(ModalScreen[bool]):
    """返回 True 表示允许执行，False 表示取消。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消", priority=True),
    ]

    def __init__(self, request: ConfirmationRequest):
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        body = f"即将{self.request.action}\n目标：{self.request.target}"
        if self.request.detail:
            body += f"\n{self.request.detail}"
        with Container(classes="confirm-dialog"):
            yield Static("需要你的确认", classes="confirm-title")
            yield Static(body, classes="confirm-body", markup=False)
            with Horizontal(classes="confirm-buttons"):
                # 默认焦点放在"取消"，避免误按 Enter 执行破坏性操作
                yield Button("取消", id="cancel", variant="primary")
                yield Button("确认执行", id="confirm", variant="error")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)
