"""配置加载。

查找顺序（先找到先使用）：
1. 显式传入的 path
2. 环境变量 PULSE_CONFIG
3. core/config.ini、Pulse/config.ini、Agent/config.ini、LLM/config.ini

从本文件位置向上查找，而不是依赖当前工作目录，这样从任何目录启动都能
复用 Agent/config.ini。
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from core.errors import ConfigError

CONFIG_ENV_VAR = "PULSE_CONFIG"
DEFAULT_SECTION = "llm"
REQUIRED_KEYS = ("base_url", "api_key", "model")
SEARCH_SECTION = "search"
SEARCH_API_KEY = "baidu_qianfan_api_key"


@dataclass(frozen=True, slots=True)
class PulseConfig:
    """运行 Agent 所需的配置。

    search_api_key / search_model 来自可选的 [search] 段：缺少该段时
    search_api_key 为空，searchWeb 工具会在被调用时返回明确的配置提示。
    """

    base_url: str
    api_key: str = field(repr=False)
    model: str
    request_timeout: float = 60.0
    max_tool_rounds: int = 20
    search_api_key: str = field(default="", repr=False)
    search_model: str = ""


def config_candidates(explicit: str | Path | None = None) -> list[Path]:
    """返回按优先级排序的候选配置文件路径。"""
    if explicit is not None:
        return [Path(explicit).expanduser()]

    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        return [Path(env_path).expanduser()]

    here = Path(__file__).resolve().parent
    directories = (here, *here.parents[:3])
    return [directory / "config.ini" for directory in directories]


def load_config(path: str | Path | None = None) -> PulseConfig:
    """读取配置文件并返回 PulseConfig；找不到或不合法时抛 ConfigError。"""
    candidates = config_candidates(path)
    config_path = next((item for item in candidates if item.is_file()), None)
    if config_path is None:
        searched = ", ".join(str(item) for item in candidates)
        raise ConfigError(f"找不到配置文件。已查找: {searched}")

    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8-sig")
    except (configparser.Error, OSError) as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}: {exc}") from exc

    if not parser.has_section(DEFAULT_SECTION):
        raise ConfigError(f"配置文件 {config_path} 缺少 [{DEFAULT_SECTION}] 段")

    values = {
        key: parser.get(DEFAULT_SECTION, key, fallback="").strip()
        for key in REQUIRED_KEYS
    }
    missing = [key for key in REQUIRED_KEYS if not values[key]]
    if missing:
        raise ConfigError(
            f"配置文件 {config_path} 缺少必填项: {', '.join(missing)}"
        )

    request_timeout = _parse_float(parser, config_path, "request_timeout", 60.0)
    max_tool_rounds = _parse_int(parser, config_path, "max_tool_rounds", 20)
    if max_tool_rounds < 1:
        raise ConfigError(f"配置文件 {config_path} 的 max_tool_rounds 必须大于 0")

    search_api_key, search_model = _parse_search_section(parser)

    return PulseConfig(
        base_url=values["base_url"].rstrip("/"),
        api_key=values["api_key"],
        model=values["model"],
        request_timeout=request_timeout,
        max_tool_rounds=max_tool_rounds,
        search_api_key=search_api_key,
        search_model=search_model,
    )


def _parse_search_section(
    parser: configparser.ConfigParser,
) -> tuple[str, str]:
    """读取可选的 [search] 段；缺失时返回空值，不影响 Pulse 启动。"""
    if not parser.has_section(SEARCH_SECTION):
        return "", ""
    api_key = parser.get(SEARCH_SECTION, SEARCH_API_KEY, fallback="").strip()
    model = parser.get(SEARCH_SECTION, "model", fallback="").strip()
    return api_key, model


def _parse_float(
    parser: configparser.ConfigParser, config_path: Path, key: str, default: float
) -> float:
    raw = parser.get(DEFAULT_SECTION, key, fallback="").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"配置文件 {config_path} 的 {key} 不是数字: {raw}") from exc


def _parse_int(
    parser: configparser.ConfigParser, config_path: Path, key: str, default: int
) -> int:
    raw = parser.get(DEFAULT_SECTION, key, fallback="").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"配置文件 {config_path} 的 {key} 不是整数: {raw}") from exc
