#!/usr/bin/env python3
"""集中式 rclone 同步脚本 — 将个人数据文件与 Google Drive 同步。

用法:
    python scripts/sync.py push              # 本地 → 远端
    python scripts/sync.py pull              # 远端 → 本地
    python scripts/sync.py status            # 显示差异
    python scripts/sync.py config --init     # 初始化配置
    python scripts/sync.py bootstrap --remote gdrive:gadget  # 新设备一键初始化

选项:
    --dry-run                        # 预览，不实际传输
    --category <name>                # 只同步某一类 (summarize/website/research/benchmark/backups; test = benchmark 旧名)
    --include-config                 # push 时同时备份配置文件
    --include-tokens                 # push/bootstrap 时包含 tokens/ 目录
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GADGET_ROOT = Path(__file__).resolve().parent.parent

# Unified repo-root config (section: sync). Override with GADGET_CONFIG.
from common import config as gadget_config

CONFIG_FILE = gadget_config.DEFAULT_CONFIG_PATH


WEBSITE_DIR = GADGET_ROOT / "tools" / "website"
WEBSITE_UPDATE_SCRIPT = WEBSITE_DIR / "update.sh"

# ---------------------------------------------------------------------------
# Sync map: category → list of (local_path, remote_subdir)
#   local_path is relative to GADGET_ROOT
#   remote_subdir is relative to the rclone remote base (e.g. gdrive:gadget/)
# ---------------------------------------------------------------------------

# Directories — synced as-is
SYNC_DIRS: dict[str, list[tuple[str, str]]] = {
    "summarize": [
        ("outputs/logs/summarize", "summarize/logs"),
        ("outputs/reports/summarize", "summarize/reports"),
        ("outputs/images/summarize", "summarize/images"),
    ],
    # 单一 Hugo 内容根：生成 + 手写内容都在 tools/website/content|static 下
    # （outputs/site staging 已在 2026-07 迁移中移除）。远端布局保持不变。
    "website": [
        ("tools/website/content/bugJournal/daily", "website/bugJournal/daily"),
        ("tools/website/content/bugJournal/weekly", "website/bugJournal/weekly"),
        ("tools/website/content/bugJournal/monthly", "website/bugJournal/monthly"),
        ("tools/website/content/research", "website/research"),
        # One entry per level that publishes a usage chart. A published level
        # whose directory is missing here self-deletes: static/images/ is
        # gitignored, and publish.py wipes public/ and rebuilds from static/,
        # so the next publish from a machine without the PNGs stages their
        # deletion while the markdown keeps linking them. That is exactly how
        # /dag/ deleted itself before 0984632.
        ("tools/website/static/images/daily", "website/static/images/daily"),
        ("tools/website/static/images/weekly", "website/static/images/weekly"),
        ("tools/website/static/images/monthly", "website/static/images/monthly"),
        ("tools/website/static/benchmark-report", "website/static/benchmark-report"),
        # Built by ../ai-companion, not by this repo (the dag category was
        # removed here), but it lands in this site tree and is published from
        # it — so it needs a way onto the other machines for exactly the reason
        # above. Without this the page deletes itself again the moment a second
        # machine publishes.
        ("tools/website/static/dag", "website/static/dag"),
        # Same story, never yet triggered: both are gitignored and published,
        # so a machine without them stages their deletion on the next publish.
        ("tools/website/static/videos", "website/static/videos"),
        ("tools/website/static/pdfs", "website/static/pdfs"),
        ("tools/website/content/leetcode", "website/leetcode"),
        ("tools/website/content/posts", "website/posts"),
    ],
    # scout 现写 research-scout/*，profiler 写 research-profiler/*。旧的
    # outputs/*/research 目录是改名前的遗留（远端同名目录里是同类数据，pull
    # 时 additively 合并进新目录，无冲突）。
    "research": [
        ("outputs/cache/research-scout", "research/cache"),
        ("tools/research/projects", "research/projects"),
        ("outputs/reports/research-scout", "research/reports"),
        ("outputs/logs/research-scout", "research/logs"),
        ("outputs/reports/research-profiler", "research/reports-profiler"),
        ("outputs/data/research-profiler", "research/data-profiler"),
    ],
    # The results ledger is a tracked file, not a synced directory, and the
    # submission queue under tools/benchmark/data/ is tracked too — so this
    # category has no directories to sync. It kept a mapping for
    # outputs/data/benchmark, which nothing has ever written.
    "benchmark": [],
    # 强制重生成前的自动备份（website-force）+ 报告覆盖备份（summarize）
    "backups": [
        ("outputs/backups/website-force", "backups/website-force"),
        ("outputs/backups/summarize", "backups/summarize"),
    ],
}

# Loose files — collected into a staging dir then synced as one rclone call
SYNC_FILES: dict[str, list[tuple[str, str]]] = {
    "website": [
        ("tools/website/content/About.pdf", "website/personal/About.pdf"),
        ("tools/website/content/benchmark.md", "website/benchmark.md"),
        ("tools/website/content/benchmark.zh.md", "website/benchmark.zh.md"),
        ("tools/website/content/Resume.md", "website/personal/Resume.md"),
        ("tools/website/content/Resume.pdf", "website/personal/Resume.pdf"),
        ("tools/website/content/Random.md", "website/personal/Random.md"),
    ],
    "benchmark": [
        # Was outputs/data/benchmark/results.csv — a path nothing writes, so
        # `push --category benchmark` copied nothing. The real ledger is here
        # (cli.py:23, core.py:171, report.py:595 all agree). Remote name kept
        # so existing objects stay where they are.
        ("tools/benchmark/benchmark_results.csv", "benchmark/data/benchmark_results.csv"),
    ],
}

# Files a pull must never replace wholesale. A pull is a whole-file copy, which
# for an append-only ledger means the remote silently discards every row this
# machine added since its last push — and the ledger's entire purpose is to
# accumulate rows from several machines. AGENTS.md: "results append to
# benchmark_results.csv by design — never rewrite or dedupe it."
# Before the mapping was repointed at the real ledger this was harmless: it
# named a path nothing writes, so pull had nothing to clobber.
APPEND_ONLY_FILES = {
    "tools/benchmark/benchmark_results.csv",
}


def merge_append_only_csv(src: Path, dst: Path) -> tuple[bool, str]:
    """Union *src*'s rows into *dst*, keeping dst's rows and their order.

    Row identity is the whole line. Every row carries a timestamp, so two
    byte-identical lines are one measurement synced twice, not two runs that
    happened to agree — which is why this adds rows and never drops any.
    Returns (ok, message).
    """
    src_lines = src.read_text(encoding="utf-8").splitlines()
    if not src_lines:
        return True, "远端为空，本地不变"
    if not dst.exists():
        shutil.copy2(str(src), str(dst))
        return True, f"本地不存在，直接写入 {len(src_lines) - 1} 行"

    dst_lines = dst.read_text(encoding="utf-8").splitlines()
    if not dst_lines:
        shutil.copy2(str(src), str(dst))
        return True, f"本地为空，直接写入 {len(src_lines) - 1} 行"

    if src_lines[0] != dst_lines[0]:
        # Merging rows under mismatched headers would put values in the wrong
        # columns. Refuse rather than corrupt the ledger.
        return False, "表头不一致，拒绝合并（先统一列定义再同步）"

    have = set(dst_lines[1:])
    added = [ln for ln in src_lines[1:] if ln and ln not in have]
    if not added:
        return True, "远端没有本地缺的行"

    needs_newline = not dst.read_text(encoding="utf-8").endswith("\n")
    with open(dst, "a", newline="", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        for ln in added:
            f.write(ln + "\n")
    return True, f"追加 {len(added)} 行（本地 {len(dst_lines) - 1} 行一行未动）"


# Pre-2026-08 category name. Same mappings as `benchmark`; remote layout moved
# from test/data → benchmark/data (old GDrive objects are not auto-migrated).
CATEGORY_ALIASES: dict[str, str] = {
    "test": "benchmark",
}


def resolve_category(category: str | None) -> str | None:
    """Map a CLI --category value to a SYNC_DIRS/SYNC_FILES key."""
    if not category:
        return None
    return CATEGORY_ALIASES.get(category, category)


def rclone_category_choices() -> list[str]:
    return list(SYNC_DIRS) + list(CATEGORY_ALIASES)


# Config files for bootstrap — single root config.json
BOOTSTRAP_CONFIGS: list[tuple[str, Path]] = [
    ("config/config.json", gadget_config.DEFAULT_CONFIG_PATH),
]

TOKENS_DIR = GADGET_ROOT / "tokens"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_config_cache: dict | None = None


def load_config() -> dict:
    """Load the ``sync`` section from the unified root config.json."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    cfg = gadget_config.load_section("sync")
    _config_cache = dict(cfg)
    return _config_cache


