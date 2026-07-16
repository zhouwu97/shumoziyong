# 人工终审交接指南

本项目的最终审核由人工执行。Paper Reader 仍可用于调试论文可读性，但不作为自动晋级
条件，也不应为此冻结 `technical_and_reader_required_v1`。

## 审核策略

新 Run 创建时默认冻结为 `gate_5_policy_version=human_final_technical_required_v1`。该策略要求：

- AI 或人工 Technical Review 审核当前不可变 Candidate；
- 最终 Gate 5 的 approved 决策只能由人工作出，并引用同一 Candidate 的 approved Technical Review；
- Gate 5 的 reviewer 也使用 `type: human`；
- 不提交 Paper Reader Review，不将 `declared_only` 结果伪装为正式证据。

已创建的 Run 必须保持初始化时冻结的策略，不能在终审前编辑 `run_manifest.json` 改变
审核要求。

## 交接材料

提交给审核人的材料至少包括当前 Candidate 目录、其 manifest、Formal Result、Gate 3/4
验证包、最新 Reasonableness Review，以及本 Run 的 `run_manifest.json`。审核人需要记录
自己的身份和可选会话号；不得由写作者替代审核人填写结论。

当当前 Candidate 已有 approved Technical Review 后，使用以下命令生成与 Candidate 和
Technical Review 哈希绑定的只读交接包：

```powershell
python scripts/run_workflow.py prepare-human-final-review-handoff `
  --run-dir <Run 目录>
```

命令只会在 `human_final_technical_required_v1` 策略下工作，不写入 Gate 5 审批、转换记录
或封存记录。输出目录中的 `human_final_review_dossier.md` 用于人工核对；
`gate_5_review.human-input.template.json` 故意不能直接提交，人工必须删除模板提示并填写真实
身份、时间、结论、检查项与证据，再通过 `record-gate5-review` 保存不可变最终决策。

先确认 `current_paper_candidate.json` 指向待审 Candidate。对历史 Run 的过渡 Candidate，
以 `gate_artifacts/gate_4.manifest.json` 的哈希绑定为准。

## Technical Review

AI 预审或人工审核都可以填写 Technical Review。AI 使用 `type: ai_assistant`，不得伪装成
`independent_llm`；`attempt` 由不可变 Ledger 自动分配，输入文件不要手填该字段。

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "technical_review",
  "review_id": "TR-填写唯一编号",
  "run_id": "Run ID",
  "candidate_id": "当前 Candidate ID",
  "candidate_manifest_sha256": "当前 Candidate manifest SHA-256",
  "reviewed_at": "2026-07-16T00:00:00+08:00",
  "reviewer": {
    "type": "ai_assistant",
    "identity": "AI 审核会话标识",
    "session_id": "可追溯会话标识"
  },
  "decision": "approved",
  "reviewed_inputs": [],
  "reasonableness_review_ref": {
    "path": "reviews/reasonableness/RR-...json",
    "sha256": "最新 approved Reasonableness Review 的 SHA-256"
  },
  "restriction_closure_refs": [],
  "issues": [],
  "required_actions": [],
  "claim_restrictions": [],
  "required_limitations": []
}
```

当 Run 启用了 Reasonableness 合同，`reasonableness_review_ref` 必须引用最新 approved
审核；其中存在限制时，`restriction_closure_refs` 必须引用论文或 Claim Map 的闭合证据。
若 AI 或人工结论为 `needs_revision` 或 `rejected`，如实写入 issues 与 required_actions。
Agent 根据该记录修订后必须生成新 Candidate，再由 AI 重新预审并送交人工终审。

```powershell
python scripts/run_workflow.py record-technical-review `
  --run-dir <Run 目录> `
  --review-file <人工填写的 technical_review.json>
```

命令输出的 `path`、`sha256` 和 `review_id` 是最终 Gate 5 的唯一合法引用；人工审核文件
写入后不可覆盖。

## Gate 5 最终决策

Gate 5 JSON 的 `policy_version` 必须与 Run manifest 相同，`supporting_reviews` 只能引用
上一步输出的 approved Technical Review。其 reviewer 同样是人工。approved 时，八项
checklist 都必须为 `passed`，不能包含阻断问题、修订动作或修订范围。

```powershell
python scripts/run_workflow.py record-gate5-review `
  --run-dir <Run 目录> `
  --review-file <人工填写的 gate5_review.json>

python scripts/run_workflow.py complete `
  --run-dir <Run 目录> `
  --reviewer <完成人身份> `
  --approved-review-id <G5R 唯一编号>

python scripts/run_workflow.py verify --run-dir <Run 目录>
```

若最终结论为 `needs_revision`，仅论文表达问题使用 `submit-paper-revision` 创建新
Candidate；模型路线、Formal Result 或诊断问题必须使用 `fork-revision` 创建修订 Run。
任何失败审核和旧 Candidate 均保留在不可变 history 中。
