from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.agent import AgentEngine
from core.config import PulseConfig
from core.llm.base import ChatChunk, ToolCallDelta
from core.prompts import SYSTEM_PROMPT
from core.skills.loader import (
    discover_skills,
    load_skill_body,
    parse_frontmatter,
    split_frontmatter,
)
from core.skills.models import SkillMetadata
from core.skills.prompt import build_system_prompt
from core.skills.registry import SkillRegistry
from core.tools.defaults import build_default_registry
from core.tools.registry import ToolRegistry
from tests.conftest import FakeChatModel, text_turn
from tui.app import PulseApp
from tui.widgets.messages import SystemNotice

SKILL_BODY = "1. 通知标题必须包含部门名称。\n2. 落款必须写明起草人。"


def write_skill(
    root: Path,
    directory_name: str = "notice",
    *,
    name: str = "notice",
    description: str = "撰写公司内部通知",
    body: str = SKILL_BODY,
) -> Path:
    skill_dir = root / ".agents" / "skills" / directory_name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8",
    )
    return skill_dir


async def collect(engine: AgentEngine, text: str):
    return [event async for event in engine.run_turn(text)]


def tool_turn(*deltas: ToolCallDelta) -> list[ChatChunk]:
    return [ChatChunk(tool_calls=deltas)]


def messages_text(messages) -> str:
    return "\n".join(message.content or "" for message in messages)


# ----------------------------------------------------------------------
# 发现与注册
# ----------------------------------------------------------------------


def test_discovers_metadata_from_required_frontmatter(tmp_path):
    skill_dir = write_skill(tmp_path, name="notice", description="撰写公司内部通知")

    registry = discover_skills(tmp_path)

    assert registry.names == ("notice",)
    skill = registry.get("notice")
    assert skill is not None
    assert skill.name == "notice"
    assert skill.description == "撰写公司内部通知"
    assert skill.directory == skill_dir
    assert skill.skill_file == skill_dir / "SKILL.md"


def test_initialization_does_not_read_body(tmp_path):
    """正文即使不是合法 UTF-8，也不应影响初始化。"""
    skill_dir = tmp_path / ".agents" / "skills" / "broken-body"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(
        b"---\nname: broken-body\ndescription: body is not utf-8\n---\n"
        + b"\xff\xfe\x00" * 5000
    )

    registry = discover_skills(tmp_path)

    assert registry.names == ("broken-body",)


def test_missing_skills_directory_is_empty(tmp_path):
    registry = discover_skills(tmp_path / "not-there")
    assert len(registry) == 0
    assert registry.warnings == ()


def test_directory_without_skill_md_is_skipped(tmp_path):
    (tmp_path / ".agents" / "skills" / "empty").mkdir(parents=True)

    registry = discover_skills(tmp_path)

    assert len(registry) == 0
    assert any("缺少 SKILL.md" in warning for warning in registry.warnings)


@pytest.mark.parametrize(
    "content, missing",
    [
        ("---\ndescription: 没有名称\n---\n", "name"),
        ("---\nname: no-description\n---\n", "description"),
        ("---\nname: ''\ndescription: 空名称\n---\n", "name"),
        ("没有 frontmatter\n", "Frontmatter"),
        ("---\nname: unclosed\n", "未闭合"),
    ],
)
def test_invalid_skill_is_skipped_with_warning(tmp_path, content, missing):
    skill_dir = tmp_path / ".agents" / "skills" / "invalid"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    registry = discover_skills(tmp_path)

    assert len(registry) == 0
    assert any(missing in warning for warning in registry.warnings)


def test_duplicate_names_keep_first(tmp_path):
    write_skill(tmp_path, "first", name="same", description="第一个")
    write_skill(tmp_path, "second", name="same", description="第二个")

    registry = discover_skills(tmp_path)

    assert registry.names == ("same",)
    assert registry.get("same").description == "第一个"
    assert any("名称重复" in warning for warning in registry.warnings)


def test_skill_name_lookup_is_case_insensitive(tmp_path):
    write_skill(tmp_path, "notice", name="Notice")

    registry = discover_skills(tmp_path)

    assert registry.get("notice") is not None
    assert registry.get("NOTICE") is not None


# ----------------------------------------------------------------------
# Frontmatter 解析
# ----------------------------------------------------------------------


