# Optimization Claim Scope Audit

本表是临时人工审计工具，不接入 Gate、Runtime Profile、Failure Label 或 Stable。

## A. 决策空间

- 原题完整候选对象数量：
- 正式模型实际包含对象数量：
- 是否在求解前固定候选集合：
- 候选缩减用途：
  - [ ] 下界证明
  - [ ] 初始解
  - [ ] 安全筛选
  - [ ] 正式可行域截断
- 候选缩减是否有严格安全证明：

## B. 词典序锁定

- 第一阶段优化目标：
- 第二阶段固定的是：
  - [ ] 前序目标值
  - [ ] 对象数量
  - [ ] 具体对象名单
  - [ ] 完整前序解
- 第三阶段固定的是：
  - [ ] 前序目标值
  - [ ] 完整前序解
- 后续阶段是否保留前序最优集合中的全部可能解：

## C. 求解状态

- `solver_status`：
- `incumbent`：
- `best_bound`：
- `mip_gap`：
- `time_limit`：
- 是否有可行解：
- 是否有不可行证书：

## D. 不可行作用域

- 求解对象是：
  - [ ] 完整模型
  - [ ] 固定候选集
  - [ ] 局部子问题
  - [ ] 启发式搜索空间
- 是否尝试开放未入选对象：
- 是否允许增加对象数量：
- 论文当前措辞：

## E. 允许结论

- [ ] `global_optimum`
- [ ] `candidate_set_optimum`
- [ ] `best_known_heuristic`
- [ ] `feasible_not_proven_optimal`
- [ ] `local_infeasible`
- [ ] `globally_infeasible`
- [ ] `no_feasible_solution_found_within_limit`
- [ ] `unable_to_determine`

## F. 证据引用

- 模型构建代码及行号：
- 求解日志或状态文件：
- 论文结论及位置：
- 审计人/日期：
