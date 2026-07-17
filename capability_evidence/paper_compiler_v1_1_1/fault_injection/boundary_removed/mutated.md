## 结果分析

<!--PARAGRAPH:P-C-RESULT role=report_result cards=RC-RESULT-REPORT-001-->按统一的七年累计口径，超产滞销情形的复算利润为 <!--FACT:CB-Q1-WASTE-PROFIT type=metric-->1730.80 万元<!--/FACT:CB-Q1-WASTE-PROFIT-->；超产部分折价销售时为 <!--FACT:CB-Q1-DISCOUNT-PROFIT type=metric-->5406.55 万元<!--/FACT:CB-Q1-DISCOUNT-PROFIT-->。

<!--PARAGRAPH:P-C-COMPARE role=compare_with_baseline cards=RC-RESULT-COMPARE-001-->以滞销规则为参照，折价销售情形<!--FACT:CB-Q1-SCENARIO-DIFFERENCE type=comparison-->较超产滞销情形增加 3675.75 万元<!--/FACT:CB-Q1-SCENARIO-DIFFERENCE-->。不过，这一差额不能脱离比较口径解释：<!--FACT:BD-Q1-DISCOUNT-SCOPE type=boundary-->利润提高来自销售规则变化，不解释为同一目标函数下的算法改进或全局最优<!--/FACT:BD-Q1-DISCOUNT-SCOPE-->。

<!--PARAGRAPH:P-C-EXPLAIN role=explain_change cards=RC-RESULT-ATTRIBUTION-001-->差异所对应的模型规则是：<!--FACT:BD-Q1-SALES-RULE type=boundary-->超产部分在滞销情形不计收入，在折价情形按正常价格的一半计入<!--/FACT:BD-Q1-SALES-RULE-->。因此，结果反映的是收入计入方式变化，而不是求解算法本身的改进。

## 模型边界

<!--PARAGRAPH:P-C-BOUNDARY role=state_boundary cards=RC-BOUNDARY-SCOPE-001-->上述比较只在已冻结的材料与求解条件内成立。<!--FACT:BD-Q1-WASTE-SCOPE type=boundary-->仅覆盖当前官方材料、价格中点口径和 60 秒求解时限内的约束可行方案<!--/FACT:BD-Q1-WASTE-SCOPE-->；同时，。因此，论文应报告可行方案及其口径，不应给出全局最优性承诺。
