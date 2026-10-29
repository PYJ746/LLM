"""Pulse 的 Textual 应用。

职责边界：
- 只消费 core 的 AgentEvent，并渲染为组件；
- 通过 TuiConfirmationProvider 实现 core 的确认协议；
- 不包含任何模型调用、工具实现或会话逻辑。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Markdown

from core.agent import AgentEngine
from core.config import PulseConfig
from core.events import (
    ErrorOccurred,
    TextDelta,
    ToolCallCompleted,
    ToolCallRequested,
    TurnFinished,
    TurnStarted,
    TurnStatus,
)
from core.llm.base import ChatModel
from core.skills.registry import SkillRegistry
from core.tools.registry import ToolRegistry
from tui.confirmation import TuiConfirmationProvider
from tui.widgets.chat_view import ChatView
from tui.widgets.confirm_modal import ConfirmScreen
from tui.widgets.info_panel import InfoPanel
from tui.widgets.messages import AssistantMessage
from tui.widgets.prompt_input import PromptInput
from tui.widgets.sidebar import SessionSidebar
from tui.widgets.status_bar import StatusBar

HELP_TEXT = """可用命令：
/help    显示帮助
/tools   列出可用工具
/skills  列出已发现的 Skills
/clear   开始新会话（清空历史与聊天记录）
/quit    退出 Pulse

