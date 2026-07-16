# 论文图形契约

全部图形由既有结果数据生成，不调用求解器。

## 图 1 | 01_supplier_metric_distributions

- 核心结论：供应商能力高度集中，可靠性指标的离散说明仅按规模排序不足以评价保障作用。
- 图形类型：quantitative grid
- 证据链：四项评价指标在 402 家供应商上的归一化分布及其中位数。
- 审稿风险：归一化会隐藏原始单位，因此源数据同时保留原始值和归一化值。
- 源数据：source_data/01_supplier_metric_distributions.csv

## 图 2 | 03_material_capacity_distribution

- 核心结论：三类原料的供应商数量相近，但产品等价常规期望供货上限分布存在差异。
- 图形类型：quantitative grid
- 证据链：类别计数与按类别分组的产品等价能力分布。
- 审稿风险：箱线图隐藏极端点，源数据保留全部 402 家供应商。
- 源数据：source_data/03_material_capacity_distribution.csv

## 图 3 | 02_supplier_top20_scores

- 核心结论：在给定业务权重下，前 20 家供应商形成明确但非绝对客观的候选排序。
- 图形类型：quantitative grid
- 证据链：前 20 家综合得分、排名和原料类别。
- 审稿风险：权重具有主观业务属性，必须与图 4 的敏感性结果联合解释。
- 源数据：source_data/02_supplier_top20_scores.csv

## 图 4 | 11_rank_weight_sensitivity

- 核心结论：小幅单项权重扰动下整体排序稳定，但等权会使 S140 从第 3 降至第 53。
- 图形类型：quantitative grid
- 证据链：前 10 重合数、前 50 重合率、Spearman 相关系数及 S140 名次。
- 审稿风险：不能把局部稳定性解释为权重客观或排序绝对稳健。
- 源数据：source_data/11_rank_weight_sensitivity.csv

## 图 5 | 04_problem2_weekly_orders

- 核心结论：平稳参数使问题二的周订购结构在 24 周保持一致。
- 图形类型：quantitative grid
- 证据链：A/B/C 类及总订购量的逐周轨迹。
- 审稿风险：恒定轨迹来自平稳假设，不代表真实未来不存在周波动。
- 源数据：source_data/04_problem2_weekly_orders.csv

## 图 6 | 05_problem2_transporter_load

- 核心结论：低损耗转运商 T3、T6 饱和，T2 接近饱和，构成问题二的运输瓶颈。
- 图形类型：quantitative grid
- 证据链：8 家转运商 24 周负载及 6000 m3/周容量上限。
- 审稿风险：热图必须使用固定 0-6000 标尺，避免跨转运商比较失真。
- 源数据：source_data/05_problem2_transporter_load.csv

## 图 7 | 06_problem2_inventory_trajectory

- 核心结论：损耗后到货恰好满足周需求，库存始终贴合两周安全下界。
- 图形类型：quantitative grid
- 证据链：库存轨迹与逐周产品等价到货量。
- 审稿风险：库存贴边是模型目标和无仓储奖励共同造成，不能泛化为现实最优库存。
- 源数据：source_data/06_problem2_inventory_trajectory.csv

## 图 8 | 07_problem3_material_mix

- 核心结论：问题三的词典序目标提高 A 类、压低 C 类并减少总原料用量。
- 图形类型：quantitative grid
- 证据链：问题二与问题三的 A/B/C 周均期望供货量对比。
- 审稿风险：结构改善不等于运营更易执行，需结合供应商分散性解释。
- 源数据：source_data/07_problem3_material_mix.csv

## 图 9 | 08_problem3_transport_splitting

- 核心结论：问题三拆分发生频率低，但涉及的运输量占比不可忽略。
- 图形类型：quantitative grid
- 证据链：拆分供应商-周计数和拆分运输量构成。
- 审稿风险：计数占比与体积占比口径不同，图注必须分别说明分母。
- 源数据：source_data/08_problem3_transport_splitting.csv

## 图 10 | 09_problem4_capacity_comparison

- 核心结论：历史能力与平均损耗假设下的模型预测周产能比基准高 18.2125%。
- 图形类型：quantitative grid
- 证据链：基准周产能与模型预测最大周产能。
- 审稿风险：必须标为模型预测值，不能写成保证产能。
- 源数据：source_data/09_problem4_capacity_comparison.csv

## 图 11 | 10_sensitivity_and_stress_tests

- 核心结论：完整候选网络可承受关键供应商能力下降和全期中断；需求增加10%时找到可行解但未证明成本最优。
- 图形类型：quantitative grid
- 证据链：可行情景的供应商数量和全部压力情景的求解状态。
- 审稿风险：feasible_not_proven_optimal 不得写成全局最优或不可行。
- 源数据：source_data/10_sensitivity_and_stress_tests.csv
