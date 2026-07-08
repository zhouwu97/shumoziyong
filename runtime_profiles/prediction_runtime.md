# 预测类运行配置

适用题型：

- 时间序列预测；
- 趋势外推；
- 需求预测；
- 风险预测；
- 分类预测。

本运行配置必须加载：

1. `prompt_base/prompt_base_v1.0.md`
2. `checklists/gate_0_problem_diagnosis.md`
3. `checklists/gate_1_before_modeling.md`
4. `checklists/gate_2_before_coding.md`
5. `checklists/gate_3_before_writing.md`
6. `checklists/gate_4_final_review.md`

硬规则：

1. 先说明预测对象、预测粒度、预测步长和可用历史数据。
2. 必须区分解释型模型和预测型模型。
3. 必须设置训练集、验证集或滚动检验方式。
4. 必须给出误差指标和基线模型。
5. 禁止在数据量不足时直接使用复杂神经网络。

待扩展：

- `prompt_plugins/plugin_prediction_v1.md`
- 预测类优秀论文 patch；
- 预测类旧题 T3/T4 泛化测试记录。

