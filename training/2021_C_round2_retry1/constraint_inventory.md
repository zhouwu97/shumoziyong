# 约束清单

| ID | 题面原意 | 数学表达计划 | 索引 | 数据来源 | 单位 | 边界情况 | 独立检查 |
|---|---|---|---|---|---|---|---|
| C01 | 周生产需求 | `I[t-1]+A[t]-I[t]>=D` | t | 题面 | 产品m³ | D随问题4决策 | production_requirement |
| C02 | 三类原料转换 | `A[t]=Σr/j x[r,t,j](1-l[j])/q[r]` | r,t,j | 题面 | 产品m³ | q=(.6,.66,.72) | material_conversion |
| C03 | 供应能力 | `Σj x[r,t,j]<=cap[r]` | r,t | 附件1 | 原料m³ | cap=0不可用 | supplier_capacity |
| C04 | 订货与供货 | `s[r,t]=alpha[r]o[r,t]` 为导出合同 | r,t | 附件1 | 原料m³ | alpha=0不选 | order_transport_consistency |
| C05 | 最少供应商 | 问题2先最小化集合基数 | r | 附件1 | 家 | 仅问题2硬目标 | supplier_selection |
| C06 | 周库存平衡 | `I[t]=I[t-1]+A[t]-D` | t | 题面 | 产品m³ | 不可跳期 | inventory_balance |
| C07 | 两周安全库存 | `I[t]>=2D` | t | 题面 | 产品m³ | 初期同样满足 | terminal/initial_inventory |
| C08 | 承运能力 | `Σr x[r,t,j]<=6000` | t,j | 题面 | 原料m³ | 8家分别检查 | transporter_capacity |
| C09 | 单转运商偏好 | 问题2 `Σj y[r,t,j]<=1`；问题3/4软报告 | r,t,j | 题面 | - | “尽量”非硬禁令 | transporter_assignment |
| C10 | 同期转运汇总 | 按j、t聚合运输量 | t,j | 题面 | 原料m³ | 不混周 | transporter_capacity |
| C11 | 运输损耗 | `loss=Σr x*l[j]` | t,j | 附件2 | 原料m³ | 0为未运输 | transport_loss |
| C12 | 接收量 | `recv=Σj x(1-l[j])` | r,t | 题面/附件2 | 原料m³ | 不能等同供货 | arrival_quantity |
| C13 | 初始库存 | `I[0]=2D` | - | 建模假设 | 产品m³ | 题面未给绝对值 | initial_inventory |
| C14 | 期末库存 | `I[24]>=2D` | - | 题意延续 | 产品m³ | 不透支下一期 | terminal_inventory |
| C15 | 非负性 | `o,s,x,recv,I>=0` | 全部 | 题面 | 对应单位 | 浮点容差 | order_nonnegative |
| C16 | 整数/连续性 | 原料量连续；问题2指派二元 | r,t,j | 建模选择 | - | 不对体积强行取整 | solver/status |
| C17 | 时间跨度 | 历史240周、计划24周 | t | 题面 | 周 | 防止周错位 | template consistency |
| C18 | 模板字段 | 402行、24周、8转运商列组 | r,t,j | 官方模板 | 原料m³ | 零填空白 | output_template_consistency |
| C19 | 订购/转运一致 | `s=Σj x` | r,t | 导出解 | 原料m³ | 不可手改一侧 | order_transport_consistency |
| C20 | 单位转换 | 先除q后汇总 | r,t | 题面 | 产品m³ | 不直接加原料m³ | units_and_aggregation |
| C21 | 目标聚合 | 成本/损耗按周、原料、承运商求和 | r,t,j | 模型 | 相对成本/原料m³ | 词典序不任意加权 | recompute_objective |
