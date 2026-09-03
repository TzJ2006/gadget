---
name: ccbuild
description: 按依赖顺序实现已批准的想法 —— 先跑出一次真实失败的测试记录，再写实现，再拿到最新的通过记录，才能标完成。触发词：ccbuild、开始实现、动手做。
---

# ccbuild — 把 todo 变成 done，顺序由图决定

先读引擎旁边的 FORMAT.md。图决定顺序，你不决定。

## 参数

一个想法编号就只做那一个；`--all` 一直做到前沿空了或者卡住为止。
不带参数就做完当前前沿，然后停下报告。

## 第 0 步 — 现在在哪

```
node .companion/companion.mjs check
node .companion/companion.mjs next
node .companion/companion.mjs status
```

`check` 不过不许动工。`next` 是前沿：所有前置都完成了的 todo 想法。
两个想法的 `code` 写同一个文件就不是独立的 —— 按编号顺序一个一个来。

## 第 1 步 — 开工

```
node .companion/companion.mjs set I-0XX doing
```

进不去 doing 时，拒绝理由会说清缺什么：计划字段没答完 → 回 ccthink；
前置没完成 → 先做前置；文件和别的进行中想法重叠 → 等它完成。
计划还没被人批过的，写实现时守卫会拦 —— 先补一道 plan 批准。
写之前可以自检：`node .companion/companion.mjs allow src/那个文件`。

## 第 2 步 — 测试先行，看着它失败

1. 写 `verify.test_files` 里点名的测试文件，断言 `expected` 说的真实输入输出。
2. 跑出失败记录：

```
node .companion/companion.mjs run-check I-0XX --phase red
```

**失败必须是「东西还没实现」造成的**，读输出确认。意外先绿（unexpected_pass）
会挡住实现写入 —— 要么测试写错了，要么真有现成实现；请人裁决一次豁免
（`request-approval --gate red-waiver --node I-0XX`），不许自己糊弄过去。

## 第 3 步 — 实现

只写这个想法需要的，写到 `code` 承诺的文件和符号。发现需要不在 `needs`
里的前置，是图上的洞：停下告诉人、补边、让前沿重排 —— 不许顺手把前置也建了。

## 第 4 步 — 拿绿

```
node .companion/companion.mjs run-check I-0XX --phase green
```

通过后再跑整个测试套件 —— 弄坏别的想法不算完成。失败最多修三次，每次说清
改了什么为什么；三次后 `set I-0XX blocked` 交给 ccfix。
**绝不改测试让它通过** —— 测试是第 7 问，改它等于改想法本身。

## 第 5 步 — 标完成

先把真实行号填进 `code.lines`，然后：

```
node .companion/companion.mjs set I-0XX done --note "一句话说清建了什么"
```

`set` 会拒绝没有最新通过记录的 done —— 实现每改一笔、测试每变一次，旧的
通过记录都会过期，重跑就是了。人工验收的想法要人签字才关得上
（`request-approval --gate manual-check --node I-0XX`）。

## 第 6 步 — 循环

回第 0 步。前沿空了、有想法卡死了、或人喊停，就 `render` 并报告：
建成了什么、现在能做什么、什么被卡住为什么。
