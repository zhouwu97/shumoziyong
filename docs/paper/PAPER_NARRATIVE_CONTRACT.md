# 论文叙事合同 v1

`paper_narrative_contract_v1` 把论文叙事视为当前 Run 的可审计证据，而不是自由生成的
润色步骤。它不生成结果、不修改正文，也不授予 Gate 4 PASS。

## 必需叙事

- 一句且仅一句中心论点；
- 一至两项核心贡献；
- 一项模型选择理由；
- 至少一项结果洞察；
- 至少一项行动建议；
- 至少一项局限性。

每个元素必须精确出现在 `.typ` 或 `.tex` 正文中，并绑定当前
`paper_claim_map.json` 中存在的 `C###` Claim ID。报告记录正文快照哈希、Claim Map
文件哈希和逐项定位；缺项、正文无对应文本或证据引用失效都会产生失败报告。

## 主论文泄漏

检查器扫描审计术语、Gate/Formal Result、仓库内部路径、生产清单名称和 64 位哈希。
这些内容可以保留在技术证据中，但不得进入面向评审者的主论文。

## Gate 4 顺序

1. 本仓只读重实现执行上游兼容预检，只输出报告与建议修复；
2. 本仓检查 Claim Map、模型—代码—正文一致性和论文叙事；
3. 选择模板并完成渲染、PDF 校验和逐页视觉复核；
4. `paper_production_manifest_v2` 聚合三阶段证据；
5. 独立 Gate 4 Validator 重建并校验生产清单后，才可形成论文候选清单。

叙事失败时 `submission_allowed=false`、`technical_report_allowed=true`。生产清单固定
`manifest_grants_gate4_pass=false`，兼容预检也固定无修改正文、重跑结果和判定 PASS 的权限。
