# Competition Production 多题 full_replay Campaign

PR-7 使用固定的 `2016-C`、`2023-B`、`2024-B`、`2024-C`、`2024-D` 五题验证
`competition_production_v1`。完整 Run 保留在 Git 忽略的 `runs/`，版本库只保存合同、运行索引和
由验证器生成的摘要证据。

## 真源与顺序

`scripts/validate_full_replay_campaign.py` 不接受手填 PASS。它对每个新 Run 按以下顺序复算：

1. 校验官方材料、Run 身份、`full_replay` Runtime Pack 和 Adapter 哈希；
2. 校验只读 Adapter 报告与 `model_route_v3`，枚举全部子问题；
3. 调用现有 Gate 3 独立验证器，并比较存档决策与复算结果；同时要求三条路线的
   可信执行证明绑定同一 40 位 Git 提交，且执行时间落在本题回放记录窗口内；
4. 以只读模式复算 `score_v3`，拒绝致命码、时间泄漏或提交稿禁入；
5. 调用 Gate 4 独立候选验证器，重建论文生产清单及全部哈希绑定；
6. 从运行记录和路线比较派生运行时间、人工干预、基线胜率、致命错误率与提交稿准入。

只有五题及其全部子问题同时通过，报告才会得到 `status=passed` 和
`derived_lifecycle=full_replay_passed`。任何缺件、身份漂移或复算不一致都会保持
`derived_lifecycle=review_ready`。该状态不会启用 `new_problem` 默认包。

## 本地执行

```powershell
python scripts/validate_full_replay_campaign.py `
  --manifest capability_evidence/competition_production/full_replay/campaign_manifest_v1.json `
  --workspace-root . `
  --runs-root . `
  --output capability_evidence/competition_production/full_replay/campaign_report_v1.json
```

报告只有在本地五个 Run 均存在时才具有晋级意义。运行索引或材料登记本身不构成能力通过证据。

本次五题报告已全部通过，`competition_production_capability_v1.json` 因此登记为
`full_replay_passed`，并以 SHA-256 绑定该报告。此晋级不改变激活上下文，也不启用
`new_problem` 默认包；隐藏盲测和双盲人工评审仍属于后续资格阶段。
