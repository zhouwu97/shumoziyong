#import "../style.typ": abstract-title, keywords-cn, source-note, locked

#abstract-title()
#v(0.45em)

针对板材生产企业未来 #locked.horizon_weeks.display 周的原材料保障、采购成本、运输损耗与产能估计问题，本文利用 #locked.supplier_count.display 家供应商、#locked.transporter_count.display 家转运商的 #locked.historical_weeks.display 周记录，建立供应商评价和词典序 MILP/LP 模型。预处理时分别处理“未订购且零供货”与“已订购但零供货”，供应能力取常规期望供货上限，损耗率则由非零运输记录估计。

问题一按产品等价供货能力、按单供货概率、稳定性和兑现率评分。单项权重小幅扰动时，前 50 名重合率不低于 98%；采用等权后，S140 由第 #locked.s140_base_rank.display 名变为第 #locked.s140_equal_rank.display 名，反映出排序会随业务偏好变化。问题二先确定最少供应商数：能力最强的前 25 家仅覆盖 #locked.problem2_top25_net_capacity.display m³/周，未达到 #locked.base_weekly_production.display m³/周需求；#locked.problem2_minimum_supplier_count.display 家的正式模型可行。在全部 #locked.supplier_count.display 家候选中，模型固定供应商数量后依次优化相对采购成本和运输损耗，得到单承运商方案，周成本为 #locked.problem2_weekly_cost.display，周损耗为 #locked.problem2_weekly_loss.display m³。

问题三以“C 类最少、总原料最少、损耗最少”为顺序目标，A、B、C 类周供货分别为 #locked.problem3_weekly_a.display、#locked.problem3_weekly_b.display 和 #locked.problem3_weekly_c.display m³。该方案涉及 #locked.problem3_active_supplier_count.display 家正订购供应商和 #locked.problem3_split_supplier_weeks.display 个拆分供应商-周。问题四的模型预测最大周产能为 #locked.problem4_weekly_capacity.display m³，较基准提高 #locked.problem4_increase_ratio.display。三问的独立复算中，硬约束违约数均为 #locked.hard_constraint_violations.display，Excel 回读、公式重算和 #locked.fault_injection_total.display 项故障注入均通过。

压力测试表明，需求增加 10%时已有可行解，成本最优性仍待完成证明；关键供应商能力下降 10%和全期中断时，均得到全局最优可行解，对应供应商数为 26 和 27。文中的供货和产能结论使用历史统计与平稳参数，适用于本文设定的模型条件。

#keywords-cn[供应商评价；混合整数线性规划；词典序优化；库存平衡；运输分配；敏感性分析]
