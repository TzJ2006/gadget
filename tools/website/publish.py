#!/usr/bin/env python3
"""Incremental media compression + preflight + Hugo publish.

Single orchestrator for the eight-step website pipeline. update.sh and
update.ps1 are thin wrappers around this file.

Steps:
  1. Pre-translate content/ via translate_site_batch.py (non-fatal)
  2. Rewrite handwritten Markdown (site URL, jpg→png, video shortcode)
  3. Compress images newer than .last_build (pngquant + compress_image.py)
  4. Compress videos newer than .last_build (compress_video.py only)
  5. Preflight — abort only on exit 1; exit 2 (warnings) continues
  6. Clean public/ (keep .git) and run hugo
  7. Commit and push public/ if there are changes
  8. Touch .last_build
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent

SRC_DIR = SITE_ROOT / "content"
IMAGE_DIR = SITE_ROOT / "static" / "images"
VIDEO_DIR = SITE_ROOT / "static" / "videos"
PUBLIC_DIR = SITE_ROOT / "public"
TIMESTAMP_FILE = SITE_ROOT / ".last_build"
TRANSLATION_STATE_FILE = SITE_ROOT / ".translation_state.json"
CONFIG_FILE = SITE_ROOT / "config.yml"

COMPRESS_IMG_SCRIPT = SITE_ROOT / "compress_image.py"
COMPRESS_VIDEO_SCRIPT = SITE_ROOT / "compress_video.py"
PREFLIGHT_SCRIPT = SITE_ROOT / "preflight_check.py"
TRANSLATE_SCRIPT = SITE_ROOT / "translate_site_batch.py"

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}

# Pipeline-managed trees — Step 2 rewrite is handwritten content only.
GENERATED_CONTENT_DIRS = (
    "bugJournal/daily",
    "bugJournal/weekly",
    "bugJournal/monthly",
    "research",
)
GENERATED_CONTENT_FILES = ("benchmark.md", "benchmark.zh.md")

_STATIC_RE = re.compile(r"\.\./\.\./static")
# Word-boundary so `.jpeg` does not become `.pngpeg` (bash s/\.jpg/ bug).
_JPG_EXT_RE = re.compile(r"\.jpe?g\b", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)]+)(\))")
_SRC_RE = re.compile(r"""(src=["'])([^"']+)(["'])""", re.IGNORECASE)
_VIDEO_SHORTCODE = (
    "{{< video\n"
    '    src="/\\1"\n'
    '    type="video/mp4"\n'
    '    preload="auto"\n'
    '    width="360"\n'
    ">}}"
)

_TEN_YEARS = 10 * 365.25 * 24 * 3600


class _Timer:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.last = self.t0

    def step(self, name: str) -> None:
        now = time.monotonic()
        print(
            f" -- [time] {name}: {now - self.last:.0f}s "
            f"(累计 {now - self.t0:.0f}s)",
            flush=True,
        )
        self.last = now

    def total(self) -> float:
        return time.monotonic() - self.t0


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(SITE_ROOT).as_posix()
    except ValueError:
        return str(path)


def get_site_base_url(config_path: Path) -> str:
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        print(f"ERROR: Could not read '{config_path}': {e}", file=sys.stderr)
        sys.exit(1)
    for line in lines:
        m = re.match(r"^\s*baseURL\s*:\s*(.*)$", line)
        if not m:
            continue
        url = m.group(1).strip().strip("\"'").rstrip("/")
        if url:
            return url
    print(f"ERROR: Could not find baseURL in '{config_path}'.", file=sys.stderr)
    sys.exit(1)


def ensure_timestamp(path: Path) -> float:
    if not path.exists():
        print(
            f"WARNING: 未检测到时间戳文件 '{path.name}'，已初始化为十年前。",
            flush=True,
        )
        path.touch()
        past = time.time() - _TEN_YEARS
        os.utime(path, (past, past))
    return path.stat().st_mtime


def _is_generated(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(SRC_DIR.resolve()).as_posix()
    except ValueError:
        return False
    if path.name in GENERATED_CONTENT_FILES or rel in GENERATED_CONTENT_FILES:
        return True
    return any(rel == d or rel.startswith(d + "/") for d in GENERATED_CONTENT_DIRS)


def _newer_files(root: Path, exts: set[str], since: float) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.name.startswith("._"):
            continue
        if p.suffix.lower() in exts and p.stat().st_mtime > since:
            out.append(p)
    return sorted(out)


def rewrite_markdown(text: str, site_url: str) -> str:
    text = _STATIC_RE.sub(site_url, text)

    def _png_in_url(m: re.Match[str]) -> str:
        return m.group(1) + _JPG_EXT_RE.sub(".png", m.group(2)) + m.group(3)

    # Only rewrite extensions inside Markdown links/images and src="..."
    # attributes — not every `.jpg` substring in the file.
    text = _MD_LINK_RE.sub(_png_in_url, text)
    text = _SRC_RE.sub(_png_in_url, text)

    video_re = re.compile(r"\(" + re.escape(site_url) + r"/([^)]+\.mp4)\)")
    return video_re.sub(_VIDEO_SHORTCODE, text)


def invoke_translation_phase(label: str, args: list[str]) -> None:
    print(f"\n> {label}", flush=True)
    rc = subprocess.run(
        [sys.executable, str(TRANSLATE_SCRIPT), *args],
        cwd=SITE_ROOT,
    ).returncode
    if rc != 0:
        print(" -- 翻译阶段失败，继续后续构建流程", flush=True)


def rewrite_modified_markdown(since: float, site_url: str) -> None:
    print(
        "\n> Step 2/8：检查 content/ 下哪些手写 .md 文件自上次构建以来被修改：",
        flush=True,
    )
    modified: list[Path] = []
    if SRC_DIR.is_dir():
        for path in SRC_DIR.rglob("*.md"):
            if not path.is_file() or path.name.startswith("._"):
                continue
            if path.stat().st_mtime <= since:
                continue
            if _is_generated(path):
                continue
            modified.append(path)
        modified.sort()

    if not modified:
        print("  -- 暂无 .md 文件自上次构建以来发生改动，跳过此步。", flush=True)
        return

    print("  以下 Markdown 源文件被检测到已修改：", flush=True)
    for path in modified:
        print(f"    {_display(path)}", flush=True)
    print(flush=True)
    print(
        f"  > 正在把 '../../static' -> '{site_url}'，"
        f"将图片扩展改为 .png，并转换本地视频链接 ...",
        flush=True,
    )
    for path in modified:
        text = path.read_text(encoding="utf-8")
        path.write_text(rewrite_markdown(text, site_url), encoding="utf-8")
        print(f"    OK 已处理：{_display(path)}", flush=True)


def _compress_one(script: Path, path: Path) -> int:
    return subprocess.run(
        [sys.executable, str(script), str(path)],
        cwd=SITE_ROOT,
    ).returncode


def _compress_parallel(script: Path, paths: list[Path], kind: str) -> None:
    with ThreadPoolExecutor(max_workers=max(1, len(paths))) as pool:
        futs = []
        for path in paths:
            print(f"   ... {kind}压缩中：{_display(path)}", flush=True)
            futs.append(pool.submit(_compress_one, script, path))
        for fut in as_completed(futs):
            fut.result()
    print(f" -> {kind}压缩完成", flush=True)


def compress_images(since: float) -> None:
    print("\n─────────────────────────────────────────────────", flush=True)
    print("> Step 3/8：压缩更新的图片：", flush=True)
    modified = _newer_files(IMAGE_DIR, IMAGE_EXTS, since)
    if not modified:
        print(" -- 无图片需压缩", flush=True)
        return
    if shutil.which("pngquant") is None:
        print(" -- 跳过图片压缩（未安装 pngquant）", flush=True)
        return
    _compress_parallel(COMPRESS_IMG_SCRIPT, modified, "图片")


def compress_videos(since: float) -> None:
    print("\n─────────────────────────────────────────────────", flush=True)
    print("> Step 4/8：压缩更新的视频：", flush=True)
    modified = _newer_files(VIDEO_DIR, VIDEO_EXTS, since)
    if not modified:
        print(" -- 无视频需压缩", flush=True)
        return
    if not COMPRESS_VIDEO_SCRIPT.is_file():
        print(" -- 跳过视频压缩（未找到 compress_video.py）", flush=True)
        return
    if shutil.which("HandBrakeCLI") is None:
        print(" -- 跳过视频压缩（未安装 HandBrakeCLI）", flush=True)
        return
    _compress_parallel(COMPRESS_VIDEO_SCRIPT, modified, "视频")


def run_preflight() -> int:
    print("\n─────────────────────────────────────────────────", flush=True)
    print(
        "> Step 5/8：Preflight 检查（图片/链接/frontmatter/双语/语言）：",
        flush=True,
    )
    return subprocess.run(
        [sys.executable, str(PREFLIGHT_SCRIPT)],
        cwd=SITE_ROOT,
    ).returncode


def clean_public() -> None:
    print("\n─────────────────────────────────────────────────", flush=True)
    print("> Step 6/8：清理并重新构建 public/：", flush=True)
    if not PUBLIC_DIR.exists():
        PUBLIC_DIR.mkdir(parents=True)
        return
    # Windows: indexer/AV can hold handles briefly ("directory not empty").
    last_err: OSError | None = None
    for attempt in range(1, 4):
        try:
            for child in list(PUBLIC_DIR.iterdir()):
                if child.name == ".git":
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            return
        except OSError as e:
            last_err = e
            if attempt == 3:
                raise
            time.sleep(2)
    if last_err:
        raise last_err


def run_hugo() -> None:
    try:
        subprocess.run(["hugo"], cwd=SITE_ROOT, check=True)
    except FileNotFoundError:
        print("ERROR: hugo not found on PATH", file=sys.stderr)
        sys.exit(1)


def commit_and_push() -> None:
    print("\n─────────────────────────────────────────────────", flush=True)
    print("> Step 7/8：提交并推送远端仓库：", flush=True)
    if not PUBLIC_DIR.is_dir():
        print(" -- public/ 不存在，跳过推送", flush=True)
        return
    subprocess.run(["git", "add", "-A"], cwd=PUBLIC_DIR, check=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=PUBLIC_DIR,
    )
    if diff.returncode == 0:
        print(" -- 无变更需提交，跳过推送", flush=True)
        return
    message = f"update website: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    subprocess.run(["git", "commit", "-m", message], cwd=PUBLIC_DIR, check=True)
    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=PUBLIC_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if upstream.returncode == 0:
        subprocess.run(["git", "push"], cwd=PUBLIC_DIR, check=True)
        return
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=PUBLIC_DIR,
        text=True,
        encoding="utf-8",
    ).strip()
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=PUBLIC_DIR,
        check=True,
    )


def main() -> int:
    os.chdir(SITE_ROOT)
    timer = _Timer()
    site_url = get_site_base_url(CONFIG_FILE)
    since = ensure_timestamp(TIMESTAMP_FILE)

    invoke_translation_phase(
        "Step 1/8：预翻译 content/ 下缺失或变更的双语 Markdown：",
        ["--root", "content", "--state-file", TRANSLATION_STATE_FILE.name],
    )
    timer.step("Step 1 内容预翻译")

    rewrite_modified_markdown(since, site_url)
    compress_images(since)
    compress_videos(since)

    preflight_rc = run_preflight()
    if preflight_rc == 1:
        print("Preflight 检查发现阻断性错误，终止构建", flush=True)
        return 1
    timer.step("Steps 2-5 重写/压缩/preflight")

    clean_public()
    run_hugo()
    timer.step("Step 6 Hugo 构建")

    commit_and_push()
    timer.step("Step 7 提交推送")

    print("\n─────────────────────────────────────────────────", flush=True)
    print("> Step 8/8：更新时间戳：", flush=True)
    TIMESTAMP_FILE.touch()
    print(f"Done!（总耗时 {timer.total():.0f}s）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
