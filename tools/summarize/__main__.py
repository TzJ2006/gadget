"""Unified CLI entry point: python -m summarize {daily,weekly,monthly,auto,onboard}."""

import argparse
import sys


def main():
    # Bridge local-LLM / translation knobs from config into env before any dispatch
    # (auto's subprocesses inherit them).
    from summarize.config import apply_env_from_config
    apply_env_from_config()

    if len(sys.argv) >= 2 and sys.argv[1] == "auto":
        _main_auto()
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "onboard":
        _main_onboard()
        return

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m summarize {daily,weekly,monthly,auto,onboard} [args...]")
        print()
        print("Subcommands:")
        print("  daily    Daily conversation summary (export/merge/deploy)")
        print("  weekly   Weekly summary generation")
        print("  monthly  Monthly summary generation")
        print("  auto     Run full pipeline: daily → weekly → monthly")
        print("  onboard  Check/setup requirements for summarize auto")
        sys.exit(0)

    subcmd = sys.argv[1]
    sys.argv = [f"summarize-{subcmd}"] + sys.argv[2:]

    if subcmd == "daily":
        from summarize.cli import main as daily_main
        daily_main()
    elif subcmd == "weekly":
        from summarize.weekly_summary import main as weekly_main
        weekly_main()
    elif subcmd == "monthly":
        from summarize.monthly_summary import main as monthly_main
        monthly_main()
    else:
        print(f"Unknown subcommand: {subcmd}")
        print("Available: daily, weekly, monthly, auto, onboard")
        sys.exit(1)


def _main_auto():
    parser = argparse.ArgumentParser(
        prog="summarize auto",
        description="Run full pipeline: daily export → merge → weekly → monthly",
    )
    from summarize.cli import add_api_flag

    parser.add_argument("--date", type=str, default=None,
                        help="Aggregation target date (YYYY-MM-DD), default: yesterday")
    add_api_flag(parser)
    parser.add_argument("--deploy", action="store_true",
                        help="Deploy reports to Hugo after generation")
    parser.add_argument("--hugo-site", type=str, default=None,
                        help="Hugo site root directory for --deploy")
    parser.add_argument("--force", action="store_true",
                        help="Force regeneration of existing reports")
    parser.add_argument("--workers", type=int, default=1,
                        help="Daily merge --sync-all worker count (default: 1)")
    parser.add_argument("--no-ssh", action="store_true",
                        help="Skip the SSH fan-out to summarize.ssh_hosts")
    parser.add_argument("--skip-onboard-check", action="store_true",
                        help="Skip readiness checks before running auto")
    from summarize.config import cli_defaults
    parser.set_defaults(**cli_defaults())
    args = parser.parse_args(sys.argv[2:])

    from summarize.auto import cmd_auto
    cmd_auto(args)


def _main_onboard():
    from summarize.onboarding import cmd_onboard

    parser = argparse.ArgumentParser(
        prog="summarize onboard",
        description="Check/setup requirements for summarize auto",
    )
    from summarize.cli import add_api_flag

    add_api_flag(parser, help_text="LLM API used by auto")
    parser.add_argument("--deploy", action="store_true",
                        help="Also check Hugo deploy requirements")
    parser.add_argument("--hugo-site", type=str, default=None,
                        help="Hugo site root directory for --deploy")
    parser.add_argument("--init-config", action="store_true",
                        help="Interactively create/update the summarize section in repo-root config.json")
    parser.add_argument("--json", action="store_true",
                        help="Print machine-readable check results")
    from summarize.config import cli_defaults
    parser.set_defaults(**cli_defaults())
    args = parser.parse_args(sys.argv[2:])

    cmd_onboard(args)


if __name__ == "__main__":
    main()
