"""把 core 的确认协议适配到 Textual ModalScreen。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

from core.confirmation import ConfirmationRequest
from tui.widgets.confirm_modal import ConfirmScreen

if TYPE_CHECKING:
    from tui.app import PulseApp


class TuiConfirmationProvider:
    """在 Textual 主线程中弹出确认框，并等待用户选择。"""

    def __init__(self, app: "PulseApp"):
        self.app = app

    async def confirm(self, request: ConfirmationRequest) -> bool:
        screen = ConfirmScreen(request)
        self.app.set_state("等待确认", "busy")
        try:
            return bool(await self.app.push_screen_wait(screen))
        except asyncio.CancelledError:
            # 取消生成时，如果确认框仍在最上层，主动关闭它
            if self.app.screen is screen:
                with suppress(Exception):
                    self.app.pop_screen()
            raise
        finally:
            if self.app.engine.is_busy:
                self.app.set_state("调用工具", "busy")
