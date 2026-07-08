# Runtime Pack 不确定性情景测试记录：2024-C 农作物种植策略

测试日期：2026-07-08

## 测试对象

- `E:/AI/数模_runtime_test/2024C_test/code/scenario_analysis.py`
- `E:/AI/数模_runtime_test/2024C_test/reports/SCENARIO_ANALYSIS_REPORT.md`
- `E:/AI/数模_runtime_test/2024C_test/results/scenario_summary.csv`

## 检查项

| 检查项 | 结果 |
|---|---|
| 情景参数是否明确标注为 smoke-test 假设 | 通过 |
| 是否区分 baseline 和 improved | 通过 |
| 是否每个情景都重新检查约束 | 通过 |
| 是否避免编造未来真实概率 | 通过 |
| 是否输出收益对比表 | 通过 |
| 是否说明不是最终答案 | 通过 |

## 情景收益结果

| 情景 | baseline_profit | improved_profit | 提升比例 | baseline 违规数 | improved 违规数 |
|---|---:|---:|---:|---:|---:|
| base | 16,250,142.79 | 17,276,602.82 | 6.32% | 0 | 0 |
| pessimistic | 12,020,704.32 | 12,847,215.49 | 6.88% | 0 | 0 |
| optimistic | 19,239,675.12 | 20,420,618.39 | 6.14% | 0 | 0 |
| mixed | 15,316,212.31 | 16,375,095.34 | 6.91% | 0 | 0 |

## 结论

Gate 2.7 scenario analysis dry-run pass。

本轮只验证不确定性情景分析流程，不代表正式预测参数，不输出最终方案，不写论文，不计入 stable。
