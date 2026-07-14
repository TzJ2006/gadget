# update.ps1  ——  增量图片 / 视频压缩 + Preflight 检查 + Hugo 发布 (Windows PowerShell)
# ---------------------------------------------------------------

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot  # relative paths below assume the script's own dir

# ─── 配置区 ───────────────────────────────────────────────────────
$SRC_DIR        = "content"
$IMAGE_DIR      = "static/images"
$VIDEO_DIR      = "static/videos"
$PUBLIC_DIR     = "public"
$TIMESTAMP_FILE = ".last_build"
$TRANSLATION_STATE_FILE = ".translation_state.json"
$CONFIG_FILE    = "config.yml"

$PATTERN        = '\.\.\/\.\.\/static'

$COMPRESS_IMG_SCRIPT   = "compress_image.py"
$COMPRESS_VIDEO_SCRIPT = "compress_video.py"
$PREFLIGHT_SCRIPT      = "preflight_check.py"
$TRANSLATE_SCRIPT      = "translate_site_batch.py"
$COMMIT_MESSAGE        = "update website: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
# 流水线自动生成的内容目录（daily/weekly/monthly/research 由部署管线写入并
# 自带双语对 + gadget 标记）：Step 2 的重写只针对手写内容，跳过这些。
$GENERATED_CONTENT_DIRS = @(
    "$SRC_DIR/bugJournal/daily",
    "$SRC_DIR/bugJournal/weekly",
    "$SRC_DIR/bugJournal/monthly",
    "$SRC_DIR/research"
)
# ────────────────────────────────────────────────────────────────

function Get-SiteBaseUrl {
    param([string]$ConfigPath)

    $match = Select-String -Path $ConfigPath -Pattern '^\s*baseURL\s*:' | Select-Object -First 1
    if (-not $match) {
        throw "Could not find baseURL in '$ConfigPath'."
    }

    $baseUrl = ($match.Line -replace '^\s*baseURL\s*:\s*', '').Trim()
    $baseUrl = $baseUrl.Trim('"')
    $baseUrl = $baseUrl.Trim("'")
    return $baseUrl.TrimEnd('/')
}

$REPLACEMENT = Get-SiteBaseUrl -ConfigPath $CONFIG_FILE
$SITE_URL_REGEX = [regex]::Escape($REPLACEMENT)

function Invoke-TranslationPhase {
    param(
        [string]$Label,
        [string[]]$Arguments
    )

    Write-Host "`n> $Label"
    & python $TRANSLATE_SCRIPT @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host " -- 翻译阶段失败，继续后续构建流程"
    }
}

# 若无时间戳文件，则创建（设为十年前）
if (-not (Test-Path $TIMESTAMP_FILE)) {
    Write-Host "WARNING: 未检测到时间戳文件 '$TIMESTAMP_FILE'，已初始化为十年前。"
    New-Item -ItemType File -Path $TIMESTAMP_FILE -Force | Out-Null
    (Get-Item $TIMESTAMP_FILE).LastWriteTime = (Get-Date).AddYears(-10)
}

$lastBuildTime = (Get-Item $TIMESTAMP_FILE).LastWriteTime

# ─── Step 1/8：内容预翻译（唯一内容根 content/，含生成 + 手写） ─────────
Invoke-TranslationPhase -Label "Step 1/8：预翻译 content/ 下缺失或变更的双语 Markdown：" -Arguments @(
    "--root", $SRC_DIR,
    "--state-file", $TRANSLATION_STATE_FILE
)

# ─── Step 2/8：Markdown 重写（仅手写内容；生成目录被排除） ──────────────
Write-Host "`n> Step 2/8：检查 content/ 下哪些手写 .md 文件自上次构建以来被修改："

