# Competition Production 多题集成 fixture Campaign

历史 PR-7 使用固定的 `2016-C`、`2023-B`、`2024-B`、`2024-C`、`2024-D` 五题验证
`competition_production_v1` 的组件集成。其决策输入、目标和论文均为简化代理，不能代表完整官方旧题回放。
完整 Run 保留在 Git 忽略的 `runs/`，版本库只保存合同、运行索引和由验证器生成的摘要证据。

## 真源与顺序

`scripts/validate_integration_fixture_campaign.py` 不接受手填 PASS。它对每个 Run 按以下顺序复算：

1. 校验官方材料、Run 身份、`full_replay` Runtime Pack 和 Adapter 哈希；
2. 校验只读 Adapter 报告与 `model_route_v3`，枚举全部子问题；
3. 调用现有 Gate 3 独立验证器，并比较存档决策与复算结果；同时要求三条路线的
   可信执行证明绑定同一 40 位 Git 提交，且执行时间落在本题回放记录窗口内；
4. 以只读模式复算 `score_v3`，拒绝致命码、时间泄漏或提交稿禁入；
5. 调用 Gate 4 独立候选验证器，重建论文生产清单及全部哈希绑定；
6. 从运行记录和路线比较派生运行时间、人工干预、基线胜率、致命错误率与提交稿准入。

只有五题及其全部子问题同时通过，报告才会得到 `status=passed` 和
`derived_lifecycle=integration_fixture_campaign_passed`。任何缺件、身份漂移或复算不一致都会保持
`derived_lifecycle=review_ready`。该状态不会启用 `new_problem` 默认包。

该结果只证明 Runtime Pack、路线竞争、Gate 3、评分与论文流水线能够连通。它不证明读取了全部官方
附件，不证明逐问复算了原始目标与约束，也不证明生成了题目要求的完整附件和题目专用论文。

## 本地执行

```powershell
python scripts/validate_integration_fixture_campaign.py `
  --manifest capability_evidence/competition_production/integration_fixture/campaign_manifest_v1.json `
  --workspace-root . `
  --runs-root . `
  --output capability_evidence/competition_production/integration_fixture/campaign_report_v1.json
```

报告只有在本地五个 Run 均存在时才具有晋级意义。运行索引或材料登记本身不构成能力通过证据。

本次五题报告已全部通过，因此当前能力只能登记为 `integration_fixture_campaign_passed`。真正的
`full_replay_passed` 必须满足 `competition_full_replay_acceptance_v1`，包括完整官方材料、全部题目输出、
题目专用 Validator 复算和完整论文语义闭环。
