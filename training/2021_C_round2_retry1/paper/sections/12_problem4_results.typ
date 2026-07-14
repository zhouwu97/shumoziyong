#import "../style.typ": three-line-table, paper-figure, source-note
#let locked = json("../../paper_source_lock.json").claims

= 问题四求解结果

== 产能构成与独立复算

#three-line-table(
  [表 10 #h(0.6em) 问题四模型预测最大周产能复算],
  (0.8fr, 1.7fr, 1fr, 1.6fr),
  ([原料], [损耗后到货量/m³], [换算系数], [产品等价量/m³]),
  (
    [A], [8,601.929368], [$div 0.60$], [14,336.548946],
    [B], [6,519.599100], [$div 0.66$], [9,878.180455],
    [C], [6,567.261164], [$div 0.72$], [9,121.196061],
    [合计], [21,688.789632], [-], [#locked.problem4_weekly_capacity.display],
  ),
  alignments: (center, right, center, right),
  font-size: 9pt,
)

三类产品等价量相加得到 #locked.problem4_weekly_capacity.display m³/周，比基准 #locked.base_weekly_production.display m³/周增加 5,135.925462 m³/周，增幅为 #locked.problem4_increase_ratio.display。相应两周安全库存为 66,671.850924 m³产品等价量。

#paper-figure(
  "figures/fig07_capacity.svg",
  [图 7 #h(0.5em) 基准周需求与模型预测最大周产能。增幅为 #locked.problem4_increase_ratio.display，阴影范围用于强调两者差额。],
)

低损耗转运能力仍是关键限制。T3、T6 达到或接近上限，T8 的负载增至 3,826.519524 m³/周，说明扩大原料供给后还需启用次优运输通道。继续提高产能不能只增加供应商能力，还需同步改善低损耗转运资源。

#source-note[#locked.problem4_weekly_capacity.display m³/周是历史统计与平稳参数条件下的“模型预测最大周产能”，不是企业未来可长期保证的产能。]
