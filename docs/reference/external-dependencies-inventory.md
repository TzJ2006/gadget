# Gadget Project — 外部文件清单

> **项目根目录**: `/home/thomas/Desktop/algorithms/gadget/`  
> **最后更新**: 2026-07-02

本文档列出所有**项目外部依赖文件/目录/服务**（不在项目文件夹内，但被项目使用）。

---

## 1. 配置目录

| 路径 | 用途 | 引用位置 | 必需/可选 |
|------|------|----------|----------|
| `~/.config/gadget/sync.json` | Rclone 同步配置（远程基础路径、rclone 二进制路径） | `sync.py` | 必需（用于同步操作）|
| `~/.config/summarize/config.json` | Summarize 工具配置（设备名、输出目录、rclone remote、API backend、ccusage 安装偏好）— 回退路径：解析顺序为 `SUMMARIZE_CONFIG` 环境变量 > 仓库内 `summarize/config.json` > 此文件（由 `scripts/onboard.py` 写入） | `summarize/config.py`, `summarize/daily.py` | 可选（CLI 标志/环境变量优先） |
| `~/.config/research_scout/config.json` | Research Scout 配置（论文发现主配置） | `research/scout/config.py` | 可选（CLI 标志/环境变量优先） |
| `~/.config/research/config.json` | Researcher Profiler 配置（Scout 缺失键的回退配置） | `research/scout/config.py` | 可选（仅作回退） |

**初始化方式**:
```bash
python summarize/daily_summary.py config --init   # 写入仓库内 summarize/config.json（~/.config 为回退，由 scripts/onboard.py 写入）
python research/research_scout.py config --init
python scripts/sync.py config --init
```

---

## 2. AI 助手对话日志目录

| 路径 | 用途 | 引用位置 | 必需/可选 |
|------|------|----------|----------|
| `~/.claude/projects/` | Claude Code 对话日志（JSONL 格式，每个项目一个目录） | `summarize/parsers.py` | 必需（用于 Claude Code 汇总） |
| `~/.codex/sessions/YYYY/MM/DD/` | Codex 对话日志（按日期组织的 JSONL） | `summarize/parsers.py` | 可选（备用 AI 助手源） |
| ChatGPT export JSON | ChatGPT conversations.json 导出 | `summarize/parsers.py`（通过 `--chatgpt-export` 标志） | 可选（用户提供的路径） |

**说明**:
- Claude Code 日志路径可能因 OS 不同而变化：
  - **macOS**: `~/Library/Application Support/Claude Code/projects/`
  - **Linux**: `~/.claude/projects/`
  - **Windows**: `%APPDATA%\Claude Code\projects\`
- `summarize/config.py` 会自动检测这些路径

**日志格式示例**:
```json
{"timestamp": "2026-04-14T01:52:00.000Z", "source": "claude_code", "conversation": [...]}
```

---

## 3. 外部二进制工具

### 3.1 必需工具

| 二进制 | 用途 | 引用位置 | 解析方式 |
|--------|------|----------|----------|
| `rclone` | Google Drive 同步个人数据 | `sync.py`, `summarize/remote.py` | `shutil.which("rclone")` 或 config 中的 `rclone_path` |
| `hugo` | 静态站点生成和部署 | `website/update.sh`, `website/update.ps1`, `common/hugo.py` | `shutil.which("hugo")` |
| `ollama` | 本地 LLM 服务 — 默认聊天后端（Gemma4-26B）与默认翻译后端（翻译复用同一个聊天 tag） | `common/llm.py`, `common/engine.py` | `OLLAMA_BASE_URL`（默认 `http://127.0.0.1:11434`） |
| `torch` + `transformers` | 本地翻译推理引擎回退（`tencent/Hy-MT2-1.8B`；默认后端为 Ollama） | `common/engine.py`, `website/translate_content.py`, `website/translate_site_batch.py` | 通过 `pip install -e ".[translation]"` 安装；模型首次运行自动下载 |
| `bash` | Shell 脚本执行 | `common/hugo.py`, 所有 `*.sh` 脚本 | Linux/macOS 系统自带；Windows 需 Git Bash |

### 3.2 可选工具（功能扩展）

