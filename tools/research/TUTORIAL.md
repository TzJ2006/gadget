# Research Scout 使用教程

Research Scout 是一个统一的学术研究工具包，包含四大功能：

1. **论文发现**：从 arXiv / bioRxiv / PubMed 搜索论文，三阶段 LLM 管线（快速筛选 → 深度分析 → 引用影响），生成周报
2. **论文深度洞察**（`--insight`）：下载论文全文，LLM 分析写作结构、发表策略、核心知识；自动获取 OpenReview 审稿意见并分析 reviewer 共识；生成研究写作指南
3. **研究者画像**：分析研究者的学术轨迹、评分分层、发现师生关系
4. **引用图分析**：查看论文的前向引用（谁引了它）和反向参考文献（它引了谁），LLM 分析影响力

所有功能通过一个统一的 CLI 入口 `research_scout.py` 调用。

---

## 本版修复与变更（2026-06-28）

一次逻辑审计修复了以下问题（命令用法不变）：

- **bioRxiv 搜索不再崩溃**（重要）：`--source biorxiv` 多页搜索时，bioRxiv 返回的 `total` 是字符串，旧代码 `cursor >= total`（int 比 str）会抛 `TypeError` 中断整个搜索/周报流程。现已强制转 int；已用真实 API 验证（一次取回 40 篇、跨多页）。
- **洞察缓存可升级到全文分析**：首次跑没拿到全文（缺 PyMuPDF/网络波动/PubMed）会缓存「仅摘要」结果，之后即使全文可用也永远命中旧缓存。现把全文是否可用纳入缓存键，全文就绪后会重新做全文分析。
- **arXiv 重试不再重复论文**：中途遇到 429/503 重试时会跳过已产出的结果，不再把前面的论文再追加一遍。
- **旧式 arXiv ID 可解析**：`citations` / profiler `--paper` 传入 `math/0211159`、`cs.RO/0211159` 这类旧格式 ID 现能正确加 `ARXIV:` 前缀解析。
- **profiler 细节**：`--depth` 帮助文案更正为默认 1（=同时分析发现的学生）；homepage 文本抽取改用 skip 栈，`<footer>` 内嵌 `<article>` 不再泄漏页脚文本；LLM 返回非 dict 学生条目不再崩溃；不同研究者重名（如 `A. Smith` vs `A Smith`）不再相互覆盖画像文件；显式 `--hugo-site .` 不再被丢弃。

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

首次使用前需要进行配置：

```bash
python tools/research/research_scout.py config --init
```

会交互式询问以下配置项：
- **默认 LLM 后端**：`claude_cli`（默认，直接调用 Claude CLI）/ `anthropic` / `openai`
- **Hugo 站点路径**：用于将周报部署到你的博客（可选）
- **默认回溯天数**：搜索最近几天的论文（默认 7 天）
- **默认最大结果数**：每个项目每次搜索最多返回多少篇论文（默认 50）
- **报告中展示的高分论文数**：周报中详细展示多少篇（默认 5）

配置文件保存在 `~/.config/research_scout/config.json`。

查看当前配置：

```bash
python tools/research/research_scout.py config --show
```

> **注意**：使用 `anthropic` 后端需要设置环境变量 `ANTHROPIC_API_KEY`；使用 `openai` 后端需要设置 `OPENAI_API_KEY`。使用 `claude_cli` 后端不需要额外配置，但需要已安装 Claude CLI。

---

## 2. 创建研究项目

一个"项目"定义了你的一个研究方向。每个项目有自己的关键词、分类和开放问题。

### 基本创建

```bash
python tools/research/research_scout.py init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "error recovery" "benchmarking" \
    --categories "cs.RO" "cs.AI"
```

参数说明：
- `robot-manipulation`：项目 ID（小写字母、数字、连字符）
- `--title`：项目标题（显示在报告中）
- `--keywords`：搜索关键词（会用 OR 组合搜索）
- `--categories`：arXiv 分类代码（常用的如 `cs.RO` 机器人、`cs.LG` 机器学习、`cs.CV` 计算机视觉、`cs.AI` 人工智能）

### 从已有 overview 创建

如果你已经有一份研究概述文档，可以让 LLM 自动提取项目信息：

```bash
python tools/research/research_scout.py init my-project \
    --from-overview path/to/overview.md
```

LLM 会从文档中自动提取标题、关键词和开放问题。

### 添加开放问题（可选但推荐）

开放问题帮助 LLM 更好地判断论文与你研究的相关性：

```bash
python tools/research/research_scout.py init robot-manipulation \
    --title "Robot Manipulation" \
    --keywords "robot manipulation" "grasping" \
    --categories "cs.RO" \
    --questions "如何让机器人在未知环境中进行稳定抓取？" \
                "视觉-触觉融合在操作任务中的最佳实践？"
```

