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

Validator 解析 `formal_result/cases/2024_C/material_manifest.json`，校验其专用 Schema、
`artifact_type=official_material_manifest`、`problem_id=2024-C` 和
`source.kind=official`。随后按 `land_and_crop_dictionary`、
`historical_planting_and_statistics` 两个冻结角色逐项核对路径、字节数和 SHA-256。
Formal Result、正式 Manifest 或实际附件任一身份不一致时立即失败。

## 输出状态

Q1 Formal Result 的两个场景必须同时存在且不可重复。当前允许 `output_workbook_status=not_yet_generated`，这只用于合同和 Validator fixture。当前 Validator 不实现官方 Excel 文件、SHA、模板和单元格内容复核，因此即使输入状态字符串为 `generated`，`production_ready` 仍固定为 `false`。只有后续独立 Workbook Validator 完成两个官方 Excel 的文件存在性、SHA、版式、单元格和 assignments 一致性复核后，才允许讨论生产就绪。

```yaml
q1_validator: implemented
official_output_workbook_validator: implemented
q2_validator: model_contract_draft_review_pending
q3_validator: contract_pending_model_freeze
qualification_authority: false
```

正式运行入口会先将 Solver assignments 写入官方模板，再由不导入 Solver 的 Workbook Validator
反向读取工作簿，复核工作表、单元格、面积、季次、约束和目标。Formal Result Validator 仍固定
返回 `production_ready=false`；工作簿验证通过只证明 Q1 结果文件合同闭合，不构成资格或生产授权。
