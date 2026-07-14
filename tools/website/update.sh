#!/usr/bin/env bash
# update.sh  ——  增量图片 / 视频压缩 + Preflight 检查 + Hugo 发布 (macOS/Linux)
# ---------------------------------------------------------------

set -euo pipefail

# ─── 计时（Phase-A observability：每步耗时） ─────────────────────────
_T0=$SECONDS
_TLAST=$SECONDS
step_time() {
    echo " -- [time] $1: $((SECONDS-_TLAST))s (累计 $((SECONDS-_T0))s)"
    _TLAST=$SECONDS
}

# ─── 配置区 ───────────────────────────────────────────────────────
SRC_DIR="content"
IMAGE_DIR="static/images"
VIDEO_DIR="static/videos"
PUBLIC_DIR="public"
TIMESTAMP_FILE=".last_build"
TRANSLATION_STATE_FILE=".translation_state.json"
CONFIG_FILE="config.yml"

PATTERN='\.\.\/\.\.\/static'

COMPRESS_IMG_SCRIPT="compress_image.py"
COMPRESS_VIDEO_SCRIPT="compress_video.py"
PREFLIGHT_SCRIPT="preflight_check.py"
TRANSLATE_SCRIPT="translate_site_batch.py"
COMMIT_MESSAGE="update website: $(date '+%Y-%m-%d %H:%M:%S')"
# 流水线自动生成的内容目录（daily/weekly/monthly/research 由部署管线写入并
# 自带双语对 + gadget 标记）：Step 2 的 sed 重写只针对手写内容，跳过这些。
GENERATED_CONTENT_DIRS=(
    "$SRC_DIR/bugJournal/daily"
    "$SRC_DIR/bugJournal/weekly"
    "$SRC_DIR/bugJournal/monthly"
    "$SRC_DIR/research"
)
# ────────────────────────────────────────────────────────────────

get_site_base_url() {
    local config_path="$1"
    local line
    line=$(grep -m1 '^\s*baseURL\s*:' "$config_path" || true)
    if [[ -z "$line" ]]; then
        echo "ERROR: Could not find baseURL in '$config_path'." >&2
        exit 1
    fi
    local url
    url=$(echo "$line" | sed 's/^\s*baseURL\s*:\s*//' | sed "s/[\"' ]//g" | sed 's:/$::')
    echo "$url"
}

REPLACEMENT=$(get_site_base_url "$CONFIG_FILE")
SITE_URL_ESCAPED=$(printf '%s' "$REPLACEMENT" | sed 's/[.[\/*^$]/\\&/g')

invoke_translation_phase() {
    local label="$1"
    shift
    echo ""
    echo "> $label"
    if ! python "$TRANSLATE_SCRIPT" "$@"; then
        echo " -- 翻译阶段失败，继续后续构建流程"
    fi
}

# 若无时间戳文件，则创建（设为十年前）
if [[ ! -f "$TIMESTAMP_FILE" ]]; then
    echo "WARNING: 未检测到时间戳文件 '$TIMESTAMP_FILE'，已初始化为十年前。"
    touch -d "10 years ago" "$TIMESTAMP_FILE"
fi

# ─── Step 1/8：内容预翻译（唯一内容根 content/，含生成 + 手写） ─────────
invoke_translation_phase "Step 1/8：预翻译 content/ 下缺失或变更的双语 Markdown：" \
    --root "$SRC_DIR" \
    --state-file "$TRANSLATION_STATE_FILE"
step_time "Step 1 内容预翻译"

# ─── Step 2/8：Markdown 重写（仅手写内容；生成目录被 prune） ────────────
echo ""
echo "> Step 2/8：检查 content/ 下哪些手写 .md 文件自上次构建以来被修改："

prune_args=()
for gen_dir in "${GENERATED_CONTENT_DIRS[@]}"; do
    prune_args+=(-path "$gen_dir" -prune -o)
done
mapfile -t modified_md < <(find "$SRC_DIR" "${prune_args[@]}" -name '*.md' \
    ! -name 'benchmark.md' ! -name 'benchmark.zh.md' \
    -newer "$TIMESTAMP_FILE" -print 2>/dev/null)

