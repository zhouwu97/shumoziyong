## 结果分析

<!--PARAGRAPH:P-B-RESULT role=report_result cards=-->问题一的超产滞销与超产折价情形，七年累计复算利润分别为 <!--FACT:CB-Q1-WASTE-PROFIT type=metric-->1730.80 万元<!--/FACT:CB-Q1-WASTE-PROFIT-->和 <!--FACT:CB-Q1-DISCOUNT-PROFIT type=metric-->5406.55 万元<!--/FACT:CB-Q1-DISCOUNT-PROFIT-->。

<!--PARAGRAPH:P-B-COMPARE role=compare_with_baseline cards=-->相较之下，折价销售情形<!--FACT:CB-Q1-SCENARIO-DIFFERENCE type=comparison-->较超产滞销情形增加 3675.75 万元<!--/FACT:CB-Q1-SCENARIO-DIFFERENCE-->。<!--FACT:BD-Q1-DISCOUNT-SCOPE type=boundary-->利润提高来自销售规则变化，不解释为同一目标函数下的算法改进或全局最优<!--/FACT:BD-Q1-DISCOUNT-SCOPE-->。

<!--PARAGRAPH:P-B-EXPLAIN role=explain_change cards=--><!--FACT:BD-Q1-SALES-RULE type=boundary-->超产部分在滞销情形不计收入，在折价情形按正常价格的一半计入<!--/FACT:BD-Q1-SALES-RULE-->，该规则与两个情形采用不同收益口径相对应。

## 模型边界

<!--PARAGRAPH:P-B-BOUNDARY role=state_boundary cards=--><!--FACT:BD-Q1-WASTE-SCOPE type=boundary-->仅覆盖当前官方材料、价格中点口径和 60 秒求解时限内的约束可行方案<!--/FACT:BD-Q1-WASTE-SCOPE-->；<!--FACT:BD-Q1-OPTIMALITY type=boundary-->所有主场景均存在非零 MIP gap，只能解释为时限内可行解，不能宣称全局最优<!--/FACT:BD-Q1-OPTIMALITY-->。
