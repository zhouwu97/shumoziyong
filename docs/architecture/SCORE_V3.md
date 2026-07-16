# score_v3 九维评分

`score_v3` 是 `review_ready`、显式 `full_replay` 能力。它只消费 PR-2 当前 Run 的模型路线、三路线执行、
路线比较、可执行性、风险和 Gate 3 决策，不读取论文、历史运行或候选自报结果。

## 固定权重

| 维度 | 权重 |
| --- | ---: |
| 机制假设 | 10% |
| 业务约束 | 10% |
| 路线竞争 | 12% |
| 执行完整性 | 10% |
| 比较质量 | 12% |
| Formal Result 证据 | 16% |
| 可执行性 | 12% |
| 风险与稳健性 | 10% |
| 提交准备度 | 8% |

评分人给出每维 0–100 分、理由和证据路径。系统只接受固定 PR-2 文件集合，并要求 ratings 预先绑定当前
`competition_gate3_decision` SHA-256。每个维度的有效分数为人工评分与机器证据上限的较小值，不能用主观高分
覆盖执行失败、硬违约、风险阻断或环境资格不足。

## 致命规则

固定映射如下：

- `V3F_ROUTE_EXECUTION_INCOMPLETE`
- `V3F_SELECTED_ROUTE_INADMISSIBLE`
- `V3F_DATA_LEAKAGE`
- `V3F_OPERABILITY_HARD_FAILURE`
- `V3F_RISK_BLOCK`
- `V3F_FORMAL_RESULT_INELIGIBLE`

命中任一 `V3F_*` 后，最终分数为 `min(九维加权分, 70)`，禁止提交稿，但始终允许输出技术报告。Gate 3
本身要求 `technical_report_only` 或九维最终分低于 70 时，也禁止提交稿，即使没有致命码。

## 历史兼容

v3 使用独立的 `V3F_*` 命名空间，不解释、映射或修改历史 `score_v2` 的 F1–F5。政策、权重、封顶和映射
由 `runtime_contracts/score_v3_policy_v1.json` 固定；PR-4 激活前不进入默认 Runtime Pack。
