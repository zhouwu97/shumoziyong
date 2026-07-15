#import "../style.typ": three-line-table, paper-figure
#import "../style.typ": locked

= 问题三求解结果

== 原料结构变化

#three-line-table(
  [表 8 #h(0.6em) 问题三周均原料使用结构],
  (0.8fr, 1.5fr, 1.5fr, 1.6fr),
  ([原料], [期望供货量/m³], [损耗后到货量/m³], [产品等价量/m³]),
  (
    [A], [#locked.problem3_weekly_a.display], [8,601.93], [14,336.55],
    [B], [#locked.problem3_weekly_b.display], [6,519.60], [9,878.18],
    [C], [#locked.problem3_weekly_c.display], [2,869.39], [3,985.27],
    [合计], [18,090.91], [17,990.92], [28,200.00],
  ),
  alignments: (center, right, right, right),
  font-size: 8.9pt,
)

与问题二相比，A 类周供货由 7,702.69 m³增至 #locked.problem3_weekly_a.display m³，C 类由 5,235.34 m³降至 #locked.problem3_weekly_c.display m³，总原料量由 18,378.94 m³降至 18,090.91 m³。三类损耗后产品等价量之和仍为 #locked.base_weekly_production.display m³/周，因此结构变化没有牺牲生产需求。

#paper-figure(
  "figures/fig06_material_mix.svg",
  [问题二与问题三的周均原料结构。问题三提高 A 类用量、压低 C 类用量，并减少总原料体积。],
)

== 供应商分散与拆分运输

#three-line-table(
  [表 9 #h(0.6em) 问题三供应商分散性与拆分运输],
  (1.6fr, 1.4fr, 2.3fr),
  ([指标], [数值], [解释]),
  (
    [正订购供应商数], [#locked.problem3_active_supplier_count.display 家], [连续 LP 未惩罚启用数量],
    [最小单供应商周订购量], [1.02 m³], [不是容差附近伪非零],
    [$P_10$/中位数/$P_90$], [1.69/5.43/134.49], [小额合作方较多],
    [小于 10 m³的供应商], [188 家], [占正订购供应商 61.64%],
    [小于 100 m³的供应商], [268 家], [占正订购供应商 87.87%],
    [拆分供应商-周], [#locked.problem3_split_supplier_weeks.display / 7,320], [发生率 0.66%],
    [次要承运商运输量占比], [5.06%], [体积影响不能忽略],
    [单周最多承运商数], [2 家], [拆分有限但真实存在],
  ),
  alignments: (left, right, left),
  font-size: 8.55pt,
)

#locked.problem3_active_supplier_count.display 家供应商不是推荐合作规模，而是目标中没有固定启用成本的结果。拆分发生次数仅占 0.66%，但拆分周涉及 16.84%的总运输量，次要承运商承担 5.06%；因此只报告次数会低估调度影响。若企业要求更集中、严格单承运商的方案，应在新模型中加入启用成本、最小订单量或拆分惩罚，并重新求解，而不能事后删单。
