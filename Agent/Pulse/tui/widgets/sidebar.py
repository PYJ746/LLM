"""右侧栏：会话信息与工具清单。"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static

from core.agent import AgentEngine
from core.tools.spec import ToolSpec

SESSION_FIELDS = (
    ("模型", "model"),
    ("接口", "api"),
    ("目录", "workspace"),
    ("会话", "session"),
    ("轮次", "turns"),
    ("消息", "messages"),
    ("上限", "limit"),
    ("状态", "state"),
)


def _shorten(text: str, width: int = 32) -> str:
    """按字符截断；中文没有空格，textwrap.shorten 无法正确切分。"""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


class SessionSidebar(VerticalScroll):
    """显示会话元数据与全部可用工具。"""

    def __init__(
        self,
        model: str,
        base_url: str,
        workspace: Path,
        tools: tuple[ToolSpec, ...],
        session_id: str,
        max_tool_rounds: int,
    ):
        super().__init__(id="sidebar")
        self._model = model
        self._base_url = base_url
        self._workspace = workspace
        self._tools = tools
        self._session_id = session_id
        self._max_tool_rounds = max_tool_rounds

    def compose(self) -> ComposeResult:
        yield Static("会话", classes="sidebar-heading")
        for label, key in SESSION_FIELDS:
            with Horizontal(classes="kv-row"):
                yield Static(label, classes="kv-key")
                yield Static("—", id=f"kv-{key}", classes="kv-value", markup=False)

        yield Static(f"工具 · {len(self._tools)}", classes="sidebar-heading tool-heading")
        for spec in self._tools:
            yield Static(f"• {spec.name}", classes="tool-name")
            yield Static(_shorten(spec.description), classes="tool-desc", markup=False)

    def on_mount(self) -> None:
        self._set("model", self._model)
        self._set("api", self._base_url)
        self._set("workspace", str(self._workspace))
        self._set("session", self._session_id)
        self._set("turns", "0")
        self._set("messages", "1")
        self._set("limit", f"{self._max_tool_rounds} 次模型调用/轮")
        self._set("state", "就绪")

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id
        self._set("session", session_id)

    def update_session(self, engine: AgentEngine, state: str | None = None) -> None:
        self._set("turns", str(engine.session.turn_count))
        self._set("messages", str(len(engine.messages)))
        if state is not None:
            self._set("state", state)

    def _set(self, key: str, value: str) -> None:
        try:
            widget = self.query_one(f"#kv-{key}", Static)
        except Exception:
            return
        widget.update(value)
