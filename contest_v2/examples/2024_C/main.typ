#import "generated/results.typ": *
#set page(paper: "a4", margin: (x: 2.1cm, y: 1.9cm), numbering: "1")
#set text(font: ("Microsoft YaHei", "SimSun"), size: 10.2pt, lang: "zh")
#set par(justify: true, leading: 0.68em)
#show heading.where(level: 1): set text(size: 15pt, weight: "bold")
#show heading.where(level: 2): set text(size: 12pt, weight: "bold")
#show figure.caption: set text(size: 9pt)

#align(center)[#text(size: 20pt, weight: "bold")[不确定环境下的乡村种植规划与风险决策]]

= 摘要

本文针对 2024--2030 年乡村种植安排建立多期混合整数规划。问题一以超产浪费和超产半价销售为两种收益机制，所得七年利润分别为 #q1-waste-profit 和 #q1-discount-profit；两种机制在本次求解中选择了相同面积配置，利润差来自超产处置价格。问题二把销量、亩产、成本与售价视为独立随机边际，以 $0.75 E(Pi)+0.25 "CVaR"_(10%)(Pi)$ 为目标重新规划；在 2048 个独立评价情景中，方案均值为 #q2-final-mean-profit，相对确定性基准提高 #q2-relative-mean-improvement。问题三用高斯潜在因子描述需求--价格负相关、替代代理、互补代理及共同气候和市场冲击，并在相关情景下重新分配面积；相对问题二的风险效用提高 #q3-risk-utility-improvement。三问均保留 2023 年轮作边界，满足土地适宜性、容量、重茬、三年豆类覆盖和分散度限制。结论仅适用于题面区间及本文披露的情景假设。

*关键词：* 种植规划；混合整数规划；条件风险价值；相关情景；样本外评价

= 问题重述与分析

全村包括露天耕地、水浇地、普通大棚和智慧大棚。需给出 2024--2030 年逐地块、逐季次、逐作物的种植面积，并分别处理两种超产销售机制、不确定边际以及相关性与替代互补关系。三问共享同一个物理可行域，差别集中在收益函数和情景生成方式。因此先建立统一面积--启用模型，再依次替换确定性目标、独立情景风险目标和相关情景风险目标。所有种植决策在情景实现前确定；情景实现后仅核算实际正常销量与超产量，不允许事后改变种植面积。

= 模型假设

1. 附件价格区间取中点；同一作物、同一季次在可种地块上的基准售价一致。
2. 实际产量不超过预期销量的部分按正常价格销售；超出部分按问题一指定的浪费或半价机制处理。
3. 露天启用组合的最小面积为地块面积的 20%，大棚启用组合至少 0.3 亩；同一作物、年份与季次最多分布在 8 个地块。二者作为便于田间管理的量化假设。
4. 不考虑跨年库存、临时新增土地和题面未给出的运输费用。
5. 问题二、三的分布是题面区间内的决策分析假设，不解释为由多年样本估计出的真实分布。

= 符号与统一数学模型

设 $y in Y={2024,...,2030}$，地块 $p in P$，季次 $s in S$，作物 $c in C$，情景 $omega in Omega$。$A_p$ 为地块面积，$l_p$ 为启用最小面积，$D_(y,s,c)^omega$ 为销量上限，$a_(p,s,c)^omega$、$b_(p,s,c)^omega$、$v_(s,c)^omega$ 分别为亩产、亩成本和售价。

决策变量 $x_(y,p,s,c)>=0$ 表示种植面积，$z_(y,p,s,c) in {0,1}$ 表示是否启用；水浇地模式变量 $m_(y,p) in {0,1}$ 区分单季水稻与两季蔬菜。情景销量变量 $q_(y,s,c)^omega$ 表示按正常价格出售的产量。总产量与销售收入为

$ Q_(y,s,c)^omega = sum_(p in P_(s,c)) a_(p,s,c)^omega x_(y,p,s,c), $

$ 0 <= q_(y,s,c)^omega <= Q_(y,s,c)^omega, quad q_(y,s,c)^omega <= D_(y,s,c)^omega, $

$ R_(y,s,c)^omega = v_(s,c)^omega [q_(y,s,c)^omega + alpha (Q_(y,s,c)^omega-q_(y,s,c)^omega)], $

其中 $alpha=0$ 表示超产浪费，$alpha=0.5$ 表示超产半价销售。单情景七年利润为

$ Pi^omega = sum_(y,s,c) R_(y,s,c)^omega - sum_(y,p,s,c) b_(p,s,c)^omega x_(y,p,s,c). $

主要物理约束如下：

$ l_p z_(y,p,s,c) <= x_(y,p,s,c) <= A_p z_(y,p,s,c), $

$ sum_(c in C_(p,s)) x_(y,p,s,c) <= A_p, quad sum_(p) z_(y,p,s,c) <= 8. $

水浇地用 $m_(y,p)$ 保证单季水稻与两季蔬菜互斥；普通大棚第一季种蔬菜、第二季种食用菌，智慧大棚两季均可种适宜蔬菜。对相邻可比季次加入

$ z_(t,p,c)+z_(t+1,p,c) <= 1, $

并把 2023 年实际种植视为 $t=0$ 的边界。对每个地块及任意连续三年窗口 $[r,r+2]$，豆类集合 $B$ 满足

$ sum_(y=r)^(r+2) sum_(s,c in B) x_(y,p,s,c) >= A_p. $

变量域、适宜性集合和 2023 边界均直接由官方附件生成；不适宜组合固定为零。问题二、三的 $x,z$ 对所有情景相同，只有 $q^omega$ 随销售实现变化，这给出了非预见性约束的具体含义。

#include "../questions/q1/paper.typ"
#include "../questions/q2/paper.typ"
#include "../questions/q3/paper.typ"

= 模型评价与结论边界

模型的优点是把物理约束、分段销售收入和情景风险目标置于统一框架，并使用互不重叠的训练、选择和最终评价样本控制选择偏差。局限在于最小面积、分散度及相关载荷属于建模假设；受限支持集能提供其内部的求解界，却不是全空间全局最优证明；Q3 的改进量较小，说明相关结构主要改变面积细节而非推翻 Q2 的作物格局。

问题一给出两种销售规则下的确定性可行规划；问题二确实改变了作物、地块、季次和年度配置，并在独立最终情景中提高均值和左尾收益；问题三在保留 Q2 离散格局的前提下进行相关风险面积再分配，获得小幅正风险效用改进。以上结论均为给定数据、分布与预算下的条件性结论。

= 参考文献

[1] 全国大学生数学建模竞赛组委会. 2024 年高教社杯全国大学生数学建模竞赛 C 题：农作物的种植策略, 2024.

[2] Rockafellar, R. T., Uryasev, S. Optimization of Conditional Value-at-Risk. *Journal of Risk*, 2(3): 21--41, 2000.

[3] Shapiro, A., Dentcheva, D., Ruszczynski, A. *Lectures on Stochastic Programming: Modeling and Theory*. SIAM, 2009.

[4] Virtanen, P. et al. SciPy 1.0: Fundamental Algorithms for Scientific Computing in Python. *Nature Methods*, 17: 261--272, 2020.

[5] Huangfu, Q., Hall, J. A. J. Parallelizing the dual revised simplex method. *Mathematical Programming Computation*, 10: 119--142, 2018.

= 附件说明

正式提交表包括问题一两种销售机制的 `result1_1.xlsx`、`result1_2.xlsx` 与问题二的 `result2.xlsx`。问题三面积表作为补充核对材料。各表均按年份、地块、季次和作物填写面积；金额统一以元计算，正文展示时换算为万元或百万元。
