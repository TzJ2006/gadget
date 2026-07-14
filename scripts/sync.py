#!/usr/bin/env python3
"""集中式 rclone 同步脚本 — 将个人数据文件与 Google Drive 同步。

用法:
    python scripts/sync.py push              # 本地 → 远端
    python scripts/sync.py pull              # 远端 → 本地
    python scripts/sync.py status            # 显示差异
    python scripts/sync.py config --init     # 初始化配置
    python scripts/sync.py bootstrap --remote gdrive:gadget  # 新设备一键初始化
    python scripts/sync.py --category dag    # 生成并部署 DAG 站 (非 GDrive 同步)

选项:
    --dry-run                        # 预览，不实际传输
    --category <name>                # 只同步某一类 (summarize/website/research/test/backups/dag)
    --include-config                 # push 时同时备份配置文件
    --include-tokens                 # push/bootstrap 时包含 tokens/ 目录

特殊类目 dag:
    dag 类目语义不同于 rclone 同步——它「生成 + 部署 DAG 站」，而非 GDrive 同步。
    `python scripts/sync.py --category dag` 会:
      1. 运行 `npx tsx ../ai-companion/scripts/build-dag-site.ts stage`
         (生成 overview + 各项目详情页 → 加密 → 落 tools/website/static/dag/)，
         密码经环境变量 STATICRYPT_PASSWORD 传入；
      2. 触发 website 发布 (tools/website/update.sh)。
    `--dry-run` 时仅打印将运行的命令与目标路径，不实际执行。
"""

import argparse
import json
import os
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


# DAG site — generated + deployed (not a GDrive-synced category).
# ai-companion is now a separate repo checked out as a sibling (../ai-companion);
# override with AI_COMPANION_ROOT if it lives elsewhere.
# ponytail: sibling-dir assumption; AI_COMPANION_ROOT env is the escape hatch.
_AI_COMPANION_ROOT = Path(
    os.environ.get("AI_COMPANION_ROOT", GADGET_ROOT.parent / "ai-companion")
).expanduser()
DAG_BUILD_SCRIPT = _AI_COMPANION_ROOT / "scripts" / "build-dag-site.ts"
DAG_STAGE_DIR = GADGET_ROOT / "tools" / "website" / "static" / "dag"
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
        ("tools/website/static/images/weekly", "website/static/images/weekly"),
        ("tools/website/static/images/monthly", "website/static/images/monthly"),
        ("tools/website/static/benchmark-report", "website/static/benchmark-report"),
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
    "test": [
        ("outputs/data/benchmark", "test/data"),
    ],
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
    "test": [
        ("outputs/data/benchmark/results.csv", "test/data/benchmark_results.csv"),
    ],
}

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
                        if src.is_file():
                            dst.parent.mkdir(parents=True, exist_ok=True)
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

    for cat, mappings in SYNC_DIRS.items():
        if args.category and cat != args.category:
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
# DAG site — generate + deploy (not a GDrive sync category)
# ---------------------------------------------------------------------------


