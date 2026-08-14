# update.ps1  ——  增量图片 / 视频压缩 + Preflight 检查 + Hugo 发布 (Windows PowerShell)
# 实际逻辑在 publish.py；本文件只负责切到脚本目录并调用它。
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python (Join-Path $PSScriptRoot "publish.py") @args
exit $LASTEXITCODE
