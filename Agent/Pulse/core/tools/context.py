"""工具执行上下文：工作目录解析与确认网关。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from core.confirmation import (
    AutoDenyConfirmation,
    ConfirmationProvider,
    ConfirmationRequest,
)
from core.errors import ToolError


@dataclass(frozen=True, slots=True)
class ToolContext:
    """一次工具执行期间可用的上下文。

    - 相对路径一律相对 workspace 解析；
    - 绝对路径保持原行为，可访问任意位置；
    - confirm() 把确认请求交给当前前端实现；
    - search_api_key 供联网搜索工具使用。
    """

    workspace: Path
    confirmation: ConfirmationProvider = AutoDenyConfirmation()
    tool_name: str = ""
    search_api_key: str = field(default="", repr=False)

    def with_tool(self, tool_name: str) -> "ToolContext":
        return replace(self, tool_name=tool_name)

    def resolve_path(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise ToolError("路径不能为空")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        return candidate.resolve()

    async def confirm(self, action: str, target: str, detail: str = "") -> bool:
        request = ConfirmationRequest(
            action=action,
            target=target,
            tool_name=self.tool_name,
            detail=detail,
        )
        return await self.confirmation.confirm(request)
