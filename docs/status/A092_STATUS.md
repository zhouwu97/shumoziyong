# A092 状态

本文保留 A092 论文 Patch 的实验与证据边界说明，便于从 README 中移出长期会过时的
attempt 叙事。它不是 Patch 状态或 Profile 成熟度的机器事实源；最终状态以政策、证据和
状态派生流程的输出为准。

## 证据基线

在本次文档分流的基线中：

- A092 保持 `review_ready`；
- 当前没有形成满足 `regression_verified` 门槛的有效证据；
- 正控和边界题均出现独立数学验证失败；
- 负控实验因执行并发覆盖和外部用量限制未形成有效配对；
- 本轮结果不证明 A092 无效，只说明现有证据不足以支持晋级。

## 已完成的工程收口

- 进程树清理、唯一 attempt 目录和原子结果提升已实现并通过测试；
- 2023-B v2 公式适配器与 2024-C v2 数据/目标合同已复核并冻结；
- A092 v2 Pilot 已完成七类门槛注入；`A092-CONFIRMATORY-V2` 已冻结，实际执行须按冻结
  顺序、材料和外部验证要求重新确认。

## 正式比赛边界

`review_ready` A092 不会自动进入正式 `new_problem` Runtime Pack。正式包只会加载同时
满足政策状态与 Profile 适用条件的 Patch。

目标值、改进率和最优性结论只有在外部 Validator 通过后才能用于论文强结论。由生成候选
解的同一函数再次执行检查，不构成独立复算。

## 后续执行顺序

1. 执行前预检冻结组件哈希、外部用量和唯一 active attempt 状态；
2. 按冻结顺序执行新的 Baseline/Treatment 配对；无效 attempt 不计入配对数；
3. 先由 v2 外部 Validator 判定数据契约、目标与硬约束，再进行盲评和配对比较；
4. 仅在正控、边界和负控均形成有效证据后，重新评估是否满足 `regression_verified`。

## 相关报告

- [数学建模质量计划阶段三最终报告](../reports/MODELING_QUALITY_PHASE3_FINAL_REPORT.md)
- [2023-B Validator 公式 Pilot](../reports/2023B_VALIDATOR_FORMULA_PILOT.md)
- [2024-C 目标复算错误诊断](../reports/2024C_OBJECTIVE_RECOMPUTATION_DIAGNOSIS.md)
- [A092 v2 外部验证门槛 Pilot](../reports/A092_V2_PILOT_REPORT.md)
