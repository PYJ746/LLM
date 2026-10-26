"""顶部信息卡片：身份、模型、工作目录与快捷键。"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class InfoPanel(Vertical):
    """位于聊天区上方的信息卡。"""

    def __init__(self, model: str, tool_count: int, workspace: Path):
        super().__init__(id="info-panel")
        self._model = model
        self._tool_count = tool_count
        self._workspace = workspace

    def compose(self) -> ComposeResult:
        yield Static(
            f"Pulse  ·  {self._tool_count} 个工具  ·  {self._model}",
            classes="info-title",
            markup=False,
        )
        yield Static(
            f"工作目录  {self._workspace}",
            classes="info-path",
            markup=False,
        )
        yield Static(
            "Enter 发送     Shift+Enter 换行     /help 命令     Esc 中断生成     "
            "Ctrl+B 侧栏     Ctrl+N 新会话",
            classes="info-keys",
            markup=False,
        )
