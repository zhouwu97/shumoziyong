# 2024-C Q2/Q3 合同状态

Q2 不确定性模型合同草案已完成并待独立审查，尚未实现 Solver、Validator 或正式工作簿；Q3 仍只登记需求边界。两者都不提供空接口或伪 Formal Result。

| 问题 | 状态 | 在模型冻结前不得假设 |
| --- | --- | --- |
| Q2 | `model_contract_draft_review_pending` | 合同审查后再冻结；随后才实现 Solver、样本外评估、独立 Validator、result2.xlsx 反向复核 |
| Q3 | `contract_pending_model_freeze` | 替代/互补关系、相关矩阵、联合分布、消融基线和比较指标 |

Q2 合同见 `docs/cases/2024_C/Q2_MODEL_CONTRACT.md` 和 `runtime_contracts/2024c_q2_model_contract.json`。合同审查前不得启动 Q2 Solver；只有完成合同规定的 Solver、样本外评估和独立复算，才会新增 Q2 Validator；Q3 仍需单独冻结模型合同。当前不修改全局 Validator 注册表中的完整回放 scaffold 状态。
