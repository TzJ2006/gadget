# Research Toolkit — Code Summary

> 6,100 行 Python 代码 | 17 个文件 | 2 个独立工具共用 1 套基础设施

## 1. 整体功能

这是一个学术研究辅助工具包，提供两大核心功能：

- **Research Scout** (`research_scout.py`, 2934 行) — 论文发现与评估。从 arXiv / bioRxiv / PubMed 搜索论文，经三阶段 LLM 管线（筛选 → 深度分析 → 引用影响）生成研究报告，可部署到 Hugo 博客。
- **Researcher Profiler** (模块化包, ~1660 行) — 学术研究者画像。聚合 ArXiv + Semantic Scholar 数据，运行 LLM 轨迹分析、层级打分、师生关系推断，输出 JSON profile + Markdown 报告。

两者共享 `common/` 包（LLM 调用、磁盘缓存、路径管理、JSON 修复、Hugo 部署）和相同的 CLI 模式（`--api` 三后端切换）。

---

## 2. 核心模块与关键函数

### 主入口

| 文件 | 职责 |
|------|------|
| `research_scout.py` | Research Scout 单文件脚本（搜索、评估、报告、部署） |
| `cli.py` → `analysis.py` | Researcher Profiler 入口 → BFS 分析编排器 |
| `__main__.py` | `python -m research` 的入口点，调用 `cli.main()` |

### Research Scout (`research_scout.py`)

```
arXiv / bioRxiv / PubMed
    │
    ▼
Stage 1: _screen_papers()          ← 全部论文：motivation, innovation_point, paper_type
    │    分类 "high" / "low"
    │
    ├── Low  → 折叠进报告（文献阅读记录）
    │
    └── High（上限 20 篇）
         │
         ▼
Stage 2: _deep_evaluate_papers()   ← 读取 overview.md，3 条 highlights，relevance/novelty/inspiration 评分
         │    composite = 0.4R + 0.3I + 0.3N
         │
         ▼
Stage 3: _analyze_citations()      ← 前 5 篇：S2 正向/反向引用 + LLM 影响力分析
         │
         ▼
suggest_directions() + append_literature_note() + deploy_to_hugo()
```

**关键函数：**
- `build_arxiv_query()` — 从项目关键词+分类构建查询
- `search_arxiv()` — arXiv 搜索 + 去重 + 连续已知论文早停（5 篇）
- `evaluate_papers_for_project()` → 返回 `{"high_relevance": [...], "low_relevance": [...], "screening_stats": {...}}`
- `_resolve_param()` — 配置优先级：CLI > project.json > config.json > 默认值
- `create_project_from_overview()` — 从现有 overview.md 反向用 LLM 提取项目信息

### Researcher Profiler

```
cli.py
  └→ analysis.py::run_analysis()        ← BFS 递归入口
       └→ analyze_researcher()           ← 6 步管线/每位研究者
            1. ArXiv 论文获取
            2. Semantic Scholar 指标（3 层解析：直接 ID → 论文反查 → 名字搜索）
            3. LLM 奖项识别（Best Paper / Spotlight / Oral）
            4. 全文下载（详细模式：HTML 优先 → PDF 回退）
            5. LLM 轨迹分析（研究主题、突破、方法论演进）
            6. 层级打分（加权公式 → 四档分类）
       └→ discover_students()            ← 4 阶段师生推断
            1. 主页提取（homepage_discovery.py）
            2. 共著分析（student_discovery.py）
            3. 合并去重（homepage 优先）
            4. LLM 补充研究方向
```

**核心子模块：**

| 文件 | 行数 | 职责 |
|------|------|------|
| `analysis.py` | 618 | BFS 编排器，论文选择/合并/奖项重排 |
| `output.py` | 310 | JSON 持久化 + Markdown 报告渲染 + Hugo 部署 |
| `prompts.py` | 318 | 7 个 LLM prompt 模板（轨迹分析、奖项识别、引用影响、主页 URL/学生提取等） |
| `homepage_discovery.py` | 262 | 多策略主页 URL 发现 → HTML 解析 → LLM 学生提取 |
| `models.py` | 180 | 5 个 dataclass：Paper, ResearcherMetrics, ResearcherTier, StudentCandidate, ResearcherProfile |
| `scoring.py` | 91 | 加权打分：h-index 25% + 总引用 20% + 近 5 年引用 20% + 顶会比 20% + 学术年龄 15% |
| `student_discovery.py` | 94 | 共著模式打分：第一作者信号 40% + 时间跨度 25% + 频次 20% + 时近性 15% |
| `llm.py` | 95 | LLM 调用封装 + SHA-256 内容哈希缓存 + 4 阶段 JSON 修复 |
| `config.py` | 116 | `~/.config/research/config.json` 管理 + 路径解析 |

