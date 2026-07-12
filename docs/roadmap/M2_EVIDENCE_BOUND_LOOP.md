# M2：证据绑定的端到端建模闭环

## 首个纵向样例

首个样例使用官方 T3 材料 `2024-C 农作物的种植策略`，并把首轮交付严格限定为问题 1 的**单季旱地资源配置基线**。该基线使用附件 1、附件 2 的真实耕地与统计数据，验证“从合同到正式结果”的链路；它不宣称已经完成 2024--2030 全问题求解，也不生成最终竞赛论文。

这个限定避免把“系统闭环验证”误写成“已经给出国奖级完整解答”。后续扩展到轮作、豆类三年约束、多季地块、销售上限与不确定性时，必须作为新的已批准合同和新运行执行。

## 固定链路

```text
official materials
-> diagnosis / model_route_v2 / execution_spec
-> candidate_execution_record
-> clean collector rerun
-> optimization numerical validation
-> formal_result_manifest
-> paper_claim_map
-> seal and empty-directory reproduction
```

Candidate 记录只能证明候选程序运行过。只有 Collector 在新工作目录中重新执行同一代码与同一输入，并由优化验证器复算目标、基线、容量和残差后，才能写入 `formal_result_manifest`。

## M2 退出条件

1. 使用官方 `material_manifest.json` 验证的真实旧题材料；
2. 每个执行任务同时绑定 `execution_spec`、代码、输入、输出和环境哈希；
3. 执行失败写入 blocker，且不生成正式结果；
4. Collector 不复用候选输出或候选工作目录；
5. 正式结果包含独立重跑和数值复算；
6. 每条论文 Claim 引用正式指标和正式输出；
7. Gate 3/4/5 只能引用正式结果；
8. 从只含固定输入和合同的空运行目录可重新执行并得到同一正式输出哈希。