### 查看所有项目

```bash
python tools/research/research_scout.py list
```

### 手动编辑项目

创建后可以直接编辑 `research/projects/<project-id>/project.json` 来修改关键词、分类、开放问题等。还可以编辑 `overview.md` 添加你的研究背景和当前进展（中文），这些信息会被 Stage 2 深度评估使用。

---

## 3. 搜索论文

搜索从配置的来源获取论文，不调用 LLM，速度很快。

### 搜索单个项目

```bash
python tools/research/research_scout.py search --project robot-manipulation
```

默认搜索最近 7 天的论文（来自 arXiv），最多 50 篇。

### 调整搜索范围

```bash
# 搜索最近 30 天
python tools/research/research_scout.py search --project robot-manipulation --lookback-days 30

# 最多返回 100 篇
python tools/research/research_scout.py search --project robot-manipulation --max-results 100
```

### 搜索特定作者

```bash
python tools/research/research_scout.py search --author "Pieter Abbeel"
```

### 搜索所有项目

```bash
python tools/research/research_scout.py search
```

不指定 `--project` 时，会搜索所有 `active` 状态的项目。

### 忽略缓存

同一天对同一项目的搜索结果会被缓存。如需强制重新搜索：

```bash
python tools/research/research_scout.py search --project robot-manipulation --no-cache
```

---

## 4. 生成周报（完整管线）

这是最核心的命令。它会执行完整管线：**搜索 → 三阶段 LLM 评估 → 方向建议 → 生成周报**。

```bash
python tools/research/research_scout.py report --project robot-manipulation
```

### 三阶段评估流程

```
50 篇论文（来自 arXiv / bioRxiv / PubMed）
    |
Stage 1: 快速筛选（1 次 LLM 调用，所有论文）
    |--- 每篇论文标注：动机、创新点、论文类型、机构
    |--- 分类为 "high"（高相关）或 "low"（低相关）
    |
    +--- 低相关论文 → 报告的"文献阅读记录"（折叠显示）
    |
    +--- 高相关论文（最多 20 篇）
            |
            Stage 2: 深度分析（1 次 LLM 调用）
                |--- 每篇论文 3 个亮点（关键点/设计动机/对我们的价值/行动建议）
                |--- 相关性/新颖性/启发性打分（1-5）
                |--- 综合得分 = 0.4×相关性 + 0.3×启发性 + 0.3×新颖性
                |--- 排序：综合得分降序，引用数作为同分时的 tiebreaker
                |
                Stage 3: 引用影响分析（自动执行，前 5 篇高分论文）
                    |--- 通过 Semantic Scholar 查找论文 ID
                    |--- 获取前向引用（被谁引用了，按引用数排序，前 20 篇）
                    |--- 获取反向参考文献（它引了谁，前 20 篇）
                    |--- LLM 分析："这篇论文为什么被广泛引用？后续工作沿什么方向？"
                |
                → 建议新研究方向
                → 自动更新项目 overview.md
                → 生成 Markdown 周报
                |
                [可选] 加 --insight 开启 Stage 4+5（详见第 5 节）
```

### 选择 LLM 后端

```bash
# 使用 Anthropic API（需要 ANTHROPIC_API_KEY）
python tools/research/research_scout.py report --project robot-manipulation --api anthropic

# 使用 OpenAI API（需要 OPENAI_API_KEY）
python tools/research/research_scout.py report --project robot-manipulation --api openai

# 使用 Claude CLI（默认，无需 API key）
python tools/research/research_scout.py report --project robot-manipulation --api claude_cli
```

### 选择输出语言

```bash
# 英文输出
python tools/research/research_scout.py report --project robot-manipulation --language en

# 中文输出（默认）
python tools/research/research_scout.py report --project robot-manipulation --language zh
```

### 跳过缓存

评估结果会被缓存（Stage 1 和 Stage 2 分别缓存）。如需重新评估：

```bash
python tools/research/research_scout.py report --project robot-manipulation --no-cache
```

### 生成报告同时部署

```bash
python tools/research/research_scout.py report --project robot-manipulation --deploy
```

---

## 5. 论文深度洞察（--insight）

在标准的三阶段评估之上，`--insight` 开启两个额外阶段，帮你真正**读懂**论文：

- **Stage 4：论文洞察分析**——下载全文，LLM 分析写作结构、发表策略、可复用知识
- **Stage 5：OpenReview 审稿意见**——自动匹配论文到 OpenReview，获取 reviewer 评分和评价，LLM 分析共识与争议
- **综合输出：研究写作指南**——跨论文综合分析，生成领域写作规范、审稿重点、方法论要点、代码参考

