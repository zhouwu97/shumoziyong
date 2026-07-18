# 2024-C Q1-S1 证据合同

Q1-S1 只封存已经生成的 Q1 两种情形的 Solver、Formal Result 和独立数学复算证据，不负责 S2 官方工作簿基线冻结。

`scripts/validate_2024c_q1_s1.py` 不调用 Solver。它读取 Q1 Formal Result、Solver run log、官方材料 Manifest 和官方附件，调用已合并的独立 Q1 Validator，重新检查两个场景的目标和全部硬约束，并要求 run log 中的 Formal Result SHA、场景工作簿 SHA 和工作簿独立复核结果一致。

输出：

- `formal_result/cases/2024_C/q1/q1_validator_report.json`：独立数学复算报告；
- `formal_result/cases/2024_C/q1/q1_s1_evidence_manifest.json`：绑定 Formal Result、run log 和 Validator report 的文件 SHA。

S1 允许登记：

```yaml
q1_solver_status: implemented
q1_formal_result_status: generated
q1_mathematical_validation: passed
q1_workbook_status: pending_s2_baseline_freeze
q1_baseline_frozen: false
production_ready: false
```

S1 不证明全局最优；`optimality_proven`、`mip_gap` 和时限状态必须原样保留。S2 仍需独立反向读取两个官方工作簿并生成最终 Q1 基线 Manifest。
