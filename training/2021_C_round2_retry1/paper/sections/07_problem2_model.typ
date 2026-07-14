#import "../style.typ": source-note
#let locked = json("../../paper_source_lock.json").claims

= 问题二：最少供应商与订购运输模型

问题二含供应商选择与单承运商二元变量，属于混合整数线性规划；问题三、四在连续流口径下属于线性规划 [3-4]。

== 订购、供货与能力覆盖

历史订单响应率截断到 $[0,1]$，并用于由订购量反推期望实际供货量：

$
  rho_i = min(frac(sum_tau S_(i tau), sum_tau O_(i tau)), 1),
  quad s_(i t) = rho_i o_(i t).
$ <eq-order-supply>

式 @eq-order-supply 中，采购成本按企业实际收购的 $s_(i t)$ 计量，$o_(i t)$ 只用于形成订购方案。以 $z_i$ 表示是否选择供应商，并用最低预测损耗 $ell_min = min_j ell_j$ 构造必要能力覆盖模型：

$
  min sum_(i in cal(I)) z_i.
$ <eq-cardinality>

$
  sum_(i in cal(I)) frac(u_i(1 - ell_min), q_(k(i))) z_i >= D,
  quad z_i in {0, 1}.
$ <eq-capacity-cover>

式 @eq-cardinality 最小化供应商基数，式 @eq-capacity-cover 是正式模型的放松必要条件。将净产品能力记为 $b_i=u_i(1-ell_min)/q_(k(i))$ 并降序排列，则任意 25 家集合 $S$ 满足
$sum_(i in S)b_i <= sum_(r=1)^25 b_((r)) = #locked.problem2_top25_net_capacity.display < #locked.base_weekly_production.display$。加入第 26 家后覆盖量为 #locked.problem2_top26_net_capacity.display m³/周，且正式模型存在可行解。因此最少数量恰为 #locked.problem2_minimum_supplier_count.display，而不是一次启发式返回值。该数量只对应基准需求下的数学下界，不表示企业推荐维持的长期合作规模。

== 运输与库存约束

供应商期望供货全部进入运输流：

$
  s_(i t) = sum_(j in cal(J)) x_(i j t).
$ <eq-flow-balance>

供应能力限制为

$
  0 <= s_(i t) <= u_i z_i.
$ <eq-supply-cap>

每家转运商的周运输能力为

$
  sum_(i in cal(I)) x_(i j t) <= U_j = 6000,
  quad forall j,t.
$ <eq-carrier-cap>

问题二把同一供应商同一周由一家转运商承运作为硬约束：

$
  sum_j y_(i j t) <= 1,
  quad 0 <= x_(i j t) <= u_i y_(i j t),
  quad y_(i j t) in {0, 1}.
$ <eq-single-carrier>

损耗后接收的原料量为

$
  r_(i t) = sum_j x_(i j t)(1 - ell_j).
$ <eq-received>

当周产品等价到货量为

$
  A_t = sum_i frac(r_(i t), q_(k(i))).
$ <eq-arrival>

库存按产品等价量统一记账，其守恒关系为

$
  I_t = I_(t-1) + A_t - D.
$ <eq-inventory>

基准问题的初始库存和安全库存下界为

$
  I_0 = 2D,
  quad I_t >= 2D,
  quad t = 1, dots, 24.
$ <eq-safety-stock>

式 @eq-flow-balance 至 @eq-safety-stock 分别约束供货守恒、历史能力、运输能力、单承运商、损耗后接收、产品换算和库存安全。库存平衡采用经典确定性库存结构 [6]，但能力与损耗参数来自本文的数据语义处理。

== 两阶段词典序目标

在固定 #locked.problem2_minimum_supplier_count.display 家候选集合后，第一阶段最小化相对采购成本：

$
  Z_1 = min sum_(t,i) c_(k(i)) s_(i t).
$ <eq-p2-cost>

第二阶段最小化运输损耗：

$
  Z_2 = min sum_(t,i,j) ell_j x_(i j t).
$ <eq-p2-loss>

式 @eq-p2-cost 和 @eq-p2-loss 分别对应第一、第二优先级。

设第一阶段最优值为 $Z_1^star$，第二阶段加入

$
  sum_(t,i) c_(k(i)) s_(i t) <= Z_1^star + 10^(-6).
$ <eq-p2-lock>

式 @eq-p2-lock 用绝对容差吸收浮点误差，同时保持采购成本优先于损耗。顺序求解符合词典序多目标优化的定义 [5]，也避免人为设置大权重造成尺度失真。

#source-note[问题二采用混合整数线性规划。供应商数量、采购成本和运输损耗依次按“基数证明—成本最优—损耗最优”的逻辑确定。]
