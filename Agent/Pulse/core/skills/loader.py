"""Skill 发现与按需加载。

发现规则（Agent Skills 规范）：

- 项目根目录为程序启动时的工作目录；
- Skill 位于 ``<项目根>/.agents/skills/<skill>/SKILL.md``；
- SKILL.md 必须以 YAML Frontmatter 开头，且包含 ``name`` / ``description``。

渐进式加载：

1. 初始化只读取 frontmatter，解析 ``name`` / ``description``，不读取正文；
2. 模型调用 ``loadSkill`` 时，才读取完整 SKILL.md 并返回正文。

frontmatter 解析只实现 Skill 场景用到的 YAML 子集：顶层 ``key: value``、
单/双引号、``|`` / ``>`` 块标量。嵌套键会被忽略，因而无需引入 YAML 依赖。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from core.skills.models import SkillMetadata
from core.skills.registry import SkillRegistry

SKILLS_DIRECTORY = Path(".agents") / "skills"
SKILL_FILENAME = "SKILL.md"
REQUIRED_FIELDS = ("name", "description")

# 防止恶意/损坏文件在初始化阶段消耗过多内存。
MAX_FRONTMATTER_BYTES = 256 * 1024
MAX_FRONTMATTER_LINE = 1024 * 1024
MAX_SKILL_BODY_CHARS = 100_000
MAX_ATTACHMENT_BYTES = 200_000

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class SkillFileResolution:
    """``filename`` 的解析结果。

    - ``path``：找到唯一文件；
    - ``candidates``：同名文件有多个，交由模型选择；
    - ``error``：未找到、越界或参数为空。
    """

    path: Path | None = None
    candidates: tuple[Path, ...] = ()
    error: str | None = None


def skills_root(project_root: Path | str) -> Path:
    """返回项目根目录下的 Skill 根目录。"""
    return Path(project_root).expanduser() / SKILLS_DIRECTORY


def discover_skills(project_root: Path | str) -> SkillRegistry:
    """扫描 ``<project_root>/.agents/skills/`` 并注册 Skill 元数据。

    目录不存在时返回空注册表；单个 Skill 不合法时记录警告并跳过，
    不影响 Pulse 启动，也不影响其他 Skill。
    """
    root = skills_root(project_root).resolve()
    registry = SkillRegistry(root=root)
    if not root.is_dir():
        return registry

    try:
        directories = sorted(
            root.iterdir(), key=lambda item: item.name.casefold()
        )
    except OSError as exc:
        registry.add_warning(f"{root}: 无法读取 Skill 目录: {exc}")
        return registry

    for directory in directories:
        if not directory.is_dir():
            continue
        # 跳过隐藏目录与 __pycache__ 等内部目录，避免产生无意义的警告
        if directory.name.startswith((".", "__")):
            continue

        skill_file = directory / SKILL_FILENAME
        if not skill_file.is_file():
            registry.add_warning(f"{directory}: 缺少 {SKILL_FILENAME}")
            continue

        metadata, error = read_skill_metadata(skill_file, directory)
        if error is not None:
            registry.add_warning(f"{skill_file}: {error}")
            continue
        if not registry.add(metadata):
            registry.add_warning(
                f"{skill_file}: Skill 名称重复，已忽略: {metadata.name}"
            )

    return registry


def read_skill_metadata(
    skill_file: Path, directory: Path
) -> tuple[SkillMetadata | None, str | None]:
    """读取单个 SKILL.md 的 frontmatter，返回元数据或错误说明。"""
    frontmatter, error = read_frontmatter(skill_file)
    if error is not None or frontmatter is None:
        return None, error or "无法解析 YAML Frontmatter"

    values: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        value = frontmatter.get(field, "")
        if not isinstance(value, str) or not value.strip():
            return None, f"缺少必需的 frontmatter 字段: {field}"
        values[field] = value.strip()

    return (
        SkillMetadata(
            name=values["name"],
            description=values["description"],
            directory=directory,
            skill_file=skill_file,
        ),
        None,
    )


def read_frontmatter(skill_file: Path) -> tuple[dict[str, str] | None, str | None]:
    """只读取 SKILL.md 开头的 frontmatter，不读取正文。

    以二进制逐行读取，读到结束分隔符立即停止；因此即使正文不是合法
    UTF-8（或非常大），也不会影响初始化阶段的元数据加载。
    """
    try:
        with skill_file.open("rb") as handle:
            first = handle.readline(MAX_FRONTMATTER_LINE)
            if first.startswith(b"\xef\xbb\xbf"):  # UTF-8 BOM
                first = first[3:]
            if first.strip() != b"---":
                return None, "SKILL.md 必须以 YAML Frontmatter (---) 开头"

            payload = bytearray()
            while True:
                line = handle.readline(MAX_FRONTMATTER_LINE)
                if not line:
                    return None, "YAML Frontmatter 未闭合（缺少结束的 ---）"
                if line.strip() in (b"---", b"..."):
                    break
                payload.extend(line)
                if len(payload) > MAX_FRONTMATTER_BYTES:
                    return None, "YAML Frontmatter 过大"
    except OSError as exc:
        return None, f"无法读取 SKILL.md: {exc}"

    return parse_frontmatter(_decode(bytes(payload))), None


def parse_frontmatter(text: str) -> dict[str, str]:
    """解析 frontmatter 的 YAML 子集，返回顶层键的字符串值。"""
    result: dict[str, str] = {}
    lines = text.splitlines()
    index = 0

    while index < len(lines):
        raw = lines[index]
        index += 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # 缩进行属于嵌套结构或上一项的续行，Skill 元数据不需要
        if raw[:1].isspace():
            continue
        if ":" not in raw:
            continue

        key, _, remainder = raw.partition(":")
        key = key.strip()
        if not _KEY_PATTERN.match(key):
            continue

        value = remainder.strip()
        if value[:1] in ("|", ">") and value.rstrip("+-") in ("|", ">"):
            block, index = _collect_block(lines, index)
            result[key] = _render_block(
                block,
                folded=value[0] == ">",
                keep=value.endswith("+"),
            )
        else:
            result[key] = _parse_scalar(value)

    return result


def load_skill_body(skill: SkillMetadata) -> str:
    """读取 SKILL.md 完整正文（去掉 frontmatter），供 loadSkill 使用。"""
    text = _decode(skill.skill_file.read_bytes())
    _, body = split_frontmatter(text)
    body = body.replace("\r\n", "\n").replace("\r", "\n").lstrip("\n")
    if len(body) > MAX_SKILL_BODY_CHARS:
        body = (
            body[:MAX_SKILL_BODY_CHARS]
            + "\n\n（Skill 正文过长，已截断）"
        )
    return body


def resolve_skill_file(
    skill: SkillMetadata, filename: str
) -> SkillFileResolution:
    """在 Skill 目录内解析 ``filename``。

    解析顺序（先精确、后模糊）：

    1. 绝对路径；
    2. 相对 Skill 目录的路径；
    3. 相对项目根目录的路径（如 ``.agents/skills/<name>/a.md``）；
    4. 只给文件名时，在 Skill 目录内递归查找；唯一命中才返回，
       多个同名文件返回 ``candidates`` 供模型选择。

    所有结果都必须位于该 Skill 目录内；符号链接会先 resolve，
    因此指向目录外部的链接同样会被拒绝。
    """
    raw = filename.strip() if isinstance(filename, str) else ""
    if not raw:
        return SkillFileResolution(error="filename 不能为空")

    skill_dir = skill.directory.expanduser().resolve()
    user_path = Path(raw).expanduser()

    exact_candidates: list[Path] = []
    if user_path.is_absolute():
        exact_candidates.append(user_path)
    else:
        exact_candidates.append(skill_dir / user_path)
        project_root = _project_root(skill_dir)
        if project_root is not None:
            exact_candidates.append(project_root / user_path)

    for candidate in exact_candidates:
        resolved = _safe_resolve(candidate)
        if resolved is None:
            continue
        if _is_within(resolved, skill_dir) and resolved.is_file():
            return SkillFileResolution(path=resolved)

    if not _is_bare_filename(raw):
        return SkillFileResolution(
            error=(
                f"在 Skill '{skill.name}' 中找不到文件: {raw}"
                f"（读取范围限于 {skill_dir}）"
            )
        )

    matches = _find_files_by_name(skill_dir, raw)
    if not matches:
        return SkillFileResolution(
            error=(
                f"在 Skill '{skill.name}' 中找不到名为 {raw} 的文件"
                f"（读取范围限于 {skill_dir}）"
            )
        )
    if len(matches) == 1:
        return SkillFileResolution(path=matches[0])
    return SkillFileResolution(candidates=tuple(matches))


def read_skill_attachment(
    path: Path, *, max_bytes: int = MAX_ATTACHMENT_BYTES
) -> tuple[str, bool]:
    """读取 Skill 目录内的文本附件，返回 ``(文本, 是否截断)``。

    读取量最多 ``max_bytes + 1`` 字节，避免大文件撑爆上下文；
    含 NUL 字节的文件视为二进制并拒绝。
    """
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)

    truncated = len(data) > max_bytes
    data = data[:max_bytes]
    if b"\x00" in data:
        raise ValueError("二进制文件不支持直接读取")

    text = _decode(data)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, truncated


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _project_root(skill_dir: Path) -> Path | None:
    """由 ``<项目>/.agents/skills/<name>`` 推出项目根目录。"""
    parents = skill_dir.parents
    return parents[2] if len(parents) >= 3 else None


def _is_bare_filename(value: str) -> bool:
    path = Path(value)
    return (
        not path.is_absolute()
        and path.parent == Path(".")
        and path.name not in ("", ".", "..")
    )


def _find_files_by_name(skill_dir: Path, filename: str) -> list[Path]:
    """在 Skill 目录内递归查找同名文件（忽略大小写）。"""
    target = filename.casefold()
    matches: list[Path] = []
    seen: set[Path] = set()

    try:
        for current_root, directory_names, file_names in os.walk(skill_dir):
            directory_names.sort(key=str.casefold)
            for name in sorted(file_names, key=str.casefold):
                if name.casefold() != target:
                    continue
                resolved = _safe_resolve(Path(current_root) / name)
                if resolved is None or not _is_within(resolved, skill_dir):
                    continue
                if not resolved.is_file() or resolved in seen:
                    continue
                seen.add(resolved)
                matches.append(resolved)
    except OSError:
        return []

    matches.sort(
        key=lambda item: item.relative_to(skill_dir).as_posix().casefold()
    )
    return matches


def split_frontmatter(text: str) -> tuple[str, str]:
    """把文档拆成 (frontmatter, 正文)；没有 frontmatter 时第一部分为空。"""
    lines = text.splitlines(keepends=True)
    if not lines:
        return "", text
    if lines[0].lstrip(chr(0xFEFF)).strip() != "---":
        return "", text
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    return "", text


def _collect_block(lines: list[str], index: int) -> tuple[list[str], int]:
    """收集块标量的内容行；遇到下一个顶层键时停止。"""
    block: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line.strip() and not line[:1].isspace():
            break
        block.append(line)
        index += 1
    return block, index


def _render_block(lines: list[str], *, folded: bool, keep: bool) -> str:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]

    indent = min(
        (len(line) - len(line.lstrip(" ")) for line in lines if line.strip()),
        default=0,
    )
    content = [line[indent:] if len(line) >= indent else "" for line in lines]

    if folded:
        parts: list[str] = []
        blank_lines = 0
        for line in content:
            if line.strip():
                if parts:
                    parts.append("\n" if blank_lines else " ")
                parts.append(line)
                blank_lines = 0
            else:
                blank_lines += 1
        text = "".join(parts)
    else:
        text = "\n".join(content)

    if keep:
        return text + "\n" if text else text
    return text.rstrip("\n")


def _parse_scalar(value: str) -> str:
    if not value or value.startswith("#"):
        return ""

    quote = value[0]
    if quote in ('"', "'"):
        end = _closing_quote(value, quote)
        if end is not None:
            inner = value[1:end]
            if quote == "'":
                return inner.replace("''", "'")
            return _unescape_double(inner)

    # 未加引号（或引号未闭合）时，按 YAML 规则去掉 " #" 之后的注释
    comment = value.find(" #")
    if comment != -1:
        value = value[:comment]
    return value.strip()


def _closing_quote(value: str, quote: str) -> int | None:
    index = 1
    while index < len(value):
        char = value[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            return index
        index += 1
    return None


def _unescape_double(text: str) -> str:
    mapping = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        '"': '"',
        "\\": "\\",
        "0": "\0",
    }
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            escape = text[index + 1]
            result.append(mapping.get(escape, escape))
            index += 2
        else:
            result.append(char)
            index += 1
    return "".join(result)


def _decode(data: bytes) -> str:
    """与文件工具一致：优先 UTF-8（含 BOM），其次 GBK。"""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")
