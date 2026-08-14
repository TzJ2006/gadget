# Research Toolkit — Code Summary

> Scout 在 `research.scout` 包（`tools/research/scout/`）；Profiler 在同目录模块化包；共享 `common/` 与 `apis/`。依赖以仓库根 `pip install -e ".[research]"` 为准。

## 1. 整体功能

学术研究辅助工具包，两大块共用同一套 CLI 后端开关（`--api`：`ollama` 默认 / `claude_cli` / `anthropic` / `openai`）：

- **Research Scout**（`research.scout`）— 论文发现与评估。从 arXiv / bioRxiv / PubMed 搜索，经三阶段 LLM 管线（筛选 → 深度分析 → 引用影响）生成研究报告，可选 `--insight`（全文 + OpenReview），可部署到 Hugo。推荐入口：`python -m research.scout`。`research_scout.py` 只是弃用 shim（转发到 `research.scout`，发 `DeprecationWarning`），不是 2934 行单文件实现。
- **Researcher Profiler** — 学术研究者画像。聚合 ArXiv + Semantic Scholar，LLM 轨迹分析、层级打分、师生关系推断，输出 JSON profile + Markdown。入口：`python -m research`，或 `python -m research.scout profile`。

配置在**仓库根** `config.json` 的 `research_scout`（Scout）与 `research`（Profiler）段，可用 `GADGET_CONFIG` 覆盖路径。没有 `~/.config/research` / `~/.config/research_scout` 回退。

---

## 2. 核心模块与关键函数

### 主入口

| 文件 | 职责 |
|------|------|
| `scout/`（安装名 `research.scout`） | Scout：搜索、评估、报告、洞察、ask、CLI |
| `research_scout.py` | 弃用兼容 shim：re-export + `main()` |
| `scout/__main__.py` | `python -m research.scout` |
| `cli.py` → `analysis.py` | Profiler 入口 → BFS 分析编排器 |
| `__main__.py` | `python -m research` → `cli.main()` |

### Research Scout (`research.scout`)

```
arXiv / bioRxiv / PubMed
    │
    ▼
Stage 1: scout.evaluate._screen_papers()     ← 全部论文：motivation, innovation_point, paper_type
    │    分类 "high" / "low"
    │
    ├── Low  → 折叠进报告（文献阅读记录）
    │
    └── High（上限 20 篇，溢出降入 low）
         │
         ▼
Stage 2: scout.evaluate._deep_evaluate_papers()  ← overview.md / current methods，3 条 highlights，
         │    relevance/novelty/inspiration；composite = 0.4R + 0.3I + 0.3N
         │
         ▼
Stage 3: scout.evaluate.analyze_citations()  ← 前 N 篇：S2 正向/反向引用 + LLM 影响力
         │
         ▼
suggest_directions() + append_literature_note() + deploy
         │
         [可选 --insight]
         Stage 4: scout.insight 全文洞察
         Stage 5: OpenReview 审稿共识 + 写作指南
```

**分包：**

| 模块 | 职责 |
|------|------|
| `scout/cli.py` | argparse：`init/ask/list/search/report/profile/citations/deploy/config` |
| `scout/search.py` | `build_arxiv_query` / `search_arxiv` / conference / author / bioRxiv / PubMed；搜索缓存；429/503 重试时跳过已产出结果 |
| `scout/evaluate.py` | `call_scout_llm` → `common.llm.call_llm_raw`；三阶段评估；`evaluate_papers_for_project` → `{"high_relevance","low_relevance","screening_stats"}` |
| `scout/report.py` | Markdown 周报、Hugo post、`append_literature_note` |
| `scout/insight.py` | Stage 4/5：全文下载、洞察缓存键含全文哈希、OpenReview |
| `scout/ask.py` | 自然语言意图解析 → 路由搜索 |
| `scout/project.py` | 项目 CRUD；`create_project_from_overview` |
| `scout/config.py` | 读根 `config.json`：`research_scout` 为主、`research` 补缺；`resolve_param`：CLI > project.json > config > 默认；路径来自 `common.paths` |
| `scout/prompts.py` | Scout 用 prompt 模板 |

### Researcher Profiler

```
cli.py
  └→ analysis.py::run_analysis()        ← BFS 递归入口
       └→ analyze_researcher()           ← 6 步管线/每位研究者
            1. ArXiv 论文获取
            2. Semantic Scholar 指标（直接 ID → 论文反查 → 名字搜索）
            3. LLM 奖项识别（Best Paper / Spotlight / Oral）
            4. 全文下载（详细模式：HTML 优先 → PDF 回退）
            5. LLM 轨迹分析
            6. 层级打分
       └→ discover_students()            ← 师生推断
            1. 主页提取（homepage_discovery.py，含 SSRF）
            2. 共著分析（student_discovery.py）
            3. 合并去重（homepage 优先）
            4. LLM 补充研究方向
```