if [[ ${#modified_md[@]} -gt 0 ]]; then
    echo "  以下 Markdown 源文件被检测到已修改："
    for f in "${modified_md[@]}"; do
        echo "    $f"
    done
    echo ""
    echo "  > 正在把 '../../static' -> '$REPLACEMENT'，将图片扩展改为 .png，并转换本地视频链接 ..."

    for mdfile in "${modified_md[@]}"; do
        # 替换 ../../static -> site URL
        sed -i "s|$PATTERN|$REPLACEMENT|g" "$mdfile"
        # 替换 .jpg/.jpeg -> .png
        sed -i 's/\.jpg/.png/g; s/\.jpeg/.png/g' "$mdfile"
        # 转换本地视频链接到 Hugo video 短代码
        sed -i "s|(${SITE_URL_ESCAPED}/\([^)]*\.mp4\))|{{< video\n    src=\"/\1\"\n    type=\"video/mp4\"\n    preload=\"auto\"\n    width=\"360\"\n>}}|g" "$mdfile"
        echo "    OK 已处理：$mdfile"
    done
else
    echo "  -- 暂无 .md 文件自上次构建以来发生改动，跳过此步。"
fi

# ─── Step 3/8：压缩更新的图片 ────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "> Step 3/8：压缩更新的图片："

mapfile -t modified_img < <(find "$IMAGE_DIR" \( -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' \) -newer "$TIMESTAMP_FILE" 2>/dev/null)

if [[ ${#modified_img[@]} -gt 0 ]]; then
    if ! command -v pngquant &>/dev/null; then
        echo " -- 跳过图片压缩（未安装 pngquant）"
    else
        for img in "${modified_img[@]}"; do
            echo "   ... 图片压缩中：$img"
            python "$COMPRESS_IMG_SCRIPT" "$img" &
        done
        wait
        echo " -> 图片压缩完成"
    fi
else
    echo " -- 无图片需压缩"
fi

# ─── Step 4/8：压缩更新的视频 ────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "> Step 4/8：压缩更新的视频："

mapfile -t modified_vid < <(find "$VIDEO_DIR" \( -name '*.mp4' -o -name '*.mov' -o -name '*.mkv' -o -name '*.webm' \) -newer "$TIMESTAMP_FILE" 2>/dev/null)

if [[ ${#modified_vid[@]} -gt 0 ]]; then
    if [[ ! -f "$COMPRESS_VIDEO_SCRIPT" ]] && ! command -v HandBrakeCLI &>/dev/null; then
        echo " -- 跳过视频压缩（未安装 HandBrakeCLI 且无压缩脚本）"
    else
        for vid in "${modified_vid[@]}"; do
            echo "   ... 视频压缩中：$vid"
            if [[ -f "$COMPRESS_VIDEO_SCRIPT" ]]; then
                python "$COMPRESS_VIDEO_SCRIPT" "$vid" &
            else
                tmp="${vid%.*}.hb.mp4"
                HandBrakeCLI -i "$vid" -o "$tmp" -Z "Fast 1080p30" --optimize &
            fi
        done
        wait
        echo " -> 视频压缩完成"
    fi
else
    echo " -- 无视频需压缩"
fi

# ─── Step 5/8：Preflight 检查 ─────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "> Step 5/8：Preflight 检查（图片/链接/frontmatter/双语/语言）："

if ! python "$PREFLIGHT_SCRIPT"; then
    echo "Preflight 检查发现阻断性错误，终止构建"
    exit 1
fi
step_time "Steps 2-5 重写/压缩/preflight"

# ─── Step 6/8：清理并重新构建 public/ ─────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "> Step 6/8：清理并重新构建 public/："

if [[ -d "$PUBLIC_DIR" ]]; then
    find "$PUBLIC_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
else
    mkdir -p "$PUBLIC_DIR"
fi
hugo
step_time "Step 6 Hugo 构建"

# ─── Step 7/8：提交并推送远端仓库 ───────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "> Step 7/8：提交并推送远端仓库："

cd "$PUBLIC_DIR"
git add -A
if git diff --cached --quiet; then
    echo " -- 无变更需提交，跳过推送"
else
    git commit -m "$COMMIT_MESSAGE"
    current_branch=$(git rev-parse --abbrev-ref HEAD)
    if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' &>/dev/null; then
        git push
    else
        git push -u origin "$current_branch"
    fi
    git gc --aggressive
fi
cd ..
step_time "Step 7 提交推送"

# ─── Step 8/8：更新时间戳 ─────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "> Step 8/8：更新时间戳："
touch "$TIMESTAMP_FILE"
echo "Done!（总耗时 $((SECONDS-_T0))s）"
