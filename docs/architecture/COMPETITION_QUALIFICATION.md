# Competition Production 可信六题资格评测

当前资格活动默认使用 `competition_qualification_v3`。真实资格必须由至少两名项目外人工评审者和一名
独立协调员共同完成；AI 只记录评测过程、整理待确认记录和保存可校验哈希，不拥有评分、致命错误判断
或晋级决定权。

历史 `competition_qualification_v1` 和单人工辅助的 `competition_qualification_v2` 保持输入兼容。
v2 即使存在额外人工批准，也最多派生 `human_assisted_review_passed`，不能形成
`default_candidate`。v3 盲评通过只派生 `blind_review_passed`；成为 `default_candidate` 还必须绑定独立
通过的 72 小时模拟赛报告。

## 题目与材料

资格活动使用六个固定匿名槽位 `Q01`—`Q06`。每个槽位必须是此前未用于开发的完整官方题，包含完整
题面和全部官方附件。运行者在锁定前不能知道题目或答案，Baseline 与 Treatment 必须在相同材料、模型
版本、推理强度、时限、工具权限和全新上下文下运行。

每个运行必须提供：

- 题目专用 Validator 和 Formal Result 通过证据；
- 完整题目对应论文；
- 最终 Excel、附录和提交 Manifest；
- 人工修改时间、可执行方案状态、支持结论数和越界结论数。

真实题目、答案、臂映射、AI 会话记录和人工评测保存在 Git 忽略的 `qualification_runs/`。仓库只保存
预注册协议、Schema、可信公钥注册表和最终脱敏报告。

## 人工与 AI 边界

- 两名项目外人工评审者分别对每个匿名包独立评分，每篇论文必须获得两份不同人工签名。
- 独立协调员负责选题承诺、答案隔离、盲法、臂映射和最终证据摘要签名，不能兼任评审者。
- AI 记录器可以转写和整理，但评审及记录中的 `decision_authority` 都必须为 `false`。
- AI 记录必须在匿名包生成后开始、在对应人工签名前完成；未获人工确认和签名的记录不进入指标。
- 全部 24 份人工评审签名完成后才能揭示 X/Y 与 Baseline/Treatment 映射。

## 晋级边界

`validate_competition_qualification.py` 独立复算模型质量、可执行方案率、论文质量、人工修订时间和结论
越界率。证据完整但指标不达标时最多保留为 `qualification_candidate`；泄题、控制不等价、缺少正式
验证、AI 代替人工决策、记录时序错误或签名无效都会回退到 `full_replay_passed`。

当前 `policies/competition_qualification_authorities_v3.json` 为 `unconfigured`，因此仓库不能产生真实
资格结论。测试临时密钥只验证代码路径。开始真实评测前，由两名项目外评审者和独立协调员分别登记
自己控制的公钥；私钥不进入仓库，也不交给 AI。

## 执行入口

CLI 默认使用 v3 协议和 v3 公钥注册表：

```powershell
python scripts/validate_competition_qualification.py `
  --evidence qualification_runs/<campaign>/qualification_evidence_v3.json `
  --output qualification_runs/<campaign>/qualification_report_v3.json
```

人工可用 `scripts/qualification_signature_payload.py` 生成规范化签名载荷并回填签名。验证历史 v1/v2
证据时必须显式传入对应协议和公钥注册表，历史结果不会自动转换成 v3 可信资格结论。
