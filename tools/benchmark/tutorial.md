# Benchmark Tutorial

本教程将带你从零开始使用这个跨平台 CPU/GPU 基准测试工具。

## 本版修复与变更（2026-06-28）

一次逻辑审计修复了以下问题（命令用法不变；本环境缺 `pandas`/`plotly`/`torch` 未能实跑，以下为代码层修复并通过编译/逻辑校验）：

- **首次运行不再丢结果**：`BenchmarkResults.save()` 以追加模式写 CSV 前未创建目录，全新 checkout 下 `outputs/data/benchmark/` 不存在会 `FileNotFoundError`，跑完所有基准后整轮结果丢失。现先 `mkdir(parents=True)`。
- **报告生成不再崩溃**：纯 GPU（无 CPU 行）或所有 GPU 行 dtype 均为 `N/A` 的 CSV，会让排行榜 `pd.concat([])` 抛 `ValueError`。现对空排行榜加守卫（与既有 GPU 分支一致）。
- **投稿队列不再丢失**：`ingest_submissions.py` 每次只处理前 `max_pending` 行却清空整个 pending 文件，超额投稿被静默删除。现只删除已处理的行，保留其余（并兼容 ingest 期间的并发追加）。
- **记录数显示更正**：保存后「Total records in file」不再把刚写入的行重复计数。

## 1. 环境准备

### 安装依赖

```bash
cd tools/benchmark
pip install -r requirements.txt
```

核心依赖：`torch`、`numpy`、`pandas`、`plotly`、`tqdm`。

可选依赖：
- `threadpoolctl` — 精确控制 BLAS 线程数（影响 CPU 全核测试准确性）
- `pyopencl` — Intel/AMD GPU 支持（CUDA 和 MPS 之外的后备方案）

### 验证安装

```bash
python -m benchmark.cli --info
```

这条命令会打印检测到的 CPU、GPU 和软件版本信息，不会运行任何基准测试。如果能看到你的硬件信息，说明环境配置正确。

## 2. 运行第一次基准测试

### 快速体验（约 2 秒）

```bash
python -m benchmark.cli --cpu-only --matrix-size 1024 --duration 1 --no-save
```

这会只跑 CPU 测试，矩阵大小 1024，每项测试 1 秒，不保存结果。适合确认一切正常。

### 标准测试

```bash
python -m benchmark.cli
```

这会运行所有 CPU 和 GPU 基准测试（每项默认 10 秒），结果自动追加到 CSV 文件。

测试项目：
- **CPU Single-Core** — 纯 Python 标量运算（`sqrt + add` 循环），衡量单核性能
- **CPU Single-Core BLAS** — NumPy 矩阵乘法（单线程），衡量 BLAS 库性能
- **CPU All-Cores BLAS** — NumPy 矩阵乘法（全核），衡量多核并行性能
- **GPU** — PyTorch 矩阵乘法，对每种支持的精度（FP64/FP32/FP16/BF16）分别测试

### 只测 CPU 或 GPU

```bash
python -m benchmark.cli --cpu-only
python -m benchmark.cli --gpu-only
```

## 3. 理解测试结果

运行结束后，终端会显示类似输出：

```
CPU Single-Core
  Performance: 123.45 MFLOPS/s

CPU All-Cores BLAS (8 threads, 4096x4096)
  Performance: 456.78 GFLOPS/s

GPU CUDA FP32 (NVIDIA RTX 4090, 8192x8192)
  Performance: 12.34 TFLOPS/s
```

**单位说明**：
- MFLOPS = 百万浮点运算/秒（CPU 标量）
- GFLOPS = 十亿浮点运算/秒（CPU BLAS）
- TFLOPS = 万亿浮点运算/秒（GPU）

### FLOPS 计算方式

- 标量循环：`2 * iterations`（每次迭代一次 sqrt + 一次 add）
- 矩阵乘法（GEMM）：`2 * N^3 * iterations`（N 为矩阵大小）

### 测量方法

每项测试经过三个阶段：

1. **预热（Warmup）** — 运行 5–100 次迭代，让 CPU/GPU 达到稳定频率
2. **正式测量** — 在 `--duration` 时间窗口内反复运行
3. **统计分析** — 取中位数（median），用 IQR 方法剔除异常值

