# Claude Code Skills 完全使用指南

> 最后更新: 2026-04-21

---

## 目录

1. [概述](#概述)
2. [安装位置与加载规则](#安装位置与加载规则)
3. [日常开发 (每天都会用)](#日常开发)
4. [Python 专用](#python-专用)
5. [测试与质量保障](#测试与质量保障)
6. [规划与架构](#规划与架构)
7. [文档与内容](#文档与内容)
8. [Agent 与自动化](#agent-与自动化)
9. [语言专用 (非 Python)](#语言专用)
10. [ECC 系统管理](#ecc-系统管理)
11. [Slash 命令速查表](#slash-命令速查表)
12. [常见问题](#常见问题)

---

## 概述

当前共有三层 skill：

| 层级 | 位置 | 数量 | 作用范围 |
|------|------|------|----------|
| **Gadget 项目级** | `gadget/.claude/skills/`（已迁至 sibling `ai-companion` repo，gadget 内不再有 skills 目录） | 13 | 仅 gadget 项目 |
| **全局** | `~/.claude/skills/` | 28 | 所有项目 |
| **ECC 内置** | `everything-claude-code/skills/` | ~97 | 所有项目 (通过 ECC 框架) |

> 全局和 ECC 有大量重叠（如 `python-patterns` 同时存在于两处），Claude 会自动去重。

---

## 安装位置与加载规则

```
~/.claude/skills/          ← 全局：每个项目每次会话都加载
项目/.claude/skills/       ← 项目级：只在该项目下加载
everything-claude-code/skills/  ← ECC 框架：注册为 everything-claude-code:* 前缀
```

**加载顺序：** 项目级 > 全局 > ECC 内置

**使用方式：**
- **自动触发** — 大多数 skill 在对话匹配时自动激活
- **手动触发** — 用 `/skill-name` 命令显式调用，如 `/plan`、`/tdd`、`/verify`

---

## 日常开发

这些 skill 覆盖日常编码的核心流程。

### coding-standards — 编码标准

**来源：** 全局
**触发：** 编写或审查代码时自动应用

提供 TypeScript/JavaScript/React/Node.js 的通用编码标准和最佳实践。涵盖命名约定、文件组织、错误处理、类型安全等。

---

### api-design — REST API 设计

**来源：** 全局
**触发：** 设计或实现 REST API 时

提供 API 设计模式：
- 资源命名规范
- HTTP 状态码使用
- 分页、过滤、排序
- 错误响应格式
- 版本控制
- 速率限制

**示例提示词：**
```
设计一个用户管理的 REST API
帮我规范这个 API 的错误响应格式
```

---

### changelog-generator — 变更日志生成器

**来源：** Gadget 项目级
**触发：** 准备发布说明、生成 changelog
**命令：** 在对话中描述需求即可

将 git commit 历史转化为面向用户的 changelog：
1. 扫描 git 历史
2. 分类：新功能 / 改进 / Bug 修复 / 破坏性变更 / 安全更新
3. 将技术 commit 翻译为用户友好的语言
4. 过滤内部噪音

**前置依赖：** 必须在 git 仓库中

**示例提示词：**
```
从上次发布以来的 commit 生成 changelog
为 v2.5.0 生成发布说明
```

---

### mcp-builder — MCP 服务器构建指南

**来源：** Gadget 项目级
**触发：** 构建 MCP 服务器时

四阶段工作流（研究 → 实现 → 审查 → 评估），支持 Python (FastMCP) 和 TypeScript (MCP SDK)。（gadget 项目已移除 MCP 集成，不再有 `mcp_server.py`。）

**示例提示词：**
```
帮我为 Stripe API 构建一个 MCP 服务器
改进现有 MCP server 的工具定义
```

---

### mcp-server-patterns — MCP 服务器模式

**来源：** 全局
**触发：** 编写 MCP 服务器代码时自动应用

与 `mcp-builder` 互补。提供 Node/TypeScript SDK 的具体模式：tools、resources、prompts、Zod 验证、stdio vs Streamable HTTP。

---

### security-review — 安全审查

**来源：** ECC 内置
**命令：** 描述安全相关需求即可

处理认证、用户输入、密钥管理、API 端点、支付等敏感功能时自动激活。提供安全检查清单和模式。

---

### security-scan — 安全扫描

**来源：** ECC 内置

扫描 `.claude/` 目录的安全漏洞：检查 CLAUDE.md、settings.json、MCP 服务器、hooks、agent 定义中的注入风险。

**示例提示词：**
```
扫描我的 Claude Code 配置是否有安全问题
```

---

### search-first — 先搜索再写代码

**来源：** ECC 内置
**触发：** 开始新功能实现前

强制"先搜索现有工具/库/模式"的工作流，避免重复造轮子。

---

### codebase-onboarding — 代码库上手

**来源：** ECC 内置
**触发：** 加入新项目、首次在某个 repo 中使用 Claude Code

分析陌生代码库，生成结构化的上手指南：架构图、关键入口、约定规范、CLAUDE.md 模板。

**示例提示词：**
```
帮我分析这个项目的架构
生成这个代码库的上手指南
```

---

### architecture-decision-records — 架构决策记录

**来源：** ECC 内置
**触发：** 做出架构决策时自动检测

将会话中的架构决策捕获为结构化 ADR (Architecture Decision Record)：上下文、考虑的替代方案、选择理由。

---

## Python 专用

gadget 项目独享的 Python 相关 skill。

### python-patterns — Python 最佳实践

**来源：** Gadget 项目级
**触发：** 编写 Python 代码时自动应用

Pythonic 惯用法、PEP 8 标准、类型提示、构建健壮应用的最佳实践。

---

### python-testing — Python 测试

**来源：** Gadget 项目级
**触发：** 编写 Python 测试时自动应用

pytest 测试策略：TDD 方法论、fixtures、mocking、参数化、覆盖率要求。

---

### optimize — Python 代码优化

**来源：** Gadget 项目级
**触发词：** "优化"、"重构"、"简化"、"改进"、"清理"、"更 Pythonic"
**命令：** `/optimize`

专门优化 Python 代码：性能提升、可读性改进、安全加固、Pythonic 重写。

**示例提示词：**
```
优化这段代码
这段代码感觉很 hacky，有更好的写法吗
帮我让这个函数更 Pythonic
```

> **注意：** 如果只想理解代码不想修改，用 `/summarize` 而不是 `/optimize`。

---

### summarize — 代码解读

**来源：** Gadget 项目级
**触发词：** "这段代码做什么"、"解释"、"走读"、"帮我理解"
**命令：** `/summarize`

解释和总结现有代码，帮助快速理解。

**示例提示词：**
```
这个模块是做什么的
走读一下 daily_summary.py 的主流程
我刚接手这段代码，帮我理解一下
```

---

### nature-benchmark — Nature Benchmark 论文写作引擎

**来源：** Gadget 项目级
**触发：** 撰写 Nature 系列 benchmark 论文、设计评估框架、讨论方法比较论文策略

基于 11 篇 Nature Methods / Nature Communications 高引 benchmark 论文蒸馏的写作系统。涵盖结构模型（三支柱可信度架构、权衡核心叙事）、决策启发式、表达 DNA、Reviewer 评审心理分析。

---

### NIPS-2025-paper — NeurIPS D&B Track 写作引擎

**来源：** Gadget 项目级
**触发：** 撰写 NeurIPS Dataset & Benchmarks Track 论文、准备 rebuttal

基于 NeurIPS 2025 全部 7 篇 Oral + 56 篇 Spotlight 论文 + 61 条 official reviews 的蒸馏。包含心智模型、章节级写作指南、Reviewer 评审心理实证分析和 AC 决策权重。

---

### pytorch-patterns — PyTorch 模式

**来源：** ECC 内置
**触发：** 编写 PyTorch 代码时

深度学习模式：训练管道、模型架构、数据加载、分布式训练的最佳实践。

---

### django-patterns / django-tdd / django-verification — Django 全套

**来源：** 全局
**触发：** Django 项目中自动应用

| Skill | 用途 |
|-------|------|
| django-patterns | 架构模式、DRF、ORM、缓存、中间件 |
| django-tdd | pytest-django 测试、factory_boy、mocking |
| django-verification | 迁移检查、lint、测试覆盖率、安全扫描 |

---

## 测试与质量保障

### tdd-workflow — 测试驱动开发

**来源：** Gadget 项目级
**命令：** `/tdd`
**触发：** 写新功能、修 bug、重构时

强制 TDD 工作流：
1. **RED** — 先写测试，运行必须失败
2. **GREEN** — 写最小实现让测试通过
3. **IMPROVE** — 重构
4. 确保覆盖率 ≥ 80%

包含单元测试、集成测试、E2E 测试。

**示例提示词：**
```
/tdd
用 TDD 方式给 research_scout 添加 bioRxiv 源
```

---

### e2e-testing — E2E 测试模式

**来源：** 全局
**触发：** 编写 Playwright E2E 测试时

Playwright 测试模式：Page Object Model、配置、CI/CD 集成、artifact 管理、flaky test 处理。

---

### webapp-testing — Web 应用测试

**来源：** Gadget 项目级
**触发：** 测试本地 Web 应用时

使用 Playwright 测试本地 Web 应用：
- `scripts/with_server.py` 管理服务器生命周期
- 侦查后行动模式
- 截图捕获和日志查看

**前置依赖：** Playwright, Python

**示例提示词：**
```
测试我本地应用 (端口 5173) 的登录流程
截取注册页面的截图
```

---

### ai-regression-testing — AI 回归测试

**来源：** 全局
**触发：** AI 辅助开发后的质量验证

解决"同一模型写代码又审查代码"的盲区问题：沙盒 API 测试、自动化 bug 检查工作流。

---

### verification-loop — 验证循环

**来源：** 全局
**命令：** `/verify`

在提交代码或发 PR 前执行的综合验证：构建、lint、测试、覆盖率、安全扫描。

---

### plankton-code-quality — 写时质量检查

**来源：** 全局
**触发：** 通过 hooks 在每次文件编辑后自动触发

自动格式化、lint、Claude 驱动的修复。在你写代码的同时实时保证质量。

---

### eval-harness — 评估框架

**来源：** 全局
**命令：** `/eval`

正式的评估框架，实现 eval-driven development (EDD)。用于衡量 Claude Code 会话的质量。

---

### agent-eval — Agent 对比评估

**来源：** ECC 内置

对比不同编码 agent (Claude Code, Aider, Codex 等) 在自定义任务上的表现：通过率、成本、时间、一致性。

---

## 规划与架构

### ccplan — 需求工程与规划

**来源：** 全局
**命令：** `/ccplan`
**触发词：** "计划"、"设计"、"架构"、"需求分析"、"方案设计"、"头脑风暴"

螺旋式规划流程（非线性）：
1. 假设 → 挑战 → 发散 → 收敛
2. 可行性探测
3. 对抗性验证
4. 约束语言 (ECL) 持久化决策

**适合场景：** 有歧义、多利益方、非简单技术决策的功能需求。

**不适合：** 单文件修复、已知 bug、用户说"直接做"。

**示例提示词：**
```
/ccplan
帮我规划 gadget 的同步功能重构
设计一个新的 research profiler 模块
```

---

### blueprint — 多会话工程蓝图

**来源：** ECC 内置
**触发词：** "蓝图"、"路线图"

将一句话目标转化为分步骤的工程构建计划。每个步骤有独立的上下文简报，让新 agent 可以冷启动执行。包含对抗性审查门、依赖图、并行步骤检测。

**适合场景：** 需要多个 PR、多个会话的复杂任务。

**示例提示词：**
```
为 gadget 添加多用户支持，帮我做一个蓝图
```

---

### prompt-optimizer — 提示词优化

**来源：** ECC 内置
**命令：** `/prompt-optimize`
**触发词：** "优化 prompt"、"改进 prompt"

分析你的 prompt 草稿，匹配 ECC 组件，输出优化后的 prompt。仅给建议，不执行任务。

> **注意：** "优化代码" 触发 `/optimize`，"优化 prompt" 触发这个。

---

### strategic-compact — 策略性上下文压缩

**来源：** 全局

建议在逻辑间隔点手动压缩上下文，而不是等自动压缩。在任务阶段转换时保留关键上下文。

---

## 文档与内容

### document-skills — 办公文档处理套件

**来源：** Gadget 项目级

包含 4 个子技能：

| 子技能 | 格式 | 核心功能 |
|--------|------|----------|
| **docx** | Word | 创建/编辑/修订追踪/批注 |
| **pdf** | PDF | 合并/拆分/提取/填表/OCR |
| **pptx** | PowerPoint | 创建/编辑/18种配色/模板 |
| **xlsx** | Excel | 数据分析/公式/格式化/图表 |

**前置依赖：**
```bash
# PDF
pip install pypdf pdfplumber reportlab

# Excel
pip install pandas openpyxl

# Word
pip install defusedxml
# + pandoc, LibreOffice

# PPTX
# + markitdown, pptxgenjs, playwright, LibreOffice
```

**示例提示词：**
```
提取这份 PDF 的表格数据
合并这三个 PDF
创建一份 Excel 报告
编辑这个 Word 文档并添加修订标记
```

---

### content-research-writer — 内容研究与写作

**来源：** Gadget 项目级
**触发：** 写博客、文章、教程、Newsletter 时

写作伙伴：协作大纲 → 研究引用 → 改进开头 → 逐章反馈 → 保持作者风格 → 最终润色。

**示例提示词：**
```
帮我写一篇关于 MCP 服务器设计的技术文章
研究 AI 辅助编程的最新趋势并添加引用
```

---

### documentation-lookup — 文档查询

**来源：** ECC 内置
**命令：** `/docs`
**触发：** 提到框架名、问 API 用法时

通过 Context7 MCP 获取最新的库/框架文档，而非依赖训练数据。

**示例提示词：**
```
/docs fastapi
FastAPI 的 WebSocket 怎么用
Playwright 的 Page.goto 有哪些参数
```

---

### deep-research — 深度研究

**来源：** ECC 内置

使用 firecrawl 和 exa MCP 进行多源深度研究。搜索网络、综合发现、生成带引用的报告。

**示例提示词：**
```
深入研究 Python 3.13 的新特性
调研 MCP 生态系统的现状
```

---

### exa-search — Exa 神经搜索

**来源：** ECC 内置

通过 Exa MCP 进行 AI 驱动的网络搜索、代码搜索、公司信息查找。

---

## Agent 与自动化

### continuous-learning / continuous-learning-v2 — 持续学习系统

**来源：** 全局
**命令：** `/learn`、`/learn-eval`

从 Claude Code 会话中自动提取可复用模式，保存为 learned skills。

**v2 新增：**
- 基于 instinct 的学习系统
- 置信度评分
- 项目级隔离 (防止跨项目污染)

**相关命令：**
| 命令 | 用途 |
|------|------|
| `/learn` | 从当前会话提取模式 |
| `/learn-eval` | 提取 + 自评质量 + 选择保存位置 |
| `/instinct-status` | 查看已学习的 instinct |
| `/instinct-export` | 导出 instinct |
| `/instinct-import` | 导入 instinct |
| `/promote` | 将项目级 instinct 提升为全局 |
| `/projects` | 列出已知项目及其 instinct 统计 |
| `/evolve` | 分析 instinct 并建议升级为 skill/command/agent |

---

### autonomous-loops — 自主循环

**来源：** ECC 内置

自主 agent 循环的模式和架构：从简单的顺序管道到 RFC 驱动的多 agent DAG 系统。

**相关命令：**
| 命令 | 用途 |
|------|------|
| `/loop` | 在间隔时间运行 prompt（如 `/loop 5m /verify`） |
| `/loop-start` | 启动循环 |
| `/loop-status` | 查看循环状态 |

---

### devfleet — 多 Agent 编排

**来源：** ECC 内置
**命令：** `/devfleet`

通过 Claude DevFleet 编排并行 Agent：
- 从自然语言规划项目
- 在隔离 worktree 中分派 agent
- 监控进度、读取结构化报告

**示例提示词：**
```
/devfleet
用 3 个 agent 并行重构 summarize、research 和 benchmark 模块
```

---

### dmux-workflows — dmux 多 Agent 工作流

**来源：** ECC 内置

使用 dmux (tmux pane manager) 进行多 agent 并行工作流编排。

---

### team-builder — Agent 团队组建

**来源：** ECC 内置

交互式 agent 选择器，组建并行团队执行任务。

---

### data-scraper-agent — 数据采集 Agent

**来源：** ECC 内置

构建全自动的 AI 数据采集 agent：
- 支持任何公开源 (招聘、价格、新闻、GitHub、体育等)
- 定时抓取 (GitHub Actions，免费)
- 用免费 LLM (Gemini Flash) 丰富数据
- 存储到 Notion/Sheets/Supabase

---

### cost-aware-llm-pipeline — LLM 成本优化

**来源：** ECC 内置

LLM API 调用的成本优化模式：按任务复杂度路由模型、预算追踪、重试逻辑、prompt 缓存。

---

### content-hash-cache-pattern — 内容哈希缓存

**来源：** ECC 内置

使用 SHA-256 内容哈希缓存昂贵的文件处理结果。路径无关、自动失效。gadget 的 `common/cache.py` 已使用此模式。

---

## 语言专用

这些 skill 在你开启对应语言的项目时自动生效。

### C++

| Skill | 用途 | 命令 |
|-------|------|------|
| cpp-coding-standards | C++ Core Guidelines 编码标准 | — |
| cpp-testing | GoogleTest/CTest 测试 | `/cpp-test` |
| cpp-build | 构建错误修复 | `/cpp-build` |
| cpp-review | 代码审查 (内存安全、并发、性能) | `/cpp-review` |

### Rust

| Skill | 用途 | 命令 |
|-------|------|------|
| rust-patterns | 所有权、错误处理、trait、并发 | — |
| rust-testing | 单元/集成/属性测试 | `/rust-test` |
| rust-build | cargo 构建错误修复 | `/rust-build` |
| rust-review | 代码审查 (所有权、生命周期、unsafe) | `/rust-review` |

### Java / Spring Boot

| Skill | 用途 | 命令 |
|-------|------|------|
| java-coding-standards | 命名、不可变、Optional、异常 | — |
| springboot-patterns | 架构、REST、数据访问、缓存 | — |
| springboot-tdd | JUnit 5、Mockito、Testcontainers | — |
| springboot-verification | 构建、静态分析、覆盖率、安全 | — |
| jpa-patterns | 实体设计、关系、查询优化 | — |

### Swift / iOS

| Skill | 用途 |
|-------|------|
| swiftui-patterns | SwiftUI 架构、@Observable、导航 |
| swift-concurrency-6-2 | Swift 6.2 并发模型 |
| swift-actor-persistence | Actor 线程安全持久化 |
| swift-protocol-di-testing | 基于协议的依赖注入 |
| foundation-models-on-device | Apple FoundationModels 框架 (iOS 26+) |
| liquid-glass-design | iOS 26 Liquid Glass 设计系统 |

### Go

| Skill | 用途 | 命令 |
|-------|------|------|
| golang-patterns | 惯用 Go 模式 | — |
| golang-testing | 表驱动测试、benchmark、fuzzing | `/go-test` |
| go-build | 构建错误修复 | `/go-build` |
| go-review | 代码审查 | `/go-review` |

### Kotlin / Android

| Skill | 用途 | 命令 |
|-------|------|------|
| kotlin-patterns | 惯用 Kotlin、协程、DSL | — |
| kotlin-testing | Kotest、MockK、Kover | `/kotlin-test` |
| kotlin-coroutines-flows | 协程和 Flow | — |
| kotlin-ktor-patterns | Ktor 服务器 | — |
| kotlin-exposed-patterns | Exposed ORM | — |
| compose-multiplatform-patterns | Compose UI | — |
| android-clean-architecture | Clean Architecture | — |
| kotlin-build | Gradle 构建修复 | `/kotlin-build` |
| kotlin-review | 代码审查 | `/kotlin-review` |

### PHP / Laravel

| Skill | 用途 |
|-------|------|
| laravel-patterns | 架构、Eloquent、队列、事件 |
| laravel-tdd | PHPUnit/Pest 测试 |
| laravel-verification | 验证循环 |
| laravel-security | 安全最佳实践 |

### Perl

| Skill | 用途 |
|-------|------|
| perl-patterns | 现代 Perl 5.36+ 惯用法 |
| perl-testing | Test2::V0、prove、覆盖率 |
| perl-security | taint mode、SQL 注入防护 |

### 前端 / Node.js

| Skill | 用途 |
|-------|------|
| frontend-patterns | React、Next.js、状态管理 |
| backend-patterns | Node.js、Express API |
| nextjs-turbopack | Next.js 16+ Turbopack |
| nuxt4-patterns | Nuxt 4 SSR |
| bun-runtime | Bun 运行时 |

### 数据库

| Skill | 用途 |
|-------|------|
| postgres-patterns | PostgreSQL 查询优化、索引、安全 |
| database-migrations | 迁移最佳实践、零停机部署 |
| clickhouse-io | ClickHouse 分析型数据库 |

### DevOps

| Skill | 用途 |
|-------|------|
| docker-patterns | Docker/Compose 本地开发、安全 |
| deployment-patterns | CI/CD、容器化、健康检查、回滚 |

### Flutter

| Skill | 用途 |
|-------|------|
| flutter-dart-code-review | Widget、状态管理、性能、无障碍 |

---

## ECC 系统管理

### configure-ecc — ECC 安装器

**命令：** `/configure-ecc`

交互式安装/配置 Everything Claude Code：选择要安装的 skill 和 rules，验证路径。

---

### skill-stocktake — Skill 审计

**命令：** `/skill-stocktake`

审计已安装的 skill 和 command 的质量。支持快速扫描 (仅变更的 skill) 和完整审计模式。

---

### context-budget — 上下文预算分析

**命令：** `/context-budget`

分析上下文窗口的 token 消耗：agent、skill、MCP 服务器、rules 各占多少。找出优化机会。

**示例提示词：**
```
/context-budget
分析当前上下文窗口的使用情况
```

---

### rules-distill — 规则提炼

**命令：** `/rules-distill`

从已安装的 skill 中提取跨切关注点，精炼为 rules 文件。

---

### skill-create — Skill 创建

**命令：** `/skill-create`

分析本地 git 历史，提取编码模式，生成 SKILL.md 文件。

---

### nanoclaw-repl — NanoClaw REPL

**命令：** `/claw`

ECC 的持久化、零依赖 REPL，支持模型路由、skill 热加载、分支、压缩、导出。

---

### session 管理

| 命令 | 用途 |
|------|------|
| `/save-session` | 保存当前会话状态 |
| `/resume-session` | 恢复最近的会话 |
| `/sessions` | 管理会话历史和别名 |

---

## Slash 命令速查表

### 最常用

| 命令 | 用途 | 何时用 |
|------|------|--------|
| `/plan` | 制定实现计划 | 开始复杂任务前 |
| `/tdd` | 测试驱动开发 | 写新功能、修 bug |
| `/verify` | 全面验证 | 提交前 |
| `/optimize` | 优化 Python 代码 | 有代码想改进时 |
| `/summarize` | 解读代码 | 想理解代码时 |
| `/docs` | 查文档 | 查框架/库 API 时 |
| `/context-budget` | 分析上下文 | 感觉 token 紧张时 |

### 规划类

| 命令 | 用途 |
|------|------|
| `/ccplan` | 螺旋式需求工程 |
| `/plan` | 线性实现计划 |
| `/blueprint` | 多会话蓝图 |
| `/prompt-optimize` | 优化 prompt |

### 测试类

| 命令 | 用途 |
|------|------|
| `/tdd` | 测试驱动开发 |
| `/e2e` | E2E 测试 |
| `/verify` | 综合验证 |
| `/python-review` | Python 代码审查 |
| `/code-review` | 通用代码审查 |

### 学习类

| 命令 | 用途 |
|------|------|
| `/learn` | 提取会话中的模式 |
| `/learn-eval` | 提取 + 质量评估 |
| `/instinct-status` | 查看已学习的 instinct |
| `/evolve` | 升级 instinct |

### Agent 编排类

| 命令 | 用途 |
|------|------|
| `/devfleet` | 多 agent 并行 |
| `/loop 5m /verify` | 循环执行命令 |
| `/orchestrate` | 编排指导 |
| `/aside` | 快速回答侧问题 |

### 系统类

| 命令 | 用途 |
|------|------|
| `/context-budget` | 分析 token 消耗 |
| `/configure-ecc` | 配置 ECC |
| `/skill-stocktake` | 审计 skill |
| `/save-session` | 保存会话 |
| `/resume-session` | 恢复会话 |

---

## 常见问题

### Q: Skill 太多了，怎么知道该用哪个？

**A:** 大部分会自动触发，你不需要记住。常用的只有几个：
- 开始任务 → `/plan` 或 `/ccplan`
- 写代码 → 自动加载语言 skill
- 要测试 → `/tdd`
- 要提交 → `/verify`
- 查文档 → `/docs`

### Q: 全局 skill 和 ECC skill 有什么区别？

**A:** 功能相同，只是注册方式不同。ECC skill 带 `everything-claude-code:` 前缀（如 `everything-claude-code:python-patterns`），全局 skill 不带前缀（如 `python-patterns`）。两者重叠时 Claude 自动处理。

### Q: 如何减少上下文 token 消耗？

**A:** 运行 `/context-budget` 查看详细分析。一般建议：
1. 将不常用的全局 skill 移到项目级
2. 删除完全不用的 skill
3. 在 ECC source 目录删除不需要的 skill

### Q: 怎么安装新 skill？

**A:** 三种方式：
```bash
# 1. 全局安装
cp -r new-skill ~/.claude/skills/

# 2. 项目级安装
cp -r new-skill 项目目录/.claude/skills/

# 3. 通过 ECC 安装
/configure-ecc
```

### Q: 怎么卸载 skill？

**A:**
```bash
rm -rf ~/.claude/skills/skill-name              # 全局
rm -rf 项目目录/.claude/skills/skill-name       # 项目级
rm -rf everything-claude-code/skills/skill-name  # ECC
```

### Q: langsmith-fetch 怎么配置？

**A:**
```bash
pip install langsmith-fetch
export LANGSMITH_API_KEY=your_key
export LANGSMITH_PROJECT=your_project
```
然后在对话中说"调试我的 agent"或"显示最近的 trace"。

### Q: 被删除的 skill 能恢复吗？

**A:** 可以。
- awesome-claude-skills: `git clone https://github.com/ComposioHQ/awesome-claude-skills`
- ECC skill: 从 `everything-claude-code` 仓库的 git 历史恢复，或从 GitHub 重新下载
