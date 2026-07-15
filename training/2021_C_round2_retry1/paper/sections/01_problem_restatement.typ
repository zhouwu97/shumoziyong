#import "../style.typ": locked

= 问题重述

== 问题背景

某板材生产企业以 A、B、C 三类植物纤维原料组织生产。企业当前每周基准产能为 #locked.base_weekly_production.display m³。生产 1 m³ 产品分别需要 A、B、C 类原料 #locked.raw_per_product_a.display、#locked.raw_per_product_b.display、#locked.raw_per_product_c.display m³。三类原料可以替代生产，但其单位产品消耗量和采购价格不同：若 C 类单位采购价格取 1，则 B、A 类相对价格分别为 #locked.relative_cost_b.display 和 #locked.relative_cost_a.display。

供应商的实际供货量可能高于或低于订货量，企业会收购其实际供货。原料由 #locked.transporter_count.display 家转运商承担运输，各转运商每周运输能力均为 #locked.transporter_weekly_capacity.display m³，运输过程中存在损耗。为维持连续生产，企业希望库存尽可能不少于 #locked.safety_stock_weeks.display 周生产需求；在运输组织上，通常希望同一供应商同一周的货物尽量由一家转运商承担。

附件 1 给出 #locked.supplier_count.display 家供应商连续 #locked.historical_weeks.display 周的订货量与供货量，附件 2 给出 #locked.transporter_count.display 家转运商同期的运输损耗率。供应商中 A、B、C 类分别有 #locked.material_supplier_a.display、#locked.material_supplier_b.display、#locked.material_supplier_c.display 家。题目要求利用历史记录评价供应商、制定未来 #locked.horizon_weeks.display 周订购和转运方案，并估计技术改造后的最大产能。

== 需要解决的问题

#set par(first-line-indent: 0pt)

1. *供应商重要性评价。* 量化供应商的供货规模、供货发生概率、稳定性和订单兑现能力，建立可解释的综合评价方法，从 #locked.supplier_count.display 家供应商中筛选 50 家重要供应商，并分析排序对权重的敏感性。

2. *最少供应商与经济运输。* 在满足每周 #locked.base_weekly_production.display m³产品需求、两周安全库存、供应能力和转运能力等约束的前提下，确定最少供应商数量；在该数量下制定未来 #locked.horizon_weeks.display 周订购方案与低损耗转运方案。

3. *原料结构与损耗优化。* 在保障生产的基础上尽量多使用单位产品耗量较低的 A 类原料、少使用 C 类原料，同时减少原料采购运输总量和运输损耗，并披露连续运输模型可能产生的供应商分散与拆分运输问题。

4. *最大可持续周产能估计。* 在全部供应商历史能力估计、转运能力和损耗约束下，求技术改造后的模型预测最大周产能，并给出与该产能一致的未来 #locked.horizon_weeks.display 周订购和运输方案。

#set par(first-line-indent: (amount: 2em, all: true))

四问由“候选识别”逐步推进到“最小规模决策”“结构优化”和“产能边界估计”。供应商评价只提供候选信息，不能代替后续优化模型中的可行性、成本、损耗和库存约束。