def save_sync_config(cfg: dict) -> Path:
    """Write the ``sync`` section and invalidate local cache."""
    global _config_cache
    path = gadget_config.update_section("sync", cfg, replace=True)
    _config_cache = None
    gadget_config.clear_cache()
    return path


def get_remote() -> str:
    cfg = load_config()
    remote = cfg.get("rclone_remote", "")
    if not remote:
        print("[error] 未配置 rclone_remote。运行 `python scripts/sync.py config --init` 初始化。")
        sys.exit(1)
    return remote


# ---------------------------------------------------------------------------
# rclone helpers
# ---------------------------------------------------------------------------


def find_rclone() -> str:
    cfg = load_config()
    custom = cfg.get("rclone_path")
    if custom:
        p = Path(custom).expanduser()
        if p.is_file():
            return str(p)
        print(f"[warn] rclone_path 指定的路径不存在: {custom}")
    path = shutil.which("rclone")
    if not path:
        print("[error] rclone 未找到。请安装 rclone 或在 config 中设置 rclone_path。")
        sys.exit(1)
    return path


def run_rclone(args: list[str], *, dry_run: bool = False, timeout: int = 600,
               ok_if_missing: bool = False) -> bool:
    """Run an rclone command. Returns True on success.

    ok_if_missing: treat a missing source root ("directory not found") as a
    no-op success — used on pull when the remote category dir was never pushed.
    """
    rclone = find_rclone()
    cmd = [rclone] + args
    if dry_run:
        cmd.append("--dry-run")
    print(f"  $ {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.returncode != 0:
            if ok_if_missing and "directory not found" in result.stderr.lower():
                print("  [skip] 远端目录尚不存在，跳过")
                return True
            print(f"  [error] {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  [error] rclone 超时")
        return False
    except OSError as e:
        print(f"  [error] rclone 执行失败: {e}")
        return False


# ---------------------------------------------------------------------------
# Core sync operations
# ---------------------------------------------------------------------------


def sync_dirs(direction: str, *, category: str | None = None, dry_run: bool = False) -> None:
    """Sync directory mappings.

    direction: "push" (local → remote) or "pull" (remote → local)
    """
    remote_base = get_remote()
    ok, fail = 0, 0

    category = resolve_category(category)
    for cat, mappings in SYNC_DIRS.items():
        if category and cat != category:
            continue
        for local_rel, remote_rel in mappings:
            local_path = GADGET_ROOT / local_rel
            remote_path = f"{remote_base}/{remote_rel}"

            if direction == "push":
                if not local_path.is_dir():
                    print(f"  [skip] {local_rel}/ (不存在)")
                    continue
                print(f"  [{cat}] {local_rel}/ → {remote_path}/")
                success = run_rclone(["copy", str(local_path), remote_path], dry_run=dry_run)
            else:
                local_path.mkdir(parents=True, exist_ok=True)
                print(f"  [{cat}] {remote_path}/ → {local_rel}/")
                success = run_rclone(["copy", remote_path, str(local_path)],
                                     dry_run=dry_run, ok_if_missing=True)

            if success:
                ok += 1
            else:
                fail += 1

    print(f"\n目录同步: {ok} 成功, {fail} 失败")


def sync_files(direction: str, *, category: str | None = None, dry_run: bool = False) -> None:
    """Sync individual file mappings using temporary staging directories."""
    remote_base = get_remote()
    ok, fail = 0, 0

    # Group files by their remote parent directory
    groups: dict[str, list[tuple[str, str, str]]] = {}  # remote_dir → [(local_rel, remote_filename, cat)]
    category = resolve_category(category)
    for cat, mappings in SYNC_FILES.items():
        if category and cat != category:
            continue
        for local_rel, remote_rel in mappings:
            remote_dir = Path(remote_rel).parent.as_posix()
            remote_name = Path(remote_rel).name
            groups.setdefault(remote_dir, []).append((local_rel, remote_name, cat))

    for remote_dir, files in groups.items():
        remote_path = f"{remote_base}/{remote_dir}"

        if direction == "push":
            # Collect files into a temp dir, then rclone copy the whole dir
            with tempfile.TemporaryDirectory() as tmpdir:
                has_files = False
                for local_rel, remote_name, cat in files:
                    src = GADGET_ROOT / local_rel
                    if not src.is_file():
                        print(f"  [skip] {local_rel} (不存在)")
                        continue
                    dst = Path(tmpdir) / remote_name
                    shutil.copy2(str(src), str(dst))
                    print(f"  [{cat}] {local_rel} → {remote_path}/{remote_name}")
                    has_files = True

                if has_files:
                    success = run_rclone(["copy", tmpdir, remote_path], dry_run=dry_run)
                    if success:
                        ok += 1
                    else:
                        fail += 1
        else:
            # Pull: download entire remote dir, then distribute files
            with tempfile.TemporaryDirectory() as tmpdir:
                print(f"  [pull] {remote_path}/ → staging")
                success = run_rclone(["copy", remote_path, tmpdir],
                                     dry_run=dry_run, ok_if_missing=True)
                if not success:
                    fail += 1
                    continue

                if not dry_run:
                    for local_rel, remote_name, cat in files:
                        src = Path(tmpdir) / remote_name
                        dst = GADGET_ROOT / local_rel
                        if not src.is_file():
                            continue
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        if local_rel in APPEND_ONLY_FILES:
                            merged, msg = merge_append_only_csv(src, dst)
                            print(f"  [{cat}] → {local_rel}（追加合并）：{msg}")
                            if not merged:
                                fail += 1
                                continue
                        else:
                            shutil.copy2(str(src), str(dst))
                            print(f"  [{cat}] → {local_rel}")
                ok += 1

    if ok or fail:
        print(f"文件同步: {ok} 组成功, {fail} 组失败")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def push_configs(*, dry_run: bool = False) -> None:
    """Push local config files to remote for bootstrap on other devices."""
    remote_base = get_remote()
    ok, fail = 0, 0
    for remote_rel, local_path in BOOTSTRAP_CONFIGS:
        if not local_path.is_file():
            print(f"  [skip] {local_path} (不存在)")
            continue
        remote_path = f"{remote_base}/{remote_rel}"
        print(f"  [config] {local_path} → {remote_path}")
        success = run_rclone(["copyto", str(local_path), remote_path], dry_run=dry_run)
        if success:
            ok += 1
        else:
            fail += 1
    print(f"\n配置备份: {ok} 成功, {fail} 失败")


def push_tokens(*, dry_run: bool = False) -> None:
    """Push tokens/ directory to remote."""
    remote_base = get_remote()
    if not TOKENS_DIR.is_dir():
        print("  [skip] tokens/ (不存在)")
        return
    remote_path = f"{remote_base}/tokens"
    print(f"  [tokens] {TOKENS_DIR}/ → {remote_path}/")
    success = run_rclone(["copy", str(TOKENS_DIR), remote_path], dry_run=dry_run)
    print("  tokens 备份成功" if success else "  [error] tokens 备份失败")


def cmd_push(args: argparse.Namespace) -> None:
    print("=== Push: 本地 → 远端 ===\n")
    sync_dirs("push", category=args.category, dry_run=args.dry_run)
    sync_files("push", category=args.category, dry_run=args.dry_run)
    if args.include_config:
        print("\n--- 配置文件备份 ---\n")
        push_configs(dry_run=args.dry_run)
    if args.include_tokens:
        print("\n--- Tokens 备份 ---\n")
        push_tokens(dry_run=args.dry_run)
    print("\n[done] Push 完成。" if not args.dry_run else "\n[dry-run] 以上为预览，未实际传输。")


def cmd_pull(args: argparse.Namespace) -> None:
    print("=== Pull: 远端 → 本地 ===\n")
    sync_dirs("pull", category=args.category, dry_run=args.dry_run)
    sync_files("pull", category=args.category, dry_run=args.dry_run)
    print("\n[done] Pull 完成。" if not args.dry_run else "\n[dry-run] 以上为预览，未实际传输。")


def cmd_status(args: argparse.Namespace) -> None:
    """Show diff between local and remote using rclone check."""
    remote_base = get_remote()
    print(f"=== Status: 对比本地与 {remote_base} ===\n")

    category = resolve_category(args.category)
    for cat, mappings in SYNC_DIRS.items():
        if category and cat != category:
            continue
        for local_rel, remote_rel in mappings:
            local_path = GADGET_ROOT / local_rel
            remote_path = f"{remote_base}/{remote_rel}"
            if not local_path.is_dir():
                print(f"  [{cat}] {local_rel}/ — 本地不存在")
                continue
            print(f"  [{cat}] {local_rel}/ ↔ {remote_path}/")
            run_rclone(["check", str(local_path), remote_path, "--combined", "-"], dry_run=False)
            print()

    # SYNC_FILES too, or a category whose mappings are all files reports
    # nothing at all — which is what `status --category benchmark` did once its
    # directory list was emptied, even though push and pull both covered it.
    for cat, mappings in SYNC_FILES.items():
        if category and cat != category:
            continue
        for local_rel, remote_rel in mappings:
            local_path = GADGET_ROOT / local_rel
            remote_path = f"{remote_base}/{remote_rel}"
            if not local_path.is_file():
                print(f"  [{cat}] {local_rel} — 本地不存在")
                continue
            size = local_path.stat().st_size
            print(f"  [{cat}] {local_rel} ({size} B) ↔ {remote_path}")


def cmd_bootstrap(args: argparse.Namespace) -> None:
    """One-command setup for a new device: pull configs + data from remote."""
    global _config_cache

    remote = args.remote
    print(f"=== Bootstrap: 一键初始化新设备 ===\n")
    print(f"远端: {remote}\n")

    # Step 1: Write minimal sync section so get_remote() works
    minimal_cfg = {"rclone_remote": remote}
    if not args.dry_run:
        path = save_sync_config(minimal_cfg)
        print(f"[ok] 已写入 {path} (section: sync)")
    else:
        print(f"[dry-run] 将写入 {CONFIG_FILE} (section: sync)")
    _config_cache = None  # invalidate cache

    # Step 2: Verify remote connectivity
    print("\n--- 检查远端连通性 ---\n")
    rclone = find_rclone()
    try:
        result = subprocess.run(
            [rclone, "lsd", remote],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"[error] 无法连接远端 {remote}: {result.stderr.strip()}")
            print("请检查 rclone 配置 (rclone config) 和远端路径。")
            sys.exit(1)
        print(f"[ok] 远端可达\n")
    except subprocess.TimeoutExpired:
        print(f"[error] 连接远端超时")
        sys.exit(1)

    # Step 3: Pull unified config.json (may overwrite the minimal sync section)
    print("--- 拉取配置文件 ---\n")
    cfg_ok, cfg_fail = 0, 0
    for remote_rel, local_path in BOOTSTRAP_CONFIGS:
        remote_path = f"{remote}/{remote_rel}"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"  [config] {remote_path} → {local_path}")
        success = run_rclone(["copyto", remote_path, str(local_path)], dry_run=args.dry_run)
        if success:
            cfg_ok += 1
        else:
            cfg_fail += 1
    print(f"\n配置: {cfg_ok} 成功, {cfg_fail} 失败")

    # Ensure sync.rclone_remote survives a missing/partial remote config
    if not args.dry_run:
        gadget_config.clear_cache()
        _config_cache = None
        sync_cfg = load_config()
        if not sync_cfg.get("rclone_remote"):
            save_sync_config({**sync_cfg, "rclone_remote": remote})

    # Step 4: Pull tokens (opt-in)
    if args.include_tokens:
        print("\n--- 拉取 Tokens ---\n")
        TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        remote_tokens = f"{remote}/tokens"
        print(f"  [tokens] {remote_tokens}/ → {TOKENS_DIR}/")
        run_rclone(["copy", remote_tokens, str(TOKENS_DIR)], dry_run=args.dry_run)

    # Step 5: Pull all data (reuse existing sync functions)
    # Reload config in case remote config had rclone_path or other settings
    _config_cache = None
    print("\n--- 拉取数据目录 ---\n")
    sync_dirs("pull", dry_run=args.dry_run)
    sync_files("pull", dry_run=args.dry_run)

    if args.dry_run:
        print("\n[dry-run] 以上为预览，未实际传输。")
    else:
        print("\n[done] Bootstrap 完成！新设备已就绪。")


