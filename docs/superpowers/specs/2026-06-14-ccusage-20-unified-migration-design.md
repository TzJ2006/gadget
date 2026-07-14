# 设计：summarize 迁移到 ccusage 20.x（逐源命名空间抓取）

**日期：** 2026-06-14
**模块：** `summarize/`
**分支：** `fix/ccusage-20-migration`（从 main 切出）
**状态：** 待 review

## 问题

ccusage 今日（2026-06-14）发布 **v20.0.13**，单工具即可读取 15+ 个 agent CLI
（Claude Code、Codex、Gemini、Copilot、OpenCode…），取代了过去「裸 `ccusage`（仅
Claude）+ 独立 `@ccusage/codex` 包」的拆分。本机全局版本为 **18.0.10**（20.x 之前）。

`summarize/usage.py` 现状：裸 `ccusage --json --breakdown` 抓 Claude Code；
`npx @ccusage/codex@latest` 抓 Codex。

### 为什么升级与改码必须同时进行

实测 20.x 输出（2026-06-14）：

| 命令 | 形态 | 各来源明细 |
|---|---|---|
| `ccusage --json --breakdown`（裸——现状代码调用的） | `period`、`agent:"all"`、`metadata.agents:[...]`、`modelBreakdowns[]` | ❌ 所有来源合并，`agent` 恒为 `"all"`，无法拆出各来源 token 数 |
| `ccusage claude daily --json --breakdown` | `date`、`modelBreakdowns[]`(`modelName`,`cost`)、`totalCost` | ✅ 标准形态 |
| `ccusage codex daily --json --breakdown` | `date`、`costUSD`、`models{}` 字典、`reasoningOutputTokens` | ✅ 形态与 claude 不同 |

一旦全局升到 20.x，裸 `ccusage --json` 静默切换为统一形态（`period` 取代 `date`、
所有来源合并），导致：(1) `load_ccusage_for_date()` 按 `d["date"]` 匹配失败 → Claude
统计静默丢失；(2) Codex 被重复计算。故版本升级与抓取重写必须一起发布。

**结论：** 统一命令拆不出各来源 → **逐个来源跑命名空间命令** `ccusage <source> daily`。

## 决策（已与用户确认）

- **抓取策略：** 逐源命名空间命令 `ccusage <source> daily --json --breakdown`。
- **来源发现：** 先跑一次 `ccusage daily --json`，取所有 entry 的 `metadata.agents`
  并集 = 本机有数据的来源集合；只对这些来源抓取（避免盲跑 18 个来源）。
- **纳入范围：** 发现到的全部来源（不限于 Claude/Codex）。
- **归一化：** 通用归一化器，统一已知两种形态（标准 / codex），未知来源尽力映射。
- **schema：** `token_usage_by_source: {source: 归一化用量}` + `token_usage`（全部来源
  合并，向后兼容旧字段）。
- **版本处理：** 静默自动升级、**尽力而为**——缺失或主版本 <20 静默
  `npm install -g ccusage@latest`；失败该次回退 `npx --yes ccusage@latest`，绝不阻塞。
- **旧按天路径**（`fetch_ccusage` / `cmd_legacy`）：保留但修正为命名空间命令。
- **向后兼容：** 旧报告 `codex_token_usage`、旧快照 `ccusage_*.json` /
  `codex_usage_*.json` 仍能被读取。

## 设计

### 1. `_ensure_ccusage_global()` → 静默尽力版本守卫

- 解析 `ccusage --version`（先 `shutil.which`）。
- 缺失 **或** 主版本 `< 20`：静默 `npm install -g ccusage@latest`（捕获输出、限时）。
- 任何失败 → `[warn]`，置模块级标志让调用方优先 `npx`。
- 删除 `[y]/[n]/[e]` 交互提示与 `ccusage_global_install` 配置项。
- 新增 `_ccusage_cmd(args)`：返回 `["ccusage", *args]`（存在可用 ≥20 全局）或
  `["npx", "--yes", "ccusage@latest", *args]`。

### 2. `discover_sources()` → 来源发现

- 跑 `<ccusage> daily --json`，取所有 daily entry 的 `metadata.agents` 并集。
- 返回 `list[str]`（如 `["claude", "codex"]`）。失败 → 回退到默认集合
  `["claude", "codex"]`（保证不退化）。

### 3. `fetch_source_usage(source)` → 逐源抓取 + 归一化

- 命令：`<ccusage> <source> daily --json --breakdown`（全历史）。
- 经 `_normalize_usage(raw, source)` → 内部标准形态。
- 失败（未装/超时/解析/空）→ `[warn]` + 返回 `None`，跳过该来源。

### 4. `_normalize_usage(raw, source)` → 通用归一化器

