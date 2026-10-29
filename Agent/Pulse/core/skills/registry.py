"""Skill 注册表：按名称索引，供系统提示词与 loadSkill 工具使用。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

from core.skills.models import SkillMetadata


class SkillRegistry:
    """持有已发现 Skill 的元数据。

    注册表只保存 ``SkillMetadata``，不缓存正文。名称匹配先精确后忽略大小写，
    以适应模型偶尔改变大小写的情况。
    """

    def __init__(
        self,
        skills: Iterable[SkillMetadata] = (),
        *,
        warnings: Iterable[str] = (),
        root: Path | str | None = None,
    ):
        self.root = Path(root).expanduser() if root is not None else None
        self._skills: dict[str, SkillMetadata] = {}
        self._casefold_names: dict[str, str] = {}
        self._warnings: list[str] = list(warnings)
        for skill in skills:
            self.add(skill)

    def add(self, skill: SkillMetadata) -> bool:
        """注册一个 Skill；名称重复时保留先注册的并返回 False。"""
        if skill.name in self._skills:
            return False
        self._skills[skill.name] = skill
        self._casefold_names.setdefault(skill.name.casefold(), skill.name)
        return True

    def add_warning(self, message: str) -> None:
        self._warnings.append(message)

    @property
    def skills(self) -> tuple[SkillMetadata, ...]:
        return tuple(self._skills.values())

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._skills)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def get(self, name: str) -> SkillMetadata | None:
        if not isinstance(name, str):
            return None
        skill = self._skills.get(name)
        if skill is not None:
            return skill
        actual = self._casefold_names.get(name.casefold())
        return self._skills.get(actual) if actual is not None else None

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self) -> Iterator[SkillMetadata]:
        return iter(self._skills.values())
