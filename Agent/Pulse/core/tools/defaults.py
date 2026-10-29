"""内置工具的默认装配。

工具顺序与 Practice02/chat.py 的 TOOLS 保持一致。
"""

from __future__ import annotations

from pathlib import Path

from core.confirmation import ConfirmationProvider
from core.tools.builtin.datetime_tools import (
    GETDATE_SPEC,
    IS_LEAP_YEAR_SPEC,
)
from core.tools.builtin.filesystem import (
    CREATE_DIRECTORY_SPEC,
    DELETE_DIRECTORY_SPEC,
    DELETE_FILE_SPEC,
    GET_CWD_SPEC,
    GET_FILE_TYPE_SPEC,
    LIST_DIRECTORY_SPEC,
    READ_TEXT_FILE_SPEC,
    RENAME_PATH_SPEC,
)
from core.skills.registry import SkillRegistry
from core.tools.builtin.run_cli import RUN_CLI_SPEC
from core.tools.builtin.skills import make_load_skill_spec
from core.tools.builtin.web_fetch import FETCH_WEB_SPEC
from core.tools.builtin.web_search import SEARCH_WEB_SPEC
from core.tools.registry import ToolRegistry

DEFAULT_TOOL_SPECS = (
    GETDATE_SPEC,
    IS_LEAP_YEAR_SPEC,
    GET_CWD_SPEC,
    LIST_DIRECTORY_SPEC,
    GET_FILE_TYPE_SPEC,
    READ_TEXT_FILE_SPEC,
    CREATE_DIRECTORY_SPEC,
    DELETE_DIRECTORY_SPEC,
    DELETE_FILE_SPEC,
    RENAME_PATH_SPEC,
    SEARCH_WEB_SPEC,
    FETCH_WEB_SPEC,
    RUN_CLI_SPEC,
)


def build_default_registry(
    workspace: Path | str | None = None,
    confirmation: ConfirmationProvider | None = None,
    *,
    search_api_key: str = "",
    skills: SkillRegistry | None = None,
) -> ToolRegistry:
    registry = ToolRegistry(
        workspace=workspace,
        confirmation=confirmation,
        search_api_key=search_api_key,
    )
    registry.register_all(DEFAULT_TOOL_SPECS)
    # 没有 Skill 时不暴露 loadSkill，避免无意义的工具定义
    if skills is not None and len(skills) > 0:
        registry.register(make_load_skill_spec(skills))
    return registry
