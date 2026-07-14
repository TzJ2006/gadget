# Repo Audit Report

**Project:** gadget
**Date:** 2026-04-21
**Audited by:** repo-audit skill
**Scope:** 75/75 Python source files analyzed (100%)

---

## Executive Summary

gadget 是一个结构清晰、依赖管理良好的 Python 工具集。无循环依赖，无安全隐患（secrets/hardcoded keys），代码整洁度高。主要问题集中在：项目结构命名歧义（`test/` vs `tests/`）、`pyproject.toml` 包声明不完整、以及部分大函数需要拆分。整体健康度评级：**良好**。

## Project Understanding

### Overview
Python 3.10+ 独立脚本工具集，包含 AI 对话摘要（summarize）、学术论文发现（research）、硬件性能测试（test/benchmark）、Hugo 博客管理（website），以及 MCP Server 统一暴露所有功能。

### Tech Stack
- 语言: Python 3.10+
- 框架: FastMCP (MCP Server), Hugo (website)
- LLM: anthropic SDK, openai SDK, Claude CLI, Ollama (翻译)
- 计算: PyTorch, NumPy, Pandas, Plotly
- 部署: GitHub Pages, rclone (数据同步)

### Architecture
- `common/` — 共享基础设施包（pip 安装），提供 IO、缓存、LLM 调用、翻译、路径管理
- 5 个独立 CLI 入口: sync.py, mcp_server.py, summarize/cli.py, research/research_scout.py, research/cli.py
- `mcp_server.py` 是唯一跨模块聚合器，通过 sys.path hack 导入所有子系统
- 无循环依赖，clean 的分层架构（5 tier）

---

## Findings

### P1: 项目结构合理性

| # | Severity | Location | Finding | Suggestion | Confidence | Status |
|---|----------|----------|---------|------------|------------|--------|
| F-001 | Medium | `test/` vs `tests/` | `test/` 是 benchmark 工具，`tests/` 是单元测试，命名极易混淆 | 删除 `tests/`，重命名 `test/` → `benchmark/`，更新所有引用 | 0.85 | confirmed |
| F-002 | Medium | `skills/` | `nature-benchmark-skill/`, `repo-audit/`, `repo-tidy/` 未被 git 跟踪，`skills-lock.json` 和 `.agents/` 也未跟踪 | 跟踪 skill 源码，将 `.agents/` 和 `skills-lock.json` 加入 `.gitignore` | 0.90 | confirmed |
| F-003 | Medium | `common/` | 共享工具包缺少 CLAUDE.md 或 README，是唯一没有文档的核心模块 | 添加 `common/CLAUDE.md` 文档化公共 API | 0.95 | confirmed |
| F-004 | High | `pyproject.toml:20` | `packages` 字段缺少 `research`，导致 `pip install -e .` 不安装该包，`mcp_server.py` 用 `sys.path.insert` 绕过 | 添加 `research` 到 packages 列表 | 0.95 | confirmed |
| F-005 | Low | `research/research_scout.py` | 作为 deprecation shim 存在，实际 CLI 入口是 `scout/cli.py` | 可考虑添加 deprecation warning 或更新文档 | 0.40 | confirmed |

### P2: 逻辑疑问

| # | Severity | Location | Finding | Suggestion | Confidence | Status |
|---|----------|----------|---------|------------|------------|--------|
| F-006 | Medium | `test/benchmark/core.py:252` | 裸 `except:` 捕获所有异常并返回 0，掩盖错误 | 改为 `except (OSError, IOError):` | 1.0 | confirmed |
| F-007 | Medium | `test/benchmark/gpu.py:231` | 裸 `except: pass` 静默忽略 dtype 转换失败 | 改为 `except (RuntimeError, TypeError):` 并记录日志 | 1.0 | confirmed |
| F-008 | Low | `summarize/formatter.py:99` | `generate_markdown` 函数 289 行 | 拆分为多个子函数 | 1.0 | confirmed |
| F-009 | Low | `summarize/daily.py:463` | `cmd_merge` 函数 244 行 | 拆分为多个子函数 | 1.0 | confirmed |
| F-010 | Low | `summarize/weekly_summary.py:499` | `generate_weekly_markdown` 函数 236 行 | 拆分为多个子函数 | 1.0 | confirmed |
| F-011 | Low | `summarize/monthly_summary.py:645` | `generate_monthly_markdown` 函数 204 行 | 拆分为多个子函数 | 1.0 | confirmed |
| F-012 | Low | `test/benchmark/gpu.py:248` | `_benchmark_device_dtype` 函数 197 行 | 拆分为多个子函数 | 1.0 | confirmed |
| F-013 | Low | `mcp_server.py:221` | `summarize_merge` 函数 163 行 | 拆分为多个子函数 | 1.0 | confirmed |
| F-014 | Info | 多文件 | 1196 行代码嵌套超过 5 层（top: parsers.py 139 行, weekly_summary.py 137 行） | 提取辅助函数降低嵌套 | 1.0 | confirmed |

