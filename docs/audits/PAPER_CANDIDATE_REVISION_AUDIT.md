# 论文候选稿修订审计

## 审计结论

当前 v2.1 Gate 4 有固定稿件文件和 Gate artifact manifest，但没有版本化 Candidate Manifest。计划中“绑定当前 Gate 4 Candidate Manifest SHA”的前提在现有实现中不成立；PR 2 必须先确定过渡候选根，PR 5 才能安全演进为候选稿版本账本。

审计样本：`runs/2024C_v21_full_replay_20260715/`。

## 当前 Gate 4 产物布局

`scripts/run_workflow.py` 的 `V21_GATE_ARTIFACT_SPECS` 固定 Gate 4 文件为：

- `paper_claim_map.json`
- `paper_production_manifest.json`
- `reviewer_a_round1.json`
- `reviewer_b_round1.json`
- `reviewer_a_round2.json`
- `reviewer_b_round2.json`

样本 `gate_artifacts/gate_4.manifest.json` 对这些固定路径形成 Gate artifact 级清单。`paper_production_manifest.json` 只引用：

- `paper/submission_paper_candidate.typ`
- `submission_paper_candidate.pdf`
- `paper_claim_map.json`

生产清单的 Schema 是生产交付清单，不包含 `candidate_id`、父版本、候选不可变性、候选 history 或 current pointer。因此它不是完整候选稿哈希闭包。

## 构建与覆盖行为

`scripts/build_2024c_v21_gate4.py` 的 `compile_manuscript` 会覆盖最终稿路径：

- `paper/submission_paper_candidate.typ`
- `submission_paper_candidate.pdf`

第一轮稿件仅以题目专用路径 `paper/archive/submission_paper_candidate_round1.*` 保存。`scripts/build_2024c_v21_reviews.py` 会复制该 round1 存档，并以前后 SHA 生成修复证据；这是一条 2024-C 的构建脚本实践，不是通用候选版本合同。

当前不存在：

- `paper_candidate_manifest.json`；
- `paper_candidates/`；
- `current_paper_candidate.json`；
- `candidate_id`、父候选 ID 或候选 history；
- 可由审核失败引用的不可变候选稿快照。

## Reviewer 拓扑审计

| 主题 | 当前实现 | 与目标的差距 |
| --- | --- | --- |
| 报告 Schema | `schemas/reviewer_report.schema.json` | 只有 `model` 和 `paper` 角色，决策词为 `pass/revise/reject`。 |
| 验证 | `scripts/v21_contracts.py` 的 `validate_reviewer_report`、`validate_reviewer_pair` | 验证固定 A/B 报告对，不形成不可变 review history。 |
| Reviewer A | model 角色，可读模型合同、Formal Result、结果、model validity 与稿件 | 不能直接等同于新 Technical Reviewer 的独立合同。 |
| Reviewer B | paper 角色，可读 Formal Result、结果、claim map、稿件和图表 | 不是物理隔离的 Paper Reader。 |
| 样本标识 | A/B 报告标记 `role_separated_review` | 不是 `independent` 审核。 |

因此，PR 2 的 Gate 5 final decision 可以引用现有 A/B 作为历史辅助证据，但不应将其重新解释为计划中 Required 的 Technical Reviewer/Paper Reader 审核已达成。

## 实际文件落点与演进建议

| 演进层次 | 当前实际落点 | 审计建议 |
| --- | --- | --- |
| 过渡候选绑定 | `gate_artifacts/gate_4.manifest.json`、`paper_production_manifest.json`、固定稿件路径 | 在 PR 2 前由控制器选定唯一过渡 bundle 根；推荐将 Gate 4 manifest 视为候选 bundle 根的候选方案，并明确命名/字段局限。 |
| 题目专用构建 | `scripts/build_2024c_v21_gate4.py`、`scripts/build_2024c_v21_reviews.py` | 不要将 round1 archive 约定推广为通用 history，除非先建立通用 Schema 和写入协议。 |
| 通用候选版本化 | 新增的 `paper_candidates/`、Candidate Manifest、history、current pointer | 作为后续 PR 的新合同，必须被 Gate 4 manifest、审核记录和 Evidence 明确引用。 |
| 审核与修订关联 | `scripts/run_workflow.py` 的 Gate 4/Gate 5 验证与修订 Run 入口 | 在候选不可变 ID 存在前，不能安全表达“哪份稿件被退回、哪份稿件已修订”。 |

这里的 `paper_candidates/`、Candidate Manifest、history 和 current pointer 是计划目标的建议新落点，不是现有文件，也没有在本次审计中创建。

## PR 2 前必须确认的决策

1. 过渡绑定源采用 `gate_artifacts/gate_4.manifest.json`，还是先引入专门的桥接 Candidate Manifest。
2. 若采用 Gate 4 manifest，是否需要补充稿件、PDF、claim map、Reviewer 报告和构建元数据的完整性字段，避免把它误当作天然闭包。
3. 新的 Candidate Manifest 是在 PR 2 作为桥接合同创建，还是在 PR 5 与候选版本化一并引入。
4. Gate 5 失败审核对候选的引用是逻辑 SHA、不可变文件快照，还是二者兼有；引用必须能够被 Evidence 和状态重放复验。
5. 现有 Reviewer A/B 与计划中的新审核角色是保留为辅助证据、迁移还是并行存在。

## PR 1 交付边界

本报告只记录当前布局、差距和后续实施边界。未创建候选稿目录、Candidate Manifest、历史账本、Reviewer Schema 或修订 Run；未修改 Gate 4/Gate 5 的任何现有产物和脚本。
