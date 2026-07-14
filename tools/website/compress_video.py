#!/usr/bin/env python3
"""
compress_video.py
──────────────────────────────────────────────────
使用 HandBrakeCLI 将视频按 Fast 720p30 预设压缩，并启用 Web Optimized，
压缩完成后计算并输出：
  ‣ 原始文件大小
  ‣ 压缩后文件大小
  ‣ 压缩倍率 (orig/new)
  ‣ 节省百分比 (1 - new/orig)

调用示例：
    python3 compress_video.py /path/to/video.mp4
"""

import sys
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def fmt_bytes(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.2f}{unit}"
        n /= 1024


def compress_video(in_path: Path) -> None:
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".mp4")
    os.close(tmp_fd)

    try:
        cmd = [
            "HandBrakeCLI",
            "-i", str(in_path),
            "-o", tmp_name,
            "-Z", "Fast 720p30",
            "--optimize",
            "--audio", "none"
        ]

        print(f"🗜️ 开始压缩：{in_path.name}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("✅ 压缩完成，准备计算比例…")

        orig_size = in_path.stat().st_size
        new_size = Path(tmp_name).stat().st_size

        ratio = orig_size / new_size if new_size else float('inf')
        saving_pct = (1 - new_size / orig_size) * 100 if orig_size else 0

        print(f"   • 原始大小   : {fmt_bytes(orig_size)}")
        print(f"   • 压缩后大小 : {fmt_bytes(new_size)}")
        print(f"   • 压缩倍率   : {ratio:.2f}×")
        print(f"   • 体积节省   : {saving_pct:.1f}%")

        if new_size < orig_size:
            shutil.move(tmp_name, in_path)
            print(f"📦 已用压缩后文件覆盖原文件：{in_path.name}")
        else:
            # Re-encode came out larger (already-compressed / already ≤720p) —
            # keep the original instead of inflating it. tmp removed in finally.
            print(f"↩️ 压缩后更大，保留原文件：{in_path.name}")
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def main():
    if len(sys.argv) != 2:
        print("用法: python3 compress_video.py <input_video>", file=sys.stderr)
        sys.exit(1)

    in_path = Path(sys.argv[1]).resolve()
    if not in_path.is_file():
        print(f"❌ 输入文件不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    compress_video(in_path)


if __name__ == "__main__":
    main()
