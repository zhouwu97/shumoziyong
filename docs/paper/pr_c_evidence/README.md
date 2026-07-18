# PR C 重建负例证据快照

这些文件是 `pilot_2025c_reconstructed_negative_control_20260718` 的机器生成快照，供审查者复核 F2 负例边界。

| 文件 | 作用 |
| --- | --- |
| `paper_evidence_role_registry.json` | 现场注册表；明确没有已实现 Role |
| `paper_substantive_completeness_report.json` | 64 个 Required Role、0 个实现、覆盖率 0.0 的 F2 报告 |
| `paper_content_delta_report.json` | 新 clean Run 未产生技术或论文增量 |
| `paper_gate_f_status.json` | `F1 passed`、`F2 content_repair_required`、`F3 pending` |
| `run_evidence_manifest.json` | Run 现场证据路径、大小和 SHA-256 快照 |

这是 `reconstructed_negative_control` 的不可变零证据快照，不是原七页论文的复现证据，也不是 Formal Result、Validator、Candidate 或资格证据。项目 File Library 中已确认存在七页 `submission.pdf`，但尚未导入本 Run；后续必须新建 Run、冻结 PDF SHA，并从 PDF 实际内容提取非空 Registry，不能覆盖本目录快照。
