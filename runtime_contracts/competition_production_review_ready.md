# Competition Production v1（full_replay_passed）

本能力只在调用方显式选择 `full_replay` 且 Profile 为 `general`、`engineering_optimization`、`evaluation`
或 `prediction` 时编译。它不是 `new_problem` 默认能力，也不授予比赛提交资格。

文件名保留 `review_ready` 是为了维持既有 Runtime Pack 路径兼容；能力登记已由五题 Campaign 报告推进至
`full_replay_passed`，下一阶段仍须经过隐藏盲测与双盲人工评审。

固定链路不得跳步或倒置：

1. Gate 0 完成材料诊断；
2. `plugin_competition_production_v1` 只提取诊断与证据请求，不生成结果、不改论文、不判 PASS；
3. Gate 1 生成并验证 `model_route_v3`，每个子问题含机制假设、基线、主路线和结构不同备选；
4. Gate 2 在三个隔离子 Run 中执行三条路线，Collector 分别生成 Formal Result；
5. Gate 3 由独立 Validator 绑定三份 Formal Result、比较、可执行性和风险证据；
6. `score_v3` 只消费上述当前 Run 证据，决定提交稿、技术报告或阻断。

任何合同缺失、哈希漂移、跨 Run 拼接、数据泄漏、硬可执行性失败或无理由风险降级均失败即关闭。通用
Gate 1–3 检查表继续适用；发生冲突时，本能力的 v3 合同更严格且优先。
