# 旧题闭环执行计划

- 题目：`2024-C`
- profile：`engineering_optimization`（0.2.0 / assembled）
- 闸门范围：Gate 0-5
- 材料：`tests/fixtures/historical_sealed_run_v1_1/materials`
- 材料清单：`tests/fixtures/historical_sealed_run_v1_1/materials/material_manifest.json`
- review_ready 实验 patch：无
- 排除 patch：无
- 实验类型：standard
- 状态：材料校验通过

## Gate 0-5 定义

- Gate 0：题目与材料诊断
- Gate 1：模型路线
- Gate 2：代码计划
- Gate 3：结果确认
- Gate 4：论文确认
- Gate 5：最终验收

## 执行顺序

1. 先检查 `material_review.json`：只有 `status=ready` 才能进入 Gate 0。
2. 人工确认材料等级 T0-T4 与风险 M1-M5。
3. 读取 `runtime_pack.md`，只执行指定 Gate。
4. 把发送给 AI 的提示词存入 `request.json`。
5. 将诊断写入 `diagnosis.md`（人看）与 `diagnosis.json`（机器检查，符合 `schemas/diagnosis.schema.json`）。
6. 把 AI 原始输出存入 `response.md` 和 `response.json`。
7. 运行 `evaluate_prompt_response.py` 生成 `automatic_evaluation.json`。
8. 人工填写 `human_review.md`、`score.json` 与 `failure_labels.json`。
9. 只把升级建议写入 `patch_suggestions.md`，不得自动修改 patch 状态。
