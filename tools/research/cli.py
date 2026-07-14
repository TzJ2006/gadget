"""CLI interface for the research analysis tool."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from research.config import (
    load_config,
    interactive_config_init,
    show_config,
    resolve_output_dir,
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
    from research.analysis import run_analysis
    from research.cache import DiskCache

    config = load_config()
    paths = resolve_profiler_paths(config)
    cache = DiskCache(paths["cache"]) if not args.no_cache else None

    from research.analysis import _parse_batch_line

    # Collect names and batch hints
    names: list[str] = []
    batch_hints: dict[str, tuple[str, str]] = {}
    if args.names:
        names.extend(args.names)
    if args.from_file:
        path = Path(args.from_file)
        if not path.exists():
            print(f"错误: 文件不存在 — {path}")
            sys.exit(1)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parsed_name, ph, aid = _parse_batch_line(line)
                    names.append(parsed_name)
                    if ph or aid:
                        batch_hints[parsed_name] = (ph, aid)

    if not names:
        print("错误: 请提供至少一个研究者姓名")
        print("用法: python -m research analyze \"Sergey Levine\" --mode fast")
        sys.exit(1)

    mode = args.mode or config.get("default_mode", "fast")
    depth = args.depth if args.depth is not None else config.get("default_depth", 1)
    max_students = args.max_students if args.max_students is not None else config.get("max_students", 10)
    model = args.model or config.get("model", "sonnet")
    backend = getattr(args, "api", None) or config.get("default_api", "ollama")
    s2_key = config.get("semantic_scholar_api_key", "")

    homepage_url = getattr(args, "homepage", "") or ""
    affiliation = getattr(args, "affiliation", "") or ""
    paper_hint = getattr(args, "paper", "") or ""
    author_id_hint = getattr(args, "author_id", "") or ""

    profiles = run_analysis(
        seed_names=names,
        mode=mode,
        depth=depth,
        max_students=max_students,
        model=model,
        cache=cache,
        no_cache=args.no_cache,
        profiles_dir=str(paths["profiles"]),
        reports_dir=str(paths["reports"]),
        s2_api_key=s2_key,
        backend=backend,
        homepage_url=homepage_url,
        affiliation=affiliation,
        paper_hint=paper_hint,
        author_id_hint=author_id_hint,
        hints=batch_hints if batch_hints else None,
    )

    # Deploy to Hugo if requested
    if getattr(args, "deploy", False) and profiles:
        from research.output import deploy_to_hugo
        from common.paths import GADGET_ROOT, resolve_repo_path

        raw_hugo = getattr(args, "hugo_site", None) or config.get("hugo_site", "")
        # Distinguish "unset" from a valid path with an empty .name (e.g. "."):
        # only fall back to the default site when no value was provided at all.
        hugo_site = (
            resolve_repo_path(raw_hugo)
            if raw_hugo
            else (GADGET_ROOT / "tools" / "website")
        )
        if hugo_site.exists():
            for p in profiles:
                deploy_to_hugo(p, hugo_site)
            from common.hugo import run_hugo_update
            run_hugo_update(hugo_site)
        else:
            print(f"警告: Hugo 站点不存在: {hugo_site}，跳过部署")


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
