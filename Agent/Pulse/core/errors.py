"""领域异常。"""

from __future__ import annotations


class PulseError(Exception):
    """Pulse 所有受控异常的基类。"""


class ConfigError(PulseError):
    """配置文件缺失或内容不合法。"""


class ToolError(PulseError):
    """工具参数或操作不合法。"""


class LLMError(PulseError):
    """模型服务调用失败。"""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    def __str__(self) -> str:
        message = super().__str__()
        if self.status_code is not None:
            return f"{message}（HTTP {self.status_code}）"
        return message
