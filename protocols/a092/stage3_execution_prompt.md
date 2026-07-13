# 确认性运行执行说明

你正在一个完全隔离的新工作目录中完成一次数学建模确认性运行。只能读取当前目录中的 `materials/`、`formal_result_contract.md` 和本提示；禁止读取父目录、其他运行、历史解答、参考答案或网络内容。

运行标识：`{{RUN_ID}}`

题号与范围：`{{PROBLEM_ID}} / {{SCOPE}}`

必须实际检查材料、编写并运行代码、保存结果。禁止编造数值，禁止把未运行路线写成已完成路线。代码注释、报告和论文使用中文。

## 统一产物

在当前目录生成以下文件；两种提示词配置的文件名、篇幅约束和工具权限完全相同。

```text
gate0/diagnosis.md
gate0/diagnosis.json
gate0/material_inventory.json
gate1/model_route.md
gate1/model_spec.json
gate1/variable_table.json
gate1/constraint_table.json
gate2/implementation_plan.md
gate2/experiment_config.json
gate2/validation_plan.json
code/
results/formal_result.json
results/result_summary.json
results/sensitivity_results.json
results/generated_files_manifest.json
figures/
tables/
gate3/validator_self_check.json
gate4/paper_claim_map.json
gate4/paper_draft.md
gate4/paper_evidence_check.json
gate5/final_review.json
gate5/solution_failures.json
gate5/experiment_validity.json
run_metadata.json
```

`paper_draft.md` 应使用统一竞赛论文结构，正文控制在约 20 页等价篇幅以内，摘要不超过约 800 个中文字符，图不超过 12 幅、表不超过 12 个。摘要和正文中的每个关键定量结论必须能追溯到 `results/`、代码输出或图表。

`results/formal_result.json` 必须严格遵守本目录的 `formal_result_contract.md`。`generated_files_manifest.json` 列出每个结果/图表的生成脚本。`experiment_validity.json` 只检查本次运行输入是否完整、代码是否实际运行和证据是否齐全，不得猜测另一配置的结果。

完成后只在最终回复中简要报告实际生成的文件和未解决限制，不要输出文件全文。

## 题目专用要求

{{CASE_INSTRUCTIONS}}

## 已编译提示词栈

{{PROMPT_STACK}}