$generatedFullPaths = $GENERATED_CONTENT_DIRS | ForEach-Object {
    (Join-Path $PSScriptRoot ($_ -replace '/', '\')) + '\'
}
$modifiedMd = @()
if (Test-Path $SRC_DIR) {
    $modifiedMd = Get-ChildItem -Path $SRC_DIR -Recurse -Filter "*.md" |
        Where-Object { $_.LastWriteTime -gt $lastBuildTime } |
        Where-Object { $_.Name -ne 'benchmark.md' -and $_.Name -ne 'benchmark.zh.md' } |
        Where-Object {
            $full = $_.FullName
            -not ($generatedFullPaths | Where-Object { $full.StartsWith($_) })
        }
}

if ($modifiedMd.Count -gt 0) {
    Write-Host "  以下 Markdown 源文件被检测到已修改："
    $modifiedMd | ForEach-Object { Write-Host "    $_" }
    Write-Host ""
    Write-Host "  > 正在把 '../../static' -> '$REPLACEMENT'，将图片扩展改为 .png，并转换本地视频链接 ..."

    foreach ($mdfile in $modifiedMd) {
        $text = Get-Content -Path $mdfile.FullName -Raw -Encoding UTF8
        # 替换 ../../static -> site URL
        $text = $text -replace $PATTERN, $REPLACEMENT
        # 替换 .jpg/.jpeg -> .png
        $text = $text -replace '\.(jpg|jpeg)', '.png'
        # 转换本地视频链接到 Hugo video 短代码
        $text = $text -replace "\($SITE_URL_REGEX/([^)]+\.mp4)\)",
            ('{{< video' + "`n" + '    src="/$1"' + "`n" + '    type="video/mp4"' + "`n" + '    preload="auto"' + "`n" + '    width="360"' + "`n" + '>}}')
        # 写回文件（无 BOM 的 UTF-8）
        [System.IO.File]::WriteAllText($mdfile.FullName, $text, [System.Text.UTF8Encoding]::new($false))
        Write-Host "    OK 已处理：$($mdfile.FullName)"
    }
} else {
    Write-Host "  -- 暂无 .md 文件自上次构建以来发生改动，跳过此步。"
}

# ─── Step 3/8：压缩更新的图片 ────────────────────────────────────────
Write-Host "`n─────────────────────────────────────────────────"
Write-Host "> Step 3/8：压缩更新的图片："

$modifiedImg = @()
if (Test-Path $IMAGE_DIR) {
    $modifiedImg = Get-ChildItem -Path $IMAGE_DIR -Recurse -Include "*.jpg","*.jpeg","*.png" |
        Where-Object { $_.LastWriteTime -gt $lastBuildTime }
}

if ($modifiedImg.Count -gt 0) {
    $hasPngquant = Get-Command pngquant -ErrorAction SilentlyContinue
    if (-not $hasPngquant) {
        Write-Host " -- 跳过图片压缩（未安装 pngquant）"
    } else {
        $jobs = @()
        foreach ($img in $modifiedImg) {
            Write-Host "   ... 图片压缩中：$($img.FullName)"
            $jobs += Start-Job -ScriptBlock {
                param($script, $path)
                python $script $path
            } -ArgumentList $COMPRESS_IMG_SCRIPT, $img.FullName
        }
        $jobs | Wait-Job | Out-Null
        $jobs | ForEach-Object {
            $output = Receive-Job $_
            if ($output) { Write-Host $output }
            Remove-Job $_
        }
        Write-Host " -> 图片压缩完成"
    }
} else {
    Write-Host " -- 无图片需压缩"
}

# ─── Step 4/8：压缩更新的视频 ────────────────────────────────────────
Write-Host "`n─────────────────────────────────────────────────"
Write-Host "> Step 4/8：压缩更新的视频："

$modifiedVid = @()
if (Test-Path $VIDEO_DIR) {
    $modifiedVid = Get-ChildItem -Path $VIDEO_DIR -Recurse -Include "*.mp4","*.mov","*.mkv","*.webm" |
        Where-Object { $_.LastWriteTime -gt $lastBuildTime }
}

if ($modifiedVid.Count -gt 0) {
    $hasHandBrake = Get-Command HandBrakeCLI -ErrorAction SilentlyContinue
    if ((-not (Test-Path $COMPRESS_VIDEO_SCRIPT)) -and (-not $hasHandBrake)) {
        Write-Host " -- 跳过视频压缩（未安装 HandBrakeCLI 且无压缩脚本）"
    } else {
        $jobs = @()
        foreach ($vid in $modifiedVid) {
            Write-Host "   ... 视频压缩中：$($vid.FullName)"
            if (Test-Path $COMPRESS_VIDEO_SCRIPT) {
                $jobs += Start-Job -ScriptBlock {
                    param($script, $path)
                    python $script $path
                } -ArgumentList $COMPRESS_VIDEO_SCRIPT, $vid.FullName
            } else {
                $jobs += Start-Job -ScriptBlock {
                    param($path)
                    $tmp = [System.IO.Path]::ChangeExtension($path, ".hb.mp4")
                    HandBrakeCLI -i $path -o $tmp -Z "Fast 1080p30" --optimize
                } -ArgumentList $vid.FullName
            }
        }
        $jobs | Wait-Job | Out-Null
        $jobs | ForEach-Object {
            $output = Receive-Job $_
            if ($output) { Write-Host $output }
            Remove-Job $_
        }
        Write-Host " -> 视频压缩完成"
    }
} else {
    Write-Host " -- 无视频需压缩"
}

# ─── Step 5/8：Preflight 检查 ─────────────────────────────────────────
Write-Host "`n─────────────────────────────────────────────────"
Write-Host "> Step 5/8：Preflight 检查（图片/链接/frontmatter/双语/语言）："

python $PREFLIGHT_SCRIPT
if ($LASTEXITCODE -eq 1) {
    throw "Preflight 检查发现阻断性错误，终止构建"
}

# ─── Step 6/8：清理并重新构建 public/ ─────────────────────────
Write-Host "`n─────────────────────────────────────────────────"
Write-Host "> Step 6/8：清理并重新构建 public/："

if (Test-Path $PUBLIC_DIR) {
    # ponytail: Windows 递归删除非原子（索引器/杀软短暂占用句柄会报“目录非空”），重试 3 次即可
    for ($i = 1; $i -le 3; $i++) {
        try {
            Get-ChildItem -Path $PUBLIC_DIR -Force |
                Where-Object { $_.Name -ne ".git" } |
                Remove-Item -Recurse -Force -ErrorAction Stop
            break
        } catch {
            if ($i -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }
} else {
    New-Item -ItemType Directory -Path $PUBLIC_DIR -Force | Out-Null
}
hugo

# ─── Step 7/8：提交并推送远端仓库 ───────────────────────────────────
Write-Host "`n─────────────────────────────────────────────────"
Write-Host "> Step 7/8：提交并推送远端仓库："

Push-Location $PUBLIC_DIR
try {
    git add -A
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host " -- 无变更需提交，跳过推送"
    } else {
        git commit -m $COMMIT_MESSAGE
        $currentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
        git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            git push
        } else {
            git push -u origin $currentBranch
        }
        git gc --aggressive
    }
} finally {
    Pop-Location
}

# ─── Step 8/8：更新时间戳 ─────────────────────────────────────────
Write-Host "`n─────────────────────────────────────────────────"
Write-Host "> Step 8/8：更新时间戳："
(Get-Item $TIMESTAMP_FILE).LastWriteTime = Get-Date
Write-Host "Done!"
