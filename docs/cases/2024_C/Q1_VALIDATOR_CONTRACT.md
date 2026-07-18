# 2024-C Q1 Validator 合同

## 语义范围

本合同只冻结 Q1 的确定性销售口径：2023 年统计参数保持稳定，分别验证“超产浪费”和“超产按 50% 价格出售”。Q2 的不确定性模型、Q3 的替代/互补/相关性模型尚未冻结，不在本合同中实现。

## 独立复算

Validator 从官方附件独立读取地块、作物适宜性、2023 种植记录、亩产、成本和价格，恢复合并单元格后重算：

- 每个作物—季次—年度产量；
- 每个作物—季次销售上限；
- 销售收入、超产处理和种植成本；
- 地块容量、适宜性、季次制度、连续重茬和三年豆类窗口。

Validator 不读取 Solver 的目标值作为真值，不调用候选 Solver，不接受手工状态覆盖。

## 输出状态

Q1 Formal Result 的两个场景必须同时存在且不可重复。当前允许 `output_workbook_status=not_yet_generated`，这只用于合同和 Validator fixture；只有两个官方 Excel 均生成并完成版式/单元格复核时，`production_ready` 才能为真。

```yaml
q1_validator: implemented
q2_validator: contract_pending_model_freeze
q3_validator: contract_pending_model_freeze
qualification_authority: false
```

