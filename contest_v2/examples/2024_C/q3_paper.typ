#import "../../paper/generated/results.typ": *
= 问题三：相关性、替代性与互补性

== 潜在因子模型

问题三保持问题二的所有边际区间，仅改变联合分布。设 $F_g$ 为作物类别因子，$F_k$ 为作物对因子，$H$ 为气候因子，$M$ 为市场因子，各因子和特异扰动相互独立且服从标准正态。对属于结构作物对 $k$ 的作物 $c$，需求潜变量为

$ Z_(D,c) = 0.25 F_(g(c)) + 0.60 s_c F_k + sqrt(1-0.25^2-0.60^2) epsilon_(D,c). $

替代代理对的两个 $s_c$ 取 $+1,-1$，互补代理对均取 $+1$；非结构作物省略第二项。亩产、价格和成本潜变量为

$ Z_(Y,c)=0.55H+sqrt(1-0.55^2)epsilon_(Y,c), $

$ Z_(P,c)=-0.35Z_(D,c)+0.45M+sqrt(1-0.35^2-0.45^2)epsilon_(P,c), $

$ Z_(C,c)=0.50M+sqrt(1-0.50^2)epsilon_(C,c). $

各潜变量经 $Phi$ 映射后代入问题二的边际公式，所以边际范围保持不变。因模型由独立因子的线性组合构造，协方差矩阵天然半正定。替代代理对为黄豆--黑豆、小麦--玉米、红薯--土豆、西红柿--茄子、菠菜--生菜；互补代理对为红豆--谷子、绿豆--高粱、豇豆--芸豆、青椒--黄瓜、榆黄菇--香菇。这些关系表示情景共同波动的结构假设，不等同于由市场数据估计的交叉价格弹性。

最终相关样本中的需求--价格、替代对和互补对平均相关系数分别为 #q3-demand-price-correlation、#q3-substitution-pair-correlation 和 #q3-complement-pair-correlation。

#figure(image("figures/demand_correlation.png", width: 70%), caption: [代表性作物需求潜变量的经验相关矩阵；坐标使用作物名称。])

== 相关风险再规划

将上述相关情景直接代入与 Q2 相同的期望--CVaR 目标。初始离散搜索的三个候选 gap 已降至 2%以内，但独立最终集风险效用未超过 Q2，故不采用。随后保留 Q2 已启用的作物组合，对面积进行三次 128 情景的连续相关风险再分配；Q2 原面积是该可行域中的显式可行基准。三次线性规划均达到 0 gap，最终最大 gap 为 #q3-max-mip-gap。

Q3 与 Q2 的七年面积 L1 差为 #q3-plan-l1-change。变化主要集中于水浇地第二季，例如 2025 年 D7 增加大白菜 13.79 亩，2026 年 D3 减少白萝卜 8.43 亩，2030 年 D6 增加红萝卜 8.00 亩。

#figure(image("figures/plan_changes.png", width: 78%), caption: [Q3 相对 Q2 的主要作物七年累计面积变化。])

== 最终评价

在 #q3-final-sample-count 个相关最终情景中，Q3 的均值、标准差、5%分位和 5% CVaR 为 #q3-correlated-mean-profit、#q3-correlated-std-profit、#q3-correlated-p05-profit 和 #q3-correlated-cvar05-profit。Q2 在同一情景中的均值与 5% CVaR 为 #q3-q2-correlated-mean-profit 和 #q3-q2-correlated-cvar05-profit。Q3 配对均值提高 #q3-paired-mean-improvement，逐情景改进概率为 #q3-paired-improvement-probability，5% CVaR 提高 #q3-cvar05-improvement，综合风险效用提高 #q3-risk-utility-improvement。

#figure(image("figures/paired_difference.png", width: 78%), caption: [相关情景与独立边际对照中，Q3 相对 Q2 的逐情景利润差。])

独立边际对照下 Q3 均值为 #q3-independent-mean-profit。相关模型带来的面积调整和收益改进都较小，因此合理结论不是“相关性大幅提高利润”，而是：在保持 Q2 作物格局时，相关风险目标支持一组可精确求解的小幅面积修正，并改善给定情景模型下的左尾收益。
