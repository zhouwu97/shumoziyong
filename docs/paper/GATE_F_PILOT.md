# Gate F 论文实质完整性 Pilot

本 Pilot 将论文验收拆为三个不可互相替代的状态：

```text
F1 机械正确性
F2 实质内容完整性
F3 独立论文审核
```

`paper_content_contracts/2025_C_prediction_nipt_v1.yaml` 是 2025-C Prediction 专用合同，覆盖 Q1-Q4 的 Required Evidence Role。`scripts/paper/paper_content_quality.py` 只接受真实注册的 Formal Result、Validator、Claim 和论文位置；缺失任何关键绑定都会生成 `content_repair_required`。

## 生成 F2 报告

```powershell
$env:PYTHONPATH = "."
python scripts/paper/paper_content_quality.py `
  --contract paper_content_contracts/2025_C_prediction_nipt_v1.yaml `
  --registry <run>/paper_evidence_role_registry.json `
  --base-dir <run> `
  --claim-map <run>/paper_claim_map.json `
  --output <run>/paper_substantive_completeness_report.json `
  --before-registry <parent-run>/paper_evidence_role_registry.json `
  --delta-output <run>/paper_content_delta_report.json
```

## 派生 Gate F 状态

```powershell
python scripts/paper/gate_f_status.py `
  --f1-status passed `
  --completeness-report <run>/paper_substantive_completeness_report.json `
  --f3-status pending `
  --output <run>/paper_gate_f_status.json
```

F1 通过而 F2 失败时，状态只能是 `content_repair_required`，不会进入 F3。只有 F1、F2、F3 全部通过时，`eligible_for_gate_g` 才为 `true`。

`2025_C_prediction_experiment_plan.json` 只定义补实验和验证器的证据接口，不把计划本身当作结果。新增校准、消融、折外预测等事实必须创建新的 Formal Result、Validator 和 Claim Map。