### 基本用法

```bash
# 标准周报 + 深度洞察
python tools/research/research_scout.py report --project robot-manipulation --insight

# 搭配 ask 命令使用
python tools/research/research_scout.py ask "diffusion policy robot control" --insight

# 自定义分析论文数（默认 3 篇）
python tools/research/research_scout.py report --project robot-manipulation --insight --insight-top-n 5

# 部署到 Hugo
python tools/research/research_scout.py report --project robot-manipulation --insight --deploy
```

### 处理流程

```
Stage 1-3 完成后（如第 4 节所述）
    |
    +--- 高相关论文（按 composite_score 排序）
            |
            取 top N 篇（默认 3，可通过 --insight-top-n 调整）
            |
            Stage 4: 论文洞察分析
                |
                [4a] 下载全文
                |    ├── arXiv: HTML 优先，PDF 后备（复用 arxiv_client.download_fulltext）
                |    ├── bioRxiv: 尝试 HTML 全文
                |    ├── PubMed: 降级为仅使用 abstract
                |    └── 截断到 40,000 字符（避免 LLM 上下文溢出）
                |
                [4b] LLM 三维度分析（单次调用）
                     ├── 写作结构：论证流程、章节模式、论证风格
                     ├── 发表要素：关键优势、定位策略、实验设计
                     └── 核心知识：核心洞察、可复用技术、实现提示
                |
            Stage 5: OpenReview 审稿意见
                |
                [5a] 论文匹配
                |    ├── 通过 fuzzy title matching 在 OpenReview 搜索
                |    ├── 覆盖 ICLR / NeurIPS / ICML 等主流会议
                |    └── 匹配失败 → 跳过（不影响 Stage 4 结果）
                |
                [5b] 获取审稿意见
                |    └── 评分、置信度、strengths、weaknesses、questions
                |
                [5c] LLM 共识分析
                     ├── 0 条 review → 跳过
                     ├── 1 条 review → 单 reviewer 摘要
                     ├── 2 条 review → 有限共识分析
                     └── 3+ 条 review → 完整共识/争议分析
                |
            综合：研究写作指南
                |--- LLM 综合所有论文的洞察 + 审稿意见
                |--- 输出四个板块：
                |    ├── 领域写作规范（论文该怎么写）
                |    ├── 审稿重点提示（reviewer 看什么）
                |    ├── 方法论要点（技术上能学到什么）
                |    └── 代码实现参考（怎么把想法变成代码）
                |
                → 报告中增加"论文深度洞察"和"研究写作指南"章节
```

### 报告输出示例

启用 `--insight` 后，Markdown 周报中会多出两个章节：

**论文深度洞察** — 每篇被分析的论文包含：

```
#### [2503.12345] Paper Title

**写作结构**:
- 论证流程: Problem → Gap → Hypothesis → Method → Experiments → Ablation → Discussion
- 章节模式: Introduction → Related Work → Preliminary → Method → Experiments → Conclusion
- 论证风格: 实验驱动，大量消融研究验证设计选择

**发表要素**:
- 优势: 首次在 X 任务上超越人类水平
- 优势: 提出通用框架，适用于多种场景
- 定位策略: 填补了 X 和 Y 之间的鸿沟
- 实验设计: 6 个数据集、3 个强基线、完整消融

**核心知识**:
- 洞察: 关键发现是 X 和 Y 之间的 trade-off 可以通过 Z 解决
- 可复用技术: 提出的 attention mask 策略可以直接用于其他任务
- 实现提示: 学习率需要 warmup 1000 步，batch size 对结果影响很大

**审稿意见** (3 reviewers):
- 平均评分: 6.7 / 10
- 共识优点: 实验全面，方法有理论支撑
- 共识问题: 计算成本未讨论，缺少与最新方法的比较
- 争议点: Reviewer 2 认为 novelty 有限，Reviewer 3 强烈反对
- 关键建议: 增加计算效率分析和更多 baseline 比较
```

**研究写作指南** — 跨论文综合：

```
**领域写作规范**
该领域论文普遍采用"问题定义→方法→理论分析→实验验证"的四段式结构。
Introduction 部分通常用 1-2 段描述现实场景，然后明确指出现有方法的 gap...

**审稿重点提示**
Reviewer 最看重的三个方面：(1) 实验的全面性和公平性 (2) 与 state-of-the-art 的差距分析
(3) 方法的泛化性论证。常见的被拒原因包括...

**方法论要点**
三篇论文共同的技术趋势：(1) 用 diffusion model 做策略表示
(2) contrastive learning 用于特征对齐 (3) 混合精度训练加速...

**代码实现参考**
核心算法建议使用 PyTorch + Hydra 配置管理。Paper A 的关键创新点可以用
3 行代码实现：先计算 attention mask，然后...
```

