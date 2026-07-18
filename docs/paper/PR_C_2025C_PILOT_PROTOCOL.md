# PR C：2025-C Gate F 真实 Pilot 协议

## 冻结协议

```yaml
protocol_version: "1.1.0"
problem_id: "2025-C"
profile: prediction
pilot_type: original_paper_baseline_with_unrecovered_structured_evidence
source_candidate: submission.pdf
source_candidate_status: available_original_seven_page_pdf
source_candidate_origin: project_file_library
source_pdf_page_count: 7
source_pdf_sha256: null
source_code_status: unavailable
formal_result_status: not_yet_recovered
validator_status: not_yet_recovered
candidate_manifest_status: not_yet_recovered
expected_initial_result: F2_fail
expected_final_result: F2_pass
qualification_usage: false
qualification_claim_allowed: false
```

本协议从 PR #40 合并后的 `main` 建立。项目 File Library 中已确认存在七页 `submission.pdf`，但它尚未导出到受控 Run，因此 PDF SHA、页面锚点和结构化证据仍待冻结。原论文源稿、Formal Result、Validator 和正式 Candidate 尚未恢复；在导入和绑定完成前，现有 `4ece55d` 只能继续作为不可变零证据检查点，不能声称已经复现原七页论文，也不能用于比赛资格或能力闭环声明。

## 允许的证据

- 新 Run 的初始化 Manifest、Runtime Pack 和合同继承 SHA；
- 现场生成的 Evidence Role Registry；
- 由 `paper_content_quality.py` 生成的 F2 完整性报告和 Content Delta；
- 由 `gate_f_status.py` 生成的 `content_repair_required` 状态；
- 所有失败原因和输入文件 SHA。

## 禁止的证据替代

- 不把实验计划当作 Formal Result；
- 不把官方题目材料当作论文正文；
- 不手写 `paper_gate_f_status.json` 冒充生产派生结果；
- 不创建没有真实证据绑定的 Candidate；
- 不将重建负例登记为 `real_2025c_negative_control` 或资格证据。

## 后续解锁条件

只有将 `submission.pdf` 导入新的受控 Run、冻结 PDF SHA、完成 Claim Map 和论文位置绑定，并恢复或独立重算真实 Formal Result、Validator 后，才可以继续执行 Gate 4 两阶段编排、F2 Pass、F3 真人审核和 Gate 5 封存。
