# Competition Production 六题隐藏盲测资格

PR-8 不把测试夹具、Codex 自评或未签名分数当作人工评审。资格活动使用六个固定匿名槽位
`Q01`—`Q06`，真实题目、答案、配对映射和评审记录只保存在 Git 忽略的
`qualification_runs/`。仓库只保存预注册协议、Schema、可信公钥注册表和最终脱敏报告。

## 证据顺序

1. 独立资格协调员先选择六题并在首次揭题、首次运行前签署题目材料 SHA-256 承诺根；锁定前不向运行者
   公开题目身份，评审结束后的证明不能替代这份预先签名。
2. Baseline 与 Treatment 在相同模型、推理强度、时限、工具权限和材料下分别运行，禁止跨臂读取。
3. 两个输出被处理为只含 `X/Y` 标签的匿名论文包；每个包由两名已登记公钥的真实人工评审签名评分，
   资格证据同时绑定公钥注册表文件的 SHA-256。
4. 全部 24 份评审签名完成后才能揭示 `X/Y` 映射；协调员再签署题目承诺根、映射摘要、全部运行指标与
   评审记录摘要，以及双盲过程证明。
5. `validate_competition_qualification.py` 复算模型质量、可执行方案率、论文质量、人工修订时间和结论越界率。
6. 指标通过只派生 `blind_review_passed`；另一个与完整证据摘要绑定的协调员签名才能派生
   `default_candidate`。即使达到该状态，报告仍固定 `new_problem_default_enabled=false`，默认包切换必须另行审计。

## Fail-closed 边界

以下任一情况都会回退到 `full_replay_passed`：题目在锁定前泄露、运行控制不等价、缺少 Formal
Result 验证、Treatment 致命错误、评审前揭示臂身份、签名无效、题目承诺或映射摘要漂移。指标未达标但
证据完整时最多保留为 `qualification_candidate`，不能解释为盲评通过。

当前 `policies/competition_qualification_authorities_v1.json` 明确为 `unconfigured`，因此当前仓库不能产生
真实资格结论。测试中的临时 RSA 密钥仅验证代码路径，不进入可信注册表，也不构成人工评审。

## 执行入口

```powershell
python scripts/validate_competition_qualification.py `
  --evidence qualification_runs/<campaign>/qualification_evidence.json `
  --output qualification_runs/<campaign>/qualification_report.json
```

在开始真实活动前，应由项目外的协调员登记至少两名独立人工评审和一名资格协调员的公钥，并以单独 PR
审计身份核验方式、密钥有效期与协议哈希。不得在看到运行结果后更换题目、阈值或评审人。

评审人可先生成规范化载荷，再用其自主管理的 RSA 私钥签名并回填；仓库工具不读取私钥：

```powershell
python scripts/qualification_signature_payload.py prepare `
  --artifact qualification_runs/<campaign>/review_unsigned.json `
  --output qualification_runs/<campaign>/review.payload
openssl dgst -sha256 -sign reviewer_private.pem `
  -out qualification_runs/<campaign>/review.signature `
  qualification_runs/<campaign>/review.payload
python scripts/qualification_signature_payload.py attach `
  --artifact qualification_runs/<campaign>/review_unsigned.json `
  --signature qualification_runs/<campaign>/review.signature `
  --output qualification_runs/<campaign>/review_signed.json
```
