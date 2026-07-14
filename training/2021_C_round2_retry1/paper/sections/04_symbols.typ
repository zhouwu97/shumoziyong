#import "../style.typ": three-line-table, source-note
#let locked = json("../../paper_source_lock.json").claims

= 符号说明

本文在原料体积、产品等价体积和相对成本之间保持严格区分。表 2 给出集合、参数和决策变量；下标 $i$、$j$、$t$ 分别对应供应商、转运商和未来周次。

#three-line-table(
  [表 2 #h(0.6em) 主要符号],
  (8.2em, 1fr, 7.2em),
  ([符号], [含义], [单位]),
  (
    [$i in cal(I)$], [供应商索引，$abs(cal(I)) = 402$], [-],
    [$j in cal(J)$], [转运商索引，$abs(cal(J)) = 8$], [-],
    [$t in cal(T)$], [未来周次，$t = 1, dots, 24$], [周],
    [$k(i)$], [供应商 $i$ 的原料类别], [-],
    [$q_A, q_B, q_C$], [单位产品所需 A、B、C 类原料量], [m³原料/m³产品],
    [$c_A, c_B, c_C$], [A、B、C 类原料相对采购单价], [相对成本/m³],
    [$u_i$], [供应商 $i$ 的常规期望供货上限], [m³/周],
    [$p_i$], [供应商 $i$ 在已下单周的非零供货概率], [-],
    [$rho_i$], [历史订单响应率，截断到 $[0, 1]$], [-],
    [$ell_j$], [转运商 $j$ 的预测损耗率], [-],
  ),
  alignments: (center, left, center),
  font-size: 9.6pt,
)

集合与参数均由题面或历史统计确定。$u_i$ 只表示规律下单条件下的历史期望能力，不应解释为未来每周保证供货量。

#pagebreak()

#three-line-table(
  [表 2（续）#h(0.6em) 主要符号],
  (8.2em, 1fr, 7.2em),
  ([符号], [含义], [单位]),
  (
    [$U_j$], [转运商 $j$ 的周运输能力，均为 #locked.transporter_weekly_capacity.display], [m³/周],
    [$z_i$], [是否启用供应商 $i$], [0-1],
    [$o_(i t)$], [第 $t$ 周向供应商 $i$ 的订购量], [m³],
    [$s_(i t)$], [第 $t$ 周供应商 $i$ 的期望实际供货量], [m³],
    [$x_(i j t)$], [第 $t$ 周供应商 $i$ 经转运商 $j$ 的发运量], [m³],
    [$y_(i j t)$], [问题二中是否由转运商 $j$ 承运供应商 $i$ 当周货物], [0-1],
    [$r_(i t)$], [损耗后接收的供应商 $i$ 原料量], [m³],
    [$A_t$], [第 $t$ 周损耗后到货的产品等价量], [m³产品],
    [$I_t$], [第 $t$ 周末产品等价库存], [m³产品],
    [$D$], [周生产需求；问题四中为决策变量], [m³产品/周],
    [$E(v, k)$], [原料体积 $v$ 按类别 $k$ 换算的产品等价量], [m³产品],
  ),
  alignments: (center, left, center),
  font-size: 9.4pt,
)

三类原料按单位产品消耗系数换算为产品等价量：

$
  E(v, k) = frac(v, q_k), quad
  q_A = 0.60, quad q_B = 0.66, quad q_C = 0.72.
$ <eq-material-conversion>

@eq-material-conversion 中，$v$ 为原料体积，$k in {A, B, C}$ 为原料类别，$q_k$ 为生产 1 m³ 产品所需的该类原料体积，$E(v, k)$ 为可生产产品的等价体积。公式中的全部变量均已在表 2 定义。