快捷键：
Enter 发送；Shift+Enter 换行
Esc 取消当前生成
Ctrl+B 显示/隐藏侧栏
Ctrl+N 新会话
Ctrl+L 清屏（保留会话历史）
F1 帮助；Ctrl+Q 退出
"""


class PulseApp(App[None]):
    """聊天流 + 会话侧栏的 Agent 界面。"""

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("escape", "cancel_turn", "中断生成", priority=True, show=False),
        Binding("ctrl+q", "quit_app", "退出", priority=True),
        Binding("ctrl+l", "clear_screen", "清屏"),
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+b", "toggle_sidebar", "侧栏"),
        Binding("f1", "show_help", "帮助"),
    ]

    def __init__(
        self,
        config: PulseConfig,
        model: ChatModel,
        registry: ToolRegistry,
        workspace: Path | str,
        skills: SkillRegistry | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.config = config
        self.model = model
        self.registry = registry
        self.skills = skills if skills is not None else SkillRegistry()
        self.workspace = Path(workspace).expanduser().resolve()
        self.registry.workspace = self.workspace

        # 注册表在构造时不知道 App，这里换入 TUI 的确认实现
        self.registry.confirmation = TuiConfirmationProvider(self)
        self.engine = AgentEngine(
            model,
            registry,
            skills=self.skills.skills,
            max_tool_rounds=config.max_tool_rounds,
        )

        self.title = "Pulse"
        self.sub_title = f"{config.model} · {self.workspace}"
        self._session_id = uuid.uuid4().hex[:8]

        self._turn_worker = None
        self._turn_token = 0
        self._tool_cards: dict[str, Any] = {}

        self._task_started_at: float | None = None
        self._elapsed = 0.0
        self._tool_calls = 0
        self._state_label = "就绪"
        self._state_kind = "idle"

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="main-column"):
                yield InfoPanel(
                    model=self.config.model,
                    tool_count=len(self.registry.names),
                    workspace=self.workspace,
                    skill_count=len(self.skills),
                )
                yield ChatView()
            yield SessionSidebar(
                model=self.config.model,
                base_url=self.config.base_url,
                workspace=self.workspace,
                tools=self.registry.specs,
                skills=self.skills.skills,
                session_id=self._session_id,
                max_tool_rounds=self.config.max_tool_rounds,
            )
        yield PromptInput(
            placeholder="Enter 发送；Shift+Enter 换行；/help 查看命令；Esc 中断生成",
            id="prompt",
            show_line_numbers=False,
        )
        yield StatusBar()
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one(PromptInput).focus()
        self.set_state("就绪", "idle")
        await self.query_one(ChatView).add_notice(
            "Pulse 已就绪。输入 /help 查看可用命令。"
        )

    # ------------------------------------------------------------------
    # 输入与命令
    # ------------------------------------------------------------------

    @on(PromptInput.Submitted)
    async def _on_prompt_submitted(self, event: PromptInput.Submitted) -> None:
        await self.submit(event.value)

    async def submit(self, text: str) -> None:
        """处理一条用户输入；也供测试直接调用。"""
        text = text.strip()
        if not text:
            return
        if text.startswith("/"):
            await self._handle_command(text)
            return
        if self.engine.is_busy:
            await self.query_one(ChatView).add_notice(
                "正在处理上一条消息，请稍候或按 Esc 取消。"
            )
            return

        chat = self.query_one(ChatView)
        await chat.add_user(text)
        self._start_turn(text)

    async def _handle_command(self, text: str) -> None:
        chat = self.query_one(ChatView)
        command = text.split()[0].lower()

        if command == "/help":
            await chat.add_notice(HELP_TEXT)
        elif command == "/tools":
            lines = ["可用工具："]
            for spec in self.registry.specs:
                lines.append(f"- {spec.name}: {spec.description}")
            await chat.add_notice("\n".join(lines))
        elif command == "/skills":
            await chat.add_notice(self._skills_summary())
        elif command in ("/clear", "/new"):
            await self._new_session()
        elif command in ("/quit", "/exit"):
            self.action_quit_app()
        else:
            await chat.add_notice(f"未知命令：{command}。输入 /help 查看可用命令。")

    def _skills_summary(self) -> str:
        lines: list[str] = []
        if len(self.skills) == 0:
            root = self.skills.root or (
                Path.cwd() / ".agents" / "skills"
            )
            lines.append(
                f"未发现 Skills。请将 SKILL.md 放入：{root}/<skill>/"
            )
        else:
            lines.append(f"可用 Skills（{len(self.skills)}）：")
            for skill in self.skills.skills:
                lines.append(f"- {skill.name}: {skill.description}")
                lines.append(f"  位置: {skill.skill_file}")

        if self.skills.warnings:
            lines.append("")
            lines.append("加载警告：")
            lines.extend(f"- {warning}" for warning in self.skills.warnings)
        return "\n".join(lines)

    async def _new_session(self) -> None:
        chat = self.query_one(ChatView)
        if self.engine.is_busy:
            await chat.add_notice("请先等待当前生成结束或按 Esc 取消。")
            return

        self.engine.clear_history()
        chat.clear_messages()
        self._session_id = uuid.uuid4().hex[:8]
        self._tool_calls = 0
        self._elapsed = 0.0
        self._task_started_at = None
        self.query_one(SessionSidebar).set_session_id(self._session_id)
        self.set_state("就绪", "idle")
        await chat.add_notice("已开始新会话。")

    async def _clear_screen(self) -> None:
        if self.engine.is_busy:
            return
        chat = self.query_one(ChatView)
        chat.clear_messages()
        await chat.add_notice("屏幕已清空，会话历史保留。")

    # ------------------------------------------------------------------
    # 回合生命周期
    # ------------------------------------------------------------------

    def _start_turn(self, text: str) -> None:
        self._turn_token += 1
        token = self._turn_token
        self._tool_cards.clear()
        self._tool_calls = 0
        self._elapsed = 0.0
        self._task_started_at = time.monotonic()

        self._set_busy(True)
        self.set_state("思考中", "busy")
        self._turn_worker = self.run_worker(
            self._consume_turn(text, token),
            group="turn",
            description="Agent 回合",
            exclusive=True,
            exit_on_error=False,
        )

    async def _consume_turn(self, text: str, token: int) -> None:
        chat = self.query_one(ChatView)
        assistant: AssistantMessage | None = None
        md_stream = None
        final_state = ("就绪", "idle")

        try:
            async for event in self.engine.run_turn(text):
                if isinstance(event, TurnStarted):
                    self.set_state("思考中", "busy")

                elif isinstance(event, TextDelta):
                    if assistant is None:
                        assistant = await chat.add_assistant()
                        assistant.set_status("输出中…")
                        md_stream = Markdown.get_stream(assistant.markdown)
                    await md_stream.write(event.text)
                    chat.scroll_if_at_end()

                elif isinstance(event, ToolCallRequested):
                    await self._close_stream(md_stream)
                    md_stream = None
                    if assistant is not None:
                        assistant.set_status("")
                        assistant = None

                    self._tool_calls += 1
                    self.set_state("调用工具", "busy")
                    arguments = event.arguments
                    if not arguments and event.arguments_raw.strip() not in (
                        "",
                        "{}",
                    ):
                        # 参数不是合法 JSON 时，把原始文本显示出来便于排查
                        arguments = {"(原始参数)": event.arguments_raw}
                    card = await chat.add_tool_card(
                        event.call_id, event.name, arguments
                    )
                    self._tool_cards[event.call_id] = card

                elif isinstance(event, ToolCallCompleted):
                    card = self._tool_cards.get(event.call_id)
                    if card is not None:
                        card.finish(event.result)
                    self.set_state("思考中", "busy")

                elif isinstance(event, ErrorOccurred):
                    await chat.add_error(event.message)
                    final_state = ("错误", "error")

                elif isinstance(event, TurnFinished):
                    if event.status is TurnStatus.COMPLETED:
                        final_state = ("就绪", "idle")
                    elif event.status is TurnStatus.CANCELLED:
                        final_state = ("已取消", "cancelled")
                        await chat.add_notice("已取消本轮生成。")
                    elif event.status is TurnStatus.ERROR:
                        final_state = ("错误", "error")
                    else:
                        final_state = ("达到轮数上限", "error")

        except asyncio.CancelledError:
            final_state = ("已取消", "cancelled")
            raise
        except Exception as exc:  # 界面兜底，避免 worker 静默失败
            await chat.add_error(f"{type(exc).__name__}: {exc}")
            final_state = ("错误", "error")
        finally:
            if assistant is not None:
                assistant.set_status("")
            await self._close_stream(md_stream)

            if token == self._turn_token:
                if self._task_started_at is not None:
                    self._elapsed = time.monotonic() - self._task_started_at
                    self._task_started_at = None
                self._set_busy(False)
                self.set_state(*final_state)

    async def _close_stream(self, stream) -> None:
        if stream is None:
            return
        with suppress(Exception):
            await stream.stop()

    def action_cancel_turn(self) -> None:
        screen = self.screen
        if isinstance(screen, ConfirmScreen):
            screen.dismiss(False)
            return
        if self.engine.is_busy and self._turn_worker is not None:
            self.set_state("正在取消", "cancelled")
            self._turn_worker.cancel()

    async def action_clear_screen(self) -> None:
        await self._clear_screen()

    async def action_new_session(self) -> None:
        await self._new_session()

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one(SessionSidebar)
        sidebar.display = not sidebar.display

    async def action_show_help(self) -> None:
        await self._handle_command("/help")

    def action_quit_app(self) -> None:
        if self._turn_worker is not None:
            self._turn_worker.cancel()
        self.exit()

    async def on_unmount(self) -> None:
        if self._turn_worker is not None:
            self._turn_worker.cancel()
        close = getattr(self.model, "aclose", None)
        if close is not None:
            with suppress(Exception):
                await close()

    # ------------------------------------------------------------------
    # 供组件与确认适配器使用
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        prompt = self.query_one(PromptInput)
        prompt.read_only = busy
        if not busy:
            prompt.focus()

    def _elapsed_seconds(self) -> float:
        if self._task_started_at is None:
            return self._elapsed
        return time.monotonic() - self._task_started_at

    def set_state(self, label: str, kind: str = "idle") -> None:
        """更新状态栏与侧栏；确认适配器也会调用。"""
        self._state_label = label
        self._state_kind = kind
        with suppress(Exception):
            self.query_one(StatusBar).set_status(
                state=label,
                turns=self.engine.session.turn_count,
                model=self.config.model,
                tool_calls=self._tool_calls,
                elapsed=self._elapsed_seconds(),
                kind=kind,
            )
        with suppress(Exception):
            self.query_one(SessionSidebar).update_session(
                self.engine, state=label
            )
