#import "../style.typ": three-line-table, paper-figure, source-note
#import "../style.typ": locked

= 数据预处理与供应商特征

== 数据语义与审计

附件 1 记录了 #locked.supplier_count.display 家供应商连续 #locked.historical_weeks.display 周的订货量与供货量，附件 2 给出 #locked.transporter_count.display 家转运商同期的运输损耗率。A、B、C 类供应商分别为 #locked.material_supplier_a.display、#locked.material_supplier_b.display、#locked.material_supplier_c.display 家。数据没有数值缺失和负值。预处理重点在于按题面含义处理不同类型的零值。

#three-line-table(
  [表 3 #h(0.6em) 数据质量审计摘要],
  (1.25fr, 0.8fr, 0.8fr, 0.8fr, 1.6fr),
  ([项目], [订货量], [供货量], [损耗率], [处理]),
  (
    [数值缺失], [0], [0], [0], [无需填补],
    [零值], [#locked.not_ordered_zero_supply.display], [#locked.ordered_zero_supply.display], [479], [保留并区分语义],
    [负值], [0], [0], [0], [无异常],
    [供货大于订货], [-], [#locked.supply_greater_than_order.display], [-], [题面允许，保留],
    [正值 IQR 异常], [#locked.outlier_count.display], [合并统计], [-], [仅标记，不删除],
  ),
  alignments: (left, center, center, center, left),
  font-size: 8.8pt,
)

共有 #locked.not_ordered_zero_supply.display 个“未订购且零供货”记录、#locked.ordered_zero_supply.display 个“已订购但零供货”记录和 #locked.ordered_positive_supply.display 个正供货记录。前一类不进入按单供货概率的失败计数，后一类保留为真实履约失败。两类记录混在一起会影响供应可靠性和正供货条件下的履约能力估计。

题面中的损耗率为 0 表示该周未由相应转运商承运，损耗率均值只由正记录计算。T1 至 T8 的预测损耗率依次为 1.90%、0.92%、0.19%、1.57%、2.89%、0.54%、2.08% 和 1.01%。正值原料量按 $Q_3 + 3 I Q R$ 规则筛查，阈值为 #locked.outlier_threshold.display m³，共标记 #locked.outlier_count.display 个记录。大额供货可能反映头部供应商的能力，故不截尾、不平滑；其未来可重复性由模型假设限定。

== 分布特征与建模影响

#paper-figure(
  "figures/fig02_supplier_metrics.svg",
  [供应商四项评价指标分布。能力呈明显长尾，服务概率、稳定性和兑现率则更分散；虚线表示中位数。],
)

图 2 显示，主要产品等价能力集中在少数供应商；规模较大的供应商，其按单供货概率、稳定性或兑现率未必同样高。问题一据此采用多指标评价，问题二至四则继续使用能力、运输和库存约束求解。

#source-note[数据处理保留全部官方记录。历史统计量用于条件期望估计。]
