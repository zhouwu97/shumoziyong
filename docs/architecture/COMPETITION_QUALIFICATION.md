# Competition Production 六题人工主导资格评测

当前资格活动使用 `competition_qualification_v2`：一名已登记公钥的人工资格所有者负责最终判断，
AI 只记录评测过程、整理输入并保存可校验哈希。AI 不能填写或决定模型质量分、论文质量分、致命错误
结论和晋级状态。历史 `competition_qualification_v1` 双人工协议保持只读兼容，不能用 v2 证据冒充 v1
双人工评审。

资格活动使用六个固定匿名槽位 `Q01`—`Q06`。真实题目、答案、配对映射、AI 会话记录和人工评测
只保存在 Git 忽略的 `qualification_runs/`；仓库仅保存预注册协议、Schema、可信公钥注册表和最终脱敏
报告。

## 人工与 AI 边界

- 人工资格所有者选择题目、确认未泄漏、给出全部评分与致命错误判断，并用自己的私钥签名。
- AI 记录器可以转写、整理和生成待确认记录，但 `decision_authority` 必须为 `false`。
- 每份人工签名同时绑定 AI 的 provider、model、版本、session、系统提示、完整对话和记录 SHA-256。
- AI 输出不能自行成为评分证据；未获得人工确认和签名的记录不能进入指标计算。
- 同一名人工可以完成全部 12 个匿名包评测，但在全部签名前不能看到 X/Y 与 Baseline/Treatment 映射。

## 证据顺序

1. 人工资格所有者在首次揭题、首次运行前签署六题材料 SHA-256 承诺根。
2. Baseline 与 Treatment 在相同模型、推理强度、时限、工具权限和材料下分别运行，禁止跨臂读取。
3. 两个输出被处理为仅含 X/Y 标签的匿名论文包；每包形成一份 AI 记录和一份人工签名决定，共 12 份。
4. AI 记录必须在匿名包生成后开始、在人工签名前完成；人工签名后不得替换记录或评分。
5. 全部 12 份人工签名完成后才能揭示 X/Y 映射；资格所有者再签署题目承诺、映射和全部证据摘要。
6. `validate_competition_qualification.py` 复算模型质量、可执行方案率、论文质量、人工修订时间和结论
   越界率。
7. 指标通过只派生 `human_assisted_review_passed`；另一份绑定完整证据摘要的人工签名才能派生
   `default_candidate`。报告始终固定 `new_problem_default_enabled=false`，默认包切换仍需单独审计。

## Fail-closed 边界

题目在锁定前泄露、运行控制不等价、缺少 Formal Result 验证、Treatment 致命错误、人工签名前揭示
臂身份、AI 获得决策权、AI 记录时间倒置、人工签名无效、题目承诺或映射摘要漂移，都会回退到
`full_replay_passed`。指标未达标但证据完整时最多保留为 `qualification_candidate`。

当前 `policies/competition_qualification_authorities_v2.json` 为 `unconfigured`，因此仓库暂时不能产生真实
资格结论。测试中的临时 RSA 密钥只验证代码路径，不构成人工评测。开始真实活动前，由参与人登记自己
控制的公钥并审计密钥有效期；私钥不进入仓库，也不交给 AI。

## 执行入口

CLI 默认使用 v2 协议和 v2 公钥注册表：

```powershell
python scripts/validate_competition_qualification.py `
  --evidence qualification_runs/<campaign>/qualification_evidence_v2.json `
  --output qualification_runs/<campaign>/qualification_report_v2.json
```

人工可先生成规范化载荷，再用自己的 RSA 私钥签名并回填。工具只处理公开载荷和签名文件：

```powershell
python scripts/qualification_signature_payload.py prepare `
  --artifact qualification_runs/<campaign>/review_unsigned.json `
  --output qualification_runs/<campaign>/review.payload
openssl dgst -sha256 -sign qualification_owner_private.pem `
  -out qualification_runs/<campaign>/review.signature `
  qualification_runs/<campaign>/review.payload
python scripts/qualification_signature_payload.py attach `
  --artifact qualification_runs/<campaign>/review_unsigned.json `
  --signature qualification_runs/<campaign>/review.signature `
  --output qualification_runs/<campaign>/review_signed.json
```

验证历史 v1 证据时必须显式传入 v1 协议和注册表；验证结果仍使用 `blind_review_passed` 命名，不会被
自动转换为 v2 的 `human_assisted_review_passed`。
