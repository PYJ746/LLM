"""工具调用卡片：运行中展开，结束后折叠。"""

from __future__ import annotations

import json

from textual.containers import Vertical
from textual.widgets import Collapsible, Static

from core.models import ToolResult

MAX_DISPLAY_CHARS = 8_000


def _truncate(text: str, limit: int = MAX_DISPLAY_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，共 {len(text)} 字符）"


class ToolCard(Collapsible):
    """一次工具调用的可折叠展示。"""

    def __init__(self, call_id: str, name: str, arguments: dict):
        self.call_id = call_id
        self.tool_name = name
        try:
            arguments_text = json.dumps(arguments, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            arguments_text = str(arguments)

        self._arguments = Static(
            _truncate(arguments_text), classes="tool-args", markup=False
        )
        self._result = Static("运行中…", classes="tool-result", markup=False)
        super().__init__(
            Vertical(
                Static("参数", classes="tool-section-label"),
                self._arguments,
                Static("结果", classes="tool-section-label"),
                self._result,
                classes="tool-body",
            ),
            title=f"▸ {name}() · 运行中",
            collapsed=False,
            classes="tool-card",
        )

    def finish(self, result: ToolResult) -> None:
        if result.cancelled:
            prefix, status = "⏸", "已取消"
        elif result.ok:
            prefix, status = "✓", f"{result.duration_ms} ms"
        else:
            prefix, status = "✗", "失败"

        self.title = f"{prefix} {self.tool_name}() · {status}"
        content = _truncate(result.content or "(无输出)")
        self._result.update(content)
        self.collapsed = True