def cmd_config(args: argparse.Namespace) -> None:
    if not args.init:
        # Show current config
        cfg = load_config()
        if not cfg:
            print("未找到配置。运行 `python scripts/sync.py config --init` 初始化。")
            return
        print(f"配置文件: {gadget_config.resolve_config_path()}  (section: sync)")
        for k, v in cfg.items():
            print(f"  {k}: {v}")
        return

    # Interactive init
    print("=== 初始化 gadget sync 配置 ===\n")
    print(f"写入: {gadget_config.resolve_config_path()}  (section: sync)\n")
    cfg: dict = {}

    remote = input("rclone 远端基础路径 (默认 gdrive:gadget): ").strip()
    cfg["rclone_remote"] = remote or "gdrive:gadget"

    if not shutil.which("rclone"):
        rclone_path = input("rclone 二进制路径 (如 ~/.local/bin/rclone): ").strip()
        if rclone_path:
            cfg["rclone_path"] = rclone_path

    path = save_sync_config(cfg)
    print(f"\n[ok] 已保存配置到 {path} (section: sync)")
    print(json.dumps(cfg, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="gadget 个人数据 rclone 同步工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # rclone categories go through the push/pull/status subcommands; a bare
    # top-level --category has no meaning on its own.
    parser.add_argument(
        "--category", choices=rclone_category_choices(),
        help="类目需配合 push/pull/status 子命令使用",
    )
    # Separate dest so a subparser's own --dry-run default does not clobber a
    # global `--dry-run push`. The two are OR-ed after parsing (see below).
    parser.add_argument("--dry-run", dest="global_dry_run", action="store_true",
                        help="预览，不实际执行 (可放在子命令前后任意位置)")
    sub = parser.add_subparsers(dest="command")

    # push
    p_push = sub.add_parser("push", help="本地 → 远端")
    p_push.add_argument("--dry-run", action="store_true", help="预览，不实际传输")
    p_push.add_argument("--category", choices=rclone_category_choices(),
                        help="只同步某一类 (test = benchmark 旧名)")
    p_push.add_argument("--include-config", action="store_true", help="同时备份配置文件到远端")
    p_push.add_argument("--include-tokens", action="store_true", help="同时备份 tokens/ 到远端")

    # pull
    p_pull = sub.add_parser("pull", help="远端 → 本地")
    p_pull.add_argument("--dry-run", action="store_true", help="预览，不实际传输")
    p_pull.add_argument("--category", choices=rclone_category_choices(),
                        help="只同步某一类 (test = benchmark 旧名)")

    # status
    p_status = sub.add_parser("status", help="显示本地与远端差异")
    p_status.add_argument("--category", choices=rclone_category_choices(),
                         help="只检查某一类 (test = benchmark 旧名)")

    # bootstrap
    p_bootstrap = sub.add_parser("bootstrap", help="一键初始化新设备 (clone 后运行)")
    p_bootstrap.add_argument("--remote", default="gdrive:gadget",
                             help="rclone 远端基础路径 (默认 gdrive:gadget)")
    p_bootstrap.add_argument("--include-tokens", action="store_true",
                             help="同时拉取 tokens/ 目录 (含 API 密钥)")
    p_bootstrap.add_argument("--dry-run", action="store_true", help="预览，不实际传输")

    # config
    p_config = sub.add_parser("config", help="查看或初始化配置")
    p_config.add_argument("--init", action="store_true", help="交互式初始化配置")

    args = parser.parse_args()

    # Honor --dry-run regardless of position (before or after the subcommand).
    args.dry_run = getattr(args, "dry_run", False) or args.global_dry_run

    if not args.command:
        if args.category:
            print(f"[error] --category {args.category} 需配合子命令使用，例如 "
                  f"`python scripts/sync.py push --category {args.category}`。")
            sys.exit(1)
        parser.print_help()
        sys.exit(1)

    cmds = {
        "push": cmd_push, "pull": cmd_pull, "status": cmd_status,
        "bootstrap": cmd_bootstrap, "config": cmd_config,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
