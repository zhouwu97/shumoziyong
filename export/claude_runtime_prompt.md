# Claude Code 调用 MathModelAgent 运行提示词

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
/1start-mathmodel 完成当前目录下的数学建模任务。

在执行前，必须先读取：
1. problem/ 下的题面和附件
2. rules/runtime_pack.md

注意：
rules/runtime_pack.md 的优先级高于 MathModelAgent 默认流程。

本轮只允许完成：
1. plan.md
2. todo.md
3. reports/ANALYSIS_MODELING_REPORT.md 的总控诊断部分

禁止：
1. 直接写代码
2. 直接写论文
3. 直接生成最终答案
4. 直接使用遗传算法、粒子群、模拟退火、神经网络等复杂模型

请先完成总控诊断，并在最后列出“需要我确认的建模路线”。
```

路线确认后再继续：

```text
我确认采用第 X 条建模路线。

现在进入代码和图表阶段，但必须遵守：
1. 代码只能实现 ANALYSIS_MODELING_REPORT.md 中已经确定的模型。
2. 不允许临时更换模型。
3. 每个结果必须保存到 results/。
4. 每张图必须保存到 figures/。
5. 必须生成 reports/RESULTS_REPORT.md。
6. RESULTS_REPORT.md 里要说明每个结果来自哪个代码文件、哪个数据文件、哪个模型步骤。
```

