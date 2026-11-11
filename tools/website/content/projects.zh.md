---
title: "研究与项目"
summary: "机器人错误恢复、视觉语言动作模型的高效推理，以及 AI for Science。"
---
我的研究主要围绕两个问题展开：机器人执行任务失败后，如何恢复并继续完成任务？视觉语言动作模型如何在保持任务表现的同时，减少推理开销？

## RecoverBench
RecoverBench 是一个机器人操控错误恢复评测基准。它将评测重点从正常执行转向失败后的恢复，通过可复现的错误场景和恢复示教，比较机器人应对抓取失误、碰撞等情况的能力。

下面展示两段 Threading 任务的恢复轨迹，分别对应碰撞和抓取姿态错误。演示按原始时间间隔回放项目中保存的仿真状态。

{{< research_media >}}

[查看数据集与使用说明 ↗](https://huggingface.co/datasets/ErrorRecovery/ErrorRecoveryBenchmark)

## FLARE
FLARE 研究视觉语言动作模型在执行失败后的自主纠正与恢复。框架结合重试和环境重置：对于可以直接纠正的动作偏差，模型尝试继续执行；对于需要恢复环境状态的错误，则先执行相应的重置技能，再返回原任务。

[阅读论文 ↗](https://arxiv.org/abs/2608.26645)

## Latent Bridge
Latent Bridge 研究双系统视觉语言动作模型的推理效率。通过预测潜在特征，减少视觉语言模型骨干网络的重复调用，并评估计算开销与任务成功率之间的权衡。

## AI for Science
我也参与了单细胞药物响应预测、细胞扰动建模和医学图像分析等研究，相关工作包括 scDrugMap、scPerb 和 PINet。

---
[查看完整研究经历与简历](/zh/resume/) · [Google Scholar ↗](https://scholar.google.com/citations?user=Cbmd1GIAAAAJ) · [联系我](mailto:zijia.tang@duke.edu)