### P3: 代码重复/冗余

| # | Severity | Location | Finding | Suggestion | Confidence | Status |
|---|----------|----------|---------|------------|------------|--------|
| F-015 | Low | `website/static/scripts/compress_image.py` | 与 `website/compress_image.py` 字节级一致，冗余副本 | 删除 `website/static/scripts/compress_image.py` | 1.0 | confirmed |
| F-016 | Info | `summarize/llm_backends.py` | Re-export shim，转发 `common.llm` + `common.json_utils` | 已知设计，保持向后兼容 | 1.0 | confirmed |
| F-017 | Info | `research/cache.py` | Re-export shim，转发 `common.cache.DiskCache` | 已知设计，保持向后兼容 | 1.0 | confirmed |
| F-018 | Info | `summarize/daily_summary.py` | Backward-compat re-export shim，委托给子模块 | 已知设计 | 1.0 | confirmed |

### P4: 配置管理

| # | Severity | Location | Finding | Suggestion | Confidence | Status |
|---|----------|----------|---------|------------|------------|--------|
| F-019 | Info | 全局 | 无 .env 文件，无硬编码 API keys/secrets，tokens/ 已 gitignored | 配置管理良好，无需操作 | 1.0 | confirmed |

### P5: 死代码/未用文件

| # | Severity | Location | Finding | Suggestion | Confidence | Status |
|---|----------|----------|---------|------------|------------|--------|
| F-020 | Low | `tests/` | 仅 2 个测试文件（test_ollama.py, test_translation.py），覆盖面很小 | 用户决定删除 | 0.85 | confirmed |
| F-021 | Info | 全局 | 无注释代码块，无 TODO/FIXME/HACK 标记 | 代码整洁度好 | 0.90 | confirmed |

### P6: 硬编码路径/URL/端口

| # | Severity | Location | Finding | Suggestion | Confidence | Status |
|---|----------|----------|---------|------------|------------|--------|
| F-022 | Info | `common/ollama.py:15` | `DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"` — Ollama 标准端口 | 合理默认值，无需修改 | 1.0 | confirmed |
| F-023 | Info | 多文件 | arxiv.org, api.semanticscholar.org 等 API URLs | 标准公共 API 端点，无需修改 | 1.0 | confirmed |

### P7: 依赖健康度

| # | Severity | Location | Finding | Suggestion | Confidence | Status |
|---|----------|----------|---------|------------|------------|--------|
| F-024 | Info | 全局 | 每个子工具都有 requirements.txt，与 pyproject.toml optional-deps 对齐 | 依赖管理良好 | 1.0 | confirmed |

---

## Dependency Map

### Hub Files (被 ≥5 个文件 import)

| File | Importer Count |
|------|---------------|
| `common/io.py` | 9+ |
| `common/llm.py` | 8 |
| `common/paths.py` | 7 |
| `research/models.py` | 7 |
| `research/cache.py` | 6 |

### Orphan Files

无。所有文件都是入口文件、CLI 脚本或被其他模块导入。

### Circular Dependencies

**None detected.** 架构维持了干净的 5 层分层，`json_utils.py` 和 `llm.py` 之间的互引用通过 lazy import 避免了循环加载。

---

## Unresolved Questions

无。所有问题均已由用户确认。

---

## Statistics

- Total findings: 24
- By severity: 1 high, 6 medium, 7 low, 10 info
- By priority: P1: 5, P2: 9, P3: 4, P4: 1, P5: 2, P6: 2, P7: 1
- Coverage: 75/75 files (100%)
- Actionable by repo-tidy: 6
