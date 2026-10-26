"""Pulse TUI 入口：python -m tui [--config ...] [--workspace ...]"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from core.config import load_config
from core.errors import ConfigError
from core.llm.openai import OpenAIChatClient
from core.tools.defaults import build_default_registry
from tui.app import PulseApp

WORKSPACE_ENV_VAR = "PULSE_WORKSPACE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse",
        description="Pulse：带本地工具调用能力的 TUI Agent",
    )
    parser.add_argument(
        "--config",
        help="配置文件路径；默认向上查找 Agent/config.ini",
    )
    parser.add_argument(
        "--workspace",
        help="工具相对路径的基准目录；默认取 PULSE_WORKSPACE 或当前目录",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    workspace = Path(
        args.workspace or os.environ.get(WORKSPACE_ENV_VAR) or Path.cwd()
    ).expanduser()
    if not workspace.is_dir():
        print(f"工作区不存在或不是目录：{workspace}", file=sys.stderr)
        return 1
    workspace = workspace.resolve()

    model = OpenAIChatClient(config)
    registry = build_default_registry(
        workspace=workspace,
        search_api_key=config.search_api_key,
        search_model=config.search_model,
    )
    app = PulseApp(
        config=config,
        model=model,
        registry=registry,
        workspace=workspace,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
