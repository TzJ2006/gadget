"""CLI interface for the research analysis tool."""

from __future__ import annotations

import argparse
import logging
import sys

from research.config import (
    load_config,
    interactive_config_init,
    show_config,
    resolve_profiler_paths,
)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_analyze(args: argparse.Namespace) -> None:
    """Handle the 'analyze' subcommand."""
    from research.analysis import run_profiler

    run_profiler(args)


def cmd_show(args: argparse.Namespace) -> None:
    """Handle the 'show' subcommand."""
    from research.output import show_profile

    config = load_config()
    paths = resolve_profiler_paths(config)
    show_profile(args.name, paths["profiles"], reports_dir=paths["reports"])


def cmd_list(args: argparse.Namespace) -> None:
    """Handle the 'list' subcommand."""
    from research.output import list_profiles

    config = load_config()
    paths = resolve_profiler_paths(config)
    list_profiles(paths["profiles"])


def cmd_config(args: argparse.Namespace) -> None:
    """Handle the 'config' subcommand."""
    if args.init:
        interactive_config_init()
    else:
        config = load_config()
        show_config(config)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="research",
        description="学术研究者分析工具 — 分析研究脉络、发现 rising star",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="显示详细日志")
    subparsers = parser.add_subparsers(dest="command")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="分析研究者")
    p_analyze.add_argument("names", nargs="*", help="研究者姓名")
    p_analyze.add_argument("--from-file", help="从文件读取研究者名单（每行一个）")
    p_analyze.add_argument("--mode", choices=["fast", "detailed"],
                           help="分析模式 (默认: fast)")
    p_analyze.add_argument("--depth", type=int,
                           help="递归深度 (0=仅种子, 默认: 1=同时分析发现的学生)")
    p_analyze.add_argument("--max-students", type=int,
                           help="每层最多探索学生数 (默认: 10)")
    p_analyze.add_argument("--model", choices=["sonnet", "opus", "haiku"],
                           help="Claude 模型 (默认: sonnet)")
    p_analyze.add_argument("--api", choices=["claude_cli", "anthropic", "openai", "ollama"],
                           help="LLM 后端 (默认: ollama)")
    p_analyze.add_argument("--affiliation", type=str, default="",
                           help="机构提示（用于同名作者消歧）")
    hint_group = p_analyze.add_mutually_exclusive_group()
    hint_group.add_argument("--paper", type=str, default="",
                            help="已知论文（arXiv ID、DOI 或论文标题）用于反向查找作者")
    hint_group.add_argument("--author-id", type=str, default="",
                            help="直接指定 Semantic Scholar 作者 ID")
    p_analyze.add_argument("--homepage", type=str, default="",
                           help="研究者主页 URL（用于发现学生）")
    p_analyze.add_argument("--deploy", action="store_true",
                           help="分析后部署到 Hugo 站点")
    p_analyze.add_argument("--hugo-site", type=str, default=None,
                           help="Hugo 站点根目录")
    p_analyze.add_argument("--no-cache", action="store_true",
                           help="跳过缓存")
    p_analyze.set_defaults(func=cmd_analyze)

    # show
    p_show = subparsers.add_parser("show", help="显示已分析的研究者")
    p_show.add_argument("name", help="研究者姓名")
    p_show.set_defaults(func=cmd_show)

    # list
    p_list = subparsers.add_parser("list", help="列出所有已分析的研究者")
    p_list.set_defaults(func=cmd_list)

    # config
    p_config = subparsers.add_parser("config", help="配置管理")
    p_config.add_argument("--init", action="store_true", help="交互式配置")
    p_config.set_defaults(func=cmd_config)

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
