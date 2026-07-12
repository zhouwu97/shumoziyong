# 国奖竞争力路线图

## 已有底座

仓库已有 Runtime Pack、Patch Policy、Gate 0-5、材料冻结、证据清单、密封与转换日志，以及结构与复现检查。它们是可信运行的底座，但本身不证明建模能力或国奖水平。

## 分阶段实施

| 阶段 | 可交付物 | 完成条件 |
|---|---|---|
| R0 能力标准 | 愿景、架构、路线图、成熟度政策和证据 Schema | 所有目标均可被机器或独立评审验证，且不作过度宣称 |
| R1 Runtime Trust | 不可变身份、Fork/恢复边界、Profile 资格门禁 | Runtime 可验证且异常分支不能污染正式运行 |
| R2 Gate Contract v2 | `model_route_v2`、`execution_spec`、handoff/blocker 合同 | 另一个执行器无需聊天上下文即可理解批准任务 |
| R3 Executor Core | 工作区准备、候选执行、日志/哈希/环境/资源记录 | 命令真实执行，失败只能输出 blocker |
| R4 Collector & Validator | 干净重跑、指标重算和正式结果清单 | candidate 与 formal result 明确隔离 |
| R5 工程优化资格 | 优化专项验证器、三道独立题和人工审核 | `engineering_optimization` 满足 Profile Qualification |
| R6 论文与审稿 | CUMCM 模板、Claim Map、四类独立审稿 | PDF 数字可追溯，未证实结论被阻断 |
| R7 盲测基准 | 协议、题目登记、量表、运行记录和报告 | 先完成 6-8 道内部盲测，再扩展至多题型基准 |
| R8 多 Profile | 评价决策、预测、统计、仿真、网络空间 | 每个 Profile 重复合同、执行、验证、资格流程 |

实施顺序固定为：Runtime Trust -> Contract v2 -> Executor -> Collector -> Numeric Validators -> Engineering Qualification -> Paper/Review -> Benchmark -> Profile Expansion。不得通过继续堆积未经实测的 Patch 跳过执行、验证或盲测阶段。

## 当前状态口径

当前仓库处于从 `foundation` 向 `runtime_trusted` 演进的阶段；这只是架构判断，不替代机器派生的正式成熟度声明。正式声明必须使用 `scripts/derive_capability_maturity.py` 对 `capability_evidence` 求值。