### OpenReview 配置

OpenReview 默认以 **guest 模式**（无需账号）运行，可以读取已公开的审稿意见。

如果想获取更多数据（如尚未公开的审稿），可以配置账号：

```bash
export OPENREVIEW_USERNAME="your@email.com"
export OPENREVIEW_PASSWORD="your_password"
```

> **支持的会议**：ICLR、NeurIPS、ICML、COLM 等使用 OpenReview 平台的会议。
> **不支持**：AAAI、CVPR、ICCV、ECCV 等使用其他审稿系统的会议（这些论文的 insight 分析仍然正常，只是没有审稿意见）。

### 成本说明

`--insight` 是 **opt-in**（需要显式开启），因为它会增加额外的 LLM 调用：

| 分析类型 | LLM 调用次数 | 大约 token 消耗 |
|---------|------------|----------------|
| Stage 4: 洞察分析 | 每篇论文 1 次 | ~50K tokens/篇 |
| Stage 5: 审稿共识 | 有审稿的论文 1 次 | ~5K tokens/篇 |
| 写作指南综合 | 1 次（总） | ~20K tokens |
| **默认 3 篇总计** | **约 5-7 次** | **约 170-200K tokens** |

默认分析前 3 篇高分论文。通过 `--insight-top-n` 调整数量（会自动 cap 到不超过报告展示的论文数）。

### 缓存

Insight 分析结果会被缓存（基于论文 ID + 内容哈希），重复运行同一项目不会重复调用 LLM。使用 `--no-cache` 可以强制重新分析。

缓存位置：`outputs/cache/research-scout/insight/`

---

## 6. 会议论文搜索

可以搜索特定会议（如 CVPR、ICRA、NeurIPS）的论文：

```bash
# 仅搜索 CVPR 2025 的论文
python tools/research/research_scout.py search --conference "CVPR 2025"

# 搜索 CVPR 2025 中与你项目相关的论文
python tools/research/research_scout.py search --conference "CVPR 2025" --project robot-manipulation

# 完整管线：会议论文 + 三阶段评估
python tools/research/research_scout.py report --conference "CVPR 2025" --project robot-manipulation
```

**原理**：arXiv 没有会议字段，但作者通常在 comment 中注明会议（如 "Accepted at CVPR 2025"）。工具会搜索 arXiv 全文，然后用 comment 字段二次过滤。

> **注意**：会议搜索不需要 `--lookback-days`，因为会议论文跨越固定时间段，使用相关性排序而非日期排序。`--conference` 和 `--author` 不能同时使用。

---

## 7. 多源搜索

除了 arXiv，还支持从 bioRxiv 和 PubMed 搜索论文：

```bash
# 同时搜索 arXiv 和 bioRxiv
python tools/research/research_scout.py search --project my-project --source arxiv biorxiv

# 搜索 PubMed
python tools/research/research_scout.py search --project my-project --source pubmed

# 三个来源全部搜索
python tools/research/research_scout.py search --project my-project --source arxiv biorxiv pubmed
```

也可以在 `project.json` 中配置默认搜索来源：

```json
{
  "id": "my-bio-project",
  "title": "...",
  "sources": ["arxiv", "biorxiv"],
  "biorxiv_categories": ["neuroscience", "bioinformatics"],
  "pubmed_journals": ["Nature", "Science"]
}
```

> **注意**：bioRxiv 和 PubMed 搜索使用标准库（`urllib.request`、`xml.etree`），不需要额外依赖。

---

## 8. 研究者画像

分析一位研究者的学术轨迹：从 ArXiv 和 Semantic Scholar 获取论文数据，LLM 分析研究历程，计算评分和分层。

### 基本用法

```bash
# 分析单个研究者（快速模式）
python tools/research/research_scout.py profile "Sergey Levine"

# 详细模式（会下载论文全文进行深度分析）
python tools/research/research_scout.py profile "Sergey Levine" --mode detailed

# 分析多位研究者
python tools/research/research_scout.py profile "Sergey Levine" "Pieter Abbeel"

# 同名消歧：通过机构提示
python tools/research/research_scout.py profile "Wei Zhang" --affiliation "MIT"

# 反向查找：通过已知论文找作者
python tools/research/research_scout.py profile "Name" --paper "2301.12597"

# 直接指定 Semantic Scholar 作者 ID
python tools/research/research_scout.py profile "Name" --author-id "1234567"

# 提供研究者主页（用于发现学生）
python tools/research/research_scout.py profile "Sergey Levine" --homepage "https://..."
```

### 递归发现学生

工具可以通过共著模式推断出师生关系，并递归分析发现的学生：

