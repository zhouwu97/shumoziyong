# 2024-C Q2/Q3 合同状态

Q2、Q3 当前只登记需求边界，不提供空接口或伪 Formal Result。

| 问题 | 状态 | 在模型冻结前不得假设 |
| --- | --- | --- |
| Q2 | `contract_pending_model_freeze` | 情景规划、鲁棒优化或随机规划；随机变量分布；期望/最坏/风险调整目标 |
| Q3 | `contract_pending_model_freeze` | 替代/互补关系、相关矩阵、联合分布、消融基线和比较指标 |

只有先形成可审查的模型语义合同，才会分别新增 Q2 Validator 和 Q3 Validator。当前 PR 不修改全局 Validator 注册表中的完整回放 scaffold 状态。

