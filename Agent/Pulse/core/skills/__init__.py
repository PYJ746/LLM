"""Agent Skills：发现、注册与按需加载。

本包保持无副作用：不在这里做 eager re-export，避免与 core.prompts、
core.tools 形成循环导入。按需从子模块导入：

- ``core.skills.models``：``SkillMetadata``
- ``core.skills.registry``：``SkillRegistry``
- ``core.skills.loader``：``discover_skills`` / ``load_skill_body``
- ``core.skills.prompt``：``build_system_prompt``
"""