```bash
# 深度 1：分析 Sergey Levine 并发现其学生
python tools/research/research_scout.py profile "Sergey Levine" --depth 1

# 深度 2：进一步分析学生的学生（注意 API 调用量会指数增长）
python tools/research/research_scout.py profile "Sergey Levine" --depth 2
```

学生发现基于两个来源（自动合并去重）：

1. **主页提取**（优先）— 从 Semantic Scholar 主页字段或 LLM 推断的 URL 获取研究者主页，解析 HTML 提取学生名单。可通过 `--homepage` 手动提供 URL
2. **共著推断**（补充）— 基于以下信号打分：
   - 一作 + 导师末位的论文数（最强信号，权重 40%）
   - 合作时间集中在 3-6 年的 PhD 周期（25%）
   - 合著频率（20%）
   - 合作的时效性（15%）

### 批量分析

```bash
# 从文件读取姓名（每行一个）
python tools/research/research_scout.py profile --from-file names.txt
```

### 模型和后端选择

```bash
# 使用 Opus 模型（更深度的分析）
python tools/research/research_scout.py profile "Sergey Levine" --model opus

# 使用 Anthropic API 后端
python tools/research/research_scout.py profile "Sergey Levine" --api anthropic

# 忽略缓存
python tools/research/research_scout.py profile "Sergey Levine" --no-cache
```

### 分析流程

```
研究者姓名 (+ 可选：--affiliation, --paper, --author-id, --homepage)
    |
[1/6] 从 ArXiv 获取论文（最多 100 篇）
    |
[2/6] 从 Semantic Scholar 获取指标（h-index、引用数、所有论文及引用数）
    |--- 合并 S2 和 ArXiv 数据（S2 为主，ArXiv 补充 arxiv_id、pdf_url 等）
    |--- 每年最多保留 10 篇代表作（按奖项和引用数排序）
    |
[3/6] LLM 识别论文奖项（Best Paper / Spotlight / Oral 等）
    |
[4/6] 下载全文（仅 detailed 模式；HTML 优先，PDF 后备）
    |
[5/6] LLM 分析研究轨迹
    |--- 轨迹总结：为什么成为领域大佬/新星，关键转折点
    |--- 突破性工作（3-7 项）：做了什么、为什么之前做不出来、对领域的影响
    |--- 研究方向、方法论演进、领域影响评估
    |
[6/6] 计算评分
    |--- 加权：h-index 25% + 总引用 20% + 近5年引用 20% + 顶会比例 20% + 职业阶段 15%
    |--- 分层：领域领袖(≥75) / 学术新星(≥50) / 活跃研究者(≥30) / 早期研究者(<30)
```

消歧提示参数说明：
- `--affiliation`：机构名称，用于同名作者消歧（如 "MIT"、"Stanford"）
- `--paper`：已知论文（arXiv ID、DOI 或标题），通过论文反向查找作者
- `--author-id`：直接指定 Semantic Scholar 作者 ID，跳过搜索
- `--homepage`：研究者主页 URL，用于发现学生（优先于自动发现）

### 部署到 Hugo

```bash
# 分析后直接部署到 Hugo 站点
python tools/research/research_scout.py profile "Sergey Levine" --deploy
python tools/research/research_scout.py profile "Sergey Levine" --deploy --hugo-site /path/to/site
```

### 输出

结果保存在 `outputs/` 目录下（项目根目录）：
- `outputs/data/research-profiler/profiles/<name>.json`：完整的结构化数据
- `outputs/reports/research-profiler/<name>.md`：Markdown 格式的研究者报告
- `outputs/cache/research-profiler/`：API + LLM 响应缓存

如果在 Profiler 配置中设置了自定义 `output_dir`，则所有文件统一放在该目录下。

也可以通过独立的模块 CLI 使用：

```bash
python -m research analyze "Sergey Levine"               # 分析研究者
python -m research analyze "Sergey Levine" --api anthropic  # 选择后端（claude_cli/anthropic/openai）
python -m research show "Sergey Levine"                  # 查看已缓存的画像
python -m research list                                   # 列出所有已分析的研究者
python -m research config --init                          # 初始化 Profiler 配置
```

---

## 9. 引用图分析

对任意论文进行引用图分析：查看谁引用了它（前向引用）、它引用了谁（反向参考文献），以及 LLM 生成的影响力分析。

### 基本用法

```bash
# 用 arXiv ID 查询
python tools/research/research_scout.py citations 2301.12597

# 用 DOI 查询
python tools/research/research_scout.py citations 10.1038/s41586-023-06221-2
```

### 参数

