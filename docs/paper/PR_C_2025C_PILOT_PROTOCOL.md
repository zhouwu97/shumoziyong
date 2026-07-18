# PR C：2025-C Gate F 真实 Pilot 协议

## 冻结协议

```yaml
protocol_version: "1.0.0"
problem_id: "2025-C"
profile: prediction
pilot_type: reconstructed_negative_control_and_repair
source_candidate: unavailable_original_seven_page_paper
expected_initial_result: F2_fail
expected_final_result: F2_pass
qualification_usage: false
qualification_claim_allowed: false
```

本协议从 PR #40 合并后的 `main` 建立。官方题目材料和 2025-C Prediction 内容合同可以冻结；原七页论文、原论文 PDF/源码 SHA、可激活 Formal Result、Validator 和正式 Candidate 当前不可用。因此本轮只能登记为重建负例，不能声称已经复现原七页论文，也不能用于比赛资格或能力闭环声明。

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

只有取得原论文或经用户明确授权的完整重建源稿，并完成真实 Formal Result、独立 Validator、Claim Map 和论文位置绑定后，才可以继续执行 Gate 4 两阶段编排、F2 Pass、F3 真人审核和 Gate 5 封存。