把各来源形态映射到内部标准（与 `_merge_token_usages` 一致）：
- 成本：`totalCost` 优先，否则 `costUSD`。
- 模型：`modelBreakdowns[]` 优先；否则把 `models{}` 字典转成数组（键→`modelName`）。
- 缓存：统一 `cacheReadTokens` / `cacheCreationTokens`（旧 `cachedInputTokens` 兼容）。
- 保留 `reasoningOutputTokens`（若存在）。
- 日期保持 ISO（`date` 字段；20.x 命名空间已是 ISO，删除旧
  `_normalize_codex_date()`）。
- 标注 `_source = source`。
- 删除 `fetch_codex_usage_full`、`_normalize_codex_data`、`_normalize_codex_date`。

### 5. `_refresh_usage_snapshots(logs_dir)` → 编排

```
sources = discover_sources()
for s in sources:
    data = fetch_source_usage(s)
    if data:
        path = save_usage_file(data, s, logs_dir)   # usage_<source>_<device>.json
        _rclone_upload(path, subdirectory="logs")
```
- `save_usage_file(data, source, logs_dir)`：写 `usage_<source>_<device>.json`，
  envelope `{device_name, updated_at, source, usage}`。

### 6. `load_ccusage_for_date()`

- 扫 `usage_*_*.json`（新），并兼容旧 `ccusage_*.json`(→claude) /
  `codex_usage_*.json`(→codex)。
- 按 `date` 匹配，返回 `[{device_name, usage, _source}, ...]`（结构不变）。

### 7. `_merge_token_usages()`

- 跨设备 + 跨来源合并：`modelBreakdowns` 按 `modelName` 求和，`totals` 累加。
  逻辑基本沿用（已是来源无关的）。

### 8. 报告 / 渲染 / 聚合（双轨 → 按来源）

- `daily.py`：按来源分组 `load_ccusage_for_date` 结果 → 每个来源 `_merge_token_usages`
  → `report["token_usage_by_source"][source]`；`report["token_usage"]` = 全部来源合并
  （向后兼容 + 总量）。移除写死的 `codex_token_usage`（迁移进 by_source）。
- `formatter.py:271-282`：遍历 `token_usage_by_source` 各来源渲染一段；向后兼容旧报告的
  `token_usage` / `codex_token_usage`。
- `charts.py:102-116`：`generate_daily_chart` 改为接收 `token_usage_by_source`，平台维度
  = 来源（自动支持任意来源数量）。
- `weekly_summary.py` / `monthly_summary.py`：聚合改为遍历 `token_usage_by_source`；保留
  `aggregate_token_usage` 函数签名（`test_imports.py` 契约），内部按来源迭代；
  `combine_usage_summaries` 改为对全部来源求和。
- `remote.py:131` rclone 过滤：include 增加 `usage_*.json`（保留 `ccusage_*` /
  `codex_usage_*` 以同步历史文件）。

### 9. 文档

更新 ccusage / `@ccusage/codex` 描述：根 `CLAUDE.md`、`summarize/CLAUDE.md`、`README.md`、
`summarize/README.md`、`summarize/tutorial.md`、`docs/external_dependencies_inventory.md`。

## 数据流（改动后）

```
export（每台设备）
  _refresh_usage_snapshots(logs_dir)
    discover_sources()                    → ["claude","codex",...]
    for s: fetch_source_usage(s)          → ccusage <s> daily --json --breakdown
           → _normalize_usage             → usage_<s>_<device>.json → rclone 上传

merge（中心机）
  load_ccusage_for_date()  → 读 usage_*_*.json（兼容旧 ccusage_*/codex_usage_*）
  按来源 _merge_token_usages() → report.token_usage_by_source + token_usage（合并）
```

## 错误处理

- 版本/升级失败 → `[warn]` + npx 回退。
- `discover_sources` 失败 → 回退默认 `["claude","codex"]`。
- 单来源抓取失败 → `[warn]` + 跳过该来源，不影响其他来源与整体流程。

## 测试

- 单元：`_normalize_usage` 对标准形态（claude 夹具）与 codex 形态（`models{}`/`costUSD`
  夹具）均产出一致内部结构；未知形态尽力映射不抛错。
- 单元：`discover_sources` 解析 `metadata.agents` 并集；失败回退默认。
- 单元：版本解析——`"18.0.10"`→升级；`"20.0.13"`→不动；缺失→npx。
- 单元：`load_ccusage_for_date` 同时读新旧文件名并正确标 `_source`。
- mock `subprocess.run` 断言 argv，无真实网络。
- 跑现有 `pytest summarize/tests/`（尤其 `test_imports.py` 再导出契约）。
- 工作流闸门：`python workflow/verify.py`。

## 已知取舍

- 各来源命名空间形态不同 → 依赖通用归一化器；Gemini/Copilot 等本机无数据、无法实测，
  上线后可能需补字段映射（归一化失败时降级保留总量，不抛错）。
- 逐源各跑一次进程（已用发现机制限制为有数据的来源，控制开销）。

## 不在范围内

- 用统一 `ccusage daily` 的合并总量替代逐源（已排除——拆不出各来源）。
- 报告 schema 之外的功能扩展；无关的 `gadget-mcp` 入口损坏问题。