```bash
# 显示前 20 篇引用/参考文献（默认 10）
python tools/research/research_scout.py citations 2301.12597 --top-n 20

# 使用 Anthropic API 进行影响力分析
python tools/research/research_scout.py citations 2301.12597 --api anthropic

# 忽略缓存
python tools/research/research_scout.py citations 2301.12597 --no-cache
```

### 输出内容

```
论文信息
├── 标题、年份、会议、引用数
│
├── 前向引用（按引用数降序）
│   # | 年份 | 引用数 | 标题 | 会议
│
├── 反向参考文献（按引用数降序）
│   # | 年份 | 引用数 | 标题 | 会议
│
└── LLM 影响力分析（当引用数 ≥ 5 时自动触发）
    ├── 被广泛引用的原因
    ├── 后续研究方向
    └── 开创的趋势
```

数据来源于 Semantic Scholar API，支持缓存（7 天 TTL）。

> **注意**：引用图分析也会自动集成到周报的 Stage 3 中——前 5 篇高分论文会自动附带引用影响分析。

---

## 10. 部署到网站

将已生成的周报部署到 Hugo 博客：

```bash
# 部署所有未部署的报告
python tools/research/research_scout.py deploy

# 强制重新部署所有报告
python tools/research/research_scout.py deploy --force
```

需要在 `config --init` 中配置好 Hugo 站点路径。

---

## 11. 参数调优

参数的优先级为：**命令行参数 > project.json > config.json > 硬编码默认值**。

### 全局默认值（config.json）

通过 `config --init` 或直接编辑 `~/.config/research_scout/config.json`：

```json
{
  "default_api": "claude_cli",
  "hugo_site": "tools/website",
  "default_lookback_days": 7,
  "default_max_results": 50,
  "default_top_papers_in_report": 5,
  "max_high_relevance": 20,
  "default_insight_top_n": 3
}
```

### 项目级覆盖（project.json）

某些项目论文量大，可以单独配置。编辑 `research/projects/<id>/project.json`，添加可选字段：

```json
{
  "id": "robot-manipulation",
  "title": "Robot Manipulation",
  "lookback_days": 14,
  "max_results": 100,
  "sources": ["arxiv", "biorxiv"],
  "biorxiv_categories": ["neuroscience"],
  "pubmed_journals": ["Nature Robotics"],
  ...
}
```

这样 `robot-manipulation` 项目默认搜索 14 天、最多 100 篇，而其他项目仍然使用全局默认。

### 命令行临时覆盖

```bash
python tools/research/research_scout.py report --project robot-manipulation \
    --lookback-days 30 --max-results 200
```

命令行参数优先级最高，不会影响配置文件。

### 研究者画像配置

Profiler 使用独立的配置文件 `~/.config/research/config.json`：

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

- `output_dir` 为空时使用默认的 `outputs/` 统一目录结构；设置后所有输出统一放在指定目录
- `semantic_scholar_api_key` 可选，免费匿名访问已有每秒 10 次请求限制

通过 `python -m research config --init` 初始化。

---

## 12. 工作流示例

### 日常工作流：每周一次

```bash
# 1. 对所有项目生成周报（自动包含引用影响分析）
python tools/research/research_scout.py report

# 2. 想要深入理解本周最重要的论文？加 --insight
python tools/research/research_scout.py report --insight

# 3. 查看生成的报告
# Markdown 报告在 outputs/reports/research-scout/ 目录下
# 格式为 <date>-research.md

# 4. 部署到博客
python tools/research/research_scout.py deploy
```

### 追踪新方向

```bash
# 1. 创建新项目
python tools/research/research_scout.py init diffusion-policy \
    --title "Diffusion Policy for Robotics" \
    --keywords "diffusion policy" "denoising diffusion" "robot learning" \
    --categories "cs.RO" "cs.LG" \
    --questions "扩散模型在机器人策略学习中的优势是什么？" \
                "如何加速扩散模型的推理速度以满足实时控制？"

# 2. 先搜索看看最近有多少相关论文
python tools/research/research_scout.py search --project diffusion-policy --lookback-days 30

# 3. 看着论文数量合适，生成完整报告
python tools/research/research_scout.py report --project diffusion-policy
```

### 会议论文集中阅读

```bash
# ICRA 2025 中和机器人操作相关的论文
python tools/research/research_scout.py report \
    --conference "ICRA 2025" \
    --project robot-manipulation \
    --api anthropic
```

### 了解一位研究者

```bash
# 1. 快速了解一位研究者
python tools/research/research_scout.py profile "Sergey Levine"

# 2. 想深入了解？用详细模式（会下载全文）
python tools/research/research_scout.py profile "Sergey Levine" --mode detailed

# 3. 看看他的学生都在做什么
python tools/research/research_scout.py profile "Sergey Levine" --depth 1

# 4. 同名消歧
python tools/research/research_scout.py profile "Wei Zhang" --affiliation "Stanford"

# 5. 分析完直接部署到博客
python tools/research/research_scout.py profile "Sergey Levine" --deploy
```

