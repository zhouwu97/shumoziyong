# 比赛执行指南

本指南描述新题或模拟赛的最小执行顺序。新题模式改变的是人工确认点，不会取消
Gate 0—5 的合同、材料冻结或机器校验。

## 1. 准备工作目录

```text
比赛工作目录/
  problem/          # 题面与附件
  rules/
    runtime_pack.md
  reports/
  code/
  results/
  figures/
  paper/
```

原始受控材料不得提交到仓库。应先完成材料计划和等级确认，再创建 Run。

## 2. 第一轮：仅做总控诊断

向执行 AI 提供题面、附件与 `rules/runtime_pack.md`，并使用如下约束：

```text
执行 docs/workflows/03_新题执行流.md，模式 standard。
第一轮只输出总控诊断和人工确认项；不写代码、论文或最终答案。
```

成功标准是输出题目理解、子问题拆解、数据需求、候选路线、图表计划和人工确认项，并停在
Gate 前。若执行器越权生成代码或结论，应停止该轮输出并重新附上禁止项；越权内容不计入
正式结果。

## 3. 生成材料计划并初始化

```bash
python scripts/prepare_competition.py plan --problem 2026-A --materials competition/problem --output competition/material_plan.json
```

人工逐项填写 `material_plan.json` 的 `confirmed_category` 后，显式应用计划：

```bash
python scripts/prepare_competition.py apply \
  --plan competition/material_plan.json \
  --materials competition/problem \
  --profile general \
  --mode standard \
  --confirm-no-solution \
  --reviewer <审核人>
```

Gate 0 确认需要专项 Profile 时，从尚未推进的 general Run 创建可恢复子 Run：

```bash
python scripts/run_workflow.py fork-profile \
  --from-run runs/<GENERAL_RUN_ID> \
  --profile engineering_optimization \
  --reviewer <审核人> \
  --reason "Gate 0 确认该题为工程优化题"
```

## 4. 推进与完成

旧题完整回放的示例：

```bash
python scripts/run_workflow.py init --workflow full_replay --problem 2024-C --profile engineering_optimization --materials official_materials/2024_C
python scripts/run_workflow.py advance --run-dir runs/<run_id> --reviewer <审核人>
python scripts/run_workflow.py complete --run-dir runs/<run_id> --reviewer <审核人>
python scripts/run_workflow.py verify --run-dir runs/<run_id>
```

每个命令都受 Gate 产物约束。`complete` 会封存证据；没有人工确认、完整可复核证据和
独立验证，不得将候选代码、求解器报告或论文草稿表述为正式结果。

## 5. 相关文档

- [新题执行流](../workflows/03_新题执行流.md)
- [Runtime Pack 指南](RUNTIME_PACK_GUIDE.md)
- [A092 状态与可信边界](../status/A092_STATUS.md)
