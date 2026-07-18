# 2024-C Q1-S2 官方工作簿与基线合同

Q1-S2 只处理已通过 S1 数学复算的两个官方结果工作簿，不重新运行 Solver。独立读取器按官方模板反向读取工作表、地块行和作物列，比较 Formal Result assignments 与工作簿单元格面积，并由题目专用 Workbook Validator 重新计算目标和全部硬约束。

冻结前必须同时验证：

- `result1_1.xlsx`、`result1_2.xlsx` 使用官方模板，七张年份工作表、作物列、地块行和合并结构一致；
- 实际工作簿 SHA 与 Formal Result 中记录的 SHA 一致；
- 每个非零单元格与 Formal Result 决策变量集合及面积一致；
- 两个场景的目标和约束由独立 Workbook Validator 复核通过；
- Material Manifest、Formal Result、S1 Validator report 和两个工作簿的 SHA 写入 `q1_baseline_manifest.json`。

冻结结果登记：

```yaml
q1_baseline_frozen: true
q1_workbook_reverse_validation_passed: true
production_ready: false
```

Q1 基线冻结只解除 Q2-A 情景生成器的输入阻断，不代表 Solver 已证明全局最优、生产就绪或获得资格。