### 深入分析一篇论文的影响力

```bash
# 1. 看一篇论文的引用图
python tools/research/research_scout.py citations 2301.12597

# 2. 更多细节
python tools/research/research_scout.py citations 2301.12597 --top-n 20 --api anthropic
```

### 写论文前的深度调研

```bash
# 1. 搜索相关论文
python tools/research/research_scout.py ask "sim-to-real transfer for legged robots" --insight

# 报告会包含：
# - 标准的论文筛选和评估
# - 每篇高分论文的写作结构分析（别人怎么写的）
# - 发表策略分析（为什么能发表）
# - 核心知识提取（能学到什么）
# - OpenReview 审稿意见（reviewer 怎么看的）
# - 综合写作指南（你该怎么写）

# 2. 指定项目 + 更多论文
python tools/research/research_scout.py report \
    --project my-project --insight --insight-top-n 5

# 3. 会议论文的写作风格调研
python tools/research/research_scout.py report \
    --conference "ICLR 2025" --project my-project --insight
```

### 跨来源生物医学研究

```bash
# 1. 创建生物医学项目
python tools/research/research_scout.py init brain-computer \
    --title "Brain-Computer Interfaces" \
    --keywords "brain computer interface" "neural decoding" \
    --categories "q-bio.NC" "cs.HC"

# 2. 编辑 project.json，添加多来源配置
# "sources": ["arxiv", "biorxiv", "pubmed"],
# "biorxiv_categories": ["neuroscience"],
# "pubmed_journals": ["Nature Neuroscience", "Neuron"]

# 3. 生成跨来源报告
python tools/research/research_scout.py report --project brain-computer
```

---

## 13. 文件结构说明

```
research/
├── research_scout.py          # 主程序（统一 CLI 入口）
├── CLAUDE.md                  # 开发文档
├── TUTORIAL.md                # 本教程
├── requirements.txt           # Python 依赖
│
├── # ── 论文发现 ──
├── projects/                  # 项目定义（git 跟踪）
│   └── <project-id>/
│       ├── project.json       # 项目配置（关键词、分类、来源、开放问题）
│       └── overview.md        # 项目概述（中文，LLM 会读取）
│
├── # ── 研究者画像（模块包）──
├── __init__.py, __main__.py, cli.py
├── analysis.py                # 主编排器：BFS 递归分析
├── models.py                  # 数据类：Paper, ResearcherProfile, ...
├── scoring.py                 # 加权评分 + 分层
├── student_discovery.py       # 师生关系推断
├── homepage_discovery.py      # 主页提取 + 学生发现
├── llm.py                     # 多后端 LLM 封装
├── prompts.py                 # LLM 提示词模板
├── cache.py                   # 重导出 shim → common.cache.DiskCache
├── config.py                  # Profiler 配置
├── output.py                  # JSON 持久化 + Markdown 报告渲染 + Hugo 部署
├── apis/
│   ├── arxiv_client.py        # ArXiv 作者搜索 + 全文下载
│   ├── semantic_scholar.py    # S2 指标、论文数据、引用图、共著分析
│   ├── openreview_client.py   # OpenReview 审稿意见获取
│   └── rate_limiter.py        # 令牌桶限速器

outputs/                       # 所有生成文件（项目根目录下，已 gitignore）
├── reports/research-scout/    # Research Scout 周报
│   ├── <date>-research.json
│   └── <date>-research.md
├── cache/research-scout/      # Research Scout 缓存
│   ├── papers/                # 搜索结果缓存
│   ├── eval/                  # LLM 评估缓存（Stage 1 + Stage 2）
│   └── insight/               # Insight 分析缓存（Stage 4 + Stage 5）
├── logs/research-scout/       # 轮转日志 (5MB×3)
├── data/research-profiler/    # Profiler 结构化数据
│   └── profiles/              # JSON 研究者数据
├── reports/research-profiler/ # Profiler Markdown 报告
└── cache/research-profiler/   # Profiler 缓存（api/、llm/ 子目录）
```

### 周报内容结构

生成的 Markdown 周报包含以下部分：

1. **高相关性论文摘要表** — 得分、标题、类型、一句话总结
2. **详细分析** — 每篇高相关论文的：
   - 评分（相关性/新颖性/启发性）
   - 两句话摘要
   - 3 个亮点，每个包含：关键点、设计动机、对我们的价值、行动建议
   - 建议
