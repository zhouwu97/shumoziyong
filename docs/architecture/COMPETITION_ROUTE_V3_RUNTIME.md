# 三路线竞争 Runtime v1

## 运行拓扑

父竞争 Run 保存 `model_route_v3.json` 和 Gate 3 汇总证据；每条路线使用独立子 Run，继续复用现有
Executor、Collector 与 Formal Result Verifier：

```text
parent_run/
  run_manifest.json
  model_route_v3.json
  route_runs/Q1/R-BASE/
  route_runs/Q1/R-MAIN/
  route_runs/Q1/R-ALT/
  route_execution_report_Q1.json
  route_comparison_result_Q1.json
  operability_contract_Q1.json
  operability_report_Q1.json
  risk_decision_contract_Q1.json
  risk_decision_report_Q1.json
  competition_gate3_decision_Q1.json
```

每个子 Run 必须有不同的 `child_run_id`、独立工作区、`execution_spec.json`、候选执行记录和唯一
Formal Result Envelope。父级报告只绑定路径、身份与哈希，不把候选输出提升为正式结果。

## Gate 2

```powershell
python scripts/competition_route_runtime.py execute `
  --run-dir <parent_run> --subproblem Q1 --executor-id <executor_id>
```

执行前会一次性预检三条路线和父子身份；缺少任一子 Run 时不会开始部分执行。预检通过后，三条路线分别调用
现有 `executor_core.execute_spec()`，即使某一路线返回 blocker，其他已批准路线仍会被尝试。输出报告必须精确覆盖
`baseline`、`primary`、`structural_alternative` 三种角色。

## Gate 3

```powershell
python scripts/competition_route_runtime.py gate3 `
  --run-dir <parent_run> --subproblem Q1 --validator-id <validator_id>
```

Validator 必须与 Executor 身份不同，并执行以下闭包：

1. 复核三份候选执行记录与当前文件哈希；
2. 对三个子 Run 分别调用现有 `verify_formal_result_bundle()`；
3. 要求路线比较精确引用三份 Envelope；
4. 复核比较、可执行性、风险合同与报告的当前 Run、子问题和哈希绑定；
5. 根据执行完整性、数据泄漏、硬可执行性、风险动作和 Formal Result 资格生成决策。

决策只有 `allow_paper`、`technical_report_only`、`block`。连续解修复后违约、小订单过多、运输拆分等硬检查
失败时阻断；Formal Result 环境资格不足时保留技术报告但禁止提交稿。结构缺失、跨 Run 拼接、比较证据缺口和
无理由风险降级属于合同错误，失败即关闭。

## 生命周期边界

本 Runtime 仍为 `review_ready` 且仅允许显式 `full_replay`。PR-2B 提供可调用实现，但不修改现有 Runtime
Profile、默认运行包或 Gate 产物集合；这些激活工作在 PR-4 完成。
