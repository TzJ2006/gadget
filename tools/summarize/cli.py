"""CLI entry point for the daily summarize pipeline.

Parses command-line arguments and dispatches to the appropriate
subcommand handler (export, merge, deploy, config).
"""

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from .daily import (
    cmd_export,
    cmd_export_past,
    cmd_merge,
    cmd_deploy,
    cmd_config,
)


def _parse_date(date_str: Optional[str]) -> date:
    """解析日期字符串，None 时返回今天。"""
    if date_str:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            print(f"[error] 日期格式无效: {date_str}，请使用 YYYY-MM-DD")
            sys.exit(1)
    return date.today()


def main():
    parser = argparse.ArgumentParser(description="AI 对话日报总结工具（多设备两阶段架构）")
    subparsers = parser.add_subparsers(dest="command")

    # ── export 子命令 ──
    sp_export = subparsers.add_parser("export", help="Phase 1: 本地导出对话 log")
    sp_export.add_argument("--date", type=str, default=None,
                           help="目标日期 (YYYY-MM-DD)，默认今天")
    sp_export.add_argument("--chatgpt", type=str, default=None,
                           help="ChatGPT 导出的 conversations.json 路径")
    sp_export.add_argument("--generic", type=str, action="append", default=[],
                           help="通用 JSON 对话文件路径（可多次指定）")
    sp_export.add_argument("--summarize", action="store_true",
                           help="同时调 API 生成单设备 AI 总结")
    sp_export.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"],
                           default="ollama", help="使用的 API (默认 ollama)")
    sp_export.add_argument("--output", type=str, default=None,
                           help="输出目录 (默认 outputs/logs/summarize/)")
    sp_export.add_argument("--timeout", type=int, default=600,
                           help="每 150K chunk 的 LLM 调用时限秒数 (默认 600)")
    sp_export.add_argument("--export-past", action="store_true",
                           help="批量导出所有过去未导出的日期")
    sp_export.add_argument("--force", action="store_true",
                           help="强制重新导出所有日期（包括已 finalized 的）")

    # ── merge 子命令 ──
    sp_merge = subparsers.add_parser("merge", help="Phase 2: 合并 log 文件生成日报")
    sp_merge.add_argument("log_files", nargs="*", default=[],
                          help="要合并的 log JSON 文件路径（使用 --sync 时可省略）")
    sp_merge.add_argument("--sync", action="store_true",
                          help="从 rclone 远端下载 log 文件后合并")
    sp_merge.add_argument("--sync-all", action="store_true",
                          help="从 rclone 同步所有 log，按日期逐天处理（每天独立子进程）")
    sp_merge.add_argument("--date", type=str, default=None,
                          help="目标日期 (YYYY-MM-DD)，默认从 log 文件推断")
    sp_merge.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"],
                          default="ollama", help="使用的 API (默认 ollama)")
    sp_merge.add_argument("--output", type=str, default=None,
                          help="输出目录 (默认 outputs/reports/summarize/)")
    sp_merge.add_argument("--deploy", action="store_true",
                          help="同时部署到 Hugo 站点")
    sp_merge.add_argument("--hugo-site", type=str,
                          default=str(Path(__file__).resolve().parent.parent / "website"),
                          help="Hugo 站点根目录")
    sp_merge.add_argument("--timeout", type=int, default=600,
                          help="每 150K chunk 的 LLM 调用时限秒数 (默认 600)")
    sp_merge.add_argument("--no-cache", action="store_true",
                          help="忽略已有的 AI 总结缓存，强制重新调用 API")
    sp_merge.add_argument("--force", action="store_true",
                          help="忽略已有 finalized 报告，强制重新生成")
    sp_merge.add_argument("--workers", type=int, default=1,
                          help="--sync-all 并行 worker 数 (默认 1，即顺序处理)")
    sp_merge.add_argument("--before", type=str, default=None,
                          help="只处理该日期之前的数据 (YYYY-MM-DD)，用于排除当天未完成的记录")

    # ── deploy 子命令 ──
    sp_deploy = subparsers.add_parser("deploy", help="批量部署报告到 Hugo bugJournal")
    sp_deploy.add_argument("--date", type=str, default=None,
                           help="目标日期 (YYYY-MM-DD)，默认部署所有报告")
    sp_deploy.add_argument("--hugo-site", type=str,
                           default=str(Path(__file__).resolve().parent.parent / "website"),
                           help="Hugo 站点根目录")
    sp_deploy.add_argument("--reports-dir", type=str, default=None,
                           help="报告目录 (默认 outputs/reports/summarize/)")
    sp_deploy.add_argument("--force", action="store_true",
                           help="强制重新部署所有报告（默认跳过已部署的；"
                                "覆盖前自动备份到 outputs/backups/website-force/）")
    sp_deploy.add_argument("--overwrite-human", action="store_true",
                           help="危险：允许覆盖无 gadget 标记的手写站点文件")

    # ── config 子命令 ──
    sp_config = subparsers.add_parser("config", help="查看或初始化配置文件")
    sp_config.add_argument("--show", action="store_true", default=True,
                           help="显示当前配置（默认）")
    sp_config.add_argument("--init", action="store_true",
                           help="交互式创建配置文件")

    # config-driven defaults: CLI flag > config.json > hardcoded. Applied per
    # subparser because a subparser's explicit default overrides a parent's.
    from .config import cli_defaults
    _d = cli_defaults()
    for p in (parser, sp_export, sp_merge, sp_deploy):
        p.set_defaults(**_d)

    # ── 无子命令时的参数（默认走 export）──
    parser.add_argument("--date", type=str, default=None,
                        help="目标日期 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--chatgpt", type=str, default=None,
                        help="ChatGPT 导出的 conversations.json 路径")
    parser.add_argument("--generic", type=str, action="append", default=[],
                        help="通用 JSON 对话文件路径（可多次指定）")
    parser.add_argument("--summarize", action="store_true",
                        help="同时调 API 生成单设备 AI 总结")
    parser.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"],
                        default="ollama", help="使用的 API (默认 ollama)")
    parser.add_argument("--output", type=str, default=None,
                        help="输出目录")
    parser.add_argument("--timeout", type=int, default=600,
                        help="每 150K chunk 的 LLM 调用时限秒数 (默认 600)")
    parser.add_argument("--export-past", action="store_true",
                        help="批量导出所有过去未导出的日期")
    parser.add_argument("--force", action="store_true",
                        help="强制重新导出所有日期（包括已 finalized 的）")

    args = parser.parse_args()

    if args.command == "export":
        if args.export_past or args.date is None:
            cmd_export_past(args)
        else:
            cmd_export(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "deploy":
        cmd_deploy(args)
    elif args.command == "config":
        cmd_config(args)
    else:
        # 无子命令 → 默认走 export
        if args.export_past or args.date is None:
            cmd_export_past(args)
        else:
            cmd_export(args)


if __name__ == "__main__":
    main()
