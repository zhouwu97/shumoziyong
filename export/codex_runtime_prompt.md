# Codex 调用 MathModelAgent 运行提示词

在比赛工作目录中使用。目录应包含：

```text
problem/
rules/runtime_pack.md
reports/
code/
results/
figures/
paper/
```

第一轮只做总控诊断：

```text
$start-mathmodel 完成当前目录下的数学建模任务。

在执行前，必须先读取：
1. problem/ 下的题面和附件
2. rules/runtime_pack.md

rules/runtime_pack.md 的优先级高于 MathModelAgent 默认流程。

本轮只允许完成总控诊断，不允许进入代码和论文。

禁止：
1. 直接写代码
2. 直接写论文
3. 直接生成最终答案
4. 直接使用遗传算法、粒子群、模拟退火、神经网络等复杂模型

请输出：
1. 题目理解
2. 子问题拆解
3. 题型判断
4. 数据需求
5. 候选模型比较
6. 建模路线
7. 图表计划
8. 需要我确认的建模路线
9. 最大跑偏风险
```

路线确认后再继续：

```text
我确认采用第 X 条建模路线。

现在进入代码和图表阶段。必须读取 reports/ANALYSIS_MODELING_REPORT.md，只实现已确认模型。
所有结果保存到 results/，所有图表保存到 figures/，并生成 reports/RESULTS_REPORT.md。
```