3. **引用影响分析**（前 5 篇高分论文自动附带）— 每篇包含：
   - 被引次数和参考文献数
   - 高引后续工作列表（年份、引用数、标题、会议）
   - LLM 影响力分析：为什么被广泛引用、后续方向、开创的趋势
4. **新方向建议** — 基于高分论文的研究方向建议（中文）
5. **论文深度洞察**（仅 `--insight`）— 每篇分析论文的写作结构、发表策略、核心知识、审稿意见
6. **研究写作指南**（仅 `--insight`）— 跨论文综合：领域写作规范、审稿重点、方法论要点、代码参考
7. **文献阅读记录** — 折叠显示的低相关性论文列表（一行一篇：标题、类型、作者、会议、动机、创新点）

---

## 14. 常见问题

### Q: 搜不到论文怎么办？

- 检查关键词是否太窄，尝试更通用的词
- 增大 `--lookback-days`（比如 30 天）
- 检查 arXiv 分类是否正确（`cs.RO` 而非 `csRO`）
- 用 `--no-cache` 排除缓存问题
- 尝试多来源搜索：`--source arxiv biorxiv pubmed`

### Q: 评估结果不理想？

- 编辑 `overview.md`，添加更多研究背景和当前进展。Stage 2 会读取这些内容来做更精准的评估
- 修改 `project.json` 中的 `open_questions`，让 LLM 更清楚你关心什么
- 尝试不同的 LLM 后端（`--api anthropic` vs `--api claude_cli`）
- 尝试英文输出：`--language en`

### Q: LLM 调用超时？

- 默认超时 600 秒（10 分钟），可以用 `--timeout 900` 增加
- 减少 `--max-results` 以减少论文数量
- 使用 `--api anthropic` 通常比 `claude_cli` 更稳定

### Q: 如何暂停/恢复项目？

编辑 `research/projects/<id>/project.json`，将 `status` 从 `"active"` 改为 `"paused"`。暂停的项目不会被全局搜索/报告命令处理，但可以通过 `--project` 显式指定。

### Q: 缓存机制是什么？

- **搜索缓存**（`outputs/cache/research-scout/papers/`）：同一天、同一项目的搜索结果只调用一次 API
- **Stage 1 缓存**（`outputs/cache/research-scout/eval/`）：基于项目上下文 + 论文 ID + 摘要前 200 字的哈希
- **Stage 2 缓存**（`outputs/cache/research-scout/eval/`）：基于项目上下文 + 论文 ID + 摘要前 500 字的哈希
- **Stage 3 引用缓存**（Semantic Scholar 引用图）：周报 Stage 3 的前向引用/反向参考文献也会缓存
- **Semantic Scholar 缓存**（Profiler: `outputs/cache/research-profiler/api/`）：API 结果缓存 7 天 TTL
- **LLM 缓存**（Profiler: `outputs/cache/research-profiler/llm/`）：基于后端 + 模型 + 提示词的 SHA-256 哈希
- 用 `--no-cache` 可以跳过所有缓存（包括 Stage 3 引用缓存）

### Q: 研究者画像的 profile 和 citations 子命令有什么区别？

- `profile` 分析一位**研究者**：学术轨迹、评分、师生关系
- `citations` 分析一篇**论文**：引用图、影响力

### Q: --insight 分析了哪些论文？

默认分析 composite_score 最高的 3 篇论文。可以通过 `--insight-top-n` 调整，但不会超过报告中展示的论文数（默认 5）。

### Q: OpenReview 匹配不到怎么办？

OpenReview 匹配基于 fuzzy title matching（相似度阈值 0.85）。以下情况可能匹配失败：
- 论文不在 OpenReview 平台上的会议（如 CVPR、AAAI）
- 论文还未提交到会议（纯 arXiv 预印本）
- arXiv 标题和投稿标题差异较大

匹配失败不会影响 Stage 4 的洞察分析，只是没有审稿意见部分。

### Q: --insight 太慢了？

全文下载 + LLM 分析每篇论文需要 1-3 分钟。可以：
- 减少分析数量：`--insight-top-n 1`
- 使用更快的 API：`--api anthropic`（通常比 claude_cli 快）
- 全文和 insight 分析结果会被缓存，第二次运行同一项目会很快

### Q: 需要安装 openreview-py 吗？

`openreview-py` 是可选依赖。如果未安装，Stage 5（审稿意见）会自动跳过，Stage 4（洞察分析）和写作指南仍然正常工作。

安装：`pip install openreview-py`

### Q: 如何获取 Semantic Scholar API Key？

访问 https://www.semanticscholar.org/product/api 申请。免费版已有每秒 10 次的请求限制，对于个人使用通常够用。API Key 可以在 Profiler 的 `config --init` 中配置，也可以不配置（使用匿名访问）。
