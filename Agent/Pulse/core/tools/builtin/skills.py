"""Skill 按需加载工具。

- 只给 ``name``：读取完整 SKILL.md 正文；
- 同时给 ``filename``：读取 Skill 目录内的附件，不重复加载 SKILL.md。

附件路径支持 Skill 相对路径、项目相对路径与绝对路径；只给文件名时会在
Skill 目录内递归查找。所有读取都被限制在该 Skill 的目录内。
"""

from __future__ import annotations

from typing import Any, Mapping

from core.models import ToolOutcome
from core.skills.loader import (
    MAX_ATTACHMENT_BYTES,
    load_skill_body,
    read_skill_attachment,
    resolve_skill_file,
)
from core.skills.models import SkillMetadata
from core.skills.registry import SkillRegistry
from core.tools.context import ToolContext
from core.tools.spec import ToolSpec

LOAD_SKILL_NAME = "loadSkill"

LOAD_SKILL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "要加载的 Skill 名称，必须与可用 Skills 列表中的 name 完全一致",
        },
        "filename": {
            "type": "string",
            "description": (
                "可选。要读取的 Skill 附件：可以是相对 Skill 目录的路径、"
                "相对项目根目录的路径或绝对路径；也可以只给文件名，"
                "程序会在该 Skill 目录内递归查找。不传则读取 SKILL.md 正文。"
            ),
        },
    },
    "required": ["name"],
}


def make_load_skill_spec(skills: SkillRegistry) -> ToolSpec:
    """基于 Skill 注册表创建 loadSkill 工具声明。"""

    async def load_skill(
        arguments: Mapping[str, Any], context: ToolContext
    ) -> ToolOutcome:
        raw_name = arguments.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            return ToolOutcome("Error: 缺少参数 name")

        skill = skills.get(name)
        if skill is None:
            available = "、".join(skills.names) or "（无）"
            return ToolOutcome(
                f"Error: 未知 Skill {name}。可用 Skills: {available}"
            )

        raw_filename = arguments.get("filename")
        if raw_filename is not None and not isinstance(raw_filename, str):
            return ToolOutcome("Error: filename 必须是字符串")
        filename = raw_filename.strip() if isinstance(raw_filename, str) else ""

        if filename:
            return _load_attachment(skill, filename)

        body = load_skill_body(skill)
        if not body.strip():
            return ToolOutcome(f"Error: Skill {skill.name} 的正文为空")

        return ToolOutcome(
            f"Skill: {skill.name}\n"
            f"Skill 目录: {skill.directory}\n"
            "需要读取该 Skill 附带的文件时，可再次调用 loadSkill 并传入 filename。\n\n"
            f"{body}"
        )

    return ToolSpec(
        name=LOAD_SKILL_NAME,
        description=(
            "读取 Skill 的完整说明或附件。只传 name 时返回 SKILL.md 全文；"
            "同时传 filename 时读取该 Skill 目录内的指定文件，不会重复返回 SKILL.md。"
            "当用户请求与某个可用 Skill 的描述相符时，先用本工具加载该 Skill，"
            "再严格按照其中的说明完成任务；不要猜测 Skill 的内容。"
        ),
        parameters=LOAD_SKILL_PARAMETERS,
        handler=load_skill,
    )


def _load_attachment(skill: SkillMetadata, filename: str) -> ToolOutcome:
    resolution = resolve_skill_file(skill, filename)
    if resolution.error is not None:
        return ToolOutcome(f"Error: {resolution.error}")

    skill_dir = skill.directory.expanduser().resolve()

    if resolution.candidates:
        lines = [
            f"Skill '{skill.name}' 中找到多个名为 {filename} 的文件，"
            "请从以下候选路径中选择一个（均相对于 Skill 目录），"
            "作为 filename 再次调用 loadSkill："
        ]
        lines.extend(
            f"- {candidate.relative_to(skill_dir).as_posix()}"
            for candidate in resolution.candidates
        )
        return ToolOutcome("\n".join(lines))

    path = resolution.path
    if path is None:
        return ToolOutcome(f"Error: 无法解析附件路径: {filename}")

    try:
        text, truncated = read_skill_attachment(path)
    except (OSError, ValueError) as exc:
        return ToolOutcome(f"Error: 无法读取 {filename}: {exc}")

    lines = [
        f"Skill: {skill.name}",
        f"File: {path.relative_to(skill_dir).as_posix()}",
        f"Skill 目录: {skill_dir}",
    ]
    if truncated:
        lines.append(f"（文件超过 {MAX_ATTACHMENT_BYTES} 字节，已截断）")
    lines.extend(["", text])
    return ToolOutcome("\n".join(lines))
