# 通用比赛运行配置

适用场景：

- 题型尚未明确的新赛题；
- 需要先完成总控诊断，再判断是否加载预测、评价、优化或仿真插件；
- 比赛初期只允许拆题、识别数据和规划模型路线。

本运行配置必须加载：

1. `prompt_base/prompt_base_v1.0.md`
2. `checklists/gate_0_problem_diagnosis.md`
3. `checklists/gate_1_before_modeling.md`
4. `checklists/gate_2_before_coding.md`
5. `checklists/gate_3_before_writing.md`
6. `checklists/gate_4_final_review.md`

硬规则：

1. 先完成总控诊断，不直接写代码、论文或最终答案。
2. 每一问都必须说明：输入、处理、输出、与后续问题关系。
3. 每个候选模型都必须说明适用原因、数据需求、局限和替代方案。
4. 数据不足时必须给出缺失项、补充方式和降级路线。
5. 未经人工确认，不进入建模、代码和论文阶段。

输出要求：

1. 总控诊断表；
2. 子问题任务表；
3. 数据需求表；
4. 候选模型比较表；
5. 图表与结果计划；
6. 人工确认项；
7. 最大跑偏风险。

