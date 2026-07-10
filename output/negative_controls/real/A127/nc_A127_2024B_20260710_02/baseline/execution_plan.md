# 旧题闭环执行计划

- 题目：`2024-B`
- profile：`engineering_optimization`（0.2.0 / verified_candidate）
- 闸门范围：Gate 0-2
- 材料：`official_materials/2024_B`
- candidate patch：无
- 排除 patch：['A092', 'A127']
- 实验类型：isolation
- 状态：材料就绪

## 执行顺序

1. 人工确认 `material_review.json` 的 T0-T4 与 M1-M5。
2. 读取 `runtime_pack.md`，只执行指定 Gate。
3. 把发送给 AI 的提示词存入 `request.json`。
4. 将诊断写入 `diagnosis.md`（人看）与 `diagnosis.json`（机器检查，符合 diagnosis_output.schema.json）。
5. 把 AI 原始输出存入 `response.md` 和 `response.json`。
6. 运行 `evaluate_prompt_response.py` 生成 `automatic_evaluation.json`。
7. 人工填写 `human_review.md`。
8. 填写 `score.json` 与 `failure_labels.json`。
9. 只把升级建议写入 `patch_suggestions.md`，不得自动修改 stable 状态。
