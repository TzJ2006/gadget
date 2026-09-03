---
name: ccgraph
description: 看图 —— 渲染想法图、校验它、报告现在能动手做什么、什么被卡住。只读，不修任何东西。触发词：ccgraph、看图、项目状态、现在做什么。
---

# ccgraph — 图长什么样，现在能做什么

## 参数

一个想法编号就只看那一个（`show I-0XX`）；`--check` 只报问题、不渲染。
不带参数就是校验、渲染、汇总。

## 全都跑一遍

只读命令，按这个顺序跑：

```
node .companion/companion.mjs check
node .companion/companion.mjs render
node .companion/companion.mjs next
node .companion/companion.mjs status
node .companion/companion.mjs paths
```

报告四件事：

1. **图的画像** — 多少个想法、几个完成、终点是什么、网页在哪
   （路径以 paths 打印的为准，不许猜文件名）。
2. **错误和警告** — `check` 的输出按严重程度排：错误必须修（说清哪条命令修），
   警告逐条说要不要理。
3. **前沿** — `next` 列出的想法就是现在能动手的；每个配一句它是什么。
4. **卡住的** — blocked 的想法和它们各自在等什么（`status` 有答案）。

最后给一句「下一步跑什么命令」。

**这条工作流禁止修任何东西** —— 发现问题只报告：图的问题指给 ccthink 或
ccfix，代码的问题指给 ccbuild 或 ccfix。看单个想法用
`node .companion/companion.mjs show I-0XX`。
