# 2024-C 结论作用域跨题验证

## 定位

本记录复用已有 2024-C 多期种植优化的 Gate 0-2 工件，只验证临时
`optimization_claim_scope_check` 是否具有跨题价值，不接入 Gate、Runtime、Failure Label
或 Stable。

## Gate 0-2 证据

| Gate | 工件 | 作用域证据 |
|---|---|---|
| Gate 0 | `gate0_diagnosis.md` | 识别 54 个地块、2024-2030 年、作物与季次的完整多期资源配置问题 |
| Gate 1 | `route_approval.md` | 明确地块-作物-年份-季次变量、轮作边界、销售聚合和不确定性路线 |
| Gate 2 | `model_definition.md`、`code/build_model.py` | 对每个地块、年份、有效季次枚举全部题意允许作物；仅按硬适种规则排除不合法组合 |

正式结果包含 7,434 个面积决策变量。这里的候选排除来自题面硬适种约束，不是按收益、
能力或启发式排名截断，因此审计按完整决策空间处理。

## 检查输入

```yaml
decision_space:
  original_candidate_count: 7434
  modeled_candidate_count: 7434
  candidate_set_fixed_before_optimization: false
  candidate_reduction_safety_proven: true
solver:
  status: time_limit
  has_incumbent: true
  has_infeasibility_certificate: false
problem_scope: complete_model
```

求解状态来自 `results/q1_unsold/objective_validation.json` 和
`results/q1_unsold/raw_solution.json`：HiGHS 状态码为 1，消息为 `Time limit reached`，
同时存在经独立复算通过的可行决策。

## 检查结果

```text
allowed_conclusion: feasible_not_proven_optimal
forbidden: global_optimum
```

该输出与 `failure_review.md`、`model_definition.md` 和 `paper_draft.md` 的既有措辞一致：
四个 MILP 只形成经验证的可行策略，不构成全局最优性证明。

## 误报、漏报与实际帮助

- 误报：未发现。硬适种规则形成的安全排除没有被误报为不安全候选截断。
- 漏报：本次未覆盖不可行结论；不可行作用域仍由两个合成反例和 2021-C 压力测试覆盖。
- 实际帮助：检查器同时读取“完整决策空间”和“限时 incumbent”后，能阻止把完整模型中的
  可行解误写成全局最优，说明它对供应链以外的多期生产配置问题仍有价值。

## 当前工程化决定

保持人工检查表和独立函数状态。当前样本尚不足以证明其在安全预处理、局部搜索、无
incumbent 限时退出等更多组合上稳定工作，因此不接入 Runtime、Gate、Failure Label 或
Stable。
