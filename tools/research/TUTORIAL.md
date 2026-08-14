# Research Scout 使用教程

Research Scout 是统一的学术研究工具包，包含四大功能：

1. **论文发现**：从 arXiv / bioRxiv / PubMed 搜索论文，三阶段 LLM 管线（快速筛选 → 深度分析 → 引用影响），生成周报
2. **论文深度洞察**（`--insight`）：下载论文全文，LLM 分析写作结构、发表策略、核心知识；自动获取 OpenReview 审稿意见并分析 reviewer 共识；生成研究写作指南
3. **研究者画像**：分析研究者的学术轨迹、评分分层、发现师生关系
4. **引用图分析**：查看论文的前向引用（谁引了它）和反向参考文献（它引了谁），LLM 分析影响力

推荐入口（需先从仓库根安装 extra）：

```bash
pip install -e ".[research]"   # 依赖的 source of truth；tools/research/requirements.txt 只指向这里
python -m research.scout --help
```

`tools/research/research_scout.py` 仍能跑，但是弃用 shim（会发 `DeprecationWarning`），实现在 `research.scout` 包（`tools/research/scout/`）。Profiler 也可单独用 `python -m research`。

---

## 目录

1. [初始配置](#1-初始配置)
2. [创建研究项目](#2-创建研究项目)
3. [搜索论文](#3-搜索论文)
4. [生成周报（完整管线）](#4-生成周报完整管线)
5. [论文深度洞察（--insight）](#5-论文深度洞察--insight)
6. [会议论文搜索](#6-会议论文搜索)
7. [多源搜索](#7-多源搜索)
8. [研究者画像](#8-研究者画像)
9. [引用图分析](#9-引用图分析)
10. [部署到网站](#10-部署到网站)
11. [参数调优](#11-参数调优)
12. [工作流示例](#12-工作流示例)
13. [文件结构说明](#13-文件结构说明)
14. [常见问题](#14-常见问题)

---

## 1. 初始配置

从仓库根安装 extra 后：

```bash
python -m research.scout config --init
```

会交互式询问：
- **默认 LLM 后端**：`ollama`（默认，本地、无需 API key，需要已运行的 Ollama）/ `claude_cli` / `anthropic` / `openai`
- **Hugo 站点路径**：用于将周报部署到博客（可选，默认 `tools/website`）
- **默认回溯天数**：搜索最近几天的论文（默认 7 天）
- **默认最大结果数**：每个项目每次搜索最多返回多少篇（默认 50）
- **报告中展示的高分论文数**：周报中详细展示多少篇（默认 5）

写入仓库根 `config.json` 的 `research_scout` 段（可用 `GADGET_CONFIG` 覆盖路径）。**不会**写到 `~/.config/research_scout/`。

查看当前配置：

```bash
python -m research.scout config --show
```

> **注意**：`ollama` 需要本机 Ollama；`anthropic` 需要 `ANTHROPIC_API_KEY`；`openai` 需要 `OPENAI_API_KEY`；`claude_cli` 需要已安装 Claude CLI。全局还可设 `GADGET_LLM_BACKEND`。

---

## 2. 创建研究项目

一个「项目」定义一个研究方向。每个项目有自己的关键词、分类和开放问题。

### 基本创建

```bash
python -m research.scout init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "error recovery" "benchmarking" \
    --categories "cs.RO" "cs.AI"
```

参数说明：
- `robot-manipulation`：项目 ID（小写字母、数字、连字符）
- `--title`：项目标题（显示在报告中）
- `--keywords`：搜索关键词（会用 OR 组合搜索）
- `--categories`：arXiv 分类代码（常用如 `cs.RO` 机器人、`cs.LG` 机器学习、`cs.CV` 计算机视觉、`cs.AI` 人工智能）

### 从已有 overview 创建

```bash
python -m research.scout init my-project \
    --from-overview path/to/overview.md
```

LLM 会从文档中提取标题、关键词和开放问题。

### 添加开放问题（可选但推荐）

```bash
python -m research.scout init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "grasping" \
    --categories "cs.RO" \
    --questions "如何让机器人在未知环境中进行稳定抓取？" \
                "视觉-触觉融合在操作任务中的最佳实践？"
```

### 查看所有项目

```bash
python -m research.scout list
```

### 手动编辑项目

创建后可编辑 `tools/research/projects/<project-id>/project.json`（关键词、分类、开放问题等），以及 `overview.md`（研究背景，中文；Stage 2 会读）。该目录整体 gitignore，只跟踪 `.gitkeep`。

---

## 3. 搜索论文

搜索从配置的来源获取论文，不调用 LLM。

### 搜索单个项目

```bash
python -m research.scout search --project robot-manipulation
```

默认搜索最近 7 天（arXiv），最多 50 篇。

### 调整搜索范围

```bash
python -m research.scout search --project robot-manipulation --lookback-days 30
python -m research.scout search --project robot-manipulation --max-results 100
```

### 搜索特定作者

```bash
python -m research.scout search --author "Pieter Abbeel"
```

### 搜索所有项目

```bash
python -m research.scout search
```

不指定 `--project` 时，搜索所有 `active` 项目。

### 忽略缓存

同一天对同一项目的搜索结果会被缓存。强制重新搜索：

```bash
python -m research.scout search --project robot-manipulation --no-cache
```

---

## 4. 生成周报（完整管线）

完整管线：**搜索 → 三阶段 LLM 评估 → 方向建议 → 生成周报**。

```bash
python -m research.scout report --project robot-manipulation
```

### 三阶段评估流程

```
50 篇论文（来自 arXiv / bioRxiv / PubMed）
    |
Stage 1: 快速筛选（LLM，所有论文）
    |--- 每篇：动机、创新点、论文类型、机构
    |--- 分类 "high" / "low"
    |
    +--- 低相关 → 报告「文献阅读记录」（折叠）
    |
    +--- 高相关（最多 20 篇，溢出降入 low）
            |
            Stage 2: 深度分析
                |--- 每篇 3 个亮点（关键点/设计动机/对我们的价值/行动建议）
                |--- 相关性/新颖性/启发性（1-5）
                |--- 综合得分 = 0.4×相关性 + 0.3×启发性 + 0.3×新颖性
                |
                Stage 3: 引用影响（前若干高分论文）
                    |--- Semantic Scholar 前向引用 / 反向参考文献
                    |--- LLM：「为什么被广泛引用？后续沿什么方向？」
                |
                → 建议新研究方向
                → 更新项目 overview.md
                → Markdown 周报
                |
                [可选] --insight → Stage 4+5（第 5 节）
```

### 选择 LLM 后端

```bash
# 默认 ollama（本地，无需 API key）
python -m research.scout report --project robot-manipulation

python -m research.scout report --project robot-manipulation --api anthropic
python -m research.scout report --project robot-manipulation --api openai
python -m research.scout report --project robot-manipulation --api claude_cli
```

### 选择输出语言

```bash
python -m research.scout report --project robot-manipulation --language en
python -m research.scout report --project robot-manipulation --language zh   # 默认
```

### 跳过缓存 / 同时部署

```bash
python -m research.scout report --project robot-manipulation --no-cache
python -m research.scout report --project robot-manipulation --deploy
```

---

## 5. 论文深度洞察（--insight）

在三阶段之上，`--insight` 打开：

- **Stage 4**：下载全文，LLM 分析写作结构、发表策略、可复用知识
- **Stage 5**：匹配 OpenReview，获取 reviewer 评分与评价，LLM 分析共识与争议
- **研究写作指南**：跨论文综合

### 基本用法

```bash
python -m research.scout report --project robot-manipulation --insight
python -m research.scout ask "diffusion policy robot control" --insight
python -m research.scout report --project robot-manipulation --insight --insight-top-n 5
python -m research.scout report --project robot-manipulation --insight --deploy
```

### 处理流程

```
Stage 1-3 完成后
    |
    取 composite_score 最高的 N 篇（默认 3，--insight-top-n）
            |
            Stage 4: 论文洞察
                [4a] 下载全文
                |    ├── arXiv: HTML 优先，PDF 后备
                |    ├── bioRxiv: 尝试 HTML 全文
                |    ├── PubMed: 降级为 abstract
                |    └── 截断到 40,000 字符
                |
                [4b] LLM：写作结构 / 发表要素 / 核心知识
                |
            Stage 5: OpenReview
                [5a] fuzzy title matching（ICLR / NeurIPS / ICML 等）
                [5b] 评分、confidence、strengths/weaknesses
                [5c] 共识分析（0 条跳过；条数越多分析越完整）
                |
            综合：领域写作规范 / 审稿重点 / 方法论要点 / 代码参考
```

Insight 缓存键包含全文内容哈希：第一次只有摘要时不会永远挡住后续的全文分析。缓存目录：`outputs/cache/research-scout/insight/`。`--no-cache` 强制重跑。

### OpenReview 配置

默认 guest 模式（已公开审稿）。更多数据可设：

```bash
export OPENREVIEW_USERNAME="your@email.com"
export OPENREVIEW_PASSWORD="your_password"
```

> **支持**：ICLR、NeurIPS、ICML、COLM 等 OpenReview 会议。
> **不支持**：AAAI、CVPR、ICCV、ECCV 等（insight 仍跑，只是没有审稿段）。

### 成本（opt-in）

| 分析类型 | LLM 调用 | 大约 token |
|---------|----------|-----------|
| Stage 4 洞察 | 每篇 1 次 | ~50K/篇 |
| Stage 5 审稿共识 | 有审稿的论文 1 次 | ~5K/篇 |
| 写作指南 | 1 次 | ~20K |
| **默认 3 篇** | **约 5–7 次** | **约 170–200K** |

`--insight-top-n` 不会超过报告展示篇数。

---

## 6. 会议论文搜索

```bash
python -m research.scout search --conference "CVPR 2025"
python -m research.scout search --conference "CVPR 2025" --project robot-manipulation
python -m research.scout report --conference "CVPR 2025" --project robot-manipulation
```

arXiv 没有会议字段；工具搜全文再用 comment（如 "Accepted at CVPR 2025"）过滤。会议搜索不用 `--lookback-days`。`--conference` 与 `--author` 不能同时用。

---

## 7. 多源搜索

```bash
python -m research.scout search --project my-project --source arxiv biorxiv
python -m research.scout search --project my-project --source pubmed
python -m research.scout search --project my-project --source arxiv biorxiv pubmed
```

也可在 `project.json` 里设默认来源：

```json
{
  "id": "my-bio-project",
  "title": "...",
  "sources": ["arxiv", "biorxiv"],
  "biorxiv_categories": ["neuroscience", "bioinformatics"],
  "pubmed_journals": ["Nature", "Science"]
}
```

bioRxiv / PubMed 用标准库，不另装包。bioRxiv 的 `total` 会转成 int，多页搜索不会因类型比较崩掉。

---

## 8. 研究者画像

从 ArXiv + Semantic Scholar 拉数据，LLM 分析轨迹，打分分层。主页抓取有 SSRF 过滤（拒绝私网/回环等，并对 redirect 再验）。

### 基本用法

```bash
python -m research.scout profile "Sergey Levine"
python -m research.scout profile "Sergey Levine" --mode detailed
python -m research.scout profile "Sergey Levine" "Pieter Abbeel"
python -m research.scout profile "Wei Zhang" --affiliation "MIT"
python -m research.scout profile "Name" --paper "2301.12597"
python -m research.scout profile "Name" --author-id "1234567"
python -m research.scout profile "Sergey Levine" --homepage "https://..."
```

`--paper` 支持旧式 arXiv ID（如 `math/0211159`）。`--depth` 默认 1（同时分析发现的学生）。

### 递归发现学生

```bash
python -m research.scout profile "Sergey Levine" --depth 1
python -m research.scout profile "Sergey Levine" --depth 2
```

1. **主页提取**（优先）— S2 主页字段或 LLM 推断的 URL；可用 `--homepage`
2. **共著推断**：一作+导师末位 40% / PhD 周期时间窗 25% / 频次 20% / 时近性 15%

```bash
python -m research.scout profile --from-file names.txt
python -m research.scout profile "Sergey Levine" --model opus
python -m research.scout profile "Sergey Levine" --api anthropic
python -m research.scout profile "Sergey Levine" --no-cache
python -m research.scout profile "Sergey Levine" --deploy
```

### 分析流程

```
[1/6] ArXiv 论文（最多 100 篇）
[2/6] S2 指标；每年最多 10 篇代表作
[3/6] LLM 奖项识别
[4/6] 全文（仅 detailed；HTML 优先，PDF 后备）
[5/6] LLM 轨迹
[6/6] 加权打分 → 领域领袖(≥75) / 学术新星(≥50) / 活跃研究者(≥30) / 早期(<30)
```

输出（默认）：
- `outputs/data/research-profiler/profiles/<name>.json`
- `outputs/reports/research-profiler/<name>.md`
- `outputs/cache/research-profiler/`

Profiler 配置里若设了 `output_dir`，则全部落到该目录。

独立 Profiler CLI：

```bash
python -m research analyze "Sergey Levine"
python -m research analyze "Sergey Levine" --api ollama
python -m research show "Sergey Levine"
python -m research list
python -m research config --init    # 写入根 config.json 的 research 段
```

---

## 9. 引用图分析

```bash
python -m research.scout citations 2301.12597
python -m research.scout citations 10.1038/s41586-023-06221-2
python -m research.scout citations 2301.12597 --top-n 20
python -m research.scout citations 2301.12597 --api anthropic
python -m research.scout citations 2301.12597 --no-cache
```

数据来自 Semantic Scholar（缓存 TTL 7 天）。引用数 ≥ 5 时自动做 LLM 影响力分析。周报 Stage 3 也会对前若干高分论文做同样的事。

---

## 10. 部署到网站

```bash
python -m research.scout deploy
python -m research.scout deploy --force
```

Hugo 路径来自 `config --init` / `research_scout.hugo_site`（默认 `tools/website`）。

---

## 11. 参数调优

优先级：**命令行 > project.json > 根 config.json > 硬编码默认**。

### 全局（`config.json` → `research_scout`）

```json
{
  "default_api": "ollama",
  "hugo_site": "tools/website",
  "default_lookback_days": 7,
  "default_max_results": 50,
  "default_top_papers_in_report": 5,
  "max_high_relevance": 20,
  "default_insight_top_n": 3
}
```

### 项目级（`tools/research/projects/<id>/project.json`）

```json
{
  "id": "robot-manipulation",
  "title": "Robot Manipulation",
  "lookback_days": 14,
  "max_results": 100,
  "sources": ["arxiv", "biorxiv"],
  "biorxiv_categories": ["neuroscience"],
  "pubmed_journals": ["Nature Robotics"]
}
```

```bash
python -m research.scout report --project robot-manipulation \
    --lookback-days 30 --max-results 200
```

### Profiler（同一 `config.json` 的 `research` 段）

```json
{
  "model": "sonnet",
  "default_mode": "fast",
  "default_depth": 1,
  "max_students": 10,
  "output_dir": "",
  "semantic_scholar_api_key": ""
}
```

`python -m research config --init` 初始化。S2 key 可选；匿名已有约 10 req/s。

---

## 12. 工作流示例

### 每周一次

```bash
python -m research.scout report
python -m research.scout report --insight
# 报告在 outputs/reports/research-scout/，形如 <date>-research.md
python -m research.scout deploy
```

### 追踪新方向

```bash
python -m research.scout init diffusion-policy \
    --title "Diffusion Policy for Robotics" \
    --keywords "diffusion policy" "denoising diffusion" "robot learning" \
    --categories "cs.RO" "cs.LG" \
    --questions "扩散模型在机器人策略学习中的优势是什么？" \
                "如何加速扩散模型的推理速度以满足实时控制？"

python -m research.scout search --project diffusion-policy --lookback-days 30
python -m research.scout report --project diffusion-policy
```

### 会议 / 研究者 / 引用 / 写论文前调研

```bash
python -m research.scout report --conference "ICRA 2025" --project robot-manipulation --api anthropic
python -m research.scout profile "Sergey Levine" --mode detailed --depth 1 --deploy
python -m research.scout citations 2301.12597 --top-n 20
python -m research.scout ask "sim-to-real transfer for legged robots" --insight
python -m research.scout report --conference "ICLR 2025" --project my-project --insight
```

### 跨来源生物医学

在 `project.json` 设 `"sources": ["arxiv", "biorxiv", "pubmed"]` 等，然后：

```bash
python -m research.scout report --project brain-computer
```

---

## 13. 文件结构说明

```
tools/research/
├── scout/                     # 安装包 research.scout（实现）
│   ├── __main__.py            # python -m research.scout
│   ├── cli.py
│   ├── search.py / evaluate.py / report.py / insight.py / ask.py
│   ├── project.py / config.py / prompts.py
├── research_scout.py          # 弃用 shim
├── __main__.py, cli.py        # python -m research（Profiler）
├── analysis.py, models.py, scoring.py, ...
├── homepage_discovery.py      # 主页抓取 + SSRF
├── cache.py                   # → common.cache.DiskCache
├── apis/                      # arxiv / semantic_scholar / openreview / rate_limiter
├── projects/                  # gitignore，仅 .gitkeep
│   └── <project-id>/project.json + overview.md
├── reports/README.md          # 墓碑：真正报告在 outputs/reports/research-scout/
├── requirements.txt           # 指向 pip install -e ".[research]"
├── AGENTS.md, TUTORIAL.md, SUMMARY.md

outputs/
├── reports/research-scout/
├── cache/research-scout/{papers,eval,insight}/
├── logs/research-scout/
├── data/research-profiler/profiles/
├── reports/research-profiler/
└── cache/research-profiler/
```

仓库根 `config.json`（gitignore）段：`research_scout`、`research`。模板：`config.example.json`。

### 周报内容结构

1. 高相关性论文摘要表
2. 详细分析（评分、摘要、亮点、建议）
3. 引用影响（前若干高分）
4. 新方向建议
5. 论文深度洞察 / 研究写作指南（仅 `--insight`）
6. 文献阅读记录（低相关，折叠）

---

## 14. 常见问题

### Q: 搜不到论文？

关键词放宽、增大 `--lookback-days`、检查分类（`cs.RO` 不是 `csRO`）、`--no-cache`、`--source arxiv biorxiv pubmed`。

### Q: 评估不理想？

充实 `overview.md` 和 `open_questions`；换 `--api`；`--language en`。

### Q: LLM 超时？

默认 600s，可用 `--timeout 900`；减小 `--max-results`。Stage 1 在约 100 篇时容易超时，可 cap 在 ~50。

### Q: 如何暂停项目？

编辑 `tools/research/projects/<id>/project.json`，`status` 改为 `"paused"`。全局 search/report 会跳过，`--project` 仍可显式跑。

### Q: 缓存？

- 搜索：`outputs/cache/research-scout/papers/`（同日同项目）
- Stage 1/2：`eval/`（项目上下文 + 论文 ID + 摘要前缀哈希）
- Stage 3 / S2：引用图缓存
- Insight：全文是否可用纳入缓存键
- Profiler：`outputs/cache/research-profiler/{api,llm}/`
- `--no-cache` 跳过上述缓存

### Q: profile vs citations？

`profile` 分析**研究者**；`citations` 分析**一篇论文**。

### Q: --insight 分析哪些论文？

composite_score 最高的 3 篇，可用 `--insight-top-n`，不超过报告展示数（默认 5）。

### Q: OpenReview 匹配不到？

阈值约 0.85 的标题模糊匹配。不在 OpenReview 的会议、纯预印本、投稿标题差太多会失败；不影响 Stage 4。

### Q: --insight 太慢？

每篇全文+LLM 约 1–3 分钟。可 `--insight-top-n 1`；结果会缓存。

### Q: 还要单独装 openreview-py / PyMuPDF 吗？

`pip install -e ".[research]"` 已包含它们（extra 是 SoT）。未装时 Stage 5 会跳过，PDF 全文回退不可用，Stage 4 摘要路径仍可工作。

### Q: Semantic Scholar API Key？

https://www.semanticscholar.org/product/api 。可在 Profiler `config --init` 写入根 `config.json` 的 `research` 段；不配则匿名访问。

### Q: 默认后端是 claude_cli 吗？

不是。CLI 与 `config.json` 的 `default_api` 默认都是 **`ollama`**。`claude_cli` 是可选后端之一。
