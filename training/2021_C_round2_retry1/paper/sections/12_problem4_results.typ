#import "../style.typ": three-line-table, paper-figure, source-note
#import "../style.typ": locked

= 问题四求解结果

== 产能构成与独立复算

#three-line-table(
  [表 10 #h(0.6em) 问题四模型预测最大周产能复算],
  (0.8fr, 1.7fr, 1fr, 1.6fr),
  ([原料], [损耗后到货量/m³], [换算系数], [产品等价量/m³]),
  (
    [A], [8,601.93], [$div 0.60$], [14,336.55],
    [B], [6,519.60], [$div 0.66$], [9,878.18],
    [C], [6,567.26], [$div 0.72$], [9,121.20],
    [合计], [21,688.79], [-], [#locked.problem4_weekly_capacity.display],
  ),
  alignments: (center, right, center, right),
  font-size: 9pt,
)

三类产品等价量相加得到 #locked.problem4_weekly_capacity.display m³/周，比基准 #locked.base_weekly_production.display m³/周增加 #locked.problem4_weekly_inventory_build.display m³/周，增幅为 #locked.problem4_increase_ratio.display。相应两周安全库存为 #locked.problem4_steady_safety_stock.display m³产品等价量。

== 从现有库存到稳态的两周爬坡

企业当前库存为 #locked.initial_inventory.display m³，低于稳态安全库存 #locked.problem4_steady_safety_stock.display m³，尚需补足 #locked.problem4_inventory_gap.display m³。维持基准生产时，每周按最大到货方案采购可净积累 #locked.problem4_weekly_inventory_build.display m³，故恰需 #locked.problem4_ramp_weeks.display 周完成补库。一个保守的 24 周实施方案为：第 1--2 周生产 #locked.base_weekly_production.display m³、按 #locked.problem4_weekly_capacity.display m³到货并逐周积累库存；第 3--24 周生产与到货均为 #locked.problem4_weekly_capacity.display m³，进入稳态。该过渡方案的 24 周平均产量为 #locked.problem4_transition_average.display m³/周，较基准提高 #locked.problem4_transition_increase_ratio.display。

#paper-figure(
  "figures/fig07_capacity.svg",
  [基准周需求与模型预测最大周产能。增幅为 #locked.problem4_increase_ratio.display，阴影范围用于强调两者差额。],
)

低损耗转运能力仍是关键限制。T3、T6 达到或接近上限，T8 的负载增至 3,826.52 m³/周，扩大原料供给后需要启用次优运输通道。进一步提高产能还需改善低损耗转运资源。

#source-note[#locked.problem4_weekly_capacity.display m³/周对应历史统计与平稳参数条件下、已提前建立相应安全库存后的确定性稳态上界。]
