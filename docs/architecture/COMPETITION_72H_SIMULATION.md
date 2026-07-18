# Competition Production 72 小时模拟赛

72 小时模拟赛验证比赛现场的完整交付能力，而不是逐 Gate 分散执行。流程固定覆盖选题、材料读取、
建模、代码执行、图表生成、论文完成、提交附件和最终检查，并且从揭题到完成不得超过 72 小时。

准入前提是 `competition_qualification_v3` 已派生 `blind_review_passed`。模拟赛必须使用完整官方题面和
全部附件，输出完整 PDF、最终 Excel、附录、提交包和最终验证报告。所有文件以路径和 SHA-256 绑定，
人工观察员必须实际打开并确认最终交付物。

## 记录与判定

- 每个阶段记录开始、结束、人工工作、AI 工作和审计流程耗时。
- 审计耗时按 `audit / (active + audit)` 复算；预注册上限为 25%，用于发现审计流程挤占建模时间。
- AI 可记录全过程，但 `decision_authority=false`；最终交付确认由登记公钥的人工观察员签名。
- 超过 72 小时、阶段缺失或倒序、提交物缺失或哈希漂移、正式验证失败、题目 Validator 失败、AI
  替代人工决定均失败关闭。

当前 `policies/competition_72h_simulation_authorities_v1.json` 为 `unconfigured`，状态报告为 `not_run`。
项目没有执行过真实 72 小时模拟，因此不得声称通过。

```powershell
python scripts/validate_competition_72h_simulation.py `
  --evidence qualification_runs/<simulation>/simulation_evidence_v1.json `
  --output qualification_runs/<simulation>/simulation_report_v1.json
```

只有 v3 可信盲评报告和 `competition_72h_simulation_passed` 报告同时存在且哈希闭包时，能力 Schema 才
接受 `default_candidate`。该状态仍不自动把 `new_problem_default_enabled` 改为 `true`。
