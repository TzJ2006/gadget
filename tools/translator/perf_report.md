# Translator 性能检测报告

**日期**: 2026-06-20
**对象**: `translator/` 本地翻译 GUI · 模型 `tencent/Hy-MT2-1.8B`
**硬件**: RTX 5090 (Blackwell, sm_120) · torch 2.10.0+cu130 · fp16 · transformers backend

---

## 1. 结论(先看这个)

- **慢点不在算力,在 CPU 调度。** batch=1 时 GPU 有 **~84% 的时间在空等**,墙钟被 Python `generate` 循环 + 逐核函数启动延迟 + Hunyuan 自定义模型代码占满。
- **batch=1 的 ~30 tok/s 是当前技术栈的地板**,改不动(见第 4 节,优化手段全被缺 Triton 挡死)。
- **唯一有效的提速 = 批处理(batch)。** 长文档(>7000 字符自动切多块)已经在吃这个红利,batch=8 可达 ~255 tok/s。短文本天生 batch=1,无解。

---

## 2. 批处理(batch)行为

调用链:`translate_body` → `split_large_text(text, max_chars=7000)` → 一次 `generate_batch(prompts)`,**batch 大小 = 切出来的块数**。

| 输入 | 切块 | batch | 速度档位 |
|---|---|---|---|
| ≤ ~7000 字符(一段话 / 短页 / 大多数粘贴文本 / 小文件) | 1 块 | **batch=1** | ~30 tok/s(地板) |
| > 7000 字符(按标题 / 空行切分) | N 块 | **batch=N** | 接近线性加速 |

> 所以你在文本框里粘的东西、和大多数小文件,基本都是 batch=1。

---

## 3. Profiling 数据

### 3.1 单段翻译(batch=1,生成 187 token,共 5.75s,**30.8 ms/token**)

| 阶段 | 耗时 | 占比 |
|---|---|---|
| 分词 tokenize | 0.8 ms | 可忽略 |
| **生成 generate** | **5754 ms** | ~100% |
| 解码 decode | 0.2 ms | 可忽略 |

### 3.2 torch.profiler(128 步解码)

| 指标 | 数值 | 含义 |
|---|---|---|
| Self CPU time | **4.57 s** | CPU 端总耗时 |
| Self CUDA time | **0.73 s** | GPU 实际算的时间 |
| → GPU 利用率 | **~16%** | **GPU 空等 ~84%** |
| `aten::matmul` 调用次数 | **37,120** / 128 步 | **≈ 290 次核函数启动 / token** |
| 单次 matmul GPU 耗时 | ~10–12 µs | 极小,瞬间算完 |

### 3.3 每 token 拆解

```
墙钟 ~31 ms/token
├─ GPU 实际计算   ~6 ms  (19%)
└─ CPU 调度开销  ~25 ms  (81%)   ← 瓶颈在这
   (Python generate 循环 + 逐核函数启动延迟 + trust_remote_code Hunyuan 模型代码)
```

### 3.4 旁证:吞吐基准

| 配置 | 速度 | 说明 |
|---|---|---|
| 采样 batch=1 | 32.1 tok/s | 基准 |
| 贪心 batch=1 | 32.6 tok/s | **采样 / repetition_penalty 不是瓶颈** |
| 采样 batch=8 | **255.1 tok/s**(等效) | 8× token,几乎同样墙钟(6.27s vs 6.23s) |

→ **batch=8 和 batch=1 几乎同样的时间**,产出 8 倍 token。坐实瓶颈是"每步固定开销",批处理能摊薄。
→ 同样道理解释了 **7B ≈ 1.8B**:启动次数几乎一样,GPU 从不饱和,模型大小看不出差别。

---

## 4. 优化尝试与结果(全部失败,原因明确)

针对那 81% 的 CPU 调度开销,标准解法是 CUDA graphs / 静态 KV cache。实测:

