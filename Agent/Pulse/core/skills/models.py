"""Skill 元数据（叶子模块）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """初始化阶段发现的一个 Skill。

    只包含 frontmatter 中的 ``name`` / ``description`` 与磁盘位置，
    不包含 SKILL.md 正文；正文由 ``load_skill_body()`` 在需要时读取。
    """

    name: str
    description: str
    directory: Path
    skill_file: Path
