"""工具注册表：声明导出、按名分发、异常归一。"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from core.confirmation import (
    AutoDenyConfirmation,
    ConfirmationProvider,
)
from core.models import ToolResult
from core.tools.context import ToolContext
from core.tools.spec import ToolSpec


class ToolRegistry:
    """持有所有工具，并提供给引擎使用。"""

    def __init__(
        self,
        workspace: Path | str | None = None,
        confirmation: ConfirmationProvider | None = None,
        *,
        search_api_key: str = "",
    ):
        self.workspace = Path(workspace or Path.cwd()).expanduser().resolve()
        self.confirmation = confirmation or AutoDenyConfirmation()
        self.search_api_key = search_api_key
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"工具重复注册: {spec.name}")
        self._tools[spec.name] = spec

    def register_all(self, specs: list[ToolSpec] | tuple[ToolSpec, ...]) -> None:
        for spec in specs:
            self.register(spec)

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools.values())

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """导出 OpenAI 兼容的 tools 数组。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    async def execute(
        self, call_id: str, name: str, arguments: Mapping[str, Any]
    ) -> ToolResult:
        """执行工具；任何异常都转换为 ok=False 的结果，不中断整轮对话。"""
        started = perf_counter()
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(
                call_id=call_id,
                name=name,
                content=f"Error: 未知工具 {name}",
                ok=False,
                duration_ms=_elapsed_ms(started),
            )

        context = ToolContext(
            workspace=self.workspace,
            confirmation=self.confirmation,
            tool_name=name,
            search_api_key=self.search_api_key,
        )
        try:
            outcome = await spec.handler(arguments, context)
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                name=name,
                content=f"Error: {exc}",
                ok=False,
                duration_ms=_elapsed_ms(started),
            )

        return ToolResult(
            call_id=call_id,
            name=name,
            content=outcome.content,
            ok=True,
            cancelled=outcome.cancelled,
            duration_ms=_elapsed_ms(started),
        )


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
