---
title: "Research & projects"
summary: "Error recovery in robotics, efficient vision-language-action models and AI for Science."
---
My research centers on two questions: how can robots recover when task execution goes wrong, and how can vision-language-action models reduce inference costs while maintaining task performance?

## RecoverBench
RecoverBench is a benchmark for error recovery in robotic manipulation. It makes post-failure recovery the focus of evaluation, using reproducible error scenarios and recovery demonstrations to compare how robots handle missed grasps, collisions and other execution errors.

The two Threading examples below show recovery after a collision and an incorrect grasp. The demonstrations replay recorded simulation states at their original time intervals.

{{< research_media >}}

[Dataset and documentation ↗](https://huggingface.co/datasets/ErrorRecovery/ErrorRecoveryBenchmark)

## FLARE
FLARE studies autonomous correction and recovery for vision-language-action models. It combines retry and reset: the policy corrects recoverable execution deviations directly, while reset skills restore the environment when needed before the original task resumes.

[Read the paper ↗](https://arxiv.org/abs/2608.26645)

## Latent Bridge
Latent Bridge explores efficient inference in dual-system vision-language-action models. It predicts latent features to reduce repeated vision-language backbone calls and examines the trade-off between computational cost and task success.

## AI for Science
I have also worked on single-cell drug response prediction, cellular perturbation modeling and medical image analysis, including scDrugMap, scPerb and PINet.

---
[Full research experience and résumé](/resume/) · [Google Scholar ↗](https://scholar.google.com/citations?user=Cbmd1GIAAAAJ) · [Get in touch](mailto:zijia.tang@duke.edu)
