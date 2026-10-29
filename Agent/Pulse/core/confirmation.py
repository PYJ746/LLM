"""破坏性操作的确认协议。

core 只定义"如何请求确认"，具体由各前端实现：
- TUI：弹出 ModalScreen；
- Web：推送确认请求并等待前端响应；
- 无界面：AutoDeny / AutoApprove。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    """一次待确认的操作。"""

    action: str
    target: str
    tool_name: str = ""
    detail: str = ""


class ConfirmationProvider(Protocol):
    """各前端实现的异步确认接口。"""

    async def confirm(self, request: ConfirmationRequest) -> bool:
        """返回 True 表示允许执行，False 表示拒绝。"""
        ...


class AutoDenyConfirmation:
    """默认拒绝，适合无人值守或测试环境。"""

    async def confirm(self, request: ConfirmationRequest) -> bool:
        return False


class AutoApproveConfirmation:
    """始终允许，仅用于明确授权的自动化场景。"""

    async def confirm(self, request: ConfirmationRequest) -> bool:
        return True
