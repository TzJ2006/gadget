"""Deploy daily reports to Hugo and manage summarize config."""

import json
import platform
import shutil
import sys
from datetime import date
from io import StringIO

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from common.hugo import run_hugo_update
from common.llm import LLM_BACKENDS, DEFAULT_BACKEND
from common.site_staging import resolve_site_content_dir
from common.translation import count_translation_chunks

from .config import (
    _load_config,
    _resolve_output_dir,
    _get_device_name,
    _save_summarize_config,
    resolve_hugo_site,
)
from .daily_helpers import _parse_date, _DEFAULT_LOGS_DIR, _DEFAULT_REPORTS_DIR
from .formatter import generate_hugo_post
from .remote import _find_rclone


def cmd_deploy(args):
    """批量部署报告到 Hugo bugJournal（默认只部署尚未上线的报告）。"""
    reports_dir = _resolve_output_dir(getattr(args, 'reports_dir', None),
                                      "SUMMARIZE_REPORTS_DIR",
                                      "reports_dir", _DEFAULT_REPORTS_DIR)
    hugo_site = resolve_hugo_site(args.hugo_site)

    if not hugo_site.exists():
        print(f"[error] Hugo 站点目录不存在: {hugo_site}", file=sys.stderr)
        sys.exit(1)

    if not reports_dir.exists():
        print(f"[error] 报告目录不存在: {reports_dir}", file=sys.stderr)
        sys.exit(1)

    # Collect target markdown files
    if args.date:
        target_date = _parse_date(args.date)
        md_files = [reports_dir / f"{target_date.isoformat()}.md"]
        md_files = [f for f in md_files if f.exists()]
        if not md_files:
            print(f"[warn] 未找到 {target_date.isoformat()} 的报告", file=sys.stderr)
            sys.exit(0)
    else:
        md_files = sorted(reports_dir.glob("*.md"))
        if not md_files:
            print("[warn] 报告目录中没有 .md 文件", file=sys.stderr)
            sys.exit(0)

    # Determine which reports are already deployed to Hugo
    hugo_content_dir = resolve_site_content_dir(hugo_site, "bugJournal", "daily")
    deployed_dates: set[str] = set()
    if hugo_content_dir.exists():
        for p in hugo_content_dir.glob("*.md"):
            try:
                date.fromisoformat(p.stem)
                deployed_dates.add(p.stem)
            except ValueError:
                pass

    # Filter: only deploy reports not yet on the website (unless --force)
    force = getattr(args, 'force', False)
    to_deploy = []
    skipped = 0
    non_date_skipped = 0
    for md_file in md_files:
        try:
            file_date = date.fromisoformat(md_file.stem)
        except ValueError:
            non_date_skipped += 1
            continue
        if not force and md_file.stem in deployed_dates:
            skipped += 1
            continue
        to_deploy.append((md_file, file_date))

    if not to_deploy:
        # 已 staged ≠ 已发布：仍要跑一次 Hugo 构建 + push，确保站点是最新的
        print("[ok] 所有报告均已 staged，直接运行 Hugo 构建/发布")
        run_hugo_update(hugo_site)
        return

    # Set up log file
    log_dir = _DEFAULT_REPORTS_DIR.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "deploy.log"
    log_file = open(log_path, "w", encoding="utf-8")

    def log(msg: str) -> None:
        log_file.write(msg + "\n")
        log_file.flush()

    # Pre-calculate total translation chunks for tqdm
    total_chunks = 0
    for md_file, _ in to_deploy:
        content = md_file.read_text(encoding="utf-8")
        total_chunks += count_translation_chunks(content)

    log(f"[info] 报告总数: {len(md_files)}, 跳过非日期: {non_date_skipped}, "
        f"已部署: {skipped}, 待部署: {len(to_deploy)}, 翻译块: {total_chunks}")
    print(f"Deploying {len(to_deploy)} reports, {total_chunks} chunks (log: {log_path})")

    errors: list[str] = []
    pbar = tqdm(total=total_chunks, desc="Translating", unit="chunk") if tqdm else None

    for md_file, file_date in to_deploy:
        buf = StringIO()
        try:
            markdown_body = md_file.read_text(encoding="utf-8")
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                generate_hugo_post(markdown_body, file_date, hugo_site, pbar=pbar,
                                   force=force,
                                   overwrite_human=getattr(args, "overwrite_human", False))
            finally:
                sys.stdout = old_stdout
            log(buf.getvalue().rstrip())
        except Exception as e:
            log(buf.getvalue().rstrip())
            msg = f"[error] {file_date.isoformat()}: {e}"
            log(msg)
            print(msg, file=sys.stderr)
            errors.append(msg)

    if pbar:
        pbar.close()

    log_file.close()

    if errors:
        print(f"\n{len(errors)} errors (see {log_path}):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
    else:
        print(f"Done. {len(to_deploy)} reports deployed.")

    run_hugo_update(hugo_site)


def cmd_config(args):
    """查看或初始化配置文件。"""
    if args.init:
        _config_init()
    else:
        # 默认 --show
        _config_show()


def _config_show():
    """显示当前配置。"""
    from common.config import resolve_config_path

    path = resolve_config_path()
    print(f"配置文件路径: {path}  (section: summarize)")
    cfg = _load_config()
    if cfg:
        print("配置内容:")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
    else:
        print("(summarize 段不存在，使用默认值)")

    print()
    print("当前生效路径:")
    print(f"  device_name:  {_get_device_name()}")
    logs_dir = _resolve_output_dir(None, "SUMMARIZE_LOGS_DIR",
                                   "logs_dir", _DEFAULT_LOGS_DIR)
    reports_dir = _resolve_output_dir(None, "SUMMARIZE_REPORTS_DIR",
                                      "reports_dir", _DEFAULT_REPORTS_DIR)
    print(f"  logs_dir:     {logs_dir}")
    print(f"  reports_dir:  {reports_dir}")

    remote = cfg.get("rclone_remote")
    if remote:
        rclone_bin = _find_rclone()
        status = f"已找到: {rclone_bin}" if rclone_bin else "未找到"
        print(f"  rclone:       {remote} ({status})")
        print(f"    logs:       {remote}/logs/")
        print(f"    reports:    {remote}/reports/")
    else:
        print(f"  rclone:       (未配置)")
    rclone_path = cfg.get("rclone_path")
    if rclone_path:
        print(f"  rclone_path:  {rclone_path}")


def _config_init():
    """交互式创建 summarize 段，写入仓库根目录 config.json。"""
    from common.config import resolve_config_path

    path = resolve_config_path()
    print(f"配置文件路径: {path}  (section: summarize)")
    existing = _load_config()
    if existing:
        overwrite = input("summarize 配置已存在，是否覆盖该段？[y/N] ").strip().lower()
        if overwrite != "y":
            print("取消")
            return

    cfg = {}

    # device_name
    default_name = platform.node() or "unknown"
    name = input(f"设备别名 (device_name) [{default_name}]: ").strip()
    cfg["device_name"] = name or default_name

    # logs_dir
    logs = input("logs 输出目录 (留空使用默认 outputs/logs/summarize/): ").strip()
    if logs:
        cfg["logs_dir"] = logs

    # reports_dir
    reports = input("reports 输出目录 (留空使用默认 outputs/reports/summarize/): ").strip()
    if reports:
        cfg["reports_dir"] = reports

    # rclone_remote
    rclone = input("rclone 远端路径 (如 <remote名>:<目录>，留空跳过): ").strip()
    if rclone:
        cfg["rclone_remote"] = rclone

    # rclone_path（仅在设了 remote 且 PATH 中没有 rclone 时询问）
    if rclone and not shutil.which("rclone"):
        rclone_path = input("rclone 二进制路径 (如 ~/.local/bin/rclone，留空跳过): ").strip()
        if rclone_path:
            cfg["rclone_path"] = rclone_path

    # ── 行为默认值（供 auto / daily / weekly / monthly 作为 flag 默认）──
    api = input(f"默认 API ({'/'.join(LLM_BACKENDS)}) [{DEFAULT_BACKEND}]: ").strip()
    if api:
        cfg["default_api"] = api

    model = input("本地模型名 (OLLAMA_MODEL，如 gemma4-sum，留空跳过): ").strip()
    if model:
        cfg["model"] = model

    reasoning = input("推理力度 (reasoning_effort，本地思考模型填 none，留空跳过): ").strip()
    if reasoning:
        cfg["reasoning_effort"] = reasoning

    deploy = input("auto 是否默认部署到 Hugo？[y/N] ").strip().lower()
    if deploy == "y":
        cfg["deploy"] = True

    hugo_default = resolve_hugo_site()
    hugo_site = input(f"Hugo 站点根目录 (deploy 用，留空使用 {hugo_default}): ").strip()
    if hugo_site:
        cfg["hugo_site"] = hugo_site

    workers = input("daily merge --sync-all 并行 worker 数 (留空使用默认 1): ").strip()
    if workers.isdigit():
        cfg["workers"] = int(workers)

    saved = _save_summarize_config(cfg, replace=True)
    print(f"\n[ok] 配置已保存: {saved}  (section: summarize)")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