| 尝试 | 结果 | 原因 |
|---|---|---|
| `torch.compile(fullgraph=True)` | ❌ graph break | Hunyuan 用**动态 NTK rope**,有数据相关分支 `if seq_len > max_seq_len_cached`,无法整图编译 |
| `torch.compile(reduce-overhead)` | ❌ `TritonMissing` | inductor 后端必须 Triton,本机未装 |
| `cache_implementation="static"`(单用) | ❌ `TritonMissing` | 当前 transformers 版本会**自动触发 compile**,仍需 Triton |

**根因**: 这台 Windows 机器没装 Triton,且无 nvcc / MSVC / cmake 构建工具链。所有能打 CPU 调度开销的手段都依赖 Triton。

### 为什么不建议装 `triton-windows`

1. **风险**:要和 torch 2.10 + cu130 严格对版本,装错可能搞坏整个 `AI` 环境的 torch(benchmark / research 都依赖)。
2. **收益存疑**:即便装上,动态 NTK rope 的 graph break 会让 CUDA graph 无法完整捕获解码循环,加速大打折扣。

---

## 5. 已实施:段落微切分(#1,batch 提升)

**改动**: `split_large_text` 新增可选 `target_chars`(默认 `None` = 旧行为,其他工具不受影响);`translate_body` 透传;translator 通过 `MICRO_CHUNK_CHARS`(默认 1000,环境变量 `TRANSLATOR_MICRO_CHUNK_CHARS` 可调)opt-in。多段落文本按空行/标题边界打包成 ~target_chars 的块 → 合成 batch;单段落(无内部边界)永不切分,语义不变。

**实测**(同一 953 字符页面,输出 token 数几乎相同):

| 配置 | 块数 | 耗时 | 速度 |
|---|---|---|---|
| 旧 batch=1 | 1 | 5.43 s | 30.9 tok/s |
| 微切分(切成 4 块) | 4 | **1.58 s** | **103.3 tok/s** |

→ 同样内容 **3.4× 加速**,纯靠批处理摊薄 CPU 调度开销。

**权衡**: `target_chars` 越小 → 块越多 → 越快,但每块上下文越少(跨段术语一致性可能轻微漂移)。默认 1000 较保守:一两段的短粘贴(<1000 字符)仍是 batch=1、无加速(符合"单段无法获益")。要短文本也提速,把 `TRANSLATOR_MICRO_CHUNK_CHARS` 调到 300–500,用一点跨段上下文换 ~3× 速度。

## 6. 后续建议(同事 ranking,按优先级)

区分:哪些提升**总吞吐**,哪些能降低**单段 batch=1 延迟**。

| 方法 | 对单段短文本 | 复杂度 | 状态 / 结论 |
|---|---|---|---|
| 段落微切分 → batch=4/8 | 有(前提多段) | 低 | ✅ **已做(第 5 节,实测 3.4×)** |
| 多文件 / 并发请求合批 | 无单请求收益,吞吐高 | 低 | 复用现成 `translate_documents_batch()`,GUI 需支持多文件上传 |
| WSL2/Linux + vLLM | 可能有 | 中 | 最值得验证的后端替换(`VLLMEngine` 已就绪) |
| 隔离环境 Triton + StaticCache/compile | 可能有 | 中 | 应做 PoC,**不碰现有环境**;受 rope graph break 限制 |
| 手写 `torch.cuda.CUDAGraph` 解码步 | 有(直接打 CPU 调度) | 高 | 不依赖 Triton,但要把动态 RoPE/KV/EOS/采样改成静态流程,维护成本高 |
| FP8 / Flash Attention | 很小 | 中 | 只省那 ~6ms GPU 部分;batch 提高后再考虑 |
| TensorRT-LLM | — | 很高 | 官方支持矩阵未列 HunYuanDenseV1,需自行适配,不推荐 |

**下一步推荐**:#2 多文件合批(低复杂度、复用现有 `translate_documents_batch()`、不改单文档语义)。

**实用提示**:单段短文本的 tok/s 衡量的是固定开销,不是模型能力——看真实吞吐请看长文档。