| 二进制 | 用途 | 引用位置 | 缺失时行为 |
|--------|------|----------|-----------|
| `pngquant` | 图片压缩（JPEG→PNG 转换） | `website/compress_image.py`, `website/update.sh` | Windows `update.ps1` 跳过压缩；Linux/macOS 报错 |
| `HandBrakeCLI` | 视频压缩（720p30，无音频） | `website/compress_video.py`, `website/update.sh` | Windows `update.ps1` 跳过压缩；Linux/macOS 报错 |
| `ccusage` (Node.js, **>=20**) | 统一多来源 token 用量跟踪（Claude Code / Codex / Gemini 等，逐源命名空间命令） | `summarize/usage.py` | 缺失或 <20 时静默 `npm install -g ccusage@latest`，失败回退 `npx --yes ccusage@latest`；再失败则跳过 token 统计 |
| `claude` CLI | Claude Code CLI（用于 `--api claude_cli` 模式） | `summarize/summarizer.py` | 可使用 `--api anthropic` 或 `--api openai` 替代 |

**安装方式**:
```bash
# Linux (Debian/Ubuntu)
apt-get install hugo pngquant handbrake-cli

# macOS (Homebrew)
brew install hugo pngquant handbrake

# Windows (Chocolatey)
choco install hugo pngquant handbrake-cli

# rclone (跨平台)
curl https://rclone.org/install.sh | sudo bash

# 翻译依赖（通过 pip，见 Python 包依赖节）
pip install torch>=2.0 transformers>=4.40
# Linux 可选: pip install vllm>=0.8

# Node.js 工具
npm install -g ccusage@latest   # >=20，统一覆盖 Claude Code / Codex / Gemini 等所有来源
```

---

## 4. 环境变量

| 变量 | 用途 | 引用位置 | 必需/可选 |
|------|------|----------|----------|
| `ANTHROPIC_API_KEY` | Anthropic Claude API 认证 | `common/llm.py`, 所有 `--api anthropic` 命令 | 使用 `--api anthropic` 时必需 |
| `OPENAI_API_KEY` | OpenAI API 认证 | `common/llm.py`, 所有 `--api openai` 命令 | 使用 `--api openai` 时必需 |
| `SUMMARIZE_LOGS_DIR` | 覆盖默认日志输出路径 | `summarize/config.py` | 可选（覆盖 config.json） |
| `SUMMARIZE_REPORTS_DIR` | 覆盖默认报告输出路径 | `summarize/config.py` | 可选（覆盖 config.json） |
| `GADGET_TRANSLATION_MODEL` | 覆盖翻译模型 | `common/engine.py` | 可选（默认 `tencent/Hy-MT2-1.8B`） |
| `GADGET_TRANSLATION_BACKEND` | 强制指定推理后端（`ollama` / `vllm` / `transformers` / `llamacpp`） | `common/engine.py` | 可选（默认自动选择，Ollama 可用时优先） |
| `GADGET_TRANSLATION_BATCH_SIZE` | 翻译批次大小 | `common/engine.py` | 可选（默认自动） |

