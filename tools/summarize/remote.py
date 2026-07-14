"""Rclone-based remote sync utilities for uploading and downloading log files."""

import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

from .config import _load_config


# 通过 ssh 反向隧道传 Google Drive 延迟高、易抖动 → 多重试、限制单次卡死时间。
# rclone copy 本身幂等（按大小/时间跳过已传文件），崩溃后重跑即「断点续传」。
_RCLONE_FLAGS = [
    "--retries", "5", "--retries-sleep", "5s",
    "--low-level-retries", "10",
    "--contimeout", "30s", "--timeout", "120s",
    "--transfers", "4", "--checkers", "8",
    "--drive-chunk-size", "8M",
]


def _find_rclone() -> Optional[str]:
    """查找 rclone 可执行文件：config rclone_path > PATH。"""
    cfg = _load_config()
    custom = cfg.get("rclone_path")
    if custom:
        p = Path(custom).expanduser()
        if p.is_file():
            return str(p)
        print(f"[warn] rclone_path 指定的路径不存在: {custom}")
    return shutil.which("rclone")


def _rclone_upload(*local_paths: Path, subdirectory: str = "") -> None:
    """若 config 有 rclone_remote，将文件上传到远端目录。

    subdirectory: 上传到 <remote>/<subdirectory>/，如 "logs" 或 "reports"。
    """
    cfg = _load_config()
    remote = cfg.get("rclone_remote")
    if not remote:
        return

    rclone_bin = _find_rclone()
    if not rclone_bin:
        print("[warn] rclone 未找到，跳过上传（可在 config 中设置 rclone_path）")
        return

    dest = f"{remote}/{subdirectory}" if subdirectory else remote

    for local_path in local_paths:
        if not local_path.exists():
            continue
        print(f"[info] rclone copy {local_path.name} → {dest}/")
        try:
            result = subprocess.run(
                [rclone_bin, "copy", str(local_path), dest, *_RCLONE_FLAGS],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                print(f"[warn] rclone 上传失败 ({local_path.name}): {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print(f"[warn] rclone 上传超时 ({local_path.name})，跳过")
            return
        except OSError as e:
            print(f"[warn] rclone 执行失败: {e}")
            return

    print(f"[ok] rclone 上传完成 ({len(local_paths)} 个文件)")


def _rclone_upload_dir(local_dir: Path, subdirectory: str = "") -> None:
    """批量上传整个目录：一次 rclone copy 传完，按大小/时间跳过未变文件。

    比逐文件上传快得多（一次连接、一次 token 刷新、并发传输），且幂等——
    崩溃或超时后重跑只补缺失的文件，相当于断点续传。
    """
    cfg = _load_config()
    remote = cfg.get("rclone_remote")
    if not remote or not local_dir.is_dir():
        return

    rclone_bin = _find_rclone()
    if not rclone_bin:
        print("[warn] rclone 未找到，跳过上传（可在 config 中设置 rclone_path）")
        return

    dest = f"{remote}/{subdirectory}" if subdirectory else remote
    print(f"[info] rclone copy {local_dir}/ → {dest}/ (批量)")
    try:
        result = subprocess.run(
            [rclone_bin, "copy", str(local_dir), dest, *_RCLONE_FLAGS],
            capture_output=True, text=True, timeout=1800,
        )
        if result.returncode != 0:
            print(f"[warn] rclone 批量上传失败: {result.stderr.strip()}")
        else:
            print(f"[ok] rclone 批量上传完成 → {dest}/")
    except subprocess.TimeoutExpired:
        print("[warn] rclone 批量上传超时（重跑即续传未完成的文件）")
    except OSError as e:
        print(f"[warn] rclone 执行失败: {e}")


def _rclone_download_reports(local_reports_dir: Path) -> list[Path]:
    """从远端 reports/ 目录下载所有报告文件到本地。

    返回本地 reports 目录中下载到的 .json 文件路径列表。
    """
    cfg = _load_config()
    remote = cfg.get("rclone_remote")
    if not remote:
        return []

    rclone_bin = _find_rclone()
    if not rclone_bin:
        print("[warn] rclone 未找到，跳过报告同步")
        return []

    src = f"{remote}/reports/"
    local_reports_dir.mkdir(parents=True, exist_ok=True)

    cmd = [rclone_bin, "copy", src, str(local_reports_dir), "--include", "*.json", "--include", "*.md"]
    print(f"[info] rclone copy {src} → {local_reports_dir}/ (reports)")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "directory not found" in stderr.lower() or "not found" in stderr.lower():
                print("[info] 远端 reports/ 目录尚未创建，跳过下载")
                return []
            print(f"[warn] rclone 报告下载失败: {stderr}")
            return []
    except subprocess.TimeoutExpired:
        print("[warn] rclone 报告下载超时，跳过")
        return []
    except OSError as e:
        print(f"[warn] rclone 执行失败: {e}")
        return []

    matched = sorted(local_reports_dir.glob("*.json"))
    if matched:
        print(f"[ok] rclone 报告同步完成，找到 {len(matched)} 个报告文件")
    else:
        print("[info] rclone 报告同步完成，但未找到报告文件")

    return matched


def _rclone_download_logs(target_date: Optional[date], local_logs_dir: Path) -> list[Path]:
    """从远端 logs/ 目录下载 log 文件到本地。

    target_date: 若指定，只下载 "{date}_*.json"；否则下载全部。
    返回本地 logs 目录中匹配的 .json 文件路径列表。
    """
    cfg = _load_config()
    remote = cfg.get("rclone_remote")
    if not remote:
        print("[warn] 未配置 rclone_remote，跳过同步（可运行 config --init 配置）")
        return []

    rclone_bin = _find_rclone()
    if not rclone_bin:
        print("[warn] rclone 未找到，跳过同步（可在 config 中设置 rclone_path）")
        return []

    src = f"{remote}/logs/"
    local_logs_dir.mkdir(parents=True, exist_ok=True)

    cmd = [rclone_bin, "copy", src, str(local_logs_dir)]
    if target_date:
        pattern = f"{target_date.isoformat()}_*.json"
        cmd += ["--include", pattern,
                "--include", "usage_*.json",
                "--include", "ccusage_*.json",
                "--include", "codex_usage_*.json"]
        print(f"[info] rclone copy {src} → {local_logs_dir}/ "
              f"(filter: {pattern} + usage/ccusage/codex_usage)")
    else:
        cmd += ["--include", "*.json"]
        print(f"[info] rclone copy {src} → {local_logs_dir}/ (all .json)")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            # 远端目录不存在时非致命
            if "directory not found" in stderr.lower() or "not found" in stderr.lower():
                print(f"[info] 远端 logs/ 目录尚未创建，跳过下载")
                return []
            print(f"[warn] rclone 下载失败: {stderr}")
            return []
    except subprocess.TimeoutExpired:
        print("[warn] rclone 下载超时，跳过")
        return []
    except OSError as e:
        print(f"[warn] rclone 执行失败: {e}")
        return []

    # 收集本地匹配的文件
    if target_date:
        matched = sorted(local_logs_dir.glob(f"{target_date.isoformat()}_*.json"))
    else:
        matched = sorted(local_logs_dir.glob("*.json"))

    if matched:
        print(f"[ok] rclone 同步完成，找到 {len(matched)} 个 log 文件")
    else:
        print(f"[info] rclone 同步完成，但未找到匹配的 log 文件")

    return matched