### API 客户端

| 文件 | 行数 | 职责 |
|------|------|------|
| `apis/arxiv_client.py` | 220 | ArXiv 搜索 + 全文下载（HTML 解析 + PyMuPDF PDF 回退） |
| `apis/semantic_scholar.py` | 610 | S2 作者搜索/消歧、论文数据、共著分析、引用图谱；指数退避重试 |
| `apis/rate_limiter.py` | 44 | 线程安全令牌桶：ArXiv 1/3s, S2 10/s, Web 1/2s |

---

## 3. 依赖与模块结构

### 调用关系图

```
research_scout.py (独立)
    ├── common.llm          (call_llm_raw, LLMCallConfig, chunking)
    ├── common.json_utils   (parse_json_response, try_parse_json)
    ├── common.io           (atomic_write, content_hash)
    ├── common.hugo         (run_hugo_update)
    ├── common.site_staging (write_site_content)
    └── apis/semantic_scholar.py (引用图谱)

cli.py → analysis.py (Profiler 编排器)
    ├── apis/arxiv_client.py
    ├── apis/semantic_scholar.py
    ├── homepage_discovery.py
    │   └── apis/rate_limiter.py (web_limiter)
    ├── student_discovery.py
    ├── scoring.py
    ├── llm.py → common.llm + common.json_utils
    ├── prompts.py
    ├── output.py → common.hugo + common.site_staging
    ├── models.py
    ├── config.py → common.paths
    └── cache.py → common.cache.DiskCache
```

### 外部依赖

| 包 | 用途 |
|----|------|
| `arxiv>=2.0.0` | ArXiv API 客户端 |
| `anthropic>=0.18.0` | Anthropic LLM 后端 |
| `openai>=1.0.0` | OpenAI LLM 后端 |
| `PyMuPDF` (可选) | PDF 全文提取（详细模式） |
| stdlib `urllib.request` | bioRxiv / PubMed / S2 / 主页抓取 |
| stdlib `xml.etree` | PubMed XML 解析 |

### 配置

- `~/.config/research_scout/config.json` — Research Scout 配置
- `~/.config/research/config.json` — Researcher Profiler 配置
- `projects/<name>/project.json` — 每个项目的搜索参数
- 环境变量：`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`

### 输出路径（全部在 `outputs/` 下，gitignored）

```
outputs/
├── reports/research-scout/        ← Scout 报告
├── reports/research-profiler/     ← Profiler Markdown 报告
├── data/research-profiler/profiles/  ← JSON 研究者画像
├── cache/research-scout/{eval,papers}/  ← 评估/搜索缓存
├── cache/research-profiler/{api/arxiv, api/semantic_scholar, api/homepage, api/pdfs, llm}/
└── logs/research-scout/           ← 旋转日志 5MB×3
```

---

## 4. 潜在问题与代码异味

### 单文件巨石 — `research_scout.py` (2934 行)

这个文件包含搜索、评估、报告生成、CLI 解析等所有 Scout 功能。与 Profiler 的模块化设计形成鲜明对比。建议按功能拆分（search、evaluate、report、cli）以提高可维护性。

### 重复基础设施

- `research_scout.py` 有自己的 `_call_llm()` 封装，Profiler 有独立的 `llm.py`，两者都最终调用 `common.llm.call_llm_raw()` 但各自维护缓存和 JSON 解析逻辑。
- 两套独立的配置文件（`research_scout/config.json` vs `research/config.json`），分别位于不同路径。

### 硬编码值

- `scoring.py` 的层级阈值（75/50/30）和权重（25/20/20/20/15）硬编码在函数体内。
- `semantic_scholar.py` 中的顶会列表硬编码为 `TOP_VENUES` 集合，无法通过配置自定义。
- `student_discovery.py` 的阈值 0.4 和权重（40/25/20/15）均硬编码。

### 错误处理

- `apis/semantic_scholar.py` 的 `_s2_request()` 在重试耗尽后只返回 `None`，调用方需检查 None（大多数都做了）。
- `homepage_discovery.py` 的 `fetch_homepage()` 捕获所有 Exception 并返回空字符串，可能掩盖非网络错误。
- `research_scout.py` 中多处 bare `except Exception` 日志后继续，某些场景下可能遗漏关键失败。

### 类型注解覆盖

- `research_scout.py` 的函数签名缺少类型注解（2934 行单文件中几乎无类型标注）。
- Profiler 模块化代码有更好的类型注解覆盖但仍不完整（特别是 `analysis.py` 的内部函数）。

### 安全考量

- `homepage_discovery.py` 从 LLM 生成的 URL 直接 HTTP 请求，虽有 2MB 响应限制，但无 SSRF 保护（无内网 IP 过滤）。
- S2 API key 若配置在 config.json 中，以明文存储在用户目录。
