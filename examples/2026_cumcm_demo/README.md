# 2026 CUMCM 比赛目录示例

这个目录示例用于说明如何把 `shumoziyong` 导出的规则包喂给 MathModelAgent。实际比赛时，不要在 `shumoziyong` 根目录直接跑比赛任务，应新建独立比赛工作目录。

## 推荐目录结构

```text
2026_cumcm_A/
  problem/
    problem.pdf
    attachment1.xlsx
    attachment2.csv
  rules/
    runtime_pack.md
  reports/
  code/
  results/
  figures/
  paper/
```

各目录作用：

| 目录 | 用途 |
|---|---|
| `problem/` | 放题面、附件、提交模板和官方说明 |
| `rules/` | 放从 `shumoziyong` 导出的运行规则包 |
| `reports/` | 放总控诊断、建模报告、结果报告和验收报告 |
| `code/` | 放可复现求解代码 |
| `results/` | 放中间结果、最终结果表和数据产物 |
| `figures/` | 放论文图表 |
| `paper/` | 放论文源文件和最终稿 |

## 从 shumoziyong 导出规则包

在 `shumoziyong` 根目录运行：

```bash
python scripts/export_runtime_pack.py
```

默认会生成：

```text
export/cumcm_runtime_pack.md
```

把它复制到比赛目录：

```text
2026_cumcm_A/rules/runtime_pack.md
```

如果不是工程优化题，可以指定 profile：

```bash
python scripts/export_runtime_pack.py --profile general
python scripts/export_runtime_pack.py --profile evaluation
python scripts/export_runtime_pack.py --profile prediction
```

## 安装 MathModelAgent

```bash
npx skills add jihe520/MathModelAgent --all
```

安装后，按你使用的工具启动：

```bash
claude --dangerously-skip-permissions
codex --yolo
```

## 第一轮：只做总控诊断

Claude Code 输入：

```text
/1start-mathmodel 完成当前目录下的数学建模任务。

在执行前，必须先读取：
1. problem/ 下的题面和附件
2. rules/runtime_pack.md

rules/runtime_pack.md 的优先级高于 MathModelAgent 默认流程。

本轮只允许完成：
1. plan.md
2. todo.md
3. reports/ANALYSIS_MODELING_REPORT.md 的总控诊断部分

禁止直接写代码、直接写论文、直接生成最终答案。
请先完成总控诊断，并在最后列出“需要我确认的建模路线”。
```

Codex 输入：

```text
$start-mathmodel 完成当前目录下的数学建模任务。

在执行前，必须先读取 problem/ 和 rules/runtime_pack.md。
本轮只允许完成总控诊断，不允许进入代码和论文。
```

## 第二轮：确认路线后再建模和代码

人工确认路线后再输入：

```text
我确认采用第 X 条建模路线。

现在进入代码和图表阶段，但必须遵守：
1. 代码只能实现 ANALYSIS_MODELING_REPORT.md 中已经确定的模型。
2. 不允许临时更换模型。
3. 每个结果必须保存到 results/。
4. 每张图必须保存到 figures/。
5. 必须生成 reports/RESULTS_REPORT.md。
6. RESULTS_REPORT.md 里要说明每个结果来自哪个代码文件、哪个数据文件、哪个模型步骤。
```

## 第三轮：结果确认后再写论文

```text
代码和结果已确认。

现在进入论文撰写阶段。

要求：
1. 使用中文国赛论文风格。
2. 摘要必须包含方法、结果、结论，但不能编造数值。
3. 所有数值必须来自 reports/RESULTS_REPORT.md。
4. 所有图表必须来自 figures/。
5. 每一问都要有模型建立、求解过程、结果解释和合理性分析。
6. 最后必须有灵敏度分析、模型评价和改进方向。
```

## 最终验收

提交前必须要求 MathModelAgent 按 `rules/runtime_pack.md` 的 Gate 4 做最终验收。若存在题意偏差、结果无来源、图表不支撑结论或约束未检查，不建议提交最终稿。

