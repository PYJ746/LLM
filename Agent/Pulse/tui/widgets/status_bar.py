"""底部状态栏：状态、轮次、工具调用与耗时。"""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static

STATE_COLORS = {
    "idle": "#4ade80",
    "busy": "#facc15",
    "cancelled": "#c084fc",
    "error": "#f87171",
}


class StatusBar(Static):
    """单行运行指标。"""

    def __init__(self):
        super().__init__("", id="status-bar", markup=True)

    def set_status(
        self,
        *,
        state: str,
        turns: int,
        model: str,
        tool_calls: int,
        elapsed: float,
        kind: str = "idle",
    ) -> None:
        color = STATE_COLORS.get(kind, STATE_COLORS["idle"])
        self.update(
            f"[{color}]●[/] {escape(state)} · {turns} 轮 · {escape(model)}"
            f"    │    工具 {tool_calls} 次"
            f"    │    {elapsed:.1f}s"
            f"    │    Esc 中断"
        )
