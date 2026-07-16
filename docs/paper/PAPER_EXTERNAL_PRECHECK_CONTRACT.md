# 论文外部兼容预检合同

`scripts/paper/external_precheck.py` 是对固定上游 `writing_check.sh` 检查意图的本仓只读重实现。它只读取已提交的
来源路径与 SHA-256，不执行 `.vendor` 中的脚本或任何 Skill。当前检查覆盖占位文本、内部术语、图片路径与图注。

预检开始和结束时都必须对全部 `.typ`/`.tex` 正文生成逐文件哈希及组合哈希。两次快照不同即输出
`mutation_detected`，不得把该报告用于提交候选。检查发现的问题只能写入独立的 `suggested_repairs.json`；
`automatic_apply=false`，Adapter 无权修改正文、重跑建模结果或决定 Gate 4 PASS。

```powershell
python scripts/paper/external_precheck.py `
  --paper-root path/to/paper `
  --report path/to/artifacts/paper_external_precheck_report.json `
  --suggestions path/to/artifacts/suggested_repairs.json
```

`paper_production_manifest_v2` 按以下顺序聚合当前 Run 证据：外部兼容预检 → 本仓 Claim Map 与
模型—代码—正文一致性 → 模板、渲染、统一验证与逐页视觉报告。该清单只产生 `submission_candidate` 或
`technical_report_only`，并固定 `manifest_grants_gate4_pass=false`；Gate 4 仍由本仓独立 Validator 裁决。
