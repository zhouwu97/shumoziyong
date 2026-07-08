# MathModelAgent 注入提示词

你正在使用 MathModelAgent 执行数学建模任务。

在执行任何 MathModelAgent skill 前，必须先读取当前工作目录 `rules/` 下的规则文件。

规则优先级如下：

1. 题面、官方附件、提交要求；
2. `rules/base.md`；
3. `rules/runtime_profile.md`；
4. `rules/plugin.md`；
5. `rules/patches.md`；
6. `rules/checklists.md`；
7. MathModelAgent 默认流程。

如果比赛目录只提供了 `rules/runtime_pack.md`，则把它视为已经合并好的 `base + runtime_profile + plugin + patches + checklists`。

注意：

- patch 只能作为经验启发，禁止照搬公式、数值、图表结构、代码和结论。
- 不允许一上来直接写论文。
- 不允许一上来直接写代码。
- 不允许直接选择遗传算法、粒子群、模拟退火、神经网络等高级模型。
- 必须先完成总控诊断。
- 总控诊断通过后，才允许进入建模。
- 建模报告通过后，才允许进入代码。
- 代码结果和图表通过后，才允许进入论文。
- 论文必须只使用已有结果，不得编造数值。

第一阶段只输出：

1. 题目理解；
2. 子问题拆解；
3. 题型判断；
4. 数据需求；
5. 候选模型；
6. 模型取舍理由；
7. 决策变量、目标函数、约束条件；
8. 图表计划；
9. 人工确认项；
10. 最大跑偏风险。

第一阶段禁止输出：

1. 完整论文；
2. 完整代码；
3. 最终摘要；
4. 没有数据支撑的结论。

当用户确认建模路线后，才能进入 MathModelAgent 后续阶段。进入后续阶段时，仍必须遵守 `rules/runtime_pack.md` 的闸门要求。

