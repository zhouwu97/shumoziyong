#import "../style.typ": three-line-table, paper-figure
#import "../style.typ": locked

= 问题一：供应商重要性评价

== 指标定义

令历史订货量和供货量分别为 $O_(i tau)$、$S_(i tau)$，$tau = 1, dots, 240$，已订购周集合为 $Omega_i^O = {tau: O_(i tau) > 0}$。按单供货概率定义为

$
  p_i = frac(sum_(tau in Omega_i^O) 1(S_(i tau) > 0), abs(Omega_i^O)).
$ <eq-order-service>

@eq-order-service 只在实际下单周内计数。正供货均值和常规期望供货上限为

$
  overline(S)_i^+ = frac(sum_(tau: S_(i tau) > 0) S_(i tau), sum_tau 1(S_(i tau) > 0)),
  quad u_i = overline(S)_i^+ p_i.
$ <eq-regular-capacity>

@eq-regular-capacity 将发生正供货时的平均规模与按单供货概率结合。评价中的能力指标取产品等价能力 $C_i = u_i / q_(k(i))$。稳定性使用正供货周变异系数的单调变换：

$
  V_i = frac(sigma(S_(i tau) mid S_(i tau) > 0), overline(S)_i^+),
  quad G_i = frac(1, 1 + V_i).
$ <eq-stability>

兑现率定义为历史总供货量与总订货量之比，并截断到 1：

$
  F_i = min(frac(sum_tau S_(i tau), sum_tau O_(i tau)), 1).
$ <eq-fulfillment>

对 $C_i,p_i,G_i,F_i$ 分别进行极差标准化：

$
  tilde(X)_i = frac(X_i - min_m X_m, max_m X_m - min_m X_m).
$ <eq-minmax>

@eq-stability、@eq-fulfillment 和 @eq-minmax 分别刻画供货波动、累计兑现程度及跨指标可比性。

最终综合重要性得分为

$
  H_i = 0.50 tilde(C)_i + 0.25 tilde(p)_i + 0.15 tilde(G)_i + 0.10 tilde(F)_i.
$ <eq-score>

@eq-score 以保障生产规模为首要业务偏好，随后考虑订单能否发生、供货波动和累计兑现程度。权重不是统计意义上的客观真值，因此排序必须与敏感性分析共同解释。多属性加权评分的思想可追溯至加性效用与多属性决策方法 [1-2]。

== 评价结果

#three-line-table(
  [表 4 #h(0.6em) 重要性得分前 10 名供应商],
  (0.8fr, 1.2fr, 0.8fr, 1.2fr),
  ([排名], [供应商], [类型], [综合得分]),
  (
    [1], [#locked.top_supplier_1.display], [A], [0.900], [2], [#locked.top_supplier_2.display], [C], [0.801],
    [3], [S140], [B], [0.706], [4], [S201], [A], [0.702],
    [5], [S275], [A], [0.673], [6], [S108], [B], [0.670],
    [7], [S329], [A], [0.669], [8], [S340], [B], [0.663],
    [9], [S282], [A], [0.652], [10], [S131], [B], [0.620],
  ),
  alignments: center,
  font-size: 9.2pt,
)

#paper-figure(
  "figures/fig03_top20_suppliers.svg",
  [基准业务权重下综合得分前 20 名。灰度与填充纹理区分原料类别，排序表示给定权重下的候选优先级。],
)

#locked.top_supplier_1.display 和 #locked.top_supplier_2.display 在各权重测试中保持前两名。S140 在基准权重下列第 #locked.s140_base_rank.display 名，但等权时降至第 #locked.s140_equal_rank.display 名，表明其优势主要来自高权重的能力指标。

#three-line-table(
  [表 5 #h(0.6em) 排名权重敏感性],
  (1.8fr, 1fr, 1fr, 1.2fr, 0.9fr),
  ([权重方案], [前 10 重合], [前 50 重合率], [Spearman 系数], [S140 名次]),
  (
    [当前权重], [10/10], [100%], [1.000], [3],
    [单项相对扰动 $plus.minus 10%$], [至少 9/10], [至少 98%], [至少 1.000], [3 或 4],
    [等权], [7/10], [#locked.rank_min_top50_overlap.display], [0.976], [53],
  ),
  alignments: (left, center, center, center, center),
  font-size: 8.8pt,
)

#paper-figure(
  "figures/fig04_rank_sensitivity.svg",
  [供应商排序的权重敏感性。小幅单项扰动下头部集合稳定，等权方案则暴露 S140 的名次依赖。],
)

因此，前 50 名用于形成重点候选池，而非替代后续的可行性优化。完整前 50 名见结果附件 `results/supplier_analysis.json`，不与本文附录编号混用。