def sync_dag(*, dry_run: bool = False) -> bool:
    """Generate the encrypted DAG site and deploy it via the website pipeline.

    Unlike the rclone categories, this does not touch Google Drive. It:
      1. Runs `npx tsx ../ai-companion/scripts/build-dag-site.ts stage` — assembles
         the overview + per-project detail pages, encrypts each with StatiCrypt
         (password from STATICRYPT_PASSWORD), and stages them into
         website/static/dag/ for Hugo to publish at /dag/.
      2. Runs website/update.sh — Hugo build + push to tzj2006.github.io.

    Returns True on success. With dry_run=True it only prints what would run and
    always returns True (no generation/deploy is performed).
    """
    stage_cmd = ["npx", "tsx", str(DAG_BUILD_SCRIPT), "stage"]
    deploy_cmd = ["bash", str(WEBSITE_UPDATE_SCRIPT)]

    if dry_run:
        print("=== DAG: 生成 + 部署 (dry-run) ===\n")
        print("将执行 (步骤 1/2 — 生成 + 加密 DAG 站):")
        print(f"  $ STATICRYPT_PASSWORD=*** {' '.join(stage_cmd)}")
        print(f"  → 加密产物落地: {DAG_STAGE_DIR}/ (overview index.html + 各项目 <name>.html)")
        print("\n将执行 (步骤 2/2 — 发布 website):")
        print(f"  $ {' '.join(deploy_cmd)}  (cwd={WEBSITE_DIR})")
        print(f"  → Hugo 构建并推送 (发布站点的 /dag/ 路径)")
        print("\n[dry-run] 以上为预览，未实际生成或部署。")
        return True

    print("=== DAG: 生成 + 部署 ===\n")

    # Step 0:密码必须来自环境变量，绝不硬编码。
    password = os.environ.get("STATICRYPT_PASSWORD")
    if not password:
        print("[error] 未设置环境变量 STATICRYPT_PASSWORD。")
        print("  DAG 站每个页面都会用该密码做 StatiCrypt 加密，请先设置后再运行，例如:")
        print("    STATICRYPT_PASSWORD='<your-password>' python scripts/sync.py --category dag")
        return False

    if not DAG_BUILD_SCRIPT.is_file():
        print(f"[error] 找不到 DAG 构建脚本: {DAG_BUILD_SCRIPT}")
        return False

    # Step 1: 生成 + 加密 → website/static/dag/
    print(f"--- 生成 DAG 站 (→ {DAG_STAGE_DIR}/) ---\n")
    print(f"  $ {' '.join(stage_cmd)}")
    try:
        result = subprocess.run(stage_cmd, cwd=str(GADGET_ROOT), text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print("  [error] DAG 站生成超时")
        return False
    except OSError as e:
        print(f"  [error] 无法运行 npx/tsx (是否已安装 Node.js?): {e}")
        return False
    if result.returncode != 0:
        print(f"  [error] DAG 站生成失败 (退出码 {result.returncode})")
        return False

    # Step 2: 发布 website
    if not WEBSITE_UPDATE_SCRIPT.is_file():
        print(f"[error] 找不到 website 发布脚本: {WEBSITE_UPDATE_SCRIPT}")
        return False
    print(f"\n--- 发布 website (→ /dag/) ---\n")
    print(f"  $ {' '.join(deploy_cmd)}  (cwd={WEBSITE_DIR})")
    try:
        result = subprocess.run(deploy_cmd, cwd=str(WEBSITE_DIR), text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print("  [error] website 发布超时")
        return False
    except OSError as e:
        print(f"  [error] 无法运行 website/update.sh: {e}")
        return False
    if result.returncode != 0:
        print(f"  [error] website 发布失败 (退出码 {result.returncode})")
        return False

    print("\n[done] DAG 站已生成并部署。")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="gadget 个人数据 rclone 同步工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Top-level --category supports the special `dag` target (generate + deploy
    # the DAG site, no subcommand needed). rclone categories still go through
    # push/pull/status subcommands as before.
    parser.add_argument(
        "--category", choices=list(SYNC_DIRS.keys()) + ["dag"],
        help="顶层用法仅支持 dag (生成+部署 DAG 站); 其余类目请配合 push/pull/status 子命令",
    )
    # Separate dest so a subparser's own --dry-run default does not clobber a
    # global `--dry-run push`. The two are OR-ed after parsing (see below).
    parser.add_argument("--dry-run", dest="global_dry_run", action="store_true",
                        help="预览，不实际执行 (可放在子命令前后任意位置)")
    sub = parser.add_subparsers(dest="command")

    # push
    p_push = sub.add_parser("push", help="本地 → 远端")
    p_push.add_argument("--dry-run", action="store_true", help="预览，不实际传输")
    p_push.add_argument("--category", choices=list(SYNC_DIRS.keys()), help="只同步某一类")
    p_push.add_argument("--include-config", action="store_true", help="同时备份配置文件到远端")
    p_push.add_argument("--include-tokens", action="store_true", help="同时备份 tokens/ 到远端")

    # pull
    p_pull = sub.add_parser("pull", help="远端 → 本地")
    p_pull.add_argument("--dry-run", action="store_true", help="预览，不实际传输")
    p_pull.add_argument("--category", choices=list(SYNC_DIRS.keys()), help="只同步某一类")

    # status
    p_status = sub.add_parser("status", help="显示本地与远端差异")
    p_status.add_argument("--category", choices=list(SYNC_DIRS.keys()), help="只检查某一类")

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

    # Special top-level usage: `python scripts/sync.py --category dag` — generate +
    # deploy the DAG site (no subcommand). Handle before subcommand dispatch.
    if not args.command:
        if args.category == "dag":
            ok = sync_dag(dry_run=args.dry_run)
            sys.exit(0 if ok else 1)
        if args.category:
            print(f"[error] 顶层 --category {args.category} 仅 dag 受支持；"
                  f"其余类目请用 push/pull/status 子命令，例如 "
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