GPU 测试会在每次迭代后显式调用 `torch.cuda.synchronize()` 或 `torch.mps.synchronize()` 以确保计时准确。

## 4. 生成 HTML 报告

```bash
# 运行测试 + 生成报告
python -m benchmark.cli --report

# 从已有 CSV 生成报告（不重新跑测试）
python -m benchmark.cli --report-only
```

报告包含：
- 硬件性能排行榜（Leaderboard）
- 不同硬件的对比柱状图
- 各精度的性能对比
- 历史趋势折线图

默认输出路径：
- CSV: `outputs/data/benchmark/results.csv`（相对于 gadget 项目根目录）
- HTML: `outputs/reports/benchmark/report.html`

### 自定义输出路径

```bash
python -m benchmark.cli --output my_results.csv
python -m benchmark.cli --report-only --input-csv my_results.csv --report-output my_report.html
```

## 5. 积累多台硬件数据

CSV 使用**追加模式（append）**——每次运行结果都会追加到文件末尾，不会覆盖历史数据。

典型工作流程：

```bash
# 在机器 A 上运行
python -m benchmark.cli --output shared_results.csv

# 把 shared_results.csv 复制到机器 B 上
# 在机器 B 上运行（结果追加到同一文件）
python -m benchmark.cli --output shared_results.csv

# 生成包含所有硬件的对比报告
python -m benchmark.cli --report-only --input-csv shared_results.csv
```

报告会自动展示所有曾经测试过的硬件。

## 6. 调优测试参数

### 调整测试时长

```bash
# 快速测试（每项 3 秒）
python -m benchmark.cli --duration 3

# 高精度测试（每项 1 分钟）
python -m benchmark.cli --duration 60

# 论文级精度（每项 5 分钟）
python -m benchmark.cli --duration 300
```

更长的测试时间 = 更多采样 = 更稳定的结果。默认 10 秒对日常使用足够。

### 调整矩阵大小

```bash
# 较小矩阵（适合低显存 GPU 或快速测试）
python -m benchmark.cli --matrix-size 4096

# 较大矩阵（充分利用高端 GPU）
python -m benchmark.cli --matrix-size 16384
```

GPU 矩阵大小会根据显存自动调整，但可以手动覆盖。

## 7. 部署到网站

如果你配置了 Hugo 网站（`gadget/website/`），可以直接部署报告：

```bash
# 运行测试 + 生成报告 + 部署到 Hugo
python -m benchmark.cli --report --deploy

# 只部署已有报告
python -m benchmark.cli --report-only --deploy
```

部署会将 HTML 报告复制到 `tools/website/static/benchmark-report/`，并生成 `content/benchmark.md` wrapper 页面，然后触发网站构建。

## 8. 提交结果到公共排行榜

如果有配置 relay 服务器，可以把测试结果提交到公共排行榜：

```bash
# 运行测试后交互式询问是否上传
python -m benchmark.cli --relay-url https://relay.example.com/submit

# 自动上传（适合脚本/CI）
python -m benchmark.cli --upload --relay-url https://relay.example.com/submit

# 也可以用环境变量
export BENCHMARK_RELAY_URL=https://relay.example.com/submit
python -m benchmark.cli
```

上传失败不会影响本地测试结果。

### 手动提交

```bash
# 预览要提交的数据
python scripts/submit_result.py --dry-run

# 提交 CSV 中最后一行
python scripts/submit_result.py --relay-url https://relay.example.com/submit
```

## 9. GPU 后端兼容性速查

| 精度    | CUDA (NVIDIA) | MPS (Apple) | XPU (Intel) |
|---------|:---:|:---:|:---:|
| FP64    | ✓   | ✗   | ✓   |
| FP32    | ✓   | ✓   | ✓   |
| FP16    | ✓   | ✓   | ✓   |
| BF16    | ✓   | ✗   | ✓   |
| FP8_exp | ✓*  | ✗   | ✗   |

\* FP8 需要 CUDA 8.9+，PyTorch 尚未完全支持。

## 10. 获取稳定结果的建议

- 关闭后台应用程序，减少干扰
- 确保设备散热良好（热节流会降低性能）
- 使用较长的 `--duration`（60 秒以上）
- 多次运行取最佳值——CSV 追加模式会保留所有历史数据，报告自动取最优
- 笔记本电脑请接电源运行
