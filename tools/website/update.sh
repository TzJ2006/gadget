#!/usr/bin/env bash
# update.sh  ——  增量图片 / 视频压缩 + Preflight 检查 + Hugo 发布 (macOS/Linux)
# 实际逻辑在 publish.py；本文件只负责切到脚本目录并调用它。
set -euo pipefail
cd "$(dirname "$0")"
exec python publish.py "$@"
