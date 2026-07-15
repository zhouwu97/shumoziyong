#import "../style.typ": three-line-table, paper-figure
#import "../style.typ": locked

= 敏感性与压力测试

权重敏感性已在表 5 和图 4 中说明。对问题二，需求、损耗率和关键供应商能力情景均重新求解，而不是把原方案机械代入新参数。敏感性分析用于识别结论依赖的参数与失效方向 [7]，不等于证明所有扰动下均稳健。

#three-line-table(
  [表 11 #h(0.6em) 问题二压力测试],
  (1.7fr, 1fr, 1fr, 1.4fr, 1.7fr),
  ([情景], [状态], [供应商数], [周相对成本], [解释]),
  (
    [需求 -10%], [可行], [21], [18,412.65], [所需供应商明显减少],
    [基准需求], [可行], [26], [20,463.57], [正式方案],
    [需求 +10%], [可行未证最优], [#locked.demand_plus_10_minimum_supplier_count.display], [#locked.demand_plus_10_cost_incumbent.display], [基数已证；成本阶段限时],
    [损耗率 $times 0.8$], [可行], [26], [20,441.16], [成本略降],
    [损耗率 $times 1.2$], [可行], [26], [20,486.31], [仍可行但代价上升],
    [关键能力 -10%], [最优可行], [26], [20,463.98], [替代组合吸收能力下降],
    [关键供应商全期中断], [最优可行], [27], [20,462.81], [增加 1 家后恢复可行],
  ),
  alignments: (left, center, center, right, left),
  font-size: 8.15pt,
)

#paper-figure(
  "figures/fig08_stress.svg",
  [问题二压力测试。完整最优情景显示供应商数；需求增加 10%单独标记为已找到可行解但未证明成本最优。],
)

需求增加 10%时，供应商基数阶段已证明最少需 #locked.demand_plus_10_minimum_supplier_count.display 家；#locked.demand_plus_10_limited_stage.display 在 60 秒内获得周相对成本 #locked.demand_plus_10_cost_incumbent.display 的可行 incumbent，当前下界为 #locked.demand_plus_10_cost_best_bound.display，相对 MIP 间隙为 #locked.demand_plus_10_cost_gap.display，但尚未完成最优性证明。因此不能写成全局最优或不可行。关键供应商能力下降 10%和全期中断在完整模型中均得到全局最优可行解，分别需要 26 和 27 家供应商，说明开放全部候选后可通过替代组合恢复可行。实际部署仍应保留备用供应商，并在需求增长前扩充低损耗运输能力。
