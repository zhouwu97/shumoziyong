#let locked = json("../../paper_source_lock.json").claims

= 问题三：原料结构与损耗优化模型

== 三阶段词典序目标

问题三保留式 @eq-order-supply、@eq-flow-balance 至 @eq-safety-stock 的供货、运输和库存关系，不再限制最少供应商数，也不把采购价格作为第一目标。第一阶段最小化 C 类原料期望供货量：

$
  Z_3 = min sum_t sum_(i: k(i) = C) s_(i t).
$ <eq-p3-c>

在锁定 $Z_3^star$ 后，第二阶段最小化总原料量：

$
  Z_4 = min sum_(t,i) s_(i t).
$ <eq-p3-total>

由于 $q_A < q_B < q_C$，在 C 类用量已最小的条件下，式 @eq-p3-total 会优先使用单位产品耗料更少的 A 类。第三阶段在 $Z_3 <= Z_3^star + 10^(-6)$、$Z_4 <= Z_4^star + 10^(-6)$ 下最小化运输损耗：

$
  Z_5 = min sum_(t,i,j) ell_j x_(i j t).
$ <eq-p3-loss>

三层目标按式 @eq-p3-c 至 @eq-p3-loss 顺序求解，分别对应“尽量少 C”“尽量少总原料”和“尽量少损耗”。每一层只在前序最优集内继续优化，因此不需要人为折中系数。

== 连续运输与求解边界

问题三采用连续运输流，不设置式 @eq-single-carrier 的二元指派。题面表述为“尽量由一家转运商承担”，连续 LP 能给出明确最优性状态；既有全网硬单承运商模型在 80 秒内没有获得可行解，只能记录为#locked.problem3_hard_carrier_status.display，不能写成数学不可行，也没有可与当前 LP 比较的损耗最优值。

连续流允许少量拆分，并可能产生许多小额订单。本文不在求解后手工合并或删除，因为这会改变式 @eq-p3-c 至 @eq-p3-loss 的目标值，或使主承运商超过式 @eq-carrier-cap 的容量上限。运营集中度因此作为结果边界单独披露。
