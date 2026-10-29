"""把 Skill 元数据注入系统提示词。

只注入 name / description（渐进式加载的第一层），完整正文留给 loadSkill。
"""

from __future__ import annotations

from typing import Iterable

from core.prompts import SYSTEM_PROMPT
from core.skills.models import SkillMetadata

SKILLS_HEADER = "\n\nYou have access to the following skills:\n"

SKILLS_FOOTER = (
    "Use the 'loadSkill' tool to load the full instructions of a skill "
    "when needed. When the user's request matches a skill's description, "
    "you MUST call 'loadSkill' for that skill before answering, instead of "
    "answering from guessed skill content. "
    "You can also load additional files referenced by a skill."
)


def format_skills(skills: Iterable[SkillMetadata]) -> str:
    """渲染 Skill 清单，每个 Skill 占一行：``- 'name': description``。"""
    lines: list[str] = []
    for skill in skills:
        # name / description 压成单行，避免多行 frontmatter 破坏列表结构
        name = " ".join(skill.name.split())
        description = " ".join(skill.description.split())
        lines.append(f"- '{name}': {description}")
    return "\n".join(lines)


def build_system_prompt(skills: Iterable[SkillMetadata] = ()) -> str:
    """在基础系统提示词后追加 Skill 目录；没有 Skill 时原样返回。"""
    skills = tuple(skills)
    if not skills:
        return SYSTEM_PROMPT
    return (
        SYSTEM_PROMPT
        + SKILLS_HEADER
        + format_skills(skills)
        + "\n"
        + SKILLS_FOOTER
    )