def test_parse_quoted_and_multiline_scalars():
    parsed = parse_frontmatter(
        "name: \"撰写 通知\"\n"
        "description: >\n"
        "  第一行\n"
        "  第二行\n"
        "\n"
        "  第三段\n"
        "license: MIT # 注释\n"
        "single: 'it''s'\n"
    )

    assert parsed["name"] == "撰写 通知"
    assert parsed["description"] == "第一行 第二行\n第三段"
    assert parsed["license"] == "MIT"
    assert parsed["single"] == "it's"


def test_parse_literal_block_keeps_newlines():
    parsed = parse_frontmatter("name: x\ndescription: |\n  第一行\n  第二行\n")
    assert parsed["description"] == "第一行\n第二行"


def test_parse_tolerates_trailing_text_after_quoted_value():
    parsed = parse_frontmatter('name: notice\ndescription: "通知"XX\n')
    assert parsed["description"] == "通知"


def test_split_frontmatter_returns_body():
    frontmatter, body = split_frontmatter("---\na: b\n---\n\n正文\n")
    assert frontmatter == "a: b\n"
    assert body == "\n正文\n"


# ----------------------------------------------------------------------
# 按需加载
# ----------------------------------------------------------------------


def test_load_skill_body_strips_frontmatter(tmp_path):
    skill_dir = write_skill(tmp_path)
    registry = discover_skills(tmp_path)
    skill = registry.get("notice")

    body = load_skill_body(skill)

    assert body == SKILL_BODY
    assert "description" not in body
    assert skill_dir.joinpath("SKILL.md").is_file()


def test_default_registry_registers_load_skill_only_when_needed(tmp_path):
    empty = discover_skills(tmp_path)
    assert "loadSkill" not in build_default_registry(skills=empty).names
    assert "loadSkill" not in build_default_registry().names

    write_skill(tmp_path)
    registry = discover_skills(tmp_path)
    names = build_default_registry(skills=registry).names
    assert names[-1] == "loadSkill"
    assert len(names) == 14


async def test_load_skill_tool_returns_body_and_directory(tmp_path):
    skill_dir = write_skill(tmp_path)
    skills = discover_skills(tmp_path)
    registry = build_default_registry(skills=skills)

    result = await registry.execute("call_1", "loadSkill", {"name": "notice"})

    assert result.ok
    assert "Skill: notice" in result.content
    assert str(skill_dir) in result.content
    assert SKILL_BODY in result.content


async def test_load_skill_tool_reports_unknown_name(tmp_path):
    write_skill(tmp_path)
    registry = build_default_registry(skills=discover_skills(tmp_path))

    result = await registry.execute("call_1", "loadSkill", {"name": "missing"})

    assert result.ok
    assert result.content.startswith("Error: 未知 Skill")
    assert "notice" in result.content


async def test_load_skill_tool_requires_name(tmp_path):
    write_skill(tmp_path)
    registry = build_default_registry(skills=discover_skills(tmp_path))

    result = await registry.execute("call_1", "loadSkill", {})

    assert "缺少参数 name" in result.content


# ----------------------------------------------------------------------
# loadSkill 的 filename 参数
# ----------------------------------------------------------------------


def write_attachment(skill_dir: Path, relative: str, content: str) -> Path:
    path = skill_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def skill_registry(tmp_path) -> tuple[ToolRegistry, Path]:
    skill_dir = write_skill(tmp_path)
    registry = build_default_registry(skills=discover_skills(tmp_path))
    return registry, skill_dir


async def test_filename_relative_to_skill_directory(tmp_path):
    registry, skill_dir = skill_registry(tmp_path)
    write_attachment(skill_dir, "references/guide.md", "参考内容")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": "references/guide.md"},
    )

    assert "参考内容" in result.content
    assert "File: references/guide.md" in result.content
    # 提供了 filename 时不再重复返回 SKILL.md 正文
    assert SKILL_BODY not in result.content


async def test_filename_is_absolute_path(tmp_path):
    registry, skill_dir = skill_registry(tmp_path)
    target = write_attachment(skill_dir, "assets/prompt.txt", "绝对路径内容")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": str(target)},
    )

    assert "绝对路径内容" in result.content
    assert "File: assets/prompt.txt" in result.content


async def test_filename_is_project_relative_path(tmp_path):
    registry, skill_dir = skill_registry(tmp_path)
    write_attachment(skill_dir, "references/guide.md", "项目相对内容")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {
            "name": "notice",
            "filename": ".agents/skills/notice/references/guide.md",
        },
    )

    assert "项目相对内容" in result.content


