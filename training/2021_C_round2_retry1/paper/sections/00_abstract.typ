#import "../style.typ": abstract-title, keywords-cn, source-note
#let locked = json("../../paper_source_lock.json").claims

#abstract-title()
#v(0.45em)

针对板材生产企业未来 #locked.horizon_weeks.display 周的原材料保障、采购成本、运输损耗与产能估计问题，本文基于 #locked.supplier_count.display 家供应商和 #locked.transporter_count.display 家转运商的 #locked.historical_weeks.display 周历史记录，构建可解释的供应商评价与词典序 MILP/LP 决策框架。预处理严格区分“未订购且零供货”和“已订购但零供货”，以常规期望供货上限描述历史供应能力，并仅用非零运输记录估计损耗率。

问题一由产品等价供货能力、按单供货概率、稳定性和兑现率形成业务型加权评分；小幅单项权重扰动下前 50 名重合率不低于 98%，但等权时 S140 从第 #locked.s140_base_rank.display 名降至第 #locked.s140_equal_rank.display 名，说明排序依赖业务偏好。问题二先闭合最少供应商数的上下界：能力最强的前 25 家仅覆盖 #locked.problem2_top25_net_capacity.display m³/周，低于 #locked.base_weekly_production.display m³/周需求，而 #locked.problem2_minimum_supplier_count.display 家正式模型可行；随后以相对采购成本和运输损耗为词典序目标，求得单承运商方案，周成本为 #locked.problem2_weekly_cost.display，周损耗为 #locked.problem2_weekly_loss.display m³。

问题三按“C 类最少、总原料最少、损耗最少”求解，A、B、C 类周供货分别为 #locked.problem3_weekly_a.display、#locked.problem3_weekly_b.display 和 #locked.problem3_weekly_c.display m³，但出现 #locked.problem3_active_supplier_count.display 家正订购供应商和 #locked.problem3_split_supplier_weeks.display 个拆分供应商-周。问题四得到模型预测最大周产能 #locked.problem4_weekly_capacity.display m³，较基准提高 #locked.problem4_increase_ratio.display。独立复算显示三问硬约束违约数均为 #locked.hard_constraint_violations.display，Excel 回读、公式重算和 #locked.fault_injection_total.display 项故障注入全部通过。

压力测试中，需求增加 10%和关键供应商全期中断均#locked.demand_plus_10_status.display；关键供应商能力下降 10%仅返回#locked.key_supplier_minus_10_status.display。上述结论限定在历史统计与平稳参数假设内，不构成未来供货或长期产能保证。

#keywords-cn[供应商评价；混合整数线性规划；词典序优化；库存平衡；运输分配；敏感性分析]