**配置示例** (`.bashrc` / `.zshrc`):
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-proj-..."
export SUMMARIZE_LOGS_DIR="/media/external/gadget_logs"
export GADGET_TRANSLATION_MODEL="tencent/Hy-MT2-1.8B"
```

---

## 5. Python 包依赖（外部安装）

### 5.1 核心依赖（安装 `pip install -e .`）

| 包 | 用途 | 必需于 | 版本要求 |
|----|------|--------|---------|
| （无） | `dependencies = []` — `pip install -e .` 仅安装 `common/` 与各工具包本身（MCP 已移除） | Root (pyproject.toml) | — |

### 5.2 可选依赖组

#### summarize 组（`pip install -e ".[summarize]"`）

| 包 | 用途 | 必需/可选 |
|----|------|----------|
| `anthropic>=0.18.0` | Anthropic API SDK | 可选（仅当使用 `--api anthropic`） |
| `openai>=1.0.0` | OpenAI API SDK | 可选（仅当使用 `--api openai`） |

#### research 组（`pip install -e ".[research]"`）

| 包 | 用途 | 必需/可选 |
|----|------|----------|
| `arxiv>=2.0.0` | arXiv API 客户端 | 必需（研究工具） |
| `openreview-py>=1.40.0` | OpenReview API 客户端 | 可选（insight 审稿人分析） |
| `anthropic>=0.18.0` | Anthropic API SDK | 可选（仅当使用 `--api anthropic`） |
| `openai>=1.0.0` | OpenAI API SDK | 可选（仅当使用 `--api openai`） |
| `PyMuPDF>=1.23.0` | PDF 文本提取 | 可选（详细 profiler 模式） |

#### benchmark 组（`pip install -e ".[benchmark]"`）

| 包 | 用途 | 必需/可选 |
|----|------|----------|
| `torch>=2.0.0` | PyTorch（CPU/GPU benchmark） | 必需（benchmark） |
| `numpy>=1.24.0` | 数值计算 | 必需（benchmark） |
| `pandas>=2.0.0` | 数据处理 | 必需（benchmark） |
| `plotly>=5.18.0` | 交互式可视化 | 必需（HTML 报告） |
| `tqdm>=4.65.0` | 进度条 | 必需（benchmark） |
| `threadpoolctl>=3.1.0` | BLAS 线程控制 | 可选 |
| `pyopencl>=2023.1` | OpenCL 支持 | 可选（GPU compute benchmark） |

#### translation 组（`pip install -e ".[translation]"`）

| 包 | 用途 | 必需/可选 |
|----|------|----------|
| `torch>=2.0.0` | PyTorch 推理运行时 | 必需（翻译） |
| `transformers>=4.40.0` | HuggingFace 模型加载 | 必需（翻译） |
| `vllm>=0.8.0` | 高性能批量推理（仅 Linux） | 可选（Linux 加速） |

#### website 组（`pip install -e ".[website]"`）

| 包 | 用途 | 必需/可选 |
|----|------|----------|
| `Pillow>=10.0.0` | 图片处理（JPEG→PNG） | 必需（图片压缩） |
| `torch>=2.0.0` | 翻译推理（通过 `gadget[translation]`） | 必需（翻译） |
| `transformers>=4.40.0` | 模型加载（通过 `gadget[translation]`） | 必需（翻译） |

#### all 组（`pip install -e ".[all]"`）

安装所有可选依赖（summarize + research + benchmark + website）。

---

## 6. Google Drive Rclone 远程路径

| 远程路径 | 用途 | 同步方式 | 必需/可选 |
|----------|------|----------|----------|
| `gdrive:gadget/` (base) | Google Drive 根目录 | `sync.py` | 必需（同步操作） |
| `gdrive:gadget/summarize/logs` | AI 对话日志备份 | `sync.py`, `summarize/remote.py` | 必需（多设备合并） |
| `gdrive:gadget/summarize/reports` | 生成的摘要报告 | `sync.py`, `summarize/remote.py` | 必需（多设备合并） |
| `gdrive:gadget/website/*` | 网站内容备份 | `sync.py` | 必需（多设备同步） |
| `gdrive:gadget/research/*` | 研究数据备份 | `sync.py` | 必需（多设备同步） |
| `gdrive:gadget/test/data` | Benchmark 结果 | `sync.py` | 必需（多硬件累积） |
| `gdrive:gadget/tokens/` | API 密钥备份 | `sync.py`（with `--include-tokens`） | 可选（安全敏感，opt-in） |
| `gdrive:gadget/config/*` | 配置文件备份（用于 bootstrap） | `sync.py`（with `--include-config`） | 可选（新设备 bootstrap） |

**rclone remote 配置**:
```bash
rclone config
# 选择 Google Drive，授权后 remote name 设为 "gdrive"
```

**sync.json 配置示例**:
```json
{
  "rclone_remote": "gdrive:gadget",
  "rclone_path": null
}
```

（同步类别与本地/远端路径映射硬编码在 `scripts/sync.py` 的 `SYNC_DIRS` / `SYNC_FILES` 中，不在 sync.json 里。）

---

## 7. 外部 Git 仓库

| 路径 | 仓库 | 用途 | 必需/可选 |
|------|------|------|----------|
| `website/public/` | `tzj2006/tzj2006.github.io`（独立仓库） | GitHub Pages 部署目标 | 必需（网站部署）；**不是 submodule**，独立 git repo |
| `website/themes/` | Hugo theme 目录 | Hugo 主题（可能是 PaperMod） | 必需（Hugo 构建）；在主 repo 中 gitignored |

**说明**:
- `website/public/` 是一个**独立的 Git 仓库**，指向 GitHub Pages 部署仓库
- 部署流程: `hugo` → `cd public && git add . && git commit && git push`
- `website/themes/` 中的主题通常通过 `git clone` 或 Hugo 包管理器安装

---

## 8. 翻译模型（本地推理）

| 模型名 | 用途 | 安装方式 | 存储位置 |
|--------|------|----------|----------|
| `tencent/Hy-MT2-1.8B` | 中英双向翻译（用于 Hugo 内容双语化） | 首次运行自动从 HuggingFace 下载 | `~/.cache/huggingface/hub/`（Ollama 后端存于 `~/.ollama`） |

**推理后端**:
- **默认**: `OllamaEngine`（直接复用本地聊天模型的 tag `gemma4:26b`，与聊天共享同一个 Ollama runner，不额外占显存）
- **Windows 回退**: `TransformersEngine`（`AutoModelForCausalLM` + `apply_chat_template`，左填充批量生成）
- **Linux 回退**: `VLLMEngine`（`vllm.LLM.generate`，高性能离线批量推理）
- **低内存回退**: `LlamaCppEngine`（GGUF，无需 PyTorch）
- 通过 `GADGET_TRANSLATION_BACKEND` 环境变量可强制指定后端（`ollama` / `vllm` / `transformers` / `llamacpp`）

**用途**:
- `website/translate_content.py` — 单文件翻译
- `website/translate_site_batch.py` — 批量增量翻译
- `common/translation.py` — Markdown 翻译核心逻辑（collect-then-batch 管线）
- `common/engine.py` — 推理引擎抽象层（TranslationEngine ABC + 工厂函数）
- `summarize/formatter.py` — 日报/月报双语输出

---

## 9. 硬编码绝对路径

**无发现。** 所有路径均通过以下方式动态解析：
- `GADGET_ROOT`（项目根目录，通过 `common/paths.py` 定义）
- 用户主目录（通过 `Path.home()` / `Path.expanduser()`）
- 配置文件中的相对路径

**路径解析策略**:
```python
# common/paths.py
GADGET_ROOT = Path(__file__).parent.parent  # 项目根目录
OUTPUTS_DIR = GADGET_ROOT / "outputs"        # 输出目录
CONFIG_HOME = Path.home() / ".config"        # 用户配置目录
```

---

## 10. 关键外部依赖总结

### 必需（核心功能）

| 依赖 | 用途 | 缺失影响 |
|------|------|----------|
| `~/.claude/projects/` | Claude Code 对话日志源 | 无法汇总 Claude Code 对话 |
| Ollama（默认）或 `torch` + `transformers`（回退）+ `tencent/Hy-MT2-1.8B` | 本地翻译推理 | 无法生成双语内容 |
| `hugo` 二进制 | 静态站点构建 | 无法构建/部署网站 |
| `rclone` + `gdrive:` remote | 多设备数据同步 | 无法在多设备间同步数据 |

### 可选（常用扩展）

| 依赖 | 用途 | 缺失影响 |
|------|------|----------|
| `pngquant` | 图片压缩 | 跳过图片压缩步骤 |
| `HandBrakeCLI` | 视频压缩 | 跳过视频压缩步骤 |
| `ccusage` | Token 跟踪 | 跳过 token 统计 |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | 云 LLM API | 可使用 `--api claude_cli` 或本地 Ollama 替代 |

---

## 11. 新设备 Bootstrap 流程

```bash
# ============ 阶段 1: 安装系统工具 ============
# Linux (Debian/Ubuntu)
sudo apt-get update
sudo apt-get install git python3 python3-pip hugo pngquant handbrake-cli

# macOS (Homebrew)
brew install git python3 hugo pngquant handbrake

# Windows (Chocolatey 管理员)
choco install git python3 hugo pngquant handbrake-cli

# ============ 阶段 2: 安装 rclone + 配置 Google Drive ============
curl https://rclone.org/install.sh | sudo bash
rclone config
# 选择 Google Drive，授权后 remote name 设为 "gdrive"
# 测试: rclone lsd gdrive:gadget

# ============ 阶段 3: 翻译依赖（通过 pip 安装） ============
# torch + transformers 会在阶段 4 的 pip install -e ".[all]" 中一并安装
# 模型 tencent/Hy-MT2-1.8B 首次运行时自动从 HuggingFace 下载
# Linux 可选安装 vLLM 以获得更快的批量推理: pip install vllm>=0.8

# ============ 阶段 4: 克隆项目 + 安装依赖 ============
git clone <repo-url> ~/Desktop/algorithms/gadget
cd ~/Desktop/algorithms/gadget
pip install -e ".[all]"

# ============ 阶段 5: Bootstrap 数据（可选）============
# 一键同步所有配置和数据（配置文件自动拉取；tokens 需 --include-tokens 显式开启）
python scripts/sync.py bootstrap --remote gdrive:gadget --include-tokens

# 或手动初始化配置
python summarize/daily_summary.py config --init
python research/research_scout.py config --init
python scripts/sync.py config --init

# ============ 阶段 6: 配置 API 密钥（可选）============
# 如果使用云 LLM API
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc
echo 'export OPENAI_API_KEY="sk-proj-..."' >> ~/.bashrc
source ~/.bashrc

# ============ 阶段 7: 安装 Node.js 工具（可选）============
npm install -g ccusage@latest   # >=20，统一覆盖 Claude Code / Codex / Gemini 等所有来源

# ============ 阶段 8: 验证安装 ============
python -c "from common import paths; print(paths.GADGET_ROOT)"
python -c "from common.engine import create_engine; print('Translation engine OK')"
hugo version
rclone version
pngquant --version
HandBrakeCLI --version

# ============ 完成 ============
echo "Bootstrap 完成！现在可以运行:"
echo "  python summarize/daily_summary.py export"
echo "  python research/research_scout.py report --project my-project"
echo "  python -m benchmark.cli --report --deploy"
echo "  cd website && bash update.sh"
```

---

## 12. 迁移清单（多设备部署）

### 场景 1: 新设备首次部署

**步骤**:
1. 安装系统工具（见 Bootstrap 流程阶段 1-3）
2. 克隆项目 + 安装依赖（阶段 4）
3. 运行 `python scripts/sync.py bootstrap --remote gdrive:gadget --include-tokens`（配置文件自动拉取）
4. 验证配置: `cat ~/.config/summarize/config.json`（回退路径；若存在仓库内 `summarize/config.json` 则以其优先）

**自动恢复的内容**:
- `~/.config/gadget/sync.json`
- `~/.config/summarize/config.json`（回退路径；仓库内 `summarize/config.json` 优先）
- `~/.config/research_scout/config.json`
- `tokens/` 目录（API 密钥，如果使用 `--include-tokens`）

**需要手动配置**:
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 环境变量（如果不使用 `--include-tokens`）
- GitHub Pages 部署仓库 `website/public/`（需要 `git clone`）

### 场景 2: 仅同步数据（已有配置）

```bash
# 拉取最新对话日志 + 报告
python scripts/sync.py pull --category summarize

# 推送本地新生成的报告
python scripts/sync.py push --category summarize

# 双向同步所有类别
python scripts/sync.py push --sync-all
python scripts/sync.py pull --sync-all
```

### 场景 3: 迁移到新 Google Drive 账号

```bash
# 1. 重新配置 rclone remote
rclone config
# 选择新的 Google Drive 账号

# 2. 更新 sync.json（交互式输入新的 rclone 远端，或直接编辑 ~/.config/gadget/sync.json 的 rclone_remote）
python scripts/sync.py config --init

# 3. 首次全量推送
python scripts/sync.py push --category summarize
python scripts/sync.py push --category research
python scripts/sync.py push --category test
python scripts/sync.py push --category website
```

---

## 13. 故障排查

### 问题 1: 翻译引擎加载失败 / CUDA OOM

**症状**: `common/engine.py` 报错 `CUDA out of memory` 或模型加载失败

**解决方案**:
```bash
# 检查 torch 和 transformers 安装
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
python -c "import transformers; print(transformers.__version__)"

# 如果 CUDA OOM，减小批次大小
export GADGET_TRANSLATION_BATCH_SIZE=2

# 强制使用 transformers 后端（如果 vLLM 有问题）
export GADGET_TRANSLATION_BACKEND=transformers

# 覆盖模型
export GADGET_TRANSLATION_MODEL="tencent/Hy-MT2-1.8B"
```

### 问题 2: `rclone` 认证过期

**症状**: `sync.py` 报错 `Failed to list remote directory: 401 Unauthorized`

**解决方案**:
```bash
# 重新认证
rclone config reconnect gdrive:

# 测试连接
rclone lsd gdrive:gadget
```

### 问题 3: `hugo` 找不到主题

**症状**: `hugo` 报错 `Error: Unable to locate theme`

**解决方案**:
```bash
# 安装 PaperMod 主题
cd website
git clone https://github.com/adityatelange/hugo-PaperMod themes/PaperMod --depth=1

# 或使用 Hugo module
hugo mod get -u github.com/adityatelange/hugo-PaperMod
```

### 问题 4: `ccusage` 无法统计 token

**症状**: `summarize/usage.py` 跳过 token 统计

**解决方案**:
```bash
# 安装 ccusage（>=20，统一多来源）
npm install -g ccusage@latest

# 验证安装
npx ccusage --version

# 手动测试
npx ccusage parse ~/.claude/projects/<project>/session_<id>.jsonl
```

### 问题 5: 图片/视频压缩失败

**症状**: `website/update.sh` 跳过压缩步骤

**解决方案**:
```bash
# 检查 pngquant 安装
pngquant --version

# 检查 HandBrakeCLI 安装
HandBrakeCLI --version

# 如果缺失，安装：
# Linux
sudo apt-get install pngquant handbrake-cli

# macOS
brew install pngquant handbrake

# Windows
choco install pngquant handbrake-cli
```

---

## 14. 参考文档

- **项目主文档**: `README.md`
- **CLAUDE.md**: 项目全局 Claude Code 指南
- **Summarize 工具**: `summarize/README.md`, `summarize/CLAUDE.md`
- **Research 工具**: `research/README.md`, `research/CLAUDE.md`
- **Benchmark 工具**: `benchmark/README.md`, `benchmark/CLAUDE.md`
- **Website 工具**: `website/README.md`, `website/CLAUDE.md`
- **Sync 工具**: `sync.py` docstring

---

## 附录: 完整依赖树

```
gadget/
├── 系统工具
│   ├── [必需] bash (shell 脚本)
│   ├── [必需] python3 (运行时)
│   ├── [必需] hugo (网站构建)
│   ├── [必需] ollama (默认聊天/翻译后端)
│   ├── [可选] torch + transformers (本地翻译推理回退)
│   ├── [必需] rclone (数据同步)
│   ├── [可选] pngquant (图片压缩)
│   ├── [可选] HandBrakeCLI (视频压缩)
│   └── [可选] ccusage (token 跟踪)
├── Python 包
│   ├── [核心] 无（dependencies = []）
│   ├── [summarize] anthropic, openai
│   ├── [research] arxiv, openreview-py, anthropic, openai, PyMuPDF
│   ├── [benchmark] torch, numpy, pandas, plotly, tqdm, threadpoolctl, pyopencl
│   ├── [translation] torch, transformers, vllm (可选)
│   └── [website] Pillow, gadget[translation]
├── 配置文件
│   ├── ~/.config/gadget/sync.json
│   ├── ~/.config/summarize/config.json（回退；仓库内 summarize/config.json 优先）
│   ├── ~/.config/research_scout/config.json
│   └── ~/.config/research/config.json
├── 数据目录
│   ├── ~/.claude/projects/ (Claude Code 日志)
│   ├── ~/.codex/sessions/ (Codex 日志)
│   └── [用户指定] ChatGPT export JSON
├── HuggingFace 模型缓存
│   └── ~/.cache/huggingface/hub/tencent--Hy-MT2-1.8B
├── Google Drive
│   ├── gdrive:gadget/summarize/logs
│   ├── gdrive:gadget/summarize/reports
│   ├── gdrive:gadget/website/*
│   ├── gdrive:gadget/research/*
│   ├── gdrive:gadget/test/data
│   ├── [可选] gdrive:gadget/tokens/
│   └── [可选] gdrive:gadget/config/*
├── 外部 Git 仓库
│   ├── website/public/ → tzj2006/tzj2006.github.io
│   └── website/themes/ → Hugo themes
└── 环境变量
    ├── ANTHROPIC_API_KEY
    ├── OPENAI_API_KEY
    ├── SUMMARIZE_LOGS_DIR
    ├── SUMMARIZE_REPORTS_DIR
    ├── GADGET_TRANSLATION_MODEL
    ├── GADGET_TRANSLATION_BACKEND
    └── GADGET_TRANSLATION_BATCH_SIZE
```
