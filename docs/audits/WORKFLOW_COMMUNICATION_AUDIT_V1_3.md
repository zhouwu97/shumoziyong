# 工作流沟通改造审计 v1.3

## 审计范围

本报告执行《审核失败闭环与模型沟通改造计划 v1.3》的 PR 1，仅以只读方式核对当前工作流、Schema、脚本和一份 v2.1 运行样本。报告不修改运行状态、Schema、脚本、测试或既有运行目录。

- 审计基线提交：`b231b8ca5b06ad0376fcdb3d0d742185f76da713`
- 基线主题：`feat(workflow): implement v2.1 modeling replay chain`
- 运行样本：`runs/2024C_v21_full_replay_20260715/`
- 工作树状态：审计开始时存在用户已有修改和未跟踪文件；本报告不将其视为审计结论，也不改动它们。

`runs/` 是被 Git 忽略的本地运行产物。样本用于确认运行时的实际落点，不能替代基线代码的版本证据。

## 总体结论

计划中的沟通字段、失败审核闭环和候选稿版本账本目前尚未存在。现有系统采用固定 Gate 根产物与固定文件名；后续 PR 必须在这一约束下演进，不能把计划中的目标文件误当作已存在的合同。

特别是，Gate 4 不存在 `paper_candidate_manifest.json`、`paper_candidates/`、`current_paper_candidate.json` 或 `candidate_id`。因此，PR 2 无法直接绑定“现有 Gate 4 Candidate Manifest SHA”；控制器必须先决定过渡绑定源。

## Gate 0 至 Gate 2：当前合同与差距

| Gate | 当前实际产物与验证位置 | 已有信息 | 计划所需但当前缺失的信息 |
| --- | --- | --- | --- |
| Gate 0 | `schemas/diagnosis.schema.json`；v2.1 最终校验落在 `schemas/gate_business_artifact.schema.json` 的 diagnosis 分支 | 子问题、候选路线、已知/缺失数据、人工确认、风险 | `ambiguities`、`capability_tags`、`proposed_result_role` |
| Gate 1 | `schemas/model_route_v2_1.schema.json` | `selected_model` 的名称/理由、假设、人工决策、结论范围 | 稳定模型 ID、`result_role_binding`、`communication` |
| Gate 2 | 固定 `code_plan.json`，其 Schema 为通用文件合同 | 命令、模块、输入、输出、验证步骤 | `communication_plan` |

Gate 0 需要同时注意两个层次：`diagnosis.schema.json` 描述诊断内容，而 v2.1 Gate 最终接受的是 `gate_business_artifact.schema.json` 的对应分支。后续改造若只改前者，将不会改变 Gate 的实际接受合同。

## Gate 3：数值有效性与合理性接入点

现有数值、结构和可复现性验证已具备明确落点：

| 责任 | 实际位置 | 现有能力 |
| --- | --- | --- |
| 模型与执行验证 | `scripts/model_validation.py` 的 `validate_model_and_execution` | 符号、量纲、claim-metric 绑定、优化专项检查、输入输出 SHA、可重复执行 |
| Gate 3 证据收集 | `scripts/gate3_evidence.py` 的 `collect_gate_3_math_validation` | 数学验证资格及优化/随机检查机器证据 |
| v2.1 模型有效性报告 | `scripts/v21_contracts.py` 的 `validate_model_validity_report` | small/limit cases 与 fatal code |
| 竞争价值评估 | `schemas/competition_value_assessment.schema.json` | score、pass/fail/pending 与 findings |

`competition_value_assessment.json` 接近计划中的 L3 合理性检查，但决策词不统一为 `approved`、`needs_revision`、`rejected`，也不是独立 Reasonableness Reviewer。它应被视为可复用证据，而不是已实现的目标审核角色。

若后续新增合理性审核，其最小侵入接入点是在 Gate 3 产物完成后、`scripts/run_workflow.py` 中 Gate 3 向 Gate 4 写入 `record_transition` 之前。

## 状态机与修订运行限制

| 主题 | 当前实际位置 | 审计结论 |
| --- | --- | --- |
| Gate 固定产物 | `scripts/run_workflow.py` 的 `GATE_ARTIFACT_SPECS` 与 `V21_GATE_ARTIFACT_SPECS` | v2.1 使用固定根路径，不具备版本化候选或审核 history 的抽象 |
| 事件重放 | `scripts/run_workflow.py` 的 `replay_transition_log`、`_replay_v2_transition_log` | Gate 0-4 可记录 `approved/rejected`；拒绝不会推进当前 Gate。Gate 5 完成只接受 approved。 |
| Profile fork | `scripts/run_workflow.py` 的 `_assert_parent_fork_eligible`、`fork_profile` | 仅支持 `new_problem/general` 在 Gate 0 分叉，不支持 Gate 5 的 `needs_revision` 或诊断/模型/正式结果的后期修订范围。 |

现有 `profile_forked`、`superseded` 事件说明状态机有相关事件类型，但可写入口只服务于 Gate 0 的 profile 分叉。将其直接解释为“审核失败后修订 Run”会绕过当前资格限制。

## 实际文件落点

以下清单是 PR 1 审计确认的实现落点，不表示本 PR 已作任何修改。

| 改造主题 | 现有应检查/扩展的位置 |
| --- | --- |
| Gate 0 沟通字段 | `schemas/diagnosis.schema.json`、`schemas/gate_business_artifact.schema.json`、`scripts/run_workflow.py` 的 v2.1 Gate 验证 |
| Gate 1 沟通字段 | `schemas/model_route_v2_1.schema.json`、对应 Gate 1 固定产物验证 |
| Gate 2 沟通计划 | `code_plan.json` 的 Schema、`scripts/run_workflow.py` 的 Gate 2 固定产物验证 |
| Gate 3 合理性审核 | `scripts/model_validation.py`、`scripts/gate3_evidence.py`、`scripts/run_workflow.py` 的 Gate 3 到 Gate 4 转换处 |
| Gate 5 审核/完成 | `schemas/gate_5_review.schema.json`、`scripts/run_workflow.py`、`scripts/finalize_run_evidence.py` |
| Gate 4 候选稿 | `scripts/build_2024c_v21_gate4.py`、`scripts/build_2024c_v21_reviews.py`、Gate 4 manifest 与生产清单 Schema |
| 修订 Run | `scripts/run_workflow.py` 的 `fork_profile`、事件重放及 Run 初始化逻辑 |

## PR 2 之前必须确认的决策

1. Gate 4 的过渡候选绑定源：使用 `gate_artifacts/gate_4.manifest.json` 作为 bundle 根，或先新增桥接 Candidate Manifest。不能假设 `paper_production_manifest.json` 本身已经形成完整候选哈希闭包。
2. Gate 5 的兼容策略：保留现有 `gate_5_review.json` 作为历史 v1 合同，还是以显式版本化 Schema 和转换规则引入新审核记录。
3. 修订 Run 的授权范围：是扩展现有 `fork_profile`，还是另设明确的 revision/fork 入口；两者都必须补足父 Run、修订 Scope、目标 Gate 与可重放事件合同。
4. Reviewer 角色迁移：当前 A/B 报告不能直接重命名为计划中的 Technical Reviewer/Paper Reader Required，因为二者并未物理隔离输入。

## PR 1 交付边界

本审计只新增本报告及关联审计报告。未执行 PR 2 及后续 PR，未更改任何 Schema、运行脚本、状态机、运行产物或测试。
