#let locked = json("../../paper_source_lock.json").claims

= 结论

本文在统一的数据语义下完成供应商评价、最少供应商选择、订购运输优化、原料结构优化和最大产能估计。问题一的基准权重下，S229、S361 和 S140 位列前三；小幅权重扰动保持头部集合稳定，但等权使 S140 从第 #locked.s140_base_rank.display 名降至第 #locked.s140_equal_rank.display 名，说明排序服务于给定业务偏好。

问题二证明基准生产至少需要 #locked.problem2_minimum_supplier_count.display 家供应商。正式单承运商词典序 MILP 的周相对采购成本为 #locked.problem2_weekly_cost.display，周损耗为 #locked.problem2_weekly_loss.display m³；相对透明基线，成本下降 0.0096%，损耗下降 0.8294%。问题三把 C 类周供货压缩到 #locked.problem3_weekly_c.display m³，总原料量降至 18,090.913003 m³/周，但产生 #locked.problem3_active_supplier_count.display 家正订购供应商和少量拆分运输。问题四得到#locked.problem4_weekly_capacity.display m³/周的模型预测最大周产能，较基准提高 #locked.problem4_increase_ratio.display。

Python 独立复算、MATLAB 交叉复现、硬约束检查、Excel 回读、公式重算和 #locked.fault_injection_total.display 项故障注入均通过；Python-MATLAB 最大数值误差为 $1.60 times 10^(-10)$。压力测试同时显示：需求增加 10%和关键供应商全期中断不可行，关键能力下降 10%在限时内状态未知。因而本文结论只在历史统计、平稳参数和已建模约束下成立，不构成未来供货、真实最优合作规模或长期保证产能的承诺。