async def test_bare_filename_is_found_recursively_when_unique(tmp_path):
    registry, skill_dir = skill_registry(tmp_path)
    write_attachment(skill_dir, "deep/nested/guide.md", "递归内容")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": "guide.md"},
    )

    assert "递归内容" in result.content
    assert "File: deep/nested/guide.md" in result.content


async def test_duplicate_bare_filenames_return_candidates(tmp_path):
    registry, skill_dir = skill_registry(tmp_path)
    write_attachment(skill_dir, "a/same.md", "内容 A")
    write_attachment(skill_dir, "b/same.md", "内容 B")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": "same.md"},
    )

    assert "多个" in result.content
    assert "a/same.md" in result.content
    assert "b/same.md" in result.content
    assert "内容 A" not in result.content
    assert "内容 B" not in result.content


async def test_exact_path_wins_over_recursive_search(tmp_path):
    registry, skill_dir = skill_registry(tmp_path)
    write_attachment(skill_dir, "references/guide.md", "精确内容")
    write_attachment(skill_dir, "other/guide.md", "其他内容")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": "references/guide.md"},
    )

    assert "精确内容" in result.content
    assert "其他内容" not in result.content


async def test_traversal_outside_skill_directory_is_rejected(tmp_path):
    registry, _ = skill_registry(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("不要泄露的内容", encoding="utf-8")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": "../../../secret.txt"},
    )

    assert result.content.startswith("Error:")
    assert "不要泄露的内容" not in result.content


async def test_absolute_path_outside_skill_directory_is_rejected(tmp_path):
    registry, _ = skill_registry(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("不要泄露的内容", encoding="utf-8")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": str(secret)},
    )

    assert result.content.startswith("Error:")
    assert "不要泄露的内容" not in result.content


async def test_missing_attachment_returns_clear_error(tmp_path):
    registry, _ = skill_registry(tmp_path)

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": "not-there.md"},
    )

    assert result.content.startswith("Error:")
    assert "找不到" in result.content


async def test_binary_attachment_is_rejected(tmp_path):
    registry, skill_dir = skill_registry(tmp_path)
    (skill_dir / "blob.bin").write_bytes(b"\x00\x01\x02")

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": "blob.bin"},
    )

    assert "二进制" in result.content


async def test_empty_filename_loads_skill_body(tmp_path):
    registry, _ = skill_registry(tmp_path)

    result = await registry.execute(
        "call_1",
        "loadSkill",
        {"name": "notice", "filename": ""},
    )

    assert SKILL_BODY in result.content


def test_load_skill_parameters_describe_filename():
    from core.tools.builtin.skills import LOAD_SKILL_PARAMETERS

    properties = LOAD_SKILL_PARAMETERS["properties"]
    assert set(properties) == {"name", "filename"}
    assert LOAD_SKILL_PARAMETERS["required"] == ["name"]


# ----------------------------------------------------------------------
# 动态加载原则与既有工具协作
# ----------------------------------------------------------------------


async def test_skill_body_is_not_in_context_before_load_skill(tmp_path):
    write_skill(tmp_path)
    skills = discover_skills(tmp_path)
    model = FakeChatModel([text_turn("好的")])
    engine = AgentEngine(
        model,
        build_default_registry(skills=skills),
        skills=skills.skills,
    )

    await collect(engine, "你好")

    assert "撰写公司内部通知" in engine.session.system_prompt
    assert SKILL_BODY not in engine.session.system_prompt
    assert SKILL_BODY not in messages_text(engine.messages)
    # 工具的 JSON Schema 也不包含正文
    tools_json = json.dumps(
        build_default_registry(skills=skills).to_openai_tools(),
        ensure_ascii=False,
    )
    assert SKILL_BODY not in tools_json
    # 首次请求只有 system + user，且不含 Skill 正文
    assert SKILL_BODY not in messages_text(model.calls[0][0])