| 文件 | 职责 |
|------|------|
| `analysis.py` | BFS 编排器，论文选择/合并/奖项重排 |
| `output.py` | JSON 持久化 + Markdown 渲染 + Hugo 部署 |
| `prompts.py` | Profiler prompt 模板 |
| `homepage_discovery.py` | 主页 URL 发现 → HTML 解析 → LLM 学生提取；`_is_safe_url` + `_SafeRedirectHandler` 拦私网/回环/保留地址与不安全跳转 |
| `models.py` | dataclass：`Paper`, `ResearcherMetrics`, `ResearcherTier`, `StudentCandidate`, `ResearcherProfile` |
| `scoring.py` | 默认权重：h-index 25% + 总引用 20% + 近 5 年引用 20% + 顶会比 20% + 学术年龄 15%；可用 `weights`/`thresholds` 覆盖 |
| `student_discovery.py` | 共著打分：一作信号 40% + 时间跨度 25% + 频次 20% + 时近性 15%（`weights` 可覆盖） |
| `llm.py` | Profiler LLM 封装 → `common.llm` + `common.json_utils`；默认 backend `ollama` |
| `config.py` | 根 `config.json` 的 `research` 段（非 `~/.config`） |
| `cache.py` | re-export `common.cache.DiskCache` |

### API 客户端

| 文件 | 职责 |
|------|------|
| `apis/arxiv_client.py` | ArXiv 搜索 + 全文（HTML + PyMuPDF PDF 回退） |
| `apis/semantic_scholar.py` | S2 作者/论文/共著/引用；指数退避 |
| `apis/openreview_client.py` | OpenReview 审稿 |
| `apis/rate_limiter.py` | 令牌桶：ArXiv 1/3s, S2 10/s, Web 1/2s, OpenReview 2/s |

---

## 3. 依赖与模块结构

### 调用关系

```
python -m research.scout  (scout/cli.py)
    ├── research.scout.{search,evaluate,report,insight,ask,project,config}
    ├── common.llm / common.json_utils / common.io / common.hugo / common.site_staging
    └── research.apis.semantic_scholar（引用图）

research_scout.py ──shim──► research.scout

python -m research  (cli.py → analysis.py)
    ├── apis/arxiv_client.py
    ├── apis/semantic_scholar.py
    ├── homepage_discovery.py  → apis/rate_limiter.py (web_limiter) + SSRF
    ├── student_discovery.py
    ├── scoring.py / llm.py / prompts.py / output.py / models.py
    ├── config.py → common.config（section research）
    └── cache.py → common.cache.DiskCache
```

### 外部依赖

安装源：**仓库根** `pip install -e ".[research]"`（`tools/research/requirements.txt` 只指向该 extra，不是第二份依赖表）。extra 含 `arxiv`、`anthropic`、`openai`、`openreview-py`、`pymupdf`。bioRxiv / PubMed / 主页抓取走 stdlib `urllib` / `xml.etree`。

### 配置

- 仓库根 `config.json`（gitignore；模板 `config.example.json`）
  - `research_scout` — Scout：`default_api`（默认 `ollama`）、回溯天数、max results、Hugo 路径等
  - `research` — Profiler：model / depth / S2 key 等
  - Scout 加载时合并：scout 键优先，profiler 段补缺
- `GADGET_CONFIG` 覆盖配置文件路径；无 `~/.config/...` 回退
- `tools/research/projects/<name>/project.json` — 每项目搜索参数（`projects/` gitignore，保留 `.gitkeep`）
- 环境变量：`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`；Ollama 不需要 key。全局后端还可 `GADGET_LLM_BACKEND`

### 输出路径（`outputs/`，gitignored）

```
outputs/
├── reports/research-scout/           ← Scout 报告（tools/research/reports/ 是墓碑 README）
├── reports/research-profiler/        ← Profiler Markdown
├── data/research-profiler/profiles/  ← JSON 画像
├── cache/research-scout/{eval,papers,insight}/
├── cache/research-profiler/{api/arxiv, api/semantic_scholar, api/homepage, api/pdfs, llm}/
└── logs/research-scout/              ← 旋转日志 5MB×3
```

---

## 4. 潜在问题与代码异味

### 已不是问题（旧 SUMMARY 过时）

- `research_scout.py` 已不是 2934 行巨石；实现在 `scout/`。
- 配置已统一到仓库根 `config.json`，不是两套 `~/.config/...`。
- `homepage_discovery.fetch_homepage` **有** SSRF：只允许 http/https，解析 DNS 后拒绝 private/loopback/link-local/reserved，并对 redirect 目标再验。

### 仍在的重复与硬编码

- Scout 的 `call_scout_llm` 与 Profiler 的 `llm.py` 各自包一层 `common.llm` + JSON 修复。
- 两个配置**段**（同文件）：`research_scout` vs `research`。
- `scoring.py` 层级阈值（75/50/30）和权重、`student_discovery.py` 阈值 0.4 与权重，默认仍写在函数里（可经参数覆盖，未进 config.json）。
- `semantic_scholar.py` 的 `TOP_VENUES` 仍硬编码。
- 不少 Scout 内部函数签名默认 `api="claude_cli"`；**CLI / config / `main()` 的用户默认是 `ollama`**，调用方会覆盖签名默认值。

### 错误处理与安全

- `apis/semantic_scholar.py` 重试耗尽后返回 `None`，调用方需检查。
- 主页抓取网络失败返回空字符串；HTML 解析仍 `except Exception`。
- Scout 搜索/评估多处捕获 `Exception` 后记日志继续。
- S2 API key 若写在 `config.json` 里是明文（该文件 gitignored）。
