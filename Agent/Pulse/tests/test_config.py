from __future__ import annotations

import pytest

from core.config import config_candidates, load_config
from core.errors import ConfigError


def write_config(path, *, key="sk-test", model="test-model", extra=""):
    path.write_text(
        "[llm]\n"
        "base_url = https://example.com/\n"
        f"api_key = {key}\n"
        f"model = {model}\n"
        f"{extra}",
        encoding="utf-8",
    )


def test_load_explicit_config(tmp_path):
    path = tmp_path / "config.ini"
    write_config(path, extra="request_timeout = 12.5\nmax_tool_rounds = 7\n")

    config = load_config(path)

    assert config.base_url == "https://example.com"
    assert config.api_key == "sk-test"
    assert config.model == "test-model"
    assert config.request_timeout == 12.5
    assert config.max_tool_rounds == 7
    assert "sk-test" not in repr(config)


def test_load_config_with_bom(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel = m\n",
        encoding="utf-8-sig",
    )
    assert load_config(path).model == "m"


def test_missing_required_key(tmp_path):
    path = tmp_path / "config.ini"
    write_config(path, key="")
    with pytest.raises(ConfigError, match="缺少必填项"):
        load_config(path)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="找不到配置文件"):
        load_config(tmp_path / "nope.ini")


def test_env_var_takes_priority(tmp_path, monkeypatch):
    path = tmp_path / "custom.ini"
    write_config(path, model="from-env")
    monkeypatch.setenv("PULSE_CONFIG", str(path))
    assert load_config().model == "from-env"


def test_candidates_include_agent_config():
    candidates = [str(item) for item in config_candidates()]
    assert any(item.endswith("Agent\\config.ini") or item.endswith("Agent/config.ini") for item in candidates)


def test_invalid_max_rounds(tmp_path):
    path = tmp_path / "config.ini"
    write_config(path, extra="max_tool_rounds = 0\n")
    with pytest.raises(ConfigError, match="max_tool_rounds"):
        load_config(path)


def test_search_section_is_optional(tmp_path):
    path = tmp_path / "config.ini"
    write_config(path)

    config = load_config(path)

    assert config.search_api_key == ""
    assert config.search_model == ""


def test_search_section_is_loaded_and_hidden_from_repr(tmp_path):
    path = tmp_path / "config.ini"
    write_config(
        path,
        extra=(
            "[search]\n"
            "baidu_qianfan_api_key = bce-v3/test-key\n"
            "model = custom-search-model\n"
        ),
    )

    config = load_config(path)

    assert config.search_api_key == "bce-v3/test-key"
    assert config.search_model == "custom-search-model"
    assert "bce-v3/test-key" not in repr(config)