async def test_skill_body_enters_context_only_after_load_skill(tmp_path):
    write_skill(tmp_path)
    skills = discover_skills(tmp_path)
    model = FakeChatModel(
        [
            tool_turn(ToolCallDelta(0, "call_1", "loadSkill", '{"name": "notice"}')),
            text_turn("完成"),
        ]
    )
    engine = AgentEngine(
        model,
        build_default_registry(skills=skills),
        skills=skills.skills,
    )

    await collect(engine, "写通知")

    assert SKILL_BODY not in messages_text(model.calls[0][0])
    assert SKILL_BODY in messages_text(model.calls[1][0])
    tool_message = next(m for m in engine.messages if m.role == "tool")
    assert SKILL_BODY in (tool_message.content or "")


async def test_load_skill_cooperates_with_existing_file_tools(tmp_path):
    write_skill(tmp_path)
    skills = discover_skills(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("普通文件内容", encoding="utf-8")

    model = FakeChatModel(
        [
            tool_turn(ToolCallDelta(0, "call_1", "loadSkill", '{"name": "notice"}')),
            tool_turn(
                ToolCallDelta(
                    0, "call_2", "readTextFile", '{"path": "note.txt"}'
                )
            ),
            text_turn("完成"),
        ]
    )
    engine = AgentEngine(
        model,
        build_default_registry(workspace=tmp_path, skills=skills),
        skills=skills.skills,
    )

    events = await collect(engine, "先读 Skill 再读文件")

    roles = [message.role for message in engine.messages]
    assert roles == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    tool_messages = [m for m in engine.messages if m.role == "tool"]
    assert tool_messages[0].tool_call_id == "call_1"
    assert SKILL_BODY in (tool_messages[0].content or "")
    assert tool_messages[1].tool_call_id == "call_2"
    assert "普通文件内容" in (tool_messages[1].content or "")
    assert engine.messages[-1].content == "完成"
    # 两个工具都经过正常的 ToolCallRequested/Completed 事件
    assert len(events) == 7


def test_existing_tools_are_unchanged_when_skills_are_present(tmp_path):
    write_skill(tmp_path)
    with_skills = build_default_registry(skills=discover_skills(tmp_path)).names
    baseline = build_default_registry().names

    assert with_skills[:-1] == baseline
    assert with_skills[-1] == "loadSkill"
    assert "RunCli" in with_skills
    assert "readTextFile" in with_skills


# ----------------------------------------------------------------------
# 提示词与引擎集成
# ----------------------------------------------------------------------


def metadata(tmp_path, name="notice", description="撰写公司内部通知"):
    return SkillMetadata(
        name=name,
        description=description,
        directory=tmp_path,
        skill_file=tmp_path / "SKILL.md",
    )


def test_system_prompt_lists_name_and_description(tmp_path):
    prompt = build_system_prompt([metadata(tmp_path)])

    assert prompt.startswith(SYSTEM_PROMPT)
    assert "You have access to the following skills:" in prompt
    assert "- 'notice': 撰写公司内部通知" in prompt
    assert "Use the 'loadSkill' tool" in prompt
    assert "you MUST call 'loadSkill'" in prompt
    assert "load additional files referenced by a skill" in prompt


def test_system_prompt_unchanged_without_skills():
    assert build_system_prompt([]) == SYSTEM_PROMPT


async def test_agent_engine_injects_skills_into_system_prompt(tmp_path):
    write_skill(tmp_path)
    skills = discover_skills(tmp_path)
    model = FakeChatModel([text_turn("好的")])
    engine = AgentEngine(
        model,
        build_default_registry(skills=skills),
        skills=skills.skills,
    )

    await collect(engine, "帮我写通知")

    assert "- 'notice': 撰写公司内部通知" in engine.session.system_prompt
    tool_names = [spec.name for spec in model.calls[0][1]]
    assert tool_names[-1] == "loadSkill"


async def test_tui_skills_command_lists_discovered_skills(tmp_path):
    write_skill(tmp_path)
    skills = discover_skills(tmp_path)
    config = PulseConfig(
        base_url="https://example.com",
        api_key="test-key",
        model="test-model",
    )
    app = PulseApp(
        config=config,
        model=FakeChatModel([]),
        registry=build_default_registry(workspace=tmp_path, skills=skills),
        workspace=tmp_path,
        skills=skills,
    )

    async with app.run_test(size=(100, 40)) as pilot:
        await app.submit("/skills")
        await pilot.pause()
        notices = "\n".join(
            str(item.content) for item in app.query(SystemNotice)
        )

    assert "可用 Skills（1）" in notices
    assert "notice" in notices
    assert "撰写公司内部通知" in notices
